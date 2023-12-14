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
from dataclasses import dataclass, field, Field, fields, is_dataclass
import hashlib
import logging
import socket
import struct
from typing import (
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    Type,
    TypeVar,
    Union
)
import zlib

logger = logging.getLogger(__name__)


T = TypeVar('T', bound='Serializable')


class Serializable(Protocol[T]):

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, T]:
        ...

    def serialize(self) -> bytes:
        ...


def decode_string(value: bytes) -> str:
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('cp1252')


class uint8(int):
    STRUCT = struct.Struct('<B')

    def serialize(self) -> bytes:
        return self.STRUCT.pack(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return pos + cls.STRUCT.size, cls.STRUCT.unpack_from(data, offset=pos)[0]


class uint16(int):
    STRUCT = struct.Struct('<H')

    def serialize(self) -> bytes:
        return self.STRUCT.pack(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return pos + cls.STRUCT.size, cls.STRUCT.unpack_from(data, offset=pos)[0]


class uint32(int):
    STRUCT = struct.Struct('<I')

    def serialize(self) -> bytes:
        return self.STRUCT.pack(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return pos + cls.STRUCT.size, cls.STRUCT.unpack_from(data, offset=pos)[0]


class uint64(int):
    STRUCT = struct.Struct('<Q')

    def serialize(self) -> bytes:
        return self.STRUCT.pack(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return pos + cls.STRUCT.size, cls.STRUCT.unpack_from(data, offset=pos)[0]


class int32(int):
    STRUCT = struct.Struct('<i')

    def serialize(self) -> bytes:
        return self.STRUCT.pack(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, int]:
        return pos + cls.STRUCT.size, cls.STRUCT.unpack_from(data, offset=pos)[0]


class string(str):

    def serialize(self, encoding: str = 'utf-8') -> bytes:
        byte_string = self.encode(encoding)

        return uint32(len(byte_string)).serialize() + byte_string

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, str]:
        pos_after_len, length = uint32.deserialize(pos, data)
        value = data[pos_after_len:pos_after_len + length]
        if len(value) != length:
            raise Exception(
                f"expected string with length ({length}), got {len(value)}")
        return pos_after_len + length, decode_string(value)


class bytearr(bytes):

    def serialize(self) -> bytes:
        length = len(self)
        return uint32(length).serialize() + bytes(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, bytes]:
        pos_after_len, length = uint32.deserialize(pos, data)
        value = data[pos_after_len:pos_after_len + length]
        return pos_after_len + length, value


class ipaddr(str):
    STRUCT = struct.Struct('<4s')

    def serialize(self) -> bytes:
        ip_b = socket.inet_aton(self)
        return self.STRUCT.pack(bytes(reversed(ip_b)))

    @classmethod
    def deserialize(cls, pos: int, data) -> Tuple[int, str]:
        value = cls.STRUCT.unpack(data[pos:pos + 4])[0]
        ip_addr = socket.inet_ntoa(bytes(reversed(value)))
        return pos + 4, ip_addr


class boolean(int):
    STRUCT = struct.Struct('<?')

    def serialize(self) -> bytes:
        return self.STRUCT.pack(self)

    @classmethod
    def deserialize(cls, pos: int, data: bytes) -> Tuple[int, bool]:
        return pos + cls.STRUCT.size, cls.STRUCT.unpack_from(data, offset=pos)[0]


class array(list):

    def serialize(self, element_type: Type[T]) -> bytes:
        body = uint32(len(self)).serialize()
        is_protocoldc = is_dataclass(element_type)
        for value in self:
            if is_protocoldc:
                body += value.serialize()
            else:
                body += element_type(value).serialize()
        return body

    @classmethod
    def deserialize(cls, pos: int, data: bytes, element_type: Type[T]) -> Tuple[int, List[T]]:
        items = []
        pos, array_len = uint32.deserialize(pos, data)
        for _ in range(array_len):
            pos, item = element_type.deserialize(pos, data)
            items.append(item)
        return pos, items


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
    _CACHED_FIELDS: Optional[Tuple[Field]] = None
    """Cache version of the `dataclasses.fields` return for the current class
    """

    def serialize(self) -> bytes:
        message = bytes()
        if self.__class__._CACHED_FIELDS is None:
            self.__class__._CACHED_FIELDS = fields(self)

        for obj_field in fields(self):
            value = self._get_value_for_field(self, obj_field)
            if value is None:
                continue

            # Serialize
            try:
                proto_type: Type[Serializable] = obj_field.metadata['type']
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
        if cls._CACHED_FIELDS is None:
            cls._CACHED_FIELDS = fields(cls)

        field_map: Dict[str, Any] = {}
        for obj_field in cls._CACHED_FIELDS:
            if not cls._field_needs_deserialization(obj_field, field_map, pos, message):
                continue

            try:
                proto_type = obj_field.metadata['type']
            except KeyError:
                raise Exception(f"no 'type' for field {obj_field.name!r} defined")

            if isinstance(proto_type, ProtocolDataclass):
                pos, value = proto_type.deserialize(pos, message)
            elif 'subtype' in obj_field.metadata:
                pos, value = proto_type.deserialize(pos, message, obj_field.metadata['subtype'])
            else:
                pos, value = proto_type.deserialize(pos, message)

            field_map[obj_field.name] = value

        return pos, cls(**field_map)

    @classmethod
    def _field_needs_deserialization(cls, field: Field, field_map: Dict[str, Any], pos: int, message: bytes):
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

    def _get_value_for_field(self, obj, fld: Field) -> Optional[Serializable]:
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


_ATTR_STRUCT = struct.Struct('<II')


@dataclass(frozen=True, order=True)
class Attribute(ProtocolDataclass):
    key: int = field(metadata={'type': uint32})
    value: int = field(metadata={'type': uint32})

    @classmethod
    def deserialize(cls, pos: int, message: bytes):
        return (
            pos + _ATTR_STRUCT.size,
            cls(*_ATTR_STRUCT.unpack_from(message, offset=pos))
        )

    def serialize(self) -> bytes:
        return _ATTR_STRUCT.pack(self.key, self.value)


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

    @classmethod
    def deserialize(cls, pos: int, message: bytes):
        pos, unknown = uint8.deserialize(pos, message)
        pos, filename = string.deserialize(pos, message)
        pos, filesize = uint64.deserialize(pos, message)
        pos, ext = string.deserialize(pos, message)
        pos, attrs = array.deserialize(pos, message, Attribute)
        return pos, cls(
            unknown=unknown,
            filename=filename,
            filesize=filesize,
            extension=ext,
            attributes=attrs
        )

    def serialize(self) -> bytes:
        return (
            uint8(self.unknown).serialize() +
            string(self.filename).serialize() +
            uint64(self.filesize).serialize() +
            string(self.extension).serialize() +
            array(self.attributes).serialize(Attribute)
        )


@dataclass(frozen=True, order=True)
class DirectoryData(ProtocolDataclass):
    name: str = field(metadata={'type': string})
    files: List[FileData] = field(metadata={'type': array, 'subtype': FileData})

    @classmethod
    def deserialize(cls, pos: int, message: bytes):
        pos, name = string.deserialize(pos, message)
        pos, files = array.deserialize(pos, message, element_type=FileData)
        return pos, cls(name, files)

    def serialize(self) -> bytes:
        return string(self.name).serialize() + array(self.files).serialize(FileData)


def has_unparsed_bytes(pos: int, message: bytes) -> bool:
    return len(message[pos:]) > 0


def calc_md5(value: str) -> str:
    return hashlib.md5(value.encode('utf-8')).hexdigest()
