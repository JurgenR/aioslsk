import os
import shelve
from typing import List, Protocol
from .model import SharedDirectory


class SharesCache(Protocol):
    """Abstract base class for storing shares"""

    def read(self) -> List[SharedDirectory]:
        ...

    def write(self, shared_directories: List[SharedDirectory]):
        ...


class SharesNullCache:

    def read(self) -> List[SharedDirectory]:  # pragma: no cover
        return []

    def write(self, shared_directories: List[SharedDirectory]):  # pragma: no cover
        pass


class SharesShelveCache:
    DEFAULT_FILENAME = 'shares_index'

    def __init__(self, data_directory: str):
        self.data_directory: str = data_directory

    def _get_index_path(self) -> str:
        return os.path.join(self.data_directory, self.DEFAULT_FILENAME)

    def read(self) -> List[SharedDirectory]:
        with shelve.open(self._get_index_path(), 'c') as db:
            directories: List[SharedDirectory] = db.get('index', list())
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
