from dataclasses import dataclass, field, fields, is_dataclass
import hashlib
import logging
import socket
import struct
from typing import List
import zlib

logger = logging.getLogger(__name__)


def decode_string(value: bytes) -> str:
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('cp1252')


def parse_basic(pos: int, data: bytes, data_type: str):
    size = struct.calcsize(data_type)
    value = data[pos:pos + size]
    return pos + size, struct.unpack(data_type, value)[0]


class uint8(int):

    def serialize(self):
        return struct.pack('<B', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes):
        return parse_basic(pos, data, '<B')


class uint16(int):

    def serialize(self):
        return struct.pack('<H', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes):
        return parse_basic(pos, data, '<H')


class uint32(int):

    def serialize(self):
        return struct.pack('<I', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes):
        return parse_basic(pos, data, '<I')


class uint64(int):

    def serialize(self):
        return struct.pack('<Q', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes):
        return parse_basic(pos, data, '<Q')


class string(str):

    def serialize(self, encoding='utf-8'):
        byte_string = self.encode(encoding)

        length = len(byte_string)
        return uint32(length).serialize() + byte_string

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> str:
        pos_after_len, length = uint32.deserialize(pos, data)
        data_type = '<{}s'.format(length)
        value = struct.unpack(
            data_type, data[pos_after_len:pos_after_len + length])[0]
        return pos_after_len + length, decode_string(value)


class ipaddr(str):

    def serialize(self) -> bytes:
        ip_b = socket.inet_aton(self)
        return struct.pack('<4s', bytes(reversed(ip_b)))

    @classmethod
    def deserialize(cls, pos: int, data) -> str:
        data_type = '<4s'
        value = struct.unpack(data_type, data[pos:pos + 4])[0]
        ip_addr = socket.inet_ntoa(bytes(reversed(value)))
        return pos + 4, ip_addr


class boolean(int):

    def serialize(self):
        return struct.pack('<?', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes):
        return parse_basic(pos, data, '<?')


class array(list):

    def serialize(self, element_type):
        body = uint32(len(self)).serialize()
        for value in self:
            body += element_type(value).serialize()
        return body

    @classmethod
    def deserialize(cls, pos: int, data, element_type):
        items = []
        pos_after_array_len, array_len = uint32.deserialize(pos, data)
        current_item_pos = pos_after_array_len
        for _ in range(array_len):
            current_item_pos, item = element_type.deserialize(current_item_pos, data)
            items.append(item)
        return current_item_pos, items


class ProtocolDataclass:

    def serialize(self):
        message = bytes()
        obj_fields = fields(self)
        for obj_field in obj_fields:
            value = self._get_value_for_field(self, obj_field)
            if value is None:
                continue

            # Serialize
            try:
                proto_type = obj_field.metadata['type']
            except KeyError:
                raise Exception(f"no 'type' for field {obj_field.name!r} defined")

            if is_dataclass(proto_type):
                message += value.serialize()
            elif 'subtype' in obj_field.metadata:
                if is_dataclass(obj_field.metadata['subtype']):
                    # during serialization of elements in the array the code
                    # will try to wrap the values into the passed type (in
                    # order to call 'serialize' on them) but dataclasses don't
                    # need to be wrapped. Just use a dummy lambda that returns
                    # the dataclass object as-is
                    message += proto_type(value).serialize(lambda val: val)
                else:
                    message += proto_type(value).serialize(obj_field.metadata['subtype'])
            else:
                message += proto_type(value).serialize()

        return message

    @classmethod
    def deserialize(cls, pos: int, message: bytes):
        obj_fields = fields(cls)
        field_map = {}
        for obj_field in obj_fields:
            if not cls._field_needs_deserialization(
                    obj_field, field_map, has_unparsed_bytes(pos, message)):
                continue

            try:
                proto_type = obj_field.metadata['type']
            except KeyError:
                raise Exception(f"no 'type' for field {obj_field.name!r} defined")

            if is_dataclass(proto_type):
                pos, value = proto_type.deserialize(pos, message)
            elif 'subtype' in obj_field.metadata:
                pos, value = proto_type.deserialize(
                    pos, message, obj_field.metadata['subtype'])
            else:
                pos, value = proto_type.deserialize(pos, message)

            field_map[obj_field.name] = value

        return pos, cls(**field_map)

    @classmethod
    def _field_needs_deserialization(cls, field, field_map, has_unparsed_bytes):
        # For if_true and if_false we need to return only if the condition is
        # is false as we still want to check the 'optional' field
        if 'if_true' in field.metadata:
            if not field_map[field.metadata['if_true']]:
                return False

        if 'if_false' in field.metadata:
            if field_map[field.metadata['if_false']]:
                return False

        if 'optional' in field.metadata:
            return has_unparsed_bytes

        return True

    def _get_value_for_field(self, obj, fld):
        value = getattr(obj, fld.name)

        # Order of checking the metadata is important
        if 'optional' in fld.metadata:
            if value is None:
                return None

        if 'if_true' in fld.metadata:
            other_value = getattr(obj, fld.metadata['if_true'])
            return value if bool(other_value) else None

        if 'if_false' in fld.metadata:
            other_value = getattr(obj, fld.metadata['if_false'])
            return value if not bool(other_value) else None

        return value


class MessageDataclass(ProtocolDataclass):

    def serialize(self, compress: bool = False) -> bytes:
        message = super().serialize()

        if compress:
            message = zlib.compress(message)

        message = self.MESSAGE_ID.serialize() + message
        return uint32(len(message)).serialize() + message

    @classmethod
    def deserialize(cls, message: bytes, decompress: bool = False):
        pos: int = 0

        # Parse length and header
        pos, _ = uint32.deserialize(pos, message)
        pos, message_id = type(cls.MESSAGE_ID).deserialize(pos, message)
        if message_id != cls.MESSAGE_ID:
            raise ValueError(f"message id mismatch {message_id} != {cls.MESSAGE_ID}")

        if decompress:
            message = zlib.decompress(message[pos:])
            pos, obj = super().deserialize(0, message)
        else:
            pos, obj = super().deserialize(pos, message)

        if has_unparsed_bytes(pos, message):
            logger.warning(f"message has {len(message[pos:])} unparsed bytes : {message!r}")

        return obj


@dataclass(frozen=True, order=True)
class Attribute(ProtocolDataclass):
    key: int = field(metadata={'type': uint32})
    value: int = field(metadata={'type': uint32})


@dataclass(frozen=True, order=True)
class SimilarUser(ProtocolDataclass):
    username: str = field(metadata={'type': string})
    status: int = field(metadata={'type': uint32})


@dataclass(frozen=True, order=True)
class ItemRecommendation(ProtocolDataclass):
    recommendation: str = field(metadata={'type': string})
    number: int = field(metadata={'type': uint32})


@dataclass(frozen=True, order=True)
class RoomTicker(ProtocolDataclass):
    username: str = field(metadata={'type': string})
    ticker: str = field(metadata={'type': string})


@dataclass(frozen=True, order=True)
class PotentialParent(ProtocolDataclass):
    username: str = field(metadata={'type': string})
    ip: str = field(metadata={'type': ipaddr})
    port: int = field(metadata={'type': uint32})


@dataclass(frozen=True, order=True)
class UserData(ProtocolDataclass):
    avg_speed: int = field(metadata={'type': uint32})
    download_num: int = field(metadata={'type': uint64})
    file_count: int = field(metadata={'type': uint32})
    dir_count: int = field(metadata={'type': uint32})


@dataclass(frozen=True, order=True)
class FileData(ProtocolDataclass):
    unknown: int = field(metadata={'type': uint8})
    filename: str = field(metadata={'type': string})
    filesize: int = field(metadata={'type': uint64})
    extension: str = field(metadata={'type': string})
    attributes: List[Attribute] = field(metadata={'type': array, 'subtype': Attribute})


@dataclass(frozen=True, order=True)
class DirectoryData(ProtocolDataclass):
    name: str = field(metadata={'type': string})
    files: List[FileData] = field(metadata={'type': array, 'subtype': FileData})


def has_unparsed_bytes(pos, message):
    return len(message[pos:]) > 0


def calc_md5(value: bytes):
    return hashlib.md5(value.encode('utf-8')).hexdigest()
