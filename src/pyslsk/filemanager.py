from dataclasses import dataclass, field
import logging
import mutagen
from mutagen.mp3 import BitrateMode
import os
import re
from typing import List, Tuple

from .messages import DirectoryData, FileData

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


@dataclass
class SharedItem:
    root: str
    subdir: str
    filename: str
    query_components: List[str] = field(init=False)
    """The shared item split up into components to make it more performant to
    query
    """

    def __post_init__(self):
        path = (self.subdir + "/" + self.filename).lower()
        path = re.sub(_QUERY_WORD_SEPERATORS, ' ', path)
        self.query_components = path.split()


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


def convert_item_to_file_data(shared_item: SharedItem, use_full_path=True) -> FileData:
    """Convert a L{SharedItem} object to a L{FileData} object

    @param use_full_path: use the full path of the file as 'filename' if C{True}
        otherwise use just the filename
    """
    file_path = os.path.join(shared_item.root, shared_item.subdir, shared_item.filename)
    file_size = os.path.getsize(file_path)
    file_ext = os.path.splitext(shared_item.filename)[-1]
    # attributes = extract_attributes(file_path)

    return FileData(
        unknown=1,
        filename=file_path if use_full_path else shared_item.filename,
        filesize=file_size,
        extension=file_ext,
        attributes=[]
    )


def convert_items_to_file_data(shared_items: List[SharedItem], use_full_path=True) -> List[FileData]:
    """Converts a list of L{SharedItem} instances to a list of L{FileData}
    instances. If an exception occurs when converting the item an error will be
    logged and the item will be omitted from the list
    """
    file_datas = []
    for shared_item in shared_items:
        try:
            file_datas.append(
                convert_item_to_file_data(shared_item, use_full_path=use_full_path)
            )
        except OSError:
            logger.exception(f"failed to convert to result : {shared_item!r}")

    return file_datas


class FileManager:

    def __init__(self, settings):
        self.settings = settings
        self.shared_items = self.fetch_shared_items()

    def fetch_shared_items(self) -> List[SharedItem]:
        shared_items = []
        for shared_dir in self.settings['directories']:
            shared_dir_abs = os.path.abspath(shared_dir)

            for directory, _, files in os.walk(shared_dir):
                subdir = os.path.relpath(directory, shared_dir_abs)
                if subdir == '.':
                    subdir = ''

                for filename in files:
                    shared_items.append(
                        SharedItem(shared_dir_abs, subdir, filename)
                    )
        return shared_items

    def get_shared_item(self, filename: str) -> SharedItem:
        """Gets a shared item from the cache based on the given file path. If
        the file does not exist in the L{shared_items} or the file is present
        in the cache but does not exist on disk a C{LookupError} is raised.

        This method should be called when an upload is requested from the user
        """
        for item in self.shared_items:
            if os.path.join(item.root, item.subdir, item.filename) == filename:
                if not os.path.exists(filename):
                    raise LookupError(f"file name {filename} found in cache but not on disk")
                return item
        else:
            raise LookupError(f"file name {filename} not found in shared items")

    def get_filesize(self, filename: str) -> int:
        return os.path.getsize(filename)

    def query(self, query: str) -> List[SharedItem]:
        """Queries the L{shared_items}.

        1. Transform query into terms:
            - will be split up (whitespace)
            - lowercased
            - non-alphanumeric characters stripped
        2. Shared items:
            - subdir and filename will be concatenated
            - will be split up ( seperators can be: -_,./ )
            - clean up the terms
        3. Loop over all the terms from the query and check if all match with
            with the terms in any of the shared items (any order)
        """
        terms = [re.sub(_QUERY_CLEAN_PATTERN, '', term.lower()) for term in query.split()]

        found_items = []
        for shared_item in self.shared_items:
            if all(term in shared_item.query_components for term in terms):
                found_items.append(shared_item)

        return found_items

    def get_stats(self) -> Tuple[int, int]:
        """Gets the total amount of shared directories and files.

        Directory count will include the root directories only if they contain
        files.

        @return: Directory and file count as a C{tuple}
        """
        file_count = len(self.shared_items)
        dir_count = len(set([shared_item.subdir for shared_item in self.shared_items]))
        return dir_count, file_count

    def get_download_path(self, filename: str):
        """Gets the download path for a filename returned by another peer"""
        download_dir = self.settings['download']
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)

        return os.path.join(download_dir, os.path.basename(filename))

    def create_shares_reply(self) -> List[DirectoryData]:
        # Sort files under unique directories
        directories = {}
        for item in self.shared_items:
            directory = os.path.join(item.root, item.subdir)
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
                    files=convert_items_to_file_data(files, use_full_path=False)
                )
            )

        return shares_reply
