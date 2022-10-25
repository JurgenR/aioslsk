from dataclasses import dataclass, field
from typing import ClassVar
from pyslsk.protocol.primitives import decode_string, uint32, MessageDataclass
import pytest


@dataclass(order=True)
class MismatchMessageId(MessageDataclass):
    MESSAGE_ID: ClassVar[uint32] = uint32(0x01)


@dataclass(order=True)
class FieldWithoutType(MessageDataclass):
    MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
    username: str = field(metadata={})


class TestPrimitives:

    def test_whenDecodeString_utf8_shouldDecode(self):
        a_string = "test \u4E20"
        assert a_string == decode_string(a_string.encode('utf8'))

    def test_whenDecodeString_cp1252_shouldDecode(self):
        a_string = "test \xF1"
        assert a_string == decode_string(a_string.encode('cp1252'))


class TestMessageDataclass:

    def test_whenDeserialize_mismatchMessageId_shouldRaise(self):
        data = bytes.fromhex('0400000002000000')
        with pytest.raises(Exception):
            MismatchMessageId.deserialize(data)

    def test_whenSerialize_fieldWithoutType_shouldRaise(self):
        with pytest.raises(Exception):
            FieldWithoutType('test').serialize()

    def test_whenDeserialize_fieldWithoutType_shouldRaise(self):
        data = bytes.fromhex('04000000010000000100000030')
        with pytest.raises(Exception):
            FieldWithoutType.deserialize(data)

