from aiofiles import os as asyncos
import asyncio
from collections.abc import Callable
from concurrent.futures import Executor
from functools import partial
import logging
import mutagen
from mutagen.mp3 import BitrateMode
import os
import re
import sys
import time
from typing import Optional, Union
import uuid
from weakref import WeakSet

from ..base_manager import BaseManager
from .cache import SharesNullCache, SharesCache
from ..events import (
    EventBus,
    ScanCompleteEvent,
    SessionInitializedEvent,
    SessionDestroyedEvent,
    SharedDirectoryChangeEvent,
)
from ..exceptions import (
    FileNotFoundError,
    FileNotSharedError,
    SharedDirectoryError,
)
from .model import DirectoryShareMode, SharedDirectory, SharedItem
from ..naming import (
    chain_strategies,
    DefaultNamingStrategy,
    NumberDuplicateStrategy,
)
from ..network.network import Network
from ..protocol.messages import SharedFoldersFiles
from ..protocol.primitives import DirectoryData
from ..search.model import SearchQuery
from ..session import Session
from ..settings import Settings
from .utils import convert_items_to_file_data

logger = logging.getLogger(__name__)

ItemAttributes = list[tuple[int, int]]
ExecutorFactory = Callable[[], Executor]

_COMPRESSED_FORMATS = [
    'MP3',
    'MP4',
    'ASF',  # WMA
    'OggVorbis'
]
_LOSSLESS_FORMATS = [
    'FLAC',
    'WAVE'
]
_QUERY_CLEAN_PATTERN = re.compile(r"[\W_]")
"""Pattern to remove all non-word/digit characters from a string"""


def scan_directory(
        shared_directory: SharedDirectory,
        children: Optional[list[SharedDirectory]] = None) -> set[SharedItem]:
    """Scans the directory for items to share

    Warning: when using ProcessPoolExecutor on this method the returned items
    will not have the shared directory set in some cases. The shared_directory
    passed here is a copy and the object will be removed once this function
    finishes (see https://stackoverflow.com/a/72726998/1419478). In this case
    you should manually assign it again

    :param shared_directory: :class:`.SharedDirectory` instance
    :param children: list of :class:`.SharedDirectory` instances, the items in
        this list will not be returned and should be scanned individually
    :return: set of :class:`.SharedItem` objects found during the scan
    """
    children = children or []
    shared_items = set()
    for directory, _, files in os.walk(shared_directory.absolute_path):
        # Check if the currently scanned directory is part of any of the given
        # child directories
        abs_dir = os.path.normpath(os.path.abspath(directory))
        if any(child_dir.is_parent_of(abs_dir) for child_dir in children):
            continue

        subdir = os.path.relpath(directory, shared_directory.absolute_path)

        if subdir == '.':
            subdir = ''

        for filename in files:
            filepath = os.path.join(directory, filename)
            try:
                modified = os.path.getmtime(os.path.join(directory, filename))
            except OSError:
                logger.debug("could not get modified time for file : %r ", filepath)
            else:
                shared_items.add(
                    SharedItem(shared_directory, subdir, filename, modified)
                )

    return shared_items


def extract_attributes(filepath: str) -> ItemAttributes:
    """Attempts to extract attributes from the file at ``filepath``. If there was
    an error attempting to extract the attributes this method will log a warning
    and return an empty list of attributes
    """
    attributes = []
    try:
        mutagen_file = mutagen.File(filepath)
        if not mutagen_file:
            return []

        if mutagen_file.__class__.__name__ in _COMPRESSED_FORMATS:
            attributes = [
                (0, int(mutagen_file.info.bitrate / 1000), ),
                (1, int(mutagen_file.info.length), )
            ]

            # Figure out bitrate mode if applicable
            bitrate_mode = getattr(mutagen_file, 'bitrate_mode', BitrateMode.UNKNOWN)
            if bitrate_mode == BitrateMode.CBR:
                attributes.append((2, 0, ))
            elif bitrate_mode in (BitrateMode.VBR, BitrateMode.ABR, ):
                attributes.append((2, 1, ))

        elif mutagen_file.__class__.__name__ in _LOSSLESS_FORMATS:
            attributes = [
                (1, int(mutagen_file.info.length), ),
                (4, mutagen_file.info.sample_rate, ),
                (5, mutagen_file.info.bits_per_sample, ),
            ]

    except mutagen.MutagenError as exc:
        logger.warning(
            "failed retrieve audio file metadata. path=%r", filepath, exc_info=exc)

    return attributes


class SharesManager(BaseManager):
    _ALIAS_LENGTH = 5

    def __init__(
            self, settings: Settings, event_bus: EventBus,
            network: Network, cache: Optional[SharesCache] = None,
            executor_factory: Optional[ExecutorFactory] = None):

        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network
        self._term_map: dict[str, WeakSet[SharedItem]] = {}
        self._shared_directories: list[SharedDirectory] = []
        self._session: Optional[Session] = None

        self.cache: SharesCache = cache if cache else SharesNullCache()
        self.executor: Optional[Executor] = None
        self.executor_factory: Optional[ExecutorFactory] = executor_factory

        self.naming_strategies = [
            DefaultNamingStrategy(),
            NumberDuplicateStrategy()
        ]

        self.register_listeners()

    def register_listeners(self):
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)
        self._event_bus.register(
            SessionDestroyedEvent, self._on_session_destroyed)

    @property
    def shared_directories(self):
        return self._shared_directories

    def generate_alias(self, path: str, offset: int = 0) -> str:
        """Generates a directory alias for the given path, this method will be
        called recursively increasing the offset in case the alias is already
        found in the ``shared_directories``.

        The hardware address is mixed in to avoid getting the same alias for the
        same directory on different machines. Admittedly this is a lousy
        security measure but hopefully this will prevent easy leaking of files
        in case such issue would occur. Example: 'abcde' is always generated for
        'C:\\' so the attacker could guess where a file is located.

        :param path: the path for which to generate an alias
        :param offset: offset for the value of the initial 5 bytes (default=0)
        :return: a string of 5 alphabetic characters all lowercased
        """
        path_bytes = path.encode('utf8')
        unique_id = uuid.getnode().to_bytes(6, sys.byteorder)

        alias_bytearr = bytearray(
            [unique_id[-1] | offset for _ in range(self._ALIAS_LENGTH)])

        # Chunk the path into pieces of 5
        for c_idx in range(0, len(path_bytes), self._ALIAS_LENGTH):
            chunk = path_bytes[c_idx:c_idx + self._ALIAS_LENGTH]
            # previous_iter_byte XOR unique_id XOR current_iter_byte
            for b_idx, byte in enumerate(chunk):
                alias_bytearr[b_idx] ^= byte ^ unique_id[b_idx]

        # To lowercase
        alias_bytes = bytes([(byte % 26) + 0x61 for byte in alias_bytearr])
        alias_string = alias_bytes.decode('utf8')

        return alias_string

    async def start(self):
        if self.executor_factory:
            self.executor = self.executor_factory()

    async def stop(self) -> list[asyncio.Task]:
        if self.executor:
            self.executor.shutdown()
            self.executor = None

        return []

    async def load_data(self):
        self.read_cache()
        self.load_from_settings()

    async def store_data(self):
        self.write_cache()

    def load_from_settings(self):
        """Loads the shared directories from the settings. Existing directories
        will be updated, non-existing directories added, directories that no
        longer exist will be removed
        """
        new_shared_directories: list[SharedDirectory] = []

        # Add or update directories
        for directory_entry in self._settings.shares.directories:
            try:
                shared_directory = self.get_shared_directory(directory_entry.path)
            except SharedDirectoryError:
                shared_directory = self.add_shared_directory(
                    directory_entry.path,
                    share_mode=directory_entry.share_mode,
                    users=directory_entry.users
                )
            else:
                self.update_shared_directory(
                    shared_directory,
                    share_mode=directory_entry.share_mode,
                    users=directory_entry.users or []
                )

            new_shared_directories.append(shared_directory)

        self._shared_directories = new_shared_directories

        self.rebuild_term_map()

    def read_cache(self):
        """Read the directories from the cache"""
        logger.info("reading directories from cache")
        directories = self.cache.read()
        logger.info("read %d directories from cache", len(directories))
        self._shared_directories = directories

    def write_cache(self):
        """Write current shared directories to the cache"""
        directory_count = len(self._shared_directories)
        logger.info("writing %d directories to cache", directory_count)
        self.cache.write(self._shared_directories)
        logger.info("successfully wrote %d directories to cache", directory_count)

    def get_download_directory(self) -> str:
        """Gets the absolute path the to download directory configured from the
        settings

        :return: Absolute path of the value of the ``shares.download`` setting
        """
        download_dir = self._settings.shares.download
        return os.path.abspath(download_dir)

    async def create_directory(self, absolute_path: str):
        """Ensures the passed directory exists"""
        if not await asyncos.path.exists(absolute_path):
            logger.info("creating directory : %s", absolute_path)
            await asyncos.makedirs(absolute_path, exist_ok=True)

    def rebuild_term_map(self):
        logger.info("rebuilding term map")
        self._term_map = {}
        for shared_directory in self.shared_directories:
            self._build_term_map(shared_directory)

    def _build_term_map(self, shared_directory: SharedDirectory):
        """Builds a list of valid terms for the given shared directory"""
        for item in shared_directory.items:
            self._add_item_to_term_map(item)
        logger.debug("term map contains %d terms", len(self._term_map))

    def get_shared_item_cache(self, remote_path: str, username: Optional[str] = None) -> SharedItem:
        """Gets a shared item from the cache if it exists

        If a ``username`` is passed this will also check if the file is locked
        and raise a :class:`.FileNotSharedError` if the file is not accessible
        for that user

        :param remote_path: the remote_path
        :param username: optional username to check if the file is shared or not
        :raise FileNotFoundError: filename was not found in shared_items
        :raise FileNotSharedError: file is found, but locked for the given
            ``username``
        """
        for shared_directory in self._shared_directories:
            try:
                item = shared_directory.get_item_by_remote_path(remote_path)
            except FileNotFoundError:
                pass
            else:
                if username and self.is_item_locked(item, username):
                    raise FileNotSharedError(f"file is not shared to user {username}")
                return item
        else:
            raise FileNotFoundError(f"file name {remote_path} not found in cache")

    async def get_shared_item(self, remote_path: str, username: Optional[str] = None) -> SharedItem:
        """Same as :meth:`get_shared_item_cache` but also checks if the file
        exists on disk

        :param remote_path: the remote_path
        :param username: optional username to check if the file is shared or not
        :raise FileNotFoundError: filename was not found in shared_items or was
            found but did not exist on disk
        :raise FileNotSharedError: file is found, but locked for the given
            ``username``
        """
        item = self.get_shared_item_cache(remote_path, username=username)
        if not await asyncos.path.exists(item.get_absolute_path()):
            raise FileNotFoundError(
                f"file with remote_path {remote_path} found in cache but not on disk"
            )
        return item

    def find_shared_item_cache(
            self, remote_path: str, username: Optional[str] = None) -> Optional[SharedItem]:
        """Equivelant to :meth:`get_shared_item_cache` but returns ``None`` if the
        shared item is not found
        """
        try:
            return self.get_shared_item_cache(remote_path, username=username)
        except (FileNotFoundError, FileNotSharedError):
            return None

    async def find_shared_item(
            self, remote_path: str, username: Optional[str] = None) -> Optional[SharedItem]:
        """Equivelant to :meth:`get_shared_item` but returns ``None`` if the
        shared item is not found
        """
        try:
            return await self.get_shared_item(remote_path, username=username)
        except (FileNotFoundError, FileNotSharedError):
            return None

    def add_shared_directory(
            self, shared_directory: str,
            share_mode: DirectoryShareMode = DirectoryShareMode.EVERYONE,
            users: Optional[list[str]] = None) -> SharedDirectory:
        """Adds a shared directory. This method will call :meth:`generate_alias`
        and add the directory to the directory map.

        This method will not scan the directory, however if the directory is a
        (sub)child of an already registered shared directory the items from that
        directory will be removed from the parent directory to the new directory

        For scanning see the :meth:`scan`, :meth:`scan_directory_files` and
        :meth:`scan_directory_file_attributes` methods.

        :param shared_directory: path of the shared directory
        :param share_mode: the share mode for the directory
        :param users: in case the share mode is `USERS`, a list of users to
            share it with
        :return: a :class:`.SharedDirectory` object
        :raise SharedDirectoryError: if the directory is already shared
        """
        if self.is_directory_shared(shared_directory):
            raise SharedDirectoryError(
                f"directory {shared_directory} is already shared")

        # Generate an absolute path, alias and create the object
        abs_directory = os.path.normpath(os.path.abspath(shared_directory))
        alias = self.generate_alias(abs_directory)

        directory_object = SharedDirectory(
            shared_directory,
            abs_directory,
            alias,
            share_mode=share_mode,
            users=users or []
        )

        # If the new directory is a child of an existing directory, move items
        # to the child directory and remove them from the parent directory
        parents = self._get_parent_directories(directory_object)
        if parents:
            parent = parents[-1]
            children = parent.get_items_for_directory(directory_object)
            directory_object.items |= children
            parent.items -= children

        self._shared_directories.append(directory_object)

        self._event_bus.emit_sync(SharedDirectoryChangeEvent(directory_object))

        return directory_object

    def update_shared_directory(
            self, directory: Union[str, SharedDirectory],
            share_mode: Optional[DirectoryShareMode] = None,
            users: Optional[list[str]] = None) -> SharedDirectory:
        """Updates ``share_mode`` and ``users`` values for the given directory

        :param directory: if a string is given this method will attempt to find
            the shared directory based on the absolute path
        :return: the updated directory
        :raise SharedDirectoryError: if the given directory is a string and not
            in the list of shared directories
        """
        if isinstance(directory, str):
            shared_directory = self.get_shared_directory(directory)
        else:
            shared_directory = directory

        if share_mode is not None:
            shared_directory.share_mode = share_mode

        if users is not None:
            shared_directory.users = users

        self._event_bus.emit_sync(SharedDirectoryChangeEvent(shared_directory))

        return shared_directory

    def remove_shared_directory(self, directory: Union[str, SharedDirectory]) -> SharedDirectory:
        """Removes the given shared directory. If the directory was a
        subdirectory of another shared directory its items will be moved into
        that directory

        Example file structure:

        * Music\\

            * Artist_One\\

                * song_one.mp3

            * Artist_Two\\

                * song_two.mp3

        If the user shares 2 directories:

        * Music\\ : EVERYONE
        * Music\\Artist_One\\ : FRIENDS

        And removes the `Music\\Artist_One\\ shared directory the files of that
        directory get returned back to the parent directory. In this case file
        ``song_two.mp3`` will be shared with EVERYONE again

        :param shared_directory: :class:`.SharedDirectory` instance to remove
        :return: the removed directory
        :raise SharedDirectoryError: raised when the passed `directory` was not
            added to the manager
        """
        if isinstance(directory, str):
            shared_directory = self.get_shared_directory(directory)
        else:
            if directory not in self._shared_directories:
                raise SharedDirectoryError(
                    "attempted to remove directory which was not added to the manager"
                )
            else:
                shared_directory = directory

        self._shared_directories.remove(shared_directory)

        parents = self._get_parent_directories(shared_directory)
        # If the directory has a parent directory, move all items into that
        # directory
        if parents:
            parent = parents[-1]
            parent.items |= shared_directory.items

        self._cleanup_term_map()

        self._event_bus.emit_sync(SharedDirectoryChangeEvent(shared_directory))

        return shared_directory

    def get_shared_directory(self, directory: str) -> SharedDirectory:
        """Calculates the absolute path of given ``directory`` and looks for the
        matching :class:`.SharedDirectory` instance

        :raise SharedDirectoryError: if there is no corresponding
            :class:`.SharedDirectory` instance registered in this class
        """
        abs_path = os.path.normpath(os.path.abspath(directory))
        for shared_directory in self.shared_directories:
            if shared_directory.absolute_path == abs_path:
                return shared_directory

        raise SharedDirectoryError(
            f"did not find shared directory with path : {directory}")

    def is_directory_shared(self, directory: str) -> bool:
        """Checks if a directory is already a shared directory by checking the
        absolute path of that directory
        """
        try:
            self.get_shared_directory(directory)
        except SharedDirectoryError:
            return False
        else:
            return True

    async def scan_directory_files(self, shared_directory: SharedDirectory):
        """Scans the files for the given ``shared_directory``

        :param shared_directory: :class:`.SharedDirectory` instance to scan
        :raise SharedDirectoryError: raised when the passed ``shared_directory``
            was not added to the manager
        """
        loop = asyncio.get_running_loop()

        if shared_directory not in self._shared_directories:
            raise SharedDirectoryError(
                "attempted to scan directory which was not added to the manager"
            )

        logger.info("scheduling scan for directory : %r", shared_directory)
        try:
            shared_items: set[SharedItem] = await loop.run_in_executor(
                self.executor,
                partial(
                    scan_directory,
                    shared_directory,
                    children=self._get_child_directories(shared_directory)
                )
            )
        except Exception:
            logger.exception("exception scanning directory : %r", shared_directory)

        else:
            logger.debug("scan found %d files for directory : %r", len(shared_items), shared_directory)

            # When using a ProcessPoolExecutor the `shared_directory` property
            # might be set to None (since objects are cloned instead of passed
            # by reference). Re-assign it the proper object
            for item in shared_items:
                item.shared_directory = shared_directory

            # Adds all new items to the directory items
            shared_directory.items |= shared_items

            # Remove all items from the cache that weren't in the returned items
            # set. Because the `modified` parameter is part of the hash items
            # with a changed `modified` parameter will also be removed meaning
            # their attributes will be reset and these files attributes need
            # to be rescanned
            shared_directory.items -= (shared_directory.items ^ shared_items)

        self._build_term_map(shared_directory)
        self._cleanup_term_map()

    async def scan_directory_file_attributes(self, shared_directory: SharedDirectory):
        """Scans the file attributes for files in the given ``shared_directory``
        only files that do not have attributes will be scanned

        The results of the scan are handled internally and are automatically to
        the :class:`.SharedItem` object for which the scan was performed

        :param shared_directory: :class:`.SharedDirectory` instance for which
            the files need to be scanned
        """
        loop = asyncio.get_running_loop()

        # Schedule the items on the executor
        futures: list[asyncio.Future] = []
        for item in shared_directory.items:
            if item.attributes is None:
                future = loop.run_in_executor(
                    self.executor,
                    partial(extract_attributes, item.get_absolute_path())
                )
                future.add_done_callback(
                    partial(self._extract_attributes_callback, item)
                )
                futures.append(future)

        logger.debug(
            "scheduled %d / %d items for attribute extracting for directory %s",
            len(futures), len(shared_directory.items), shared_directory
        )

        start = time.perf_counter()

        await asyncio.gather(*futures, return_exceptions=True)

        logger.debug(
            "scanned attributes for %d items in %f s", len(futures), time.perf_counter() - start)

    def _extract_attributes_callback(self, item: SharedItem, future: asyncio.Future):
        try:
            item.attributes = future.result()
        except Exception:
            logger.warning("exception fetching shared item attributes")

    async def scan(self):
        """Scan the files and their attributes for all directories currently
        defined in the ``shared_directories``

        This method will emit a :class:`.ScanCompleteEvent` on the event bus
        and report the shares to the server
        """
        start_time = time.perf_counter()

        files_tasks = [
            self.scan_directory_files(shared_directory)
            for shared_directory in self._shared_directories
        ]
        await asyncio.gather(*files_tasks, return_exceptions=True)

        attribute_futures = [
            self.scan_directory_file_attributes(shared_directory)
            for shared_directory in self._shared_directories
        ]
        await asyncio.gather(*attribute_futures)

        logger.info("completed scan in %f seconds", time.perf_counter() - start_time)
        folder_count, file_count = self.get_stats()
        await self._event_bus.emit(
            ScanCompleteEvent(folder_count, file_count)
        )

        await self.report_shares()

    async def get_filesize(self, shared_item: SharedItem) -> int:
        return await asyncos.path.getsize(shared_item.get_absolute_path())

    def query(
            self, query: Union[str, SearchQuery],
            username: Optional[str] = None,
            excluded_search_phrases: Optional[list[str]] = None) -> tuple[list[SharedItem], list[SharedItem]]:
        """Performs a query on the ``shared_directories`` returning the matching
        items. If ``username`` is passed this method will return a list of
        visible results and list of locked results. If ``None`` the second list
        will always be empty.

        This method makes a first pass using the built in term map and filters
        the remaining results using regular expressions.

        :param query: the query to perform on the shared directories
        :param username: optionally the username of the user making the query.
            This is used to determine locked results, if not given the locked
            results list will be empty
        :param excluded_search_phrases: optional list of search phrases that
            should be excluded from the search results
        :return: two lists of visible results and locked results
        """
        if not isinstance(query, SearchQuery):
            search_query = SearchQuery.parse(query)
        else:
            search_query = query

        # Ignore if no valid include or wildcard terms are given
        if not search_query.has_inclusion_terms():
            return [], []

        # First round using the term map
        include_terms = []
        for term in search_query.include_terms:
            subterms = re.split(_QUERY_CLEAN_PATTERN, term)
            for subterm in subterms:
                if not subterm:
                    continue

                if subterm not in self._term_map:  # Optimization
                    return [], []

                include_terms.append(subterm)

        for term in search_query.wildcard_terms:
            subterms = re.split(_QUERY_CLEAN_PATTERN, term)
            for idx, subterm in enumerate(subterms):
                if not subterm:
                    continue

                if idx == 0:
                    matching_terms = [
                        map_term for map_term in self._term_map.keys()
                        if map_term.endswith(subterm)
                    ]

                    if not matching_terms:  # Optimization
                        return [], []

                    include_terms.extend(matching_terms)
                else:
                    if subterm not in self._term_map:  # Optimization
                        return [], []

                    include_terms.append(subterm)

        found_items = set(self._term_map[include_terms[0]])
        for include_term in include_terms:
            found_items &= set(self._term_map[include_term])

        # Regular expressions on the remaining items

        to_keep = set()
        excl_phrases = excluded_search_phrases or []
        for found_item in found_items:

            if not all(matcher(found_item.get_query_path()) for matcher in search_query.matchers_iter()):
                continue

            # Excluded search phrases
            for excl_phrase in excl_phrases:
                if excl_phrase in found_item.get_query_path().lower():
                    logger.debug(
                        "removing search result %r due to excluded phrase %r",
                        found_item.get_absolute_path(), excl_phrase
                    )
                    break

            else:
                to_keep.add(found_item)

            if len(to_keep) >= self._settings.searches.receive.max_results:
                break

        found_items = to_keep

        # Order by visible and locked results when username is given
        if username:
            visible_results = []
            locked_results = []
            for item in found_items:
                if self.is_item_locked(item, username):
                    locked_results.append(item)
                else:
                    visible_results.append(item)
            return visible_results, locked_results
        else:
            return list(found_items), []

    def get_stats(self) -> tuple[int, int]:
        """Gets the total amount of shared directories and files.

        :return: directory and file count as a ``tuple``
        """
        file_count = sum(
            len(directory.items) for directory in self._shared_directories
        )
        dir_count = sum(
            len(set(item.subdir for item in directory.items))
            for directory in self._shared_directories
        )
        return dir_count, file_count

    def calculate_download_path(self, remote_path: str) -> tuple[str, str]:
        """Calculates the local download path for a remote path returned by
        another peer.

        :return: ``tuple`` of the directory and file name
        """
        download_dir = self.get_download_directory()

        return chain_strategies(
            self.naming_strategies,
            remote_path,
            download_dir
        )

    def get_shared_directories_for_user(self, username: str) -> tuple[list[SharedDirectory], list[SharedDirectory]]:
        public_dirs = []
        locked_dirs = []
        for shared_dir in self._shared_directories:
            if self.is_directory_locked(shared_dir, username):
                locked_dirs.append(shared_dir)
            else:
                public_dirs.append(shared_dir)

        return public_dirs, locked_dirs

    def create_shares_reply(self, username: str) -> tuple[list[DirectoryData], list[DirectoryData]]:
        """Creates a complete list of the currently shared items as a reply to
        a :class:`.PeerSharesRequest` messages

        :param username: username of the user requesting the shares reply, this
            is used to determine the locked results
        :return: ``tuple`` with two lists: public directories and locked
            directories
        """
        def list_unique_directories(directories: list[SharedDirectory]) -> dict[tuple[str, ...], list[SharedItem]]:
            response_dirs: dict[tuple[str, ...], list[SharedItem]] = {}

            for directory in directories:
                for item in directory.items:
                    dir_path = item.get_remote_directory_path_parts()

                    # Create all possible subdirectory paths
                    for x in range(len(dir_path)):
                        dir_path_subpart = dir_path[:x + 1]
                        if dir_path_subpart not in response_dirs:
                            response_dirs[dir_path_subpart] = []

                    response_dirs[dir_path].append(item)

            return response_dirs

        def convert_to_directory_shares(directory_map: dict[tuple[str, ...], list[SharedItem]]) -> list[DirectoryData]:
            public_shares = []
            for directory, files in directory_map.items():
                public_shares.append(
                    DirectoryData(
                        name='\\'.join(directory),
                        files=convert_items_to_file_data(files, use_full_path=False)
                    )
                )
            return public_shares

        visible_dirs, locked_dirs = self.get_shared_directories_for_user(username)
        visible_shares = convert_to_directory_shares(
            list_unique_directories(visible_dirs))
        locked_shares = convert_to_directory_shares(
            list_unique_directories(locked_dirs))

        return visible_shares, locked_shares

    def create_directory_reply(self, remote_directory: str) -> list[DirectoryData]:
        """Lists directory data as a response to a directory request. This will
        not contain any information about subdirectories, only the files within
        that directory

        This method differs from the official clients who don't respond at all
        to the message if the directory does not exist. Instead if the directory
        does not exist and empty list is returned

        :param remote_directory: remote path of the directory
        :return: list of directories. Empty if the directory is not shared, a
            list with one entry if the directory is found
        """
        items: list[SharedItem] = []

        remote_dir_parts = tuple(remote_directory.split('\\'))
        remote_dir_parts_len = len(remote_dir_parts)
        is_shared = False

        for shared_dir in self._shared_directories:
            for item in shared_dir.items:
                # Funny logic to determine if the directory is shared
                if not is_shared:
                    if item.get_remote_directory_path_parts()[:remote_dir_parts_len] == remote_dir_parts:
                        is_shared = True

                if item.get_remote_directory_path() == remote_directory:
                    items.append(item)

        if not is_shared:
            return []

        return [
            DirectoryData(
                name=remote_directory,
                files=convert_items_to_file_data(items, use_full_path=False)
            )
        ]

    def _add_item_to_term_map(self, item: SharedItem):
        path = (item.subdir + "/" + item.filename).lower()
        terms = re.split(_QUERY_CLEAN_PATTERN, path)
        for term in terms:
            if not term:
                continue

            if term not in self._term_map:
                self._term_map[term] = WeakSet()
            self._term_map[term].add(item)

    def _cleanup_term_map(self):
        self._term_map = {
            term: values for term, values in self._term_map.items()
            if len(values) > 0
        }

    def _get_parent_directories(self, shared_directory: SharedDirectory) -> list[SharedDirectory]:
        """Returns a list of parent shared directories. The parent directories
        will be sorted by length of the absolute path (longest last)
        """
        parent_dirs = [
            directory for directory in self._shared_directories
            if directory != shared_directory and directory.is_parent_of(shared_directory)
        ]
        return sorted(parent_dirs, key=lambda d: len(d.absolute_path))

    def _get_child_directories(self, shared_directory: SharedDirectory):
        """Returns a list of child directories"""
        children = [
            directory for directory in self._shared_directories
            if directory != shared_directory and directory.is_child_of(shared_directory)
        ]
        return children

    def is_directory_locked(self, directory: SharedDirectory, username: str) -> bool:
        """Checks if the shared directory is locked for the given ``username``
        """
        if directory.share_mode == DirectoryShareMode.FRIENDS:
            return username not in self._settings.users.friends
        elif directory.share_mode == DirectoryShareMode.USERS:
            return username not in directory.users
        return False

    def is_item_locked(self, item: SharedItem, username: str) -> bool:
        """Checks if the shared item is locked for the given ``username``"""
        return self.is_directory_locked(item.shared_directory, username)

    async def report_shares(self):
        """Reports the shares amount to the server"""
        if not self._session:
            return

        folder_count, file_count = self.get_stats()
        logger.debug("reporting shares (folder_count=%d, file_count=%d)", folder_count, file_count)
        await self._network.send_server_messages(
            SharedFoldersFiles.Request(
                shared_folder_count=folder_count,
                shared_file_count=file_count
            )
        )

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        self._session = event.session
        await self.report_shares()

    async def _on_session_destroyed(self, event: SessionDestroyedEvent):
        self._session = None
