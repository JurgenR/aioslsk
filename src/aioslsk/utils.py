import itertools
import logging
from typing import List

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
            logger.warning(f"failed to decode string {value!r}")
            raise


def get_duration(attributes: List[Attribute]):
    duration = ''
    for attr in attributes:
        if attr.key == 1:
            minutes, seconds = divmod(attr.value, 60)
            hours, minutes = divmod(minutes, 60)
            duration = f"{hours}h {minutes}m {seconds}s"
            break
    return duration


def get_attribute_string(attributes: List[Attribute]):
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


def ticket_generator(initial: int = 1234) -> int:
    idx = initial
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = initial
        yield idx