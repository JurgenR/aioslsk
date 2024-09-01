import secrets
from math import ceil
from typing import Optional


KEY_SIZE = 4
""":var KEY_SIZE: Amount of bytes in the key"""


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE)


def _rotate_key_orig(key: bytes, const: int = 31) -> bytes:  # pragma: no cover
    """Rotate the ``key`` to the right by ``const`` bits

    :param key: Key to rotate
    :param const: Amount of bits to rotate
    :return: The rotated key
    """
    key_i = int.from_bytes(key, 'little')
    char_bit = 8
    mask = char_bit * len(key) - 1
    const &= mask
    key_i_rot = (key_i >> const) | (key_i << ((0xFFFFFFFF - (const - 1)) & mask) & 0xFFFFFFFF)
    key_rot = key_i_rot.to_bytes(4, 'little')
    return key_rot


def rotate_key(key: bytes, rot_bits: int = 31) -> bytes:
    """Rotate the ``key`` to the right by ``const`` bits

    :param key: Key to rotate
    :param rot_bits: Amount of bits to rotate
    :return: The rotated key
    """
    key_i = int.from_bytes(key, 'little')
    key_i_rot = (key_i >> rot_bits) | ((key_i << (0x20 - rot_bits)) & 0xFFFFFFFF)
    return key_i_rot.to_bytes(4, 'little')


def decode(data: bytes) -> bytes:
    """De-obfuscate given ``data``, the key should be the first 4 bytes of the
    data

    :param data: Data to be de-obfuscated
    :return: De-obfuscated data
    """
    key = data[:KEY_SIZE]
    message = bytearray(data[KEY_SIZE:])
    message_len = len(message)

    # Generate key array
    key_amount = min(ceil(message_len / KEY_SIZE), 32)

    full_key = bytearray()
    for rot_bits in range(31, 31 - key_amount, -1):
        full_key.extend(rotate_key(key, rot_bits=rot_bits))
    full_key_len = len(full_key)

    # XOR all bytes with the key
    for idx in range(message_len):
        message[idx] ^= full_key[idx % full_key_len]

    return bytes(message)


def encode(data: bytes, key: Optional[bytes] = None) -> bytes:
    """Obfuscate the given ``data`` with the provided ``key``, if no key is
    given it will be automatically generated
    """
    # I'm not sure about the endianness. When testing I just used a key which
    # was already converted to little endian. When generating a key the
    # endianness doesn't really matter because it's random anyway
    if key is None:
        key = generate_key()
    orig_key = bytes(key)

    enc_message = bytearray()
    for idx, byt in enumerate(data):
        if idx % KEY_SIZE == 0:
            key = rotate_key(key, rot_bits=31)
        enc_message.append(key[idx % KEY_SIZE] ^ byt)

    return orig_key + bytes(enc_message)
