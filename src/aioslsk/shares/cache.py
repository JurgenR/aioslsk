import os
import shelve
from typing import Protocol
from .model import SharedDirectory


class SharesCache(Protocol):
    """Abstract base class for storing shares"""

    def read(self) -> list[SharedDirectory]:
        ...

    def write(self, shared_directories: list[SharedDirectory]):
        ...


class SharesNullCache:

    def read(self) -> list[SharedDirectory]:  # pragma: no cover
        return []

    def write(self, shared_directories: list[SharedDirectory]):  # pragma: no cover
        pass


class SharesShelveCache:
    """Shares cache that uses the Python built-in `shelve` module"""
    DEFAULT_FILENAME = 'shares_index'

    def __init__(self, data_directory: str, filename: str = DEFAULT_FILENAME):
        self.data_directory: str = data_directory
        self.filename: str = filename

    def _get_index_path(self) -> str:
        return os.path.join(self.data_directory, self.filename)

    def read(self) -> list[SharedDirectory]:
        with shelve.open(self._get_index_path(), 'c') as db:
            directories: list[SharedDirectory] = db.get('index', list())
            for directory in directories:
                new_items = set()
                for item in directory.items:
                    item.shared_directory = directory
                    new_items.add(item)
                directory.items = new_items
            return directories

    def write(self, shared_directories: list[SharedDirectory]):
        with shelve.open(self._get_index_path(), 'c') as db:
            db['index'] = shared_directories
