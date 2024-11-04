from dataclasses import dataclass, field
import logging
from typing import ClassVar
import pytest

from aioslsk.protocol.primitives import (
    decode_string,
    Attribute,
    AttributeKey,
    FileData,
    MessageDataclass,
    uint32,
)


logger = logging.getLogger()


@dataclass(order=True)
class SimpleMessage(MessageDataclass):
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

    def test_whenDeserialize_andHasUnparsedBytes_shouldWarn(self, caplog):
        data = bytes.fromhex('0400000001000000ff')
        SimpleMessage.deserialize(0, data)
        assert len(caplog.records) >= 1
        assert caplog.records[-1].levelname == 'WARNING'
        assert 'message has 1 unparsed bytes' in caplog.records[-1].getMessage()

    def test_whenDeserialize_mismatchMessageId_shouldRaise(self):
        data = bytes.fromhex('0400000002000000')
        with pytest.raises(Exception):
            SimpleMessage.deserialize(0, data)

    def test_whenSerialize_fieldWithoutType_shouldRaise(self):
        with pytest.raises(Exception):
            FieldWithoutType('test').serialize()

    def test_whenDeserialize_fieldWithoutType_shouldRaise(self):
        data = bytes.fromhex('04000000010000000100000030')
        with pytest.raises(Exception):
            FieldWithoutType.deserialize(0, data)


class TestFileData:

    def test_getAttributeMap(self):
        attrs = [
            Attribute(0, 320),
            Attribute(1, 120),
            Attribute(2, 1),
            Attribute(4, 44100),
            Attribute(5, 24),
            # Unknown value
            Attribute(10, 10)
        ]
        file_data = FileData(1, 'test', 2, '', attrs)

        assert file_data.get_attribute_map() == {
            AttributeKey.BITRATE: 320,
            AttributeKey.DURATION: 120,
            AttributeKey.VBR: 1,
            AttributeKey.SAMPLE_RATE: 44100,
            AttributeKey.BIT_DEPTH: 24
        }
