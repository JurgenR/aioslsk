from collections import namedtuple
import logging
import mutagen
from mutagen.mp3 import BitrateMode
import os
import re

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

SharedItem = namedtuple('SharedItem', ['root', 'subdir', 'filename'])


def convert_to_result(shared_item):
    file_path = os.path.join(shared_item.root, shared_item.subdir, shared_item.filename)
    file_size = os.path.getsize(file_path)
    file_ext = os.path.splitext(shared_item.filename)[-1]

    attributes = []
    try:
        mutagen_file = mutagen.File(file_path)
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
        logger.exception(f"failed retrieve audio file metadata path={file_path!r}")

    return {
        'filename': file_path,
        'filesize': file_size,
        'file_ext': file_ext,
        'attributes': attributes
    }


def convert_to_results(shared_items):
    results = []
    for shared_item in shared_items:
        try:
            results.append(convert_to_result(shared_item))
        except OSError:
            logger.exception(f"failed to convert to result : {shared_item!r}")
    return results


class FileManager:

    def __init__(self, settings):
        self.settings = settings
        self.shared_items = self.fetch_shared_items()

    def fetch_shared_items(self):
        shared_items = []
        for shared_dir in self.settings['directories']:
            shared_dir_abs = os.path.abspath(shared_dir)
            for directory, subdirs, files in os.walk(shared_dir):
                subdir = os.path.relpath(directory, shared_dir_abs)
                for filename in files:
                    shared_items.append(SharedItem(shared_dir_abs, subdir, filename))
        return shared_items

    def query(self, query):
        clean_pattern = re.compile(r"[^\w\d]")

        # When looking through files, take -, _ and / as word seperators
        word_seperators = re.compile(r"[\-_\/\.,]")

        terms = [re.sub(clean_pattern, '', term.lower()) for term in query.split()]

        found_items = []
        for shared_item in self.shared_items:
            path = (shared_item.subdir + "/" + shared_item.filename).lower()
            path = re.sub(word_seperators, ' ', path)
            path_components = path.split()
            if all([term in path_components for term in terms]):
                found_items.append(shared_item)

        return found_items

    def get_stats(self):
        file_count = len(self.shared_items)
        dir_count = len(set([shared_item.subdir for shared_item in self.shared_items]))
        return dir_count, file_count
