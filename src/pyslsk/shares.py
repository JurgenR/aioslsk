from concurrent.futures import Future, ThreadPoolExecutor
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
from threading import RLock
from typing import Callable, Dict, List, Set, Tuple
import uuid

from .protocol.primitives import DirectoryData, FileData
from .settings import Settings

logger = logging.getLogger()


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
class SharedItem:
    root: str
    subdir: str
    filename: str
    modified: float
    attributes: bytes = field(default=None, init=False, compare=False, hash=False)

    def get_remote_path(self):
        return '@@' + os.path.join(self.root, self.subdir, self.filename)

    def get_remote_directory_path(self):
        return '@@' + os.path.join(self.root, self.subdir)


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


class IndexingTask:
    pass


class ScanDirectoryTask(IndexingTask):

    def __init__(self, directory: str, alias: str):
        self.directory = directory
        self.alias = alias

    def __call__(self) -> Tuple[IndexingTask, Set[SharedItem]]:
        shared_items = set()
        for directory, _, files in os.walk(self.directory):
            subdir = os.path.relpath(directory, self.directory)

            if subdir == '.':
                subdir = ''

            for filename in files:
                filepath = os.path.join(directory, filename)
                try:
                    modified = os.path.getmtime(os.path.join(directory, filename))
                except OSError:
                    logger.debug(f"could not get modified time for file {filepath!r}")
                else:
                    shared_items.add(SharedItem(self.alias, subdir, filename, modified))

        return shared_items


class GetItemAttributesTask(IndexingTask):

    def __init__(self, item_path: str, shared_item: SharedItem):
        self.item_path = item_path
        self.shared_item = shared_item

    def __call__(self):
        return extract_attributes(self.item_path)


class SharesIndexer:
    DEFAULT_FILENAME = 'shares_index'

    def __init__(self):
        self._tasks = []
        self._thread_pool = ThreadPoolExecutor(
            thread_name_prefix='pyslsk-index',
            max_workers=5
        )

    def _submit_task(self, task: IndexingTask, callback: Callable):
        future = self._thread_pool.submit(task)
        future.add_done_callback(partial(callback, task))
        return task

    def scan_directory(self, directory: str, alias: str, callback: Callable) -> ScanDirectoryTask:
        """Starts scanning a directory

        :param directory: absolute path to the directory
        :param alias: directory alias, used when building the SharedItem objects
        :param callback:
        """
        task = ScanDirectoryTask(directory, alias)
        return self._submit_task(task, callback)

    def extract_attributes(self, item_path: str, shared_item: SharedItem, callback: Callable) -> GetItemAttributesTask:
        task = GetItemAttributesTask(item_path, shared_item)
        return self._submit_task(task, callback)

    def stop(self):
        self._thread_pool.shutdown(wait=False)


class SharesStorage:
    """Abstract base class for storing shares"""

    def load_items(self) -> Set[SharedItem]:
        raise NotImplementedError(
            "'load_items' needs to be overwritten in a subclass")

    def store_items(self, shared_items: Set[SharedItem]):
        raise NotImplementedError(
            "'store_items' needs to be overwritten in a subclass")


class SharesShelveStorage(SharesStorage):
    DEFAULT_FILENAME = 'shares_index'

    def __init__(self, data_directory: str):
        self.data_directory: str = data_directory

    def _get_index_path(self):
        return os.path.join(self.data_directory, self.DEFAULT_FILENAME)

    def load_items(self) -> Set[SharedItem]:
        with shelve.open(self._get_index_path(), 'c') as db:
            return db.get('index', set())

    def store_items(self, shared_items: Set[SharedItem]):
        with shelve.open(self._get_index_path(), 'c') as db:
            db['index'] = shared_items


class SharesManager:
    _ALIAS_LENGTH = 5

    def __init__(self, settings: Settings, indexer: SharesIndexer, storage: SharesStorage):
        self._settings: Settings = settings
        self.term_map: Dict[str, Set[SharedItem]] = {}
        self.shared_items: Set[SharedItem] = set()
        self.directory_aliases: Dict[str, str] = {}

        self.indexer: SharesIndexer = indexer
        self.storage: SharesStorage = storage

        self._directory_lock: RLock = RLock()
        self._shared_items_lock: RLock = RLock()

    def generate_alias(self, path: str, offset: int = 0) -> str:
        """Generates a directory alias for the given path, this method will be
        called recursively increasing the offset in case the alias is already
        found in the directory_aliases.

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

        # Check if alias exists, otherwise try to append an offset and run again
        if alias_string in self.directory_aliases:
            return self.generate_alias(path, offset=offset + 1)
        return alias_string

    def load_from_settings(self):
        for shared_directory in self._settings.get('sharing.directories'):
            self.add_shared_directory(shared_directory)

        self._prune_index()

    def _prune_index(self):
        items_to_remove = set()
        with self._shared_items_lock:
            for item in self.shared_items:
                if item.root not in self.directory_aliases.keys():
                    items_to_remove.add(item)

            logger.debug(f"pruning {len(items_to_remove)} shared items")
            self.shared_items -= items_to_remove

    def read_items_from_storage(self):
        """Read the items from the storage. Rebuilding of the term map needs to
        be called independently.
        """
        with self._shared_items_lock:
            self.shared_items = self.storage.load_items()

    def write_items_to_storage(self):
        logger.debug(f"writing {len(self.shared_items)} items to storage")
        with self._shared_items_lock:
            self.storage.store_items(self.shared_items)

    def build_term_map(self, rebuild=True):
        """Builds a list of valid terms for the current list of shared items

        :param rebuild: rebuilds the term map from scratch
        """
        if rebuild:
            self.term_map = {}

        with self._shared_items_lock:
            for item in self.shared_items:
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

    def get_shared_item(self, filename: str) -> SharedItem:
        """Gets a shared item from the cache based on the given file path. If
        the file does not exist in the L{shared_items} or the file is present
        in the cache but does not exist on disk a C{LookupError} is raised.

        This method should be called when an upload is requested from the user

        :param filename: the filename
        :raise LookupError: filename was not found in shared_items or was found
            but did not exist on disk
        """
        for item in self.shared_items:
            if item.get_remote_path() == filename:
                local_path = self.resolve_path(item)
                if not os.path.exists(local_path):
                    raise LookupError(f"file name {filename} found in cache but not on disk")
                return item
        else:
            raise LookupError(f"file name {filename} not found in shared items")

    def add_shared_directory(self, shared_directory: str):
        """Adds a shared directory. This method will:
            - call `generate_alias` and append the directory to the list of
              `directory_aliases`
            - recurse down the given path and add the items to the shared items
              list
            - rebuild the `term_map`

        :param shared_directory: path of the shared directory, the absolute path
            will be calculated before performing the rest of the functions
        """
        # Calc absolute path, generate an alias and store it
        with self._directory_lock:
            abs_directory = os.path.abspath(shared_directory)
            alias = self.generate_alias(abs_directory)
            self.directory_aliases[alias] = abs_directory

        logger.debug(f"scheduling scan for directory : {abs_directory!r} (alias={alias})")
        self.indexer.scan_directory(
            abs_directory, alias, self._scan_directory_callback)

    def _scan_directory_callback(self, task: ScanDirectoryTask, future: Future):
        try:
            shared_items: Set[SharedItem] = future.result()
        except Exception:
            # Rollback adding the directory?
            logger.exception(f"exception adding directory : {task.directory}")
        else:
            logger.debug(f"scan found {len(shared_items)} files for directory {task.directory!r}")
            with self._shared_items_lock:
                self.shared_items |= shared_items

                # Go over the current shared items and filter out those that
                # aren't returned in the scan. Also schedule a task to get the
                # attributes if they weren't set yet for this item
                items_to_remove = set()
                for shared_item in self.shared_items:
                    if shared_item.root != task.alias:
                        continue

                    if shared_item not in shared_items:
                        items_to_remove.add(shared_item)
                        continue

                    if shared_item.attributes is None:
                        self.indexer.extract_attributes(
                            self.resolve_path(shared_item),
                            shared_item,
                            self._get_attributes_callback
                        )
                logger.debug(f"removing {len(items_to_remove)} items")
                self.shared_items -= items_to_remove

            self.build_term_map(rebuild=False)

    def _get_attributes_callback(self, task: GetItemAttributesTask, future: Future):
        try:
            attributes = future.result()
        except Exception:
            logger.exception(f"exception fetching shared item attributes : {task!r}")
        else:
            task.shared_item.attributes = attributes

    def remove_shared_directory(self, shared_directory: str):
        """Removes a shared directory. This method will
            - remove the alias from `directory_aliases`
            - remove all shared items with the `root` as the alias
            - rebuild the `term_map`

        :param shared_directory: path of the shared directory to be removed (
            not the alias)
        """
        shared_dir_abs = os.path.abspath(shared_directory)

        with self._shared_items_lock:
            aliases_rev = {v: k for k, v in self.directory_aliases.items()}
            alias = aliases_rev[shared_dir_abs]

            self.shared_items -= {
                item for item in self.shared_items if item.root == alias
            }

        with self._directory_lock:
            del self.directory_aliases[alias]

    def resolve_path(self, item: SharedItem) -> str:
        """Resolves the absolute path of the given `item`

        :param item: `SharedItem` instance to be resolved
        :return: absolute path to the shared item
        """
        root_path = self.directory_aliases[item.root]
        return os.path.join(root_path, item.subdir, item.filename)

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

            found_items = found_items.intersection(term_items)

            if not found_items:
                return []

        return list(found_items)

    def get_stats(self) -> Tuple[int, int]:
        """Gets the total amount of shared directories and files.

        Directory count will include the root directories only if they contain
        files.

        :return: Directory and file count as a C{tuple}
        """
        file_count = len(self.shared_items)
        dir_count = len(set(shared_item.subdir for shared_item in self.shared_items))
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
        directories = {}
        for item in self.shared_items:
            directory = item.get_remote_directory_path()
            if directory in directories:
                directories[directory].append(item)
            else:
                directories[directory] = [item, ]

        # Create shares reply
        shares_reply = []
        for directory, files in directories.items():
            shares_reply.append(
                DirectoryData(
                    name=directory,
                    files=self.convert_items_to_file_data(files, use_full_path=False)
                )
            )

        return shares_reply

    def convert_item_to_file_data(
            self, shared_item: SharedItem, use_full_path=True) -> FileData:
        """Convert a L{SharedItem} object to a L{FileData} object

        :param use_full_path: use the full path of the file as 'filename' if
            C{True} sotherwise use just the filename. Should be false when
            generating a shares reply, true when generating search reply
        """
        file_path = self.resolve_path(shared_item)
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(shared_item.filename)[-1]
        if not shared_item.attributes:
            attributes = []
        else:
            attributes = shared_item.attributes

        return FileData(
            unknown=1,
            filename=shared_item.get_remote_path() if use_full_path else shared_item.filename,
            filesize=file_size,
            extension=file_ext,
            attributes=attributes
        )

    def convert_items_to_file_data(self, shared_items: List[SharedItem], use_full_path=True) -> List[FileData]:
        """Converts a list of L{SharedItem} instances to a list of L{FileData}
        instances. If an exception occurs when converting the item an error will be
        logged and the item will be omitted from the list
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
