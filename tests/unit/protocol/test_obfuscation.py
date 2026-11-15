from math import ceil
import random

from aioslsk.protocol.obfuscation import KEY_SIZE, decode, encode, generate_key, rotate_key

import pytest


def reference_decode(data: bytes) -> bytes:
    """Byte-by-byte implementation of the de-obfuscation, used to verify the
    optimized implementation produces identical output
    """
    key = data[:KEY_SIZE]
    message = bytearray(data[KEY_SIZE:])
    message_len = len(message)

    key_amount = min(ceil(message_len / KEY_SIZE), 32)
    full_key = bytearray()
    for rot_bits in range(31, 31 - key_amount, -1):
        full_key.extend(rotate_key(key, rot_bits=rot_bits))

    for idx in range(message_len):
        message[idx] ^= full_key[idx % len(full_key)]

    return bytes(message)


def reference_encode(data: bytes, key: bytes) -> bytes:
    """Byte-by-byte implementation of the obfuscation, see
    :func:`reference_decode`
    """
    orig_key = bytes(key)

    enc_message = bytearray()
    for idx, byt in enumerate(data):
        if idx % KEY_SIZE == 0:
            key = rotate_key(key, rot_bits=31)
        enc_message.append(key[idx % KEY_SIZE] ^ byt)

    return orig_key + bytes(enc_message)


# Lengths around the key size (4 bytes) and the point where the key stream
# repeats (32 rotations * 4 bytes = 128 bytes)
LENGTHS = [0, 1, 3, 4, 5, 127, 128, 129, 131, 132, 255, 256, 257, 1000, 65536 + 3]


class TestFunctions:

    def test_generateKey(self):
        key = generate_key()
        assert KEY_SIZE == len(key)
        assert isinstance(key, bytes)

    @pytest.mark.parametrize(
        "key,obfuscated_data,expected_data",
        [
            (bytes.fromhex('00000000'), bytes.fromhex('68656c6c'), 'hell'.encode('utf8')),
            (bytes.fromhex('99abcdef'), bytes.fromhex('5b32f7b308'), 'hello'.encode('utf8')),
            (bytes.fromhex('ffffffff'), bytes.fromhex('979a93939088908d939b'), 'helloworld'.encode('utf8'))
        ]
    )
    def test_decode(self, key: bytes, obfuscated_data: bytes, expected_data: bytes):
        actual_data = decode(key + obfuscated_data)
        assert expected_data == actual_data

    @pytest.mark.parametrize(
        "key,data,expected_obfuscated_data",
        [
            (bytes.fromhex('00000000'), 'hell'.encode('utf8'), bytes.fromhex('0000000068656c6c')),
            (bytes.fromhex('99abcdef'), 'hello'.encode('utf8'), bytes.fromhex('99abcdef5b32f7b308')),
            (bytes.fromhex('ffffffff'), 'helloworld'.encode('utf8'), bytes.fromhex('ffffffff979a93939088908d939b')),
        ]
    )
    def test_encode_knownKey(self, key: bytes, data: bytes, expected_obfuscated_data):
        actual_obfuscated_data = encode(data, key=key)
        assert expected_obfuscated_data == actual_obfuscated_data

    def test_encode_generatedKey(self):
        data = 'helloworld'.encode('utf8')
        obfuscated_data = encode(data)

        assert KEY_SIZE + len(data) == len(obfuscated_data)
        assert data == decode(obfuscated_data)

    @pytest.mark.parametrize('length', LENGTHS)
    def test_encode_shouldMatchReference(self, length: int):
        rnd = random.Random(length)
        key = rnd.randbytes(KEY_SIZE)
        data = rnd.randbytes(length)

        assert reference_encode(data, key) == encode(data, key=key)

    @pytest.mark.parametrize('length', LENGTHS)
    def test_decode_shouldMatchReference(self, length: int):
        rnd = random.Random(length)
        obfuscated = rnd.randbytes(KEY_SIZE + length)

        assert reference_decode(obfuscated) == decode(obfuscated)

    @pytest.mark.parametrize('length', LENGTHS)
    def test_roundTrip(self, length: int):
        rnd = random.Random(length)
        data = rnd.randbytes(length)

        assert data == decode(encode(data, key=rnd.randbytes(KEY_SIZE)))

    @pytest.mark.parametrize('key', [b'\x00' * 4, b'\xff' * 4, b'\x01\x00\x00\x00', b'\x00\x00\x00\x80'])
    def test_roundTrip_edgeKeys(self, key: bytes):
        data = bytes(range(256)) * 3

        assert reference_encode(data, key) == encode(data, key=key)
        assert data == decode(encode(data, key=key))

    def test_decode_onlyKey_shouldReturnEmpty(self):
        assert b'' == decode(bytes.fromhex('99abcdef'))

    def test_decode_shouldNotModifyInput(self):
        data = bytearray(bytes.fromhex('99abcdef5b32f7b308'))
        decode(bytes(data))

        assert bytes.fromhex('99abcdef5b32f7b308') == bytes(data)
