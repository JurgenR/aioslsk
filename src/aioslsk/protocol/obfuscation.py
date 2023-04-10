import secrets


KEY_SIZE = 4
""":var KEY_SIZE: Amount of bytes in the key"""


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE)


def _rotate_key_orig(key: bytes, const: int = 31) -> bytes:  # pragma: no cover
    """Rotate the L{key} to the right by L{const} bits

    :type key: C{bytes}
    :param key: Key to rotate
    :param const: Amount of bits to rotate
    :rtype: C{bytes}
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
    """Rotate the L{key} to the right by L{const} bits

    :type key: C{bytes}
    :param key: Key to rotate
    :param rot_bits: Amount of bits to rotate
    :rtype: C{bytes}
    :return: The rotated key
    """
    key_i = int.from_bytes(key, 'little')
    key_i_rot = (key_i >> rot_bits) | ((key_i << (0x20 - rot_bits)) & 0xFFFFFFFF)
    return key_i_rot.to_bytes(4, 'little')


def decode(data: bytes) -> bytes:
    """De-obfuscate given L{data}, the key should be the first 4 bytes of the
    data

    :type data: bytes like object
    :param data: Data to be de-obfuscated

    :rtype: bytes like object
    :return: De-obfuscated data
    """
    key = data[:KEY_SIZE]
    enc_message = data[KEY_SIZE:]
    dec_message = bytearray()
    for idx, byt in enumerate(enc_message):
        if idx % KEY_SIZE == 0:
            key = rotate_key(key, rot_bits=31)
        dec_message.append(key[idx % KEY_SIZE] ^ byt)
    return bytes(dec_message)


def encode(data: bytes, key: bytes = None) -> bytes:
    """Obfuscate the given L{data} with the provided L{key}, if no key is given
    it will be automatically generated
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