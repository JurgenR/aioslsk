from dataclasses import dataclass, field
import enum
import os
from typing import Optional, Union

from ..exceptions import FileNotFoundError
from .utils import normalize_remote_path


class DirectoryShareMode(enum.Enum):
    """Share mode for directories. The mode determines for who the results are
    locked and who can download the file
    """
    EVERYONE = 'everyone'
    FRIENDS = 'friends'
    USERS = 'users'


@dataclass(eq=True, unsafe_hash=True)
class SharedDirectory:
    """Class representing a directory that is explicitly shared by the user.
    This class holds information on how the directory is shared and is a
    container for shared items within this directory.
    """
    directory: str
    absolute_path: str
    alias: str
    share_mode: DirectoryShareMode = field(default=DirectoryShareMode.EVERYONE, compare=False, hash=False)
    users: list[str] = field(default_factory=list, compare=False, hash=False)
    items: set['SharedItem'] = field(default_factory=set, init=False, compare=False, hash=False, repr=False)

    def is_parent_of(self, directory: Union[str, 'SharedDirectory']) -> bool:
        """Returns true if the current directory is any parent of the passed
        shared directory

        :param directory: directory to test, if this directory is of ``str``
            type it should be an absolute path. If it is of
            :class:`.SharedDirectory` type the ``absolute_path`` will be taken
        """
        path = directory if isinstance(directory, str) else directory.absolute_path
        return os.path.commonpath([path, self.absolute_path]) == self.absolute_path

    def is_child_of(self, directory: Union[str, 'SharedDirectory']) -> bool:
        """Returns true if the passed directory is a (sub)child of the current
        directory

        :param directory: directory to test, if this directory is of ``str``
            type it should be an absolute path. If it is of
            :class:`.SharedDirectory` type the ``absolute_path`` will be taken
        """
        path = directory if isinstance(directory, str) else directory.absolute_path
        return os.path.commonpath([self.absolute_path, path]) == path

    def get_remote_path(self) -> str:
        return '@@' + self.alias

    def get_item_by_remote_path(self, remote_path: str) -> 'SharedItem':
        """Returns the :class:`.SharedItem` instance belonging to the passed
        ``remote_path``

        :raise FileNotFoundError: when the item cannot be found in the set of
            `items`
        """
        for item in self.items:
            if item.get_remote_path() == remote_path:
                return item
        else:
            raise FileNotFoundError(
                f"file with remote path {remote_path!r} not found in directory {self!r}")

    def get_items_for_directory(self, directory: 'SharedDirectory') -> set['SharedItem']:
        """Gets items in the current directory that are part of given directory
        """
        return {
            item for item in self.items
            if os.path.commonpath([directory.absolute_path, item.get_absolute_path()]) == directory.absolute_path
        }


@dataclass(eq=True, unsafe_hash=True)
class SharedItem:
    shared_directory: SharedDirectory
    subdir: str
    filename: str
    modified: float
    attributes: Optional[list[tuple[int, int]]] = field(
        default=None,
        init=False,
        compare=False,
        hash=False
    )

    def get_absolute_path(self) -> str:
        """Returns the absolute path of the shared item"""
        return os.path.join(
            self.shared_directory.absolute_path, self.subdir, self.filename)

    def get_remote_path(self) -> str:
        """Returns the full remote path of this file.

        :return: Full remote file path: Example: "@@abcde\\Music\\song.mp3"
        """
        return normalize_remote_path(
            '@@' + os.path.join(self.shared_directory.alias, self.subdir, self.filename))

    def get_remote_directory_path(self) -> str:
        """Returns the remote directory path this file resides in

        :return: Remote directory path. Example: "@@abcde\\Music"
        """
        return normalize_remote_path(
            '@@' + os.path.join(self.shared_directory.alias, self.subdir))

    def get_remote_directory_path_parts(self) -> tuple[str, ...]:
        """Returns the remote directory path split into parts"""
        return tuple(self.get_remote_directory_path().split('\\'))

    def get_query_path(self) -> str:
        """Returns the query-able part of the shared item

        :return: Queryable path of the item. Example: "Music\\Metal\\Song.mp3"
        """
        return normalize_remote_path(os.path.join(self.subdir, self.filename))

    def __getstate__(self):
        fields = self.__dict__.copy()
        fields['shared_directory'] = None
        return fields
