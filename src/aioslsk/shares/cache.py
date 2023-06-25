import os
import shelve
from typing import List
from .model import SharedDirectory


class SharesCache:
    """Abstract base class for storing shares"""

    def read(self) -> List[SharedDirectory]:
        raise NotImplementedError(
            "'read' needs to be overwritten in a subclass")

    def write(self, shared_directories: List[SharedDirectory]):
        raise NotImplementedError(
            "'write' needs to be overwritten in a subclass")


class SharesShelveCache(SharesCache):
    DEFAULT_FILENAME = 'shares_index'

    def __init__(self, data_directory: str):
        self.data_directory: str = data_directory

    def _get_index_path(self) -> str:
        return os.path.join(self.data_directory, self.DEFAULT_FILENAME)

    def read(self) -> List[SharedDirectory]:
        with shelve.open(self._get_index_path(), 'c') as db:
            directories = db.get('index', list())
            for directory in directories:
                new_items = set()
                for item in directory.items:
                    item.shared_directory = directory
                    new_items.add(item)
                directory.items = new_items
            return directories

    def write(self, shared_directories: List[SharedDirectory]):
        with shelve.open(self._get_index_path(), 'c') as db:
            db['index'] = shared_directories
