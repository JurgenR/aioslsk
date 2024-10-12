import os
import re

from .utils import split_remote_path


class NamingStrategy:
    NAME = None

    def should_be_applied(self, local_dir: str, local_filename: str) -> bool:
        return True

    def apply(self, remote_path: str, local_dir: str, local_filename: str) -> tuple[str, str]:
        """Apply the naming changes

        :param remote_path: the original remote path
        :param local_dir: the local directory the file should be written to
        :param local_filename: the local filename the file should be written to
        :return: the `local_dir` and `local_filename` after applying the desired
            changes
        """
        raise NotImplementedError("'apply' should be overwritten by a subclass")


class DefaultNamingStrategy(NamingStrategy):
    """The default naming strategy determines the filename using the
    `remote_path` parameter. The `local_filename` parameter is ignored
    """

    def apply(self, remote_path: str, local_dir: str, local_filename: str) -> tuple[str, str]:
        return local_dir, split_remote_path(remote_path)[-1]


class KeepDirectoryStrategy(NamingStrategy):
    """Keeps the original directory the remote file was in"""

    def apply(self, remote_path: str, local_dir: str, local_filename: str) -> tuple[str, str]:
        # -1 filename
        # -2 the containing directory
        remote_path_parts = split_remote_path(remote_path)

        # Only a filename (not sure if this can occur)
        if len(remote_path_parts) == 1:
            return local_dir, local_filename

        # Ignore directories starting with '@@' or Windows drives (C:, D:)
        contained_dir = remote_path_parts[-2]
        if contained_dir.startswith('@@'):
            return local_dir, local_filename

        elif re.match(r'[a-zA-Z]{1}:', contained_dir) is not None:
            return local_dir, local_filename

        return os.path.join(local_dir, contained_dir), local_filename


class DuplicateNamingStrategy(NamingStrategy):

    def should_be_applied(self, local_dir: str, local_filename: str) -> bool:
        return os.path.exists(os.path.join(local_dir, local_filename))


class NumberDuplicateStrategy(DuplicateNamingStrategy):
    """Duplicate name strategy that appends a number to the filename in case it
    already exists
    """
    PATTERN = r' \((\d+)\)'

    def apply(self, remote_path: str, local_dir: str, local_filename: str) -> tuple[str, str]:
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


def chain_strategies(strategies: list[NamingStrategy], remote_path: str, local_dir: str) -> tuple[str, str]:
    """Chains strategies together to find the target location and filename to
    which the file should be written.

    :param strategies: list of strategies to apply
    :param remote_path: the full remote path
    :param local_dir: initial local path, this should be the initial download
        directory
    :return: tuple with the path and filename
    """
    path = local_dir
    filename = ''
    for strategy in strategies:
        if strategy.should_be_applied(path, filename):
            path, filename = strategy.apply(remote_path, path, filename)
    return path, filename
