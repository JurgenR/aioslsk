"""Module defining all data primitives used in the protocol messages

Field metadata:

During (de)serialization the `metadata` parameter of the `dataclasses.field`
function to control how to perform (de)serialization. See
`aioslsk.protocol.primitives` for how (de)serialization is performed

These metadata keys are implemented:

* 'type': <type_class>
** defines the primary type of the data

* 'subtype': <type_class>
** used for arrays : the type of the elements contained in the array

* 'if_true': <field_name>
** serialization : only pack this field if the value of field with name <field_name> evaluates to True
** deserialization : only parse this field if the value of field with name <field_name> evaluates to True

* 'if_false': <field_name>
** serialization : only pack this field if the value of field with name <field_name> evaluates to False
** deserialization : only parse this field if the value of field with name <field_name> evaluates to False

* 'optional': True
** serialization : only pack this field if its value is anything other than None
** deserialization : during deserialization the code will determine if the message
    has been fully parsed. If not it will parse this field
"""
from dataclasses import dataclass, field, fields, is_dataclass
import hashlib
import logging
import socket
import struct
from typing import Any, ClassVar, Dict, List, Tuple, Union
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
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return parse_basic(pos, data, '<B')


class uint16(int):

    def serialize(self):
        return struct.pack('<H', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return parse_basic(pos, data, '<H')


class uint32(int):

    def serialize(self):
        return struct.pack('<I', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return parse_basic(pos, data, '<I')


class uint64(int):

    def serialize(self):
        return struct.pack('<Q', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return parse_basic(pos, data, '<Q')


class int32(int):

    def serialize(self):
        return struct.pack('<i', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return parse_basic(pos, data, '<i')


class string(str):

    def serialize(self, encoding: str = 'utf-8'):
        byte_string = self.encode(encoding)

        length = len(byte_string)
        return uint32(length).serialize() + byte_string

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, str]:
        pos_after_len, length = uint32.deserialize(pos, data)
        data_type = '<{}s'.format(length)
        value = struct.unpack(
            data_type, data[pos_after_len:pos_after_len + length])[0]
        return pos_after_len + length, decode_string(value)


class bytearr(bytes):

    def serialize(self):
        length = len(self)
        return uint32(length).serialize() + bytes(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, str]:
        pos_after_len, length = uint32.deserialize(pos, data)
        value = data[pos_after_len:pos_after_len + length]
        return pos_after_len + length, value


class ipaddr(str):

    def serialize(self) -> bytes:
        ip_b = socket.inet_aton(self)
        return struct.pack('<4s', bytes(reversed(ip_b)))

    @classmethod
    def deserialize(cls, pos: int, data) -> Tuple[int, str]:
        data_type = '<4s'
        value = struct.unpack(data_type, data[pos:pos + 4])[0]
        ip_addr = socket.inet_ntoa(bytes(reversed(value)))
        return pos + 4, ip_addr


class boolean(int):

    def serialize(self):
        return struct.pack('<?', self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, bool]:
        return parse_basic(pos, data, '<?')


class array(list):

    def serialize(self, element_type):
        body = uint32(len(self)).serialize()
        for value in self:
            body += element_type(value).serialize()
        return body

    @classmethod
    def deserialize(cls, pos: int, data: bytes, element_type) -> Tuple[int, List[Any]]:
        items = []
        pos_after_array_len, array_len = uint32.deserialize(pos, data)
        current_item_pos = pos_after_array_len
        for _ in range(array_len):
            current_item_pos, item = element_type.deserialize(current_item_pos, data)
            items.append(item)
        return current_item_pos, items


class ProtocolDataclass:
    """The `ProtocolDataclass` defines a collection of primitives that can be
    serialized or deserialized. Classes inheriting from this class should use
    the `@dataclass(order=True)` decorator. The order needs to be kept as the
    fields definitions will be evaluated during (de)serialization.

    Example definition:

    @dataclass(order=True)
    class CustomDataclass(ProtocolDataclass):
        username: str = field(metadata={'type': string})
        password: str = field(metadata={'type': string})
        has_privileges: bool = field(metadata={'type': boolean})
    """

    def serialize(self) -> bytes:
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
        field_map: Dict[str, Any] = {}
        for obj_field in obj_fields:
            if not cls._field_needs_deserialization(obj_field, field_map, pos, message):
                continue

            try:
                proto_type = obj_field.metadata['type']
            except KeyError:
                raise Exception(f"no 'type' for field {obj_field.name!r} defined")

            if is_dataclass(proto_type):
                pos, value = proto_type.deserialize(pos, message)
            elif 'subtype' in obj_field.metadata:
                # if obj_field.name == 'directories':
                #     import pdb; pdb.set_trace()

                pos, value = proto_type.deserialize(pos, message, obj_field.metadata['subtype'])
            else:
                pos, value = proto_type.deserialize(pos, message)

            field_map[obj_field.name] = value

        return pos, cls(**field_map)

    @classmethod
    def _field_needs_deserialization(cls, field, field_map: Dict[str, Any], pos: int, message: bytes):
        # For if_true and if_false we need to return only if the condition is
        # is false as we still want to check the 'optional' field
        if 'if_true' in field.metadata:
            if not field_map[field.metadata['if_true']]:
                return False

        if 'if_false' in field.metadata:
            if field_map[field.metadata['if_false']]:
                return False

        if 'optional' in field.metadata:
            return has_unparsed_bytes(pos, message)

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
    """Message data class for which protocol messages should inherit from. This
    takes all behaviour from the `ProtocolDataclass` class but adds:

    * Prepending the message with length and MESSAGE_ID
    * Optionally the message data will (de)compressed
    """
    MESSAGE_ID: ClassVar[Union[uint8, uint32]] = uint32(0x00)

    def serialize(self, compress: bool = False) -> bytes:
        """Serializes the current `MessageDataClass` object and prepends the
        message length and `MESSAGE_ID`

        In case the message needs to be compressed just override this method
        in the subclass and simply call the super method with `compress=True`

        :param compress: use gzip compression on the message contents
        """
        message = super().serialize()

        if compress:
            message_len_before = len(message)
            message = zlib.compress(message)
            logger.debug(f"compressed {message_len_before} to {len(message)} bytes")

        message = self.MESSAGE_ID.serialize() + message
        return uint32(len(message)).serialize() + message

    @classmethod
    def deserialize(cls, message: bytes, decompress: bool = False):
        """Deserializes the passed `message` into an object of the current type

        In case the message needs to be decompressed just override this method
        in the subclass and simply call the super method with `decompress=True`

        :param decompress: use gzip decompression on the message contents
        :raise ValueError: if the message_id found the data does not match the
            `MESSAGE_ID` defined in the current class
        :return: an object of the current class
        """
        pos: int = 0

        # Parse length and header
        pos, _ = uint32.deserialize(pos, message)
        pos, message_id = type(cls.MESSAGE_ID).deserialize(pos, message)
        if message_id != cls.MESSAGE_ID:
            raise ValueError(f"message id mismatch {message_id} != {cls.MESSAGE_ID}")

        if decompress:
            message_len_before = len(message)
            message = zlib.decompress(message[pos:])
            logger.debug(f"decompressed {message_len_before} to {len(message)} bytes")

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
class Recommendation(ProtocolDataclass):
    recommendation: str = field(metadata={'type': string})
    score: int = field(metadata={'type': int32})


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
class UserStats(ProtocolDataclass):
    avg_speed: int = field(metadata={'type': uint32})
    uploads: int = field(metadata={'type': uint64})
    shared_file_count: int = field(metadata={'type': uint32})
    shared_folder_count: int = field(metadata={'type': uint32})


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


def has_unparsed_bytes(pos: int, message: bytes) -> bool:
    return len(message[pos:]) > 0


def calc_md5(value: str) -> str:
    return hashlib.md5(value.encode('utf-8')).hexdigest()
