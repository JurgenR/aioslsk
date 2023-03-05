import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
from functools import partial
import logging
from weakref import WeakSet
import mutagen
from mutagen.mp3 import BitrateMode
import os
import re
import shelve
import sys
import time
from typing import Dict, List, Set, Tuple
import uuid

from .exceptions import FileNotFoundError
from .protocol.primitives import Attribute, DirectoryData, FileData
from .settings import Settings

logger = logging.getLogger(__name__)


_COMPRESSED_FORMATS = [
    'MP3',
    'MP4',
    'ASF', # WMA
    'OggVorbis'
]
_LOSSLESS_FORMATS = [
    'FLAC',
    'WAVE'
]
_QUERY_CLEAN_PATTERN = re.compile(r"[^\w\d]")
"""Pattern to remove all non-word/digit characters from a string"""
_QUERY_WORD_SEPERATORS = re.compile(r"[\-_\/\.,]")
"""Word seperators used to seperate terms in a query"""


@dataclass(eq=True, unsafe_hash=True)
class SharedDirectory:
    something: str
    absolute_path: str
    alias: str
    items: Set['SharedItem'] = field(default_factory=set, init=False, compare=False, hash=False, repr=False)

    def get_remote_path(self):
        return '@@' + self.alias

    def get_item_by_remote_path(self, remote_path: str):
        for item in self.items:
            if item.get_remote_path() == remote_path:
                return item
        else:
            raise FileNotFoundError(
                f"file with remote path {remote_path!r} not found in directory {self!r}")


@dataclass(eq=True, unsafe_hash=True)
class SharedItem:
    shared_directory: SharedDirectory
    subdir: str
    filename: str
    modified: float
    attributes: bytes = field(default=None, init=False, compare=False, hash=False)

    def get_absolute_path(self):
        return os.path.join(
            self.shared_directory.absolute_path, self.subdir,self.filename)

    def get_remote_path(self):
        return '@@' + os.path.join(
            self.shared_directory.alias, self.subdir, self.filename)

    def get_remote_directory_path(self):
        return '@@' + os.path.join(
            self.shared_directory.alias, self.subdir)

    def __getstate__(self):
        fields = self.__dict__.copy()
        fields['shared_directory'] = None
        return fields


def extract_attributes(filepath: str):
    """Attempts to extract attributes from the file at L{filepath}"""
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

    except mutagen.MutagenError:
        logger.exception(f"failed retrieve audio file metadata. path={filepath!r}")

    return attributes


class SharesStorage:
    """Abstract base class for storing shares"""

    def load_index(self) -> List[SharedDirectory]:
        raise NotImplementedError(
            "'load_index' needs to be overwritten in a subclass")

    def store_index(self, shared_directories: List[SharedDirectory]):
        raise NotImplementedError(
            "'store_index' needs to be overwritten in a subclass")


class SharesShelveStorage(SharesStorage):
    DEFAULT_FILENAME = 'shares_index'

    def __init__(self, data_directory: str):
        self.data_directory: str = data_directory

    def _get_index_path(self):
        return os.path.join(self.data_directory, self.DEFAULT_FILENAME)

    def load_index(self) -> List[SharedDirectory]:
        with shelve.open(self._get_index_path(), 'c') as db:
            directories = db.get('index', list())
            for directory in directories:
                new_items = set()
                for item in directory.items:
                    item.shared_directory = directory
                    new_items.add(item)
                directory.items = new_items
            return directories

    def store_index(self, shared_directories: List[SharedDirectory]):
        with shelve.open(self._get_index_path(), 'c') as db:
            db['index'] = shared_directories


class SharesManager:
    _ALIAS_LENGTH = 5

    def __init__(self, settings: Settings, storage: SharesStorage):
        self._settings: Settings = settings
        self.term_map: Dict[str, Set[SharedItem]] = {}
        self.shared_directories: List[SharedDirectory] = list()
        self._directory_aliases: Dict[str, str] = {}

        self.storage: SharesStorage = storage

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

        alias_bytes = bytearray(
            [unique_id[-1] | offset for _ in range(self._ALIAS_LENGTH)])

        # Chunk the path into pieces of 5
        for c_idx in range(0, len(path_bytes), self._ALIAS_LENGTH):
            chunk = path_bytes[c_idx:c_idx + self._ALIAS_LENGTH]
            # previous_iter_byte XOR unique_id XOR current_iter_byte
            for b_idx, byte in enumerate(chunk):
                alias_bytes[b_idx] ^= byte ^ unique_id[b_idx]

        # To lowercase
        alias_bytes = bytes([(byte % 26) + 0x61 for byte in alias_bytes])
        alias_string = alias_bytes.decode('utf8')

        return alias_string

    def load_from_settings(self):
        """Loads the directories from the settings"""
        for shared_directory in self._settings.get('sharing.directories'):
            self.add_shared_directory(shared_directory)

    def read_cache(self):
        """Read the directories from the storage. Rebuilding of the term map
        needs to be called independently.
        """
        directories = self.storage.load_index()
        self.shared_directories = directories

    def write_cache(self):
        logger.debug(f"writing {len(self.shared_directories)} directories to storage")
        self.storage.store_index(self.shared_directories)

    def build_term_map(self, shared_directory: SharedDirectory):
        """Builds a list of valid terms for the given shared directory"""
        for item in shared_directory.items:
            self._add_item_to_term_map(item)

    def _add_item_to_term_map(self, item: SharedItem):
        path = (item.subdir + "/" + item.filename).lower()
        path = re.sub(_QUERY_WORD_SEPERATORS, ' ', path)
        terms = path.split()
        for term in terms:
            term = re.sub(_QUERY_CLEAN_PATTERN, '', term)

            if term not in self.term_map:
                self.term_map[term] = WeakSet()
            self.term_map[term].add(item)

    def get_shared_item(self, remote_path: str) -> SharedItem:
        """Gets a shared item from the cache based on the given file path. If
        the file does not exist in the L{shared_items} or the file is present
        in the cache but does not exist on disk a C{FileNotFoundError} is raised

        :param remote_path: the remote_path
        :raise FileNotFoundError: filename was not found in shared_items or was found
            but did not exist on disk
        """
        for shared_directory in self.shared_directories:
            try:
                item = shared_directory.get_item_by_remote_path(remote_path)
            except FileNotFoundError:
                pass
            else:
                if not os.path.exists(item.get_absolute_path()):
                    raise FileNotFoundError(
                        f"file with remote_path {remote_path} found in cache but not on disk"
                    )
                return item
        else:
            raise FileNotFoundError(f"file name {remote_path} not found in cache")

    def add_shared_directory(self, shared_directory: str) -> SharedDirectory:
        """Adds a shared directory. This method will call `generate_alias` and
        add the directory to the directory map

        :param shared_directory: path of the shared directory
        :return: a `SharedDirectory` object
        """
        # Calc absolute path, generate an alias and store it
        abs_directory = os.path.abspath(shared_directory)
        alias = self.generate_alias(abs_directory)

        # Check if we have an existing shared directory, otherwise return it
        directory_object = SharedDirectory(
            shared_directory,
            abs_directory,
            alias
        )
        for shared_directory in self.shared_directories:
            if shared_directory == directory_object:
                return shared_directory

        # TODO: Check if the alias already exists

        self.shared_directories.append(directory_object)
        return directory_object

    async def scan(self):
        """Scans all directories in `shared_directories` list"""
        scan_futures = []
        loop = asyncio.get_running_loop()

        start_time = time.time()

        # Scan files
        for shared_directory in self.shared_directories:
            logger.info(f"scheduling scan for directory : {shared_directory!r})")
            scan_future = loop.run_in_executor(
                None,
                partial(self.scan_directory, shared_directory)
            )
            scan_future.add_done_callback(
                partial(self._scan_directory_callback, shared_directory)
            )
            scan_futures.append(scan_future)

        await asyncio.gather(*scan_futures, return_exceptions=True)

        for shared_directory in self.shared_directories:
            self.build_term_map(shared_directory)

        # Scan attributes
        for shared_directory in self.shared_directories:
            amount_scheduled = 0
            for item in shared_directory.items:
                if item.attributes is None:
                    future = loop.run_in_executor(
                        None,
                        partial(self.extract_attributes, item)
                    )
                    future.add_done_callback(
                        partial(self._extract_attributes_callback, item)
                    )
                    amount_scheduled += 1
            logger.debug(
                f"scheduled {amount_scheduled} items for attribute extracting for directory {shared_directory}")

        logger.info(f"completed scan in {time.time() - start_time} seconds")

    def scan_directory(self, shared_directory: SharedDirectory) -> Set[SharedItem]:
        """Starts scanning a directory

        :param shared_dir: absolute path to the directory
        :param alias: directory alias, used when building the SharedItem objects
        """
        shared_items = set()
        for directory, _, files in os.walk(shared_directory.absolute_path):
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

    def _scan_directory_callback(self, shared_directory: SharedDirectory, future: Future):
        try:
            shared_items: Set[SharedItem] = future.result()
        except Exception:
            logger.exception(f"exception adding directory : {shared_directory!r}")
        else:
            logger.debug(f"scan found {len(shared_items)} files for directory {shared_directory!r}")

            # Adds all new items to the directory items
            shared_directory.items |= shared_items
            # Remove all items from the cache that weren't in the returned items
            # set
            shared_directory.items -= (shared_directory.items ^ shared_items)

    def extract_attributes(self, shared_item: SharedItem):
        return extract_attributes(shared_item.get_absolute_path())

    def _extract_attributes_callback(self, shared_item: SharedItem, future: Future):
        try:
            shared_item.attributes = future.result()
        except Exception:
            logger.warn(f"exception fetching shared item attributes : {shared_item!r}")

    def get_filesize(self, filename: str) -> int:
        return os.path.getsize(filename)

    def query(self, query: str) -> List[SharedItem]:
        """Queries the L{shared_items}.

        1. Transform query into terms:
            - will be split up (whitespace)
            - lowercased
            - non-alphanumeric characters stripped

        2. For each of the terms get the shared items that are available for the
            first term. Continue to the next term and eliminate all shared items
            that do not match the second term. Continue until we found all shared
            items (if any)
        """
        terms = query.split()
        if not terms:
            return []

        # Clean up terms, return immediately in case there is a term not in the
        # list
        clean_terms = []
        for term in terms:
            clean_term = re.sub(_QUERY_CLEAN_PATTERN, '', term.lower())

            # Optimization return immediately if term is not in map
            if clean_term not in self.term_map:
                return []

            clean_terms.append(clean_term)

        found_items = self.term_map[clean_terms[0]]
        for term in clean_terms[1:]:
            term_items = self.term_map[clean_term]

            found_items &= term_items

            if not found_items:
                return []

        return list(found_items)

    def get_stats(self) -> Tuple[int, int]:
        """Gets the total amount of shared directories and files.

        :return: Directory and file count as a C{tuple}
        """
        file_count = sum(
            len(directory.items) for directory in self.shared_directories
        )
        dir_count = sum(
            len(set(item.subdir for item in directory.items))
            for directory in self.shared_directories
        )
        return dir_count, file_count

    def get_download_path(self, filename: str):
        """Gets the download path for a filename returned by another peer"""
        download_dir = self._settings.get('sharing.download')
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)

        return os.path.join(download_dir, os.path.basename(filename))

    def create_shares_reply(self) -> List[DirectoryData]:
        """Creates a complete list of the currently shared items as a reply to
        a PeerSharesRequest messages
        """
        # Sort files under unique directories
        response_dirs: Dict[str, SharedItem] = {}
        for shared_dir in self.shared_directories:
            for item in shared_dir.items:
                directory = item.get_remote_directory_path()
                if directory in response_dirs:
                    response_dirs[directory].append(item)
                else:
                    response_dirs[directory] = [item, ]

        # Create shares reply
        shares_reply = []
        for directory, files in response_dirs.items():
            shares_reply.append(
                DirectoryData(
                    name=directory,
                    files=self.convert_items_to_file_data(files, use_full_path=False)
                )
            )

        return shares_reply

    def create_directory_reply(self, remote_directory: str) -> List[DirectoryData]:
        response_dirs: Dict[str, SharedItem] = {}
        for shared_dir in self.shared_directories:
            for item in shared_dir.items:
                item_dir = item.get_remote_directory_path()
                if item_dir != remote_directory:
                    continue

                if directory in response_dirs:
                    response_dirs[directory].append(item)
                else:
                    response_dirs[directory] = [item, ]

        reply = []
        for directory, files in response_dirs.items():
            reply.append(
                DirectoryData(
                    name=directory,
                    files=self.convert_items_to_file_data(files, use_full_path=False)
                )
            )

        return reply

    def convert_item_to_file_data(
            self, shared_item: SharedItem, use_full_path: bool = True) -> FileData:
        """Convert a L{SharedItem} object to a L{FileData} object

        :param use_full_path: use the full path of the file as `filename` if
            `True` otherwise use just the filename. Should be `False` when
            generating a shares reply, `True` when generating search reply
        """
        file_path = shared_item.get_absolute_path()
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(shared_item.filename)[-1]
        if shared_item.attributes:
            attributes = [Attribute(*attr) for attr in shared_item.attributes]
        else:
            attributes = []

        return FileData(
            unknown=1,
            filename=shared_item.get_remote_path() if use_full_path else shared_item.filename,
            filesize=file_size,
            extension=file_ext,
            attributes=attributes
        )

    def convert_items_to_file_data(self, shared_items: List[SharedItem], use_full_path=True) -> List[FileData]:
        """Converts a list of L{SharedItem} instances to a list of L{FileData}
        instances. If an exception occurs when converting the item an error will
        be logged and the item will be omitted from the list
        """
        file_datas = []
        for shared_item in shared_items:
            try:
                file_datas.append(
                    self.convert_item_to_file_data(shared_item, use_full_path=use_full_path)
                )
            except OSError:
                logger.exception(f"failed to convert to result : {shared_item!r}")

        return file_datas
