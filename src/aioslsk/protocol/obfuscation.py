"""Obfuscation for the SoulSeek protocol

When receiving or sending a message on the obfuscated port, the first 4 bytes
of the message will contain the key (generated randomly for each message). To
de-obfuscate the key is XOR'd with the next 4 bytes of the message, after which
a circular rotation of 31 bits to the right is performed on the key, the result
of the rotation is then XOR'd with the next 4 bytes of the message and so forth
"""
import secrets
from typing import Optional


KEY_SIZE: int = 4
""":var KEY_SIZE: Amount of bytes in the key"""
CHUNK_SIZE: int = 16 * 1024
""":var CHUNK_SIZE: Amount of bytes being (de-)obfuscated at a time
    (default: 16 KiB)
"""

_FULL_KEY_SIZE = 4 * 32
""":var _FULL_KEY_SIZE: Size of the key after it went through one complete
rotation
"""
_MASK = 0xFFFFFFFF


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE)


def _build_key_lookup_tables() -> tuple[tuple[int, ...], ...]:
    """Precompute each key byte's contribution to the 128-byte XOR block

    Rotation distributes over XOR, so the four table entries can be combined
    with XOR to obtain exactly the keystream for any four-byte key

    This builds a table of roughly 16KiB with every possible combination of:

    1. The byte's position in the key
    2. Value of the byte

    The size is calculated as (in bytes) : 4 * 256 * 128
    """
    tables = []
    for key_byte_position in range(KEY_SIZE):
        values = []
        for byte_value in range(256):
            key_i = byte_value << (8 * key_byte_position)
            block = b''.join(
                ((key_i >> rot) | ((key_i << (32 - rot)) & _MASK)).to_bytes(
                    KEY_SIZE, 'little'
                )
                for rot in range(31, -1, -1)
            )
            values.append(int.from_bytes(block, 'little'))

        tables.append(tuple(values))

    return tuple(tables)


_KEY_LOOKUP_TABLES = _build_key_lookup_tables()


def _create_keystream(key: bytes, length: int) -> bytes:
    """Generate ``length`` bytes of the repeating XOR keystream"""
    if length == 0:
        return b''

    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes long")

    if length < 0:
        raise ValueError("length must not be negative")

    block_i = (
        _KEY_LOOKUP_TABLES[0][key[0]]
        ^ _KEY_LOOKUP_TABLES[1][key[1]]
        ^ _KEY_LOOKUP_TABLES[2][key[2]]
        ^ _KEY_LOOKUP_TABLES[3][key[3]]
    )
    block = block_i.to_bytes(_FULL_KEY_SIZE, 'little')

    if length <= _FULL_KEY_SIZE:
        return block[:length]

    repeats, remainder = divmod(length, _FULL_KEY_SIZE)
    return block * repeats + block[:remainder]


def _xor(data: bytes, key: bytes) -> bytes:
    """XOR ``data`` with the repeating stream derived from the ``key``"""
    length = len(data)
    if length == 0:
        return b''

    keystream = _create_keystream(key, min(length, CHUNK_SIZE))
    if length <= CHUNK_SIZE:
        return (
            int.from_bytes(data, 'little') ^ int.from_bytes(keystream, 'little')
        ).to_bytes(length, 'little')

    full_mask = int.from_bytes(keystream, 'little')
    pieces = []
    data_view = memoryview(data)
    for offset in range(0, length, CHUNK_SIZE):
        piece = data_view[offset:offset + CHUNK_SIZE]
        size = len(piece)
        mask = full_mask if size == CHUNK_SIZE else int.from_bytes(
            keystream[:size], 'little'
        )
        pieces.append((int.from_bytes(piece, 'little') ^ mask).to_bytes(size, 'little'))

    return b''.join(pieces)


def decode(data: bytes) -> bytes:
    """De-obfuscate ``data``, where the first four bytes contain the key"""
    if len(data) < KEY_SIZE:
        raise ValueError("encoded data is too short to contain a key")

    return _xor(data[KEY_SIZE:], data[:KEY_SIZE])


def encode(data: bytes, key: Optional[bytes] = None) -> bytes:
    """Obfuscate ``data``, generating a random key unless one is supplied"""
    if key is None:
        key = generate_key()

    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes long")

    return bytes(key) + _xor(data, key)
