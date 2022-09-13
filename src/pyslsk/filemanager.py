from dataclasses import dataclass
import logging
import mutagen
from mutagen.mp3 import BitrateMode
import os
import re
import sys
from typing import Dict, List, Tuple
import uuid

from .exceptions import FileNotSharedError
from .messages import DirectoryData, FileData
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


@dataclass(eq=True, frozen=True)
class SharedItem:
    root: str
    subdir: str
    filename: str
    # attributes: bytes = field(init=False, compare=False)

    def get_remote_path(self):
        return '@@' + os.path.join(self.root, self.subdir, self.filename)

    def get_remote_directory_path(self):
        return '@@' + os.path.join(self.root, self.subdir)


def extract_attributes(filepath: str):
    """Attempts to extract attributes from the file at L{filepath}"""
    attributes = []
    try:
        mutagen_file = mutagen.File(filepath)
        if mutagen_file is not None:
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


class FileManager:
    _ALIAS_LENGTH = 5

    def __init__(self, settings: Settings):
        self._settings: Settings = settings
        self.term_map: Dict[str, List[SharedItem]] = {}
        self.shared_items: List[SharedItem] = []
        self.directory_aliases: Dict[str, str] = {}
        self.load_from_settings()
        self.build_term_map()

    def generate_alias(self, path: str, offset=0):
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

    def build_term_map(self):
        for item in self.shared_items:
            path = (item.subdir + "/" + item.filename).lower()
            path = re.sub(_QUERY_WORD_SEPERATORS, ' ', path)
            terms = path.split()
            for term in terms:
                term = re.sub(_QUERY_CLEAN_PATTERN, '', term)
                if term in self.term_map:
                    self.term_map[term].append(item)
                else:
                    self.term_map[term] = [item, ]

    def get_shared_item(self, filename: str) -> SharedItem:
        """Gets a shared item from the cache based on the given file path. If
        the file does not exist in the L{shared_items} or the file is present
        in the cache but does not exist on disk a C{LookupError} is raised.

        This method should be called when an upload is requested from the user
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
        # Calc absolute path, generate an alias and store it
        shared_dir_abs = os.path.abspath(shared_directory)
        shared_dir_alias = self.generate_alias(shared_dir_abs)
        self.directory_aliases[shared_dir_alias] = shared_dir_abs

        for directory, _, files in os.walk(shared_directory):
            subdir = os.path.relpath(directory, shared_dir_abs)
            if subdir == '.':
                subdir = ''

            for filename in files:
                self.shared_items.append(
                    SharedItem(shared_dir_alias, subdir, filename)
                )

    def remove_shared_directory(self, shared_directory: str):
        shared_dir_abs = os.path.abspath(shared_directory)

        aliases_rev = {v: k for k, v in self.directory_aliases.items()}
        alias = aliases_rev[shared_dir_abs]
        self.shared_items = [
            item for item in self.shared_items
            if item.root != alias
        ]
        del self.directory_aliases[alias]

    def resolve_path(self, item: SharedItem) -> str:
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

        found_items = None
        for term in terms:
            clean_term = re.sub(_QUERY_CLEAN_PATTERN, '', term.lower())
            if clean_term not in self.term_map:
                return []

            term_items = set(self.term_map[clean_term])

            if not found_items:
                found_items = term_items
            else:
                found_items = found_items.intersection(term_items)

            if not found_items:
                return []

        return list(found_items)

    def get_stats(self) -> Tuple[int, int]:
        """Gets the total amount of shared directories and files.

        Directory count will include the root directories only if they contain
        files.

        @return: Directory and file count as a C{tuple}
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

    def convert_item_to_file_data(self, shared_item: SharedItem, use_full_path=True) -> FileData:
        """Convert a L{SharedItem} object to a L{FileData} object

        @param use_full_path: use the full path of the file as 'filename' if C{True}
            otherwise use just the filename
        """
        file_path = self.resolve_path(shared_item)
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(shared_item.filename)[-1]
        attributes = extract_attributes(file_path)

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
