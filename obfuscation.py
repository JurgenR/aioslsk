import secrets
import struct


KEY_SIZE = 4
"""@var KEY_SIZE: Amount of bytes in the key"""

def generate_key():
    return secrets.token_bytes(KEY_SIZE)


def rotate_key_orig(key, const=31):
    """Rotate the L{key} to the right by L{const} bits

    @type key: C{bytes}
    @param key: Key to rotate
    @param const: Amount of bits to rotate
    @rtype: C{bytes}
    @return: The rotated key
    """
    key_i = int.from_bytes(key, 'little')
    char_bit = 8
    mask = char_bit * len(key) - 1
    const &= mask
    key_i_rot = (key_i >> const) | (key_i << ((0xFFFFFFFF - (const - 1)) & mask) & 0xFFFFFFFF)
    key_rot = key_i_rot.to_bytes(4, 'little')
    return key_rot


def rotate_key(key, rot_bits=31):
    """Rotate the L{key} to the right by L{const} bits

    @type key: C{bytes}
    @param key: Key to rotate
    @param rot_bits: Amount of bits to rotate
    @rtype: C{bytes}
    @return: The rotated key
    """
    key_i = int.from_bytes(key, 'little')
    key_i_rot = (key_i >> rot_bits) | ((key_i << (0x20 - rot_bits)) & 0xFFFFFFFF)
    return key_i_rot.to_bytes(4, 'little')


def decode(data):
    """De-obfuscate given L{data}, the key should be the first 4 bytes of the
    data

    @type data: bytes like object
    @param data: Data to be de-obfuscated

    @rtype: bytes like object
    @return: De-obfuscated data
    """
    key = data[:KEY_SIZE]
    enc_message = data[KEY_SIZE:]
    dec_message = bytearray()
    for idx, byt in enumerate(enc_message):
        if idx % KEY_SIZE == 0:
            key = rotate_key(key, rot_bits=31)
        dec_message.append(key[idx % KEY_SIZE] ^ byt)
    return bytes(dec_message)


def encode(data, key=None):
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


if __name__ == '__main__':
    dec_msg = decode(bytes.fromhex('491f36ad843e6c5a2774d8b44db9dc00f79600a75c93c2a66bd2d74dd6a40f'))
    print(dec_msg.hex())
    dec_msg = decode(bytes.fromhex('dd2f3ec99e5e7c927ebff82496e25cc61db721d3a97d16f93607613a6b944fd6da98a033db2add266d15fa247bcab355bdb24e8750625d7bcb3d164ee8140814463f90ebf789167f803770d90fd02d821e4c5a1efd865928b77c8e5972105203f9add400f1edcb1a67119dd8e7aa16e1b34082d77e59309da5f7ce5e78f4c402cf6554fbb7bd8272559eb9b818edc568e9e6e467e19aa377691fa61fa51dd434c0f99da4fa21815c602f4d7252857b5087de3a64ec3301a40b4f20b63b739f984727e31ae4bbb6faac7441a4b4a258b487225e98933eb4bd09d579f374b273bca65ca6e7ac6324b15843fe1c0398818242d56924e441eec571c1d454713ba0e7c19624bfd9932d5262b5496f53516d4a1632b0455083bae48340ccf09470c0a7a65091e0fd81609727a8d472f0'))
    print(dec_msg.hex())
