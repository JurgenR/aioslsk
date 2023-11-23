from __future__ import annotations
import logging
import os
import re
from typing import List, TYPE_CHECKING

from ..constants import PATH_SEPERATOR_PATTERN
from ..protocol.primitives import Attribute, FileData

if TYPE_CHECKING:
    from .model import SharedItem


logger = logging.getLogger(__name__)


def normalize_remote_path(path: str) -> str:
    return re.sub(PATH_SEPERATOR_PATTERN, '\\\\', path).rstrip('\\/')


def create_term_pattern(term: str, wildcard=False):
    if wildcard:
        return re.compile(
            r"(?:(?<=\W|_)|^)[^\W_]*{}(?=[\W_]|$)".format(re.escape(term)),
            flags=re.IGNORECASE
        )
    else:
        return re.compile(
            r"(?:(?<=\W|_)|^){}(?=[\W_]|$)".format(re.escape(term)),
            flags=re.IGNORECASE
        )


def convert_item_to_file_data(
        shared_item: SharedItem, use_full_path: bool = True) -> FileData:
    """Convert a `SharedItem` object to a `FileData` object

    :param use_full_path: use the full path of the file as `filename` if
        `True` otherwise use just the filename. Should be `False` when
        generating a shares reply, `True` when generating search reply
    :return: the converted data
    :raise OSError: raised when an error occurred accessing the file
    """
    file_path = shared_item.get_absolute_path()
    file_size = os.path.getsize(file_path)
    file_ext = os.path.splitext(shared_item.filename)[-1][1:]
    if shared_item.attributes:
        attributes = [Attribute(*attr) for attr in shared_item.attributes]
    else:
        attributes = []

    return FileData(
        unknown=1,
        filename=shared_item.get_remote_path() if use_full_path else shared_item.filename,
        filesize=file_size,
        extension=file_ext,
        attributes=attributes
    )


def convert_items_to_file_data(shared_items: List[SharedItem], use_full_path=True) -> List[FileData]:
    """Converts a list of L{SharedItem} instances to a list of L{FileData}
    instances. If an exception occurs when converting the item an error will
    be logged and the item will be omitted from the list
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
