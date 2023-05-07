import os
import re
from typing import List, Tuple


class NamingStrategy:
    NAME = None

    def should_be_applied(self, local_dir: str, local_filename: str) -> bool:
        return True

    def apply(self, remote_dir: str, remote_filename: str, local_dir: str, local_filename: str) -> Tuple[str, str]:
        raise NotImplementedError("'apply' should be overwritten by a subclass")


class DefaultNamingStrategy(NamingStrategy):
    """The default naming strategy just uses the filename"""

    def apply(self, remote_dir: str, remote_filename: str, local_dir: str, local_filename: str) -> Tuple[str, str]:
        return local_dir, remote_filename


class KeepDirectoryStrategy(NamingStrategy):
    """Keeps the original directory the remote file was in"""

    def apply(self, remote_dir: str, remote_filename: str, local_dir: str, local_filename: str) -> Tuple[str, str]:

        return os.path.join(local_dir, )


class DuplicateNamingStrategy(NamingStrategy):

    def should_be_applied(self, local_dir: str, local_filename: str) -> bool:
        return os.path.exists(os.path.join(local_dir, local_filename))


class NumberDuplicateStrategy(DuplicateNamingStrategy):
    """Duplicate name strategy that appends a number to the filename in case it
    already exists
    """
    PATTERN = r' \((\d+)\)'

    def apply(self, remote_dir: str, remote_filename: str, local_dir: str, local_filename: str) -> Tuple[str, str]:
        # Find all files which are already numbered
        filename, extension = os.path.splitext(local_filename)
        pattern = re.escape(filename) + self.PATTERN + re.escape(extension)
        indices = []
        for path_file in os.listdir(local_dir):
            if (match := re.match(pattern, path_file)) is not None:
                indices.append(int(match.group(1)))

        # Find the next free index
        next_index = 1
        if indices:
            # +1 to include the max, +2 so that we get the next one in case all
            # indices are already taken
            possible_indices = set(range(min(indices), max(indices) + 2))
            next_index = min(possible_indices - set(indices))

        new_filename = f"{filename} ({next_index}){extension}"
        return local_dir, new_filename


def chain_strategies(strategies: List[NamingStrategy], remote_dir: str, remote_filename: str, local_dir: str) -> Tuple[str, str]:
    """Chains strategies together to find the target location and filename to
    which the file should be written.

    :param strategies: list of strategies to apply
    :param remote_dir: the remote path
    :param remote_filename: the remote filename
    :param local_dir: initial local path, this should be the initial download
        directory
    :return: tuple with the path and filename
    """
    path = local_dir
    filename = None
    for strategy in strategies:
        if strategy.should_be_applied(path, filename):
            path, filename = strategy.apply(
                remote_dir, remote_filename, path, filename)
    return path, filename
