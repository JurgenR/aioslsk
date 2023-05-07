from aioslsk.protocol.primitives import Attribute
from aioslsk.utils import (
    get_attribute_string,
    get_duration,
    normalize_remote_path,
    split_remote_path,
    ticket_generator,
    try_decoding,
)

import pytest


class TestUtils:

    @pytest.mark.parametrize(
        "duration,expected",
        [
            (0, '0h 0m 0s'),
            (120, '0h 2m 0s'),
            (7200, '2h 0m 0s'),
            (7200 + (30 * 60) + 5, '2h 30m 5s'),
        ]
    )
    def test_whenGetDuration_shouldReturnDuration(self, duration: int, expected: str):
        attributes = [Attribute(1, duration)]
        duration_str = get_duration(attributes)
        assert expected == duration_str

    def test_whenTicketGenerator_shouldGetNextTicket(self):
        ticket_gen = ticket_generator(initial=0)
        assert next(ticket_gen) == 1

    def test_whenTicketGeneratorAtMax_shouldRestartAtZero(self):
        ticket_gen = ticket_generator(initial=0xFFFFFFFE)
        assert next(ticket_gen) == 0xFFFFFFFF
        assert next(ticket_gen) == 0xFFFFFFFE

    def test_whenGetAttributeString_shouldReturnString(self):
        attrs = [
            Attribute(0, 320),
            Attribute(2, 1),
            Attribute(4, 5000),
            Attribute(5, 4)
        ]
        assert get_attribute_string(attrs) == "320kbps VBR 5.0kHz 4ch"

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("basic", "basic"),
            ("test \u4E20".encode('utf8'), "test \u4E20"),
            ("test \xF1".encode('cp1252'), "test \xF1")
        ]
    )
    def test_whenTryDecoding_shouldDecode(self, value: bytes, expected: str):
        assert try_decoding(value) == expected

    def test_whenTryDecoding_unknownEncoding_shouldRaise(self):
        with pytest.raises(Exception):
            try_decoding(bytes([0x8f]))

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("aaa/bbb/ccc", "aaa\\bbb\\ccc"),
            ("aaa\\bbb/ccc", "aaa\\bbb\\ccc"),
            ("aaa\\\\bbb/ccc", "aaa\\bbb\\ccc"),
            ("aaa\\bbb//ccc", "aaa\\bbb\\ccc"),
        ]
    )
    def test_normalizeRemotePath(self, value: str, expected: str):
        assert expected == normalize_remote_path(value)

    @pytest.mark.parametrize(
        "value",
        [
            ("aaa/bbb/ccc"),
            ("aaa\\bbb\\ccc"),
            ("aaa\\\\bbb/ccc"),
            ("aaa\\bbb//ccc"),
            ("aaa/bbb/ccc/"),
            ("aaa\\bbb\\ccc\\"),
        ]
    )
    def test_splitRemotePath(self, value: str):
        assert ['aaa', 'bbb', 'ccc'] == split_remote_path(value)
