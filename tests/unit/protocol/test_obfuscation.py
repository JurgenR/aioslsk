from pyslsk.protocol.obfuscation import KEY_SIZE, decode, encode, generate_key

import pytest


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
