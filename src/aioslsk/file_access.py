"""File access relative to a user-configured transfer directory."""
from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from typing import Optional


def validate_component(name: str) -> None:
    if not name or name in ('.', '..') or '\x00' in name:
        raise OSError("invalid transfer path component")
    if os.name == 'nt':
        if hasattr(os.path, 'isreserved'):  # Added in Python 3.13
            reserved = os.path.isreserved(name)
        else:
            reserved = PureWindowsPath(name).is_reserved()
        if reserved or re.search(r'[<>:"|?*\x00-\x1f]|[. ]$', name):
            raise OSError("invalid Windows transfer path component")


@contextmanager
def _parent(root: str, filename: str, create: bool = False) -> Iterator[tuple[Optional[int], str]]:
    # Keep the original components: resolving or normalizing first would hide
    # parent references. All callers supply paths below an absolute root.
    try:
        parts = Path(filename).relative_to(root).parts
    except ValueError as exc:
        raise OSError("transfer path outside configured directory") from exc
    if not parts:
        raise OSError("transfer path requires a filename")
    for part in parts:
        validate_component(part)
    if create:
        os.makedirs(root, exist_ok=True)

    if os.name == 'posix':
        flags = os.O_DIRECTORY | os.O_RDONLY
        fd = os.open(root, flags)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, parts[-1]
        finally:
            os.close(fd)
    else:
        # Windows has no dir_fd support. Reject reparse points, including
        # junctions, beneath the user-selected root.
        path = root
        for index, part in enumerate(parts):
            path = os.path.join(path, part)
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                if index < len(parts) - 1 and create:
                    os.mkdir(path)
                continue
            if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("reparse point in transfer path")
        yield None, path


def open_transfer_file(root: str, filename: str, flags: int) -> int:
    """Opener for builtins.open / aiofiles.open that accepts regular files only."""
    with _parent(root, filename, create=bool(flags & os.O_CREAT)) as (parent, name):
        flags |= getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(name, flags, 0o666, dir_fd=parent)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("transfer path is not a regular file")
            return fd
        except BaseException:
            os.close(fd)
            raise


def transfer_stat(root: str, filename: str) -> os.stat_result:
    with _parent(root, filename) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("transfer path is not a regular file")
        return info


def unlink_download(root: str, filename: str) -> None:
    with _parent(root, filename) as (parent, name):
        os.unlink(name, dir_fd=parent)
