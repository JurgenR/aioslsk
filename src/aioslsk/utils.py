import asyncio
from collections.abc import Generator
import itertools
import logging
import re
from typing import Optional

from .constants import PATH_SEPERATOR_PATTERN
from .protocol.primitives import Attribute


logger = logging.getLogger(__name__)
task_counter = itertools.count(1).__next__


def try_decoding(value: bytes):
    if isinstance(value, str):
        return value
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return value.decode('cp1252')
        except Exception:
            logger.warning("failed to decode string : %r", value)
            raise


def split_remote_path(path: str) -> list[str]:
    """Splits a remote path into parts. Empty parts will be filtered out"""
    return [part for part in re.split(PATH_SEPERATOR_PATTERN, path) if part]


def get_duration(attributes: list[Attribute]) -> str:
    duration = ''
    for attr in attributes:
        if attr.key == 1:
            minutes, seconds = divmod(attr.value, 60)
            hours, minutes = divmod(minutes, 60)
            duration = f"{hours}h {minutes}m {seconds}s"
            break
    return duration


def get_attribute_string(attributes: list[Attribute]) -> str:
    """Returns an attributes list to a string (excludes duration)"""
    attr_str = []
    for attr in attributes:
        if attr.key == 0:
            attr_str.append(f"{attr.value}kbps")
        elif attr.key == 2:
            attr_str.append('CBR' if attr.value == 0 else 'VBR')
        elif attr.key == 4:
            attr_str.append(f"{(attr.value / 1000):.1f}kHz")
        elif attr.key == 5:
            attr_str.append(f"{attr.value}ch")

    return ' '.join(attr_str)


def ticket_generator(initial: int = 1) -> Generator[int, None, None]:
    """Generator for tickets to be used in various protocol messages. The
    generator will be reset to the ``initial`` value once the value would exceed
    2 ^ 32
    """
    idx = initial
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = initial
        yield idx


async def cancel_task(task: Optional[asyncio.Task]):
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
