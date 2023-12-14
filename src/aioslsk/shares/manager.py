from aiofiles import os as asyncos
import asyncio
from functools import partial
import logging
import mutagen
from mutagen.mp3 import BitrateMode
import os
import re
import sys
import time
from typing import Optional, Dict, List, Set, Tuple, Union
import uuid
from weakref import WeakSet

from ..base_manager import BaseManager
from .cache import SharesNullCache, SharesCache
from ..events import (
    EventBus,
    ScanCompleteEvent,
    SessionInitializedEvent,
    SessionDestroyedEvent,
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
from .utils import create_term_pattern, convert_items_to_file_data

logger = logging.getLogger(__name__)


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
        children: Optional[List[SharedDirectory]] = None) -> Set[SharedItem]:
    """Scans the directory for items to share

    :param shared_directory: `SharedDirectory` instance
    :param children: list of `SharedDirectory` instances, the items in this list
        will not be returned and should be scanned individually
    :return: set of `SharedItem` objects found during the scan
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
                logger.debug(f"could not get modified time for file {filepath!r}")
            else:
                shared_items.add(
                    SharedItem(shared_directory, subdir, filename, modified)
                )

    return shared_items


def extract_attributes(filepath: str) -> List[Tuple[int, int]]:
    """Attempts to extract attributes from the file at `filepath`. If there was
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
            f"failed retrieve audio file metadata. path={filepath!r}", exc_info=exc)

    return attributes


class SharesManager(BaseManager):
    _ALIAS_LENGTH = 5

    def __init__(
            self, settings: Settings, event_bus: EventBus,
            network: Network, cache: Optional[SharesCache] = None):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network
        self._term_map: Dict[str, WeakSet[SharedItem]] = {}
        self._shared_directories: List[SharedDirectory] = list()
        self._session: Optional[Session] = None

        self.cache: SharesCache = cache if cache else SharesNullCache()
        self.executor = None

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
        found in the `shared_directories`.

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

    async def load_data(self):
        self.read_cache()
        self.load_from_settings()

    async def store_data(self):
        self.write_cache()

    def load_from_settings(self):
        """Loads the directories from the settings"""
        for shared_directory in self._settings.shares.directories:
            self.add_shared_directory(
                shared_directory.path,
                share_mode=shared_directory.share_mode,
                users=shared_directory.users
            )

    def read_cache(self):
        """Read the directories from the cache"""
        logger.info("reading directories from cache")
        directories = self.cache.read()
        logger.info(f"read {len(directories)} directories from cache")
        self._shared_directories = directories

    def write_cache(self):
        """Write current shared directories to the cache"""
        logger.info(f"writing {len(self._shared_directories)} directories to cache")
        self.cache.write(self._shared_directories)
        logger.info(f"successfully wrote {len(self._shared_directories)} directories to cache")

    def get_download_directory(self) -> str:
        """Gets the absolute path the to download directory configured from the
        settings

        :return: Absolute path of the value of the `shares.download` setting
        """
        download_dir = self._settings.shares.download
        return os.path.abspath(download_dir)

    async def create_directory(self, absolute_path: str):
        """Ensures the passed directory exists"""
        if not await asyncos.path.exists(absolute_path):
            logger.info(f"creating directory : {absolute_path}")
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
        logger.debug(f"term map contains {len(self._term_map)} terms")

    async def get_shared_item(self, remote_path: str, username: Optional[str] = None) -> SharedItem:
        """Gets a shared item from the cache based on the given file path. If
        the file does not exist in the `shared_items` or the file is present
        in the cache but does not exist on disk a `FileNotFoundError` is raised

        If a `username` is passed this will also check if the file is locked
        and raise a `FileNotSharedError` if the file is not accessible for that
        user

        :param remote_path: the remote_path
        :param username:
        :raise FileNotFoundError: filename was not found in shared_items or was found
            but did not exist on disk
        :raise FileNotSharedError: file is found, but locked for the given
            `username`
        """
        for shared_directory in self._shared_directories:
            try:
                item = shared_directory.get_item_by_remote_path(remote_path)
            except FileNotFoundError:
                pass
            else:
                if not await asyncos.path.exists(item.get_absolute_path()):
                    raise FileNotFoundError(
                        f"file with remote_path {remote_path} found in cache but not on disk"
                    )

                if username and self.is_item_locked(item, username):
                    raise FileNotSharedError(f"File is not shared to user {username}")
                return item
        else:
            raise FileNotFoundError(f"file name {remote_path} not found in cache")

    def add_shared_directory(
            self, shared_directory: str,
            share_mode: DirectoryShareMode = DirectoryShareMode.EVERYONE,
            users: Optional[List[str]] = None) -> SharedDirectory:
        """Adds a shared directory. This method will call `generate_alias` and
        add the directory to the directory map.

        :param shared_directory: path of the shared directory
        :param share_mode: the share mode for the directory
        :param users: in case the share mode is `USERS`, a list of users to
            share it with
        :return: a `SharedDirectory` object
        """
        # Calc absolute path, generate an alias and store it
        abs_directory = os.path.normpath(os.path.abspath(shared_directory))
        alias = self.generate_alias(abs_directory)

        # Check if we have an existing shared directory, otherwise return it
        directory_object = SharedDirectory(
            shared_directory,
            abs_directory,
            alias,
            share_mode=share_mode,
            users=users or []
        )
        for shared_dir in self._shared_directories:
            if shared_dir == directory_object:
                return shared_dir

        # If the new directory is a child of an existing directory, move items
        # to the child directory and remove them from the parent directory
        parents = self._get_parent_directories(directory_object)
        if parents:
            parent = parents[-1]
            children = parent.get_items_for_directory(directory_object)
            directory_object.items |= children
            parent.items -= children

        self._shared_directories.append(directory_object)
        return directory_object

    def remove_shared_directory(self, directory: SharedDirectory):
        """Removes the given shared directory. If the directory was a
        subdirectory of another shared directory its items will be moved into
        that directory

        :param shared_directory: `SharedDirectory` instance to remove
        :raise SharedDirectoryError: raised when the passed `shared_directory`
            was not added to the manager
        """
        if directory not in self._shared_directories:
            raise SharedDirectoryError(
                "attempted to remove directory which was not added to the manager"
            )

        self._shared_directories.remove(directory)

        parents = self._get_parent_directories(directory)
        # If the directory has a parent directory, move all items into that
        # directory
        if parents:
            parent = parents[-1]
            parent.items |= directory.items

        self._cleanup_term_map()

    async def scan_directory_files(self, shared_directory: SharedDirectory):
        """Scans the files for the given `shared_directory`

        :param shared_directory: `SharedDirectory` instance to scan
        :raise SharedDirectoryError: raised when the passed `shared_directory`
            was not added to the manager
        """
        loop = asyncio.get_running_loop()

        if shared_directory not in self._shared_directories:
            raise SharedDirectoryError(
                "attempted to scan directory which was not added to the manager"
            )

        logger.info(f"scheduling scan for directory : {shared_directory!r})")
        try:
            shared_items: Set[SharedItem] = await loop.run_in_executor(
                self.executor,
                partial(
                    scan_directory,
                    shared_directory,
                    children=self._get_child_directories(shared_directory)
                )
            )
        except Exception:
            logger.exception(f"exception scanning directory : {shared_directory!r}")
        else:
            logger.debug(f"scan found {len(shared_items)} files for directory {shared_directory!r}")

            # Adds all new items to the directory items
            shared_directory.items |= shared_items
            # Remove all items from the cache that weren't in the returned items
            # set
            shared_directory.items -= (shared_directory.items ^ shared_items)

        self._build_term_map(shared_directory)
        self._cleanup_term_map()

    async def scan_directory_file_attributes(self, shared_directory: SharedDirectory):
        """Scans the file attributes for files in the given `shared_directory`.
        only files that do not yet have attributes will be scanned

        The results of the scan are handled internally and are automatically to
        the `SharedItem` object for which the scan was performed

        :param shared_directory: `SharedDirectory` instance for which the files
            need to be scanned
        :return: List of futures for each file that needs to be scanned
        """
        def extract_item_attributes(item: SharedItem):
            return item, extract_attributes(item.get_absolute_path())

        loop = asyncio.get_running_loop()

        # Schedule the items on the executor
        extract_futures: List[asyncio.Future] = []
        for item in shared_directory.items:
            if item.attributes is None:
                future = loop.run_in_executor(
                    self.executor,
                    partial(extract_item_attributes, item)
                )
                extract_futures.append(future)

        logger.debug(
            f"scheduled {len(extract_futures)} / {len(shared_directory.items)} items "
            f"for attribute extracting for directory {shared_directory}")

        for future in asyncio.as_completed(extract_futures):
            try:
                item, attributes = await future
            except Exception:
                logger.warning("exception fetching shared item attributes")
            else:
                item.attributes = attributes

    async def scan(self):
        """Scan the files and their attributes for all directories currently
        defined in the `shared_directories`

        This method will emit a `ScanCompleteEvent` on the event bus and report
        the shares to the server
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
        await asyncio.gather(*attribute_futures, return_exceptions=True)

        logger.info(f"completed scan in {time.perf_counter() - start_time} seconds")
        folder_count, file_count = self.get_stats()
        await self._event_bus.emit(
            ScanCompleteEvent(folder_count, file_count)
        )

        await self.report_shares()

    async def get_filesize(self, shared_item: SharedItem) -> int:
        return await asyncos.path.getsize(shared_item.get_absolute_path())

    def query(
            self, query: Union[str, SearchQuery],
            username: Optional[str] = None) -> Tuple[List[SharedItem], List[SharedItem]]:
        """Performs a query on the `shared_directories` returning the matching
        items. If `username` is passed this method will return a list of
        visible results and list of locked results. If `None` the second list
        will always be empty.

        This method makes a first pass using the built in term map and filters
        the remaining results using regular expressions.

        :param query: the query to perform on the shared directories
        :param username: optionally the username of the user making the query.
            This is used to determine locked results, if not given the locked
            results list will be empty
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

        # Regular expressions on the remnants

        for include_term in search_query.include_terms:
            to_remove = set()
            for item in found_items:
                pattern = create_term_pattern(include_term, wildcard=False)
                if not re.search(pattern, item.get_query_path()):
                    to_remove.add(item)
            found_items -= to_remove

        for wildcard_term in search_query.wildcard_terms:
            to_remove = set()
            for item in found_items:
                pattern = create_term_pattern(wildcard_term, wildcard=True)
                if not re.search(pattern, item.get_query_path()):
                    to_remove.add(item)
            found_items -= to_remove

        for exclude_term in search_query.exclude_terms:
            to_remove = set()
            for item in found_items:
                pattern = create_term_pattern(exclude_term, wildcard=False)
                if re.search(pattern, item.get_query_path()):
                    to_remove.add(item)
            found_items -= to_remove

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

    def get_stats(self) -> Tuple[int, int]:
        """Gets the total amount of shared directories and files.

        :return: directory and file count as a `tuple`
        """
        file_count = sum(
            len(directory.items) for directory in self._shared_directories
        )
        dir_count = sum(
            len(set(item.subdir for item in directory.items))
            for directory in self._shared_directories
        )
        return dir_count, file_count

    def calculate_download_path(self, remote_path: str) -> Tuple[str, str]:
        """Calculates the local download path for a remote path returned by
        another peer.

        :return: tuple of the directory and file name
        """
        download_dir = self.get_download_directory()

        return chain_strategies(
            self.naming_strategies,
            remote_path,
            download_dir
        )

    def get_shared_directories_for_user(self, username: str) -> Tuple[List[SharedDirectory], List[SharedDirectory]]:
        public_dirs = []
        locked_dirs = []
        for shared_dir in self._shared_directories:
            if self.is_directory_locked(shared_dir, username):
                locked_dirs.append(shared_dir)
            else:
                public_dirs.append(shared_dir)

        return public_dirs, locked_dirs

    def create_shares_reply(self, username: str) -> Tuple[List[DirectoryData], List[DirectoryData]]:
        """Creates a complete list of the currently shared items as a reply to
        a `PeerSharesRequest` messages

        :param username: username of the user requesting the shares reply, this
            is used to determine the locked results
        :return: tuple with two lists: public directories and locked directories
        """
        def list_unique_directories(directories: List[SharedDirectory]) -> Dict[str, List[SharedItem]]:
            # Sort files under unique directories by path
            response_dirs: Dict[str, List[SharedItem]] = {}
            for directory in directories:
                for item in directory.items:
                    dir_path = item.get_remote_directory_path()
                    if dir_path in response_dirs:
                        response_dirs[dir_path].append(item)
                    else:
                        response_dirs[dir_path] = [item, ]
            return response_dirs

        def convert_to_directory_shares(directory_map: Dict[str, List[SharedItem]]) -> List[DirectoryData]:
            public_shares = []
            for directory, files in directory_map.items():
                public_shares.append(
                    DirectoryData(
                        name=directory,
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

    def create_directory_reply(self, remote_directory: str) -> List[DirectoryData]:
        """Lists directory data as a response to a directory request.

        :param remote_directory: remote path of the directory
        """
        remote_directory = remote_directory.rstrip('\\/')
        response_dirs: Dict[str, List[SharedItem]] = {}
        for shared_dir in self._shared_directories:
            for item in shared_dir.items:
                item_dir = item.get_remote_directory_path()
                if item_dir != remote_directory:
                    continue

                dir_name = shared_dir.get_remote_path()
                if dir_name in response_dirs:
                    response_dirs[dir_name].append(item)
                else:
                    response_dirs[dir_name] = [item, ]

        reply = []
        for directory, files in response_dirs.items():
            reply.append(
                DirectoryData(
                    name=directory,
                    files=convert_items_to_file_data(files, use_full_path=False)
                )
            )

        return reply

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

    def _get_parent_directories(self, shared_directory: SharedDirectory) -> List[SharedDirectory]:
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
        """Checks if the shared directory is locked for the given `username`"""
        if directory.share_mode == DirectoryShareMode.FRIENDS:
            return username not in self._settings.users.friends
        elif directory.share_mode == DirectoryShareMode.USERS:
            return username not in directory.users
        return False

    def is_item_locked(self, item: SharedItem, username: str) -> bool:
        """Checks if the shared item is locked for the given `username`"""
        return self.is_directory_locked(item.shared_directory, username)

    async def report_shares(self):
        """Reports the shares amount to the server"""
        if not self._session:
            logger.warning("attempted to report shares without valid session")
            return

        folder_count, file_count = self.get_stats()
        logger.debug(f"reporting shares ({folder_count=}, {file_count=})")
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
