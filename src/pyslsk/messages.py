from dataclasses import dataclass, field
import functools
import hashlib
import logging
import socket
import struct
from typing import Callable, List, Tuple
import zlib

from .exceptions import UnknownMessageError


logger = logging.getLogger()


@dataclass(frozen=True)
class FileData:
    unknown: str
    filename: str
    filesize: int
    extension: str
    attributes: List[Tuple[int, int]] = field(default_factory=list)

    def pack(self):
        return (
            pack_uchar(self.unknown) +
            pack_string(self.filename) +
            pack_int64(self.filesize) +
            pack_string(self.extension) +
            pack_list(self.attributes, pack_func=pack_attribute)
        )


@dataclass(frozen=True)
class DirectoryData:
    name: str
    files: List[FileData] = field(default_factory=list)

    def pack(self):
        return (
            pack_string(self.name) +
            pack_list(self.files, pack_func=lambda f: f.pack())
        )


def calc_md5(value: bytes):
    return hashlib.md5(value.encode('utf-8')).hexdigest()


# Parsing functions
def parse_basic(pos: int, data, data_type: str):
    size = struct.calcsize(data_type)
    value = data[pos:pos + size]
    return pos + size, struct.unpack(data_type, value)[0]


def parse_short(pos: int, data) -> int:
    return parse_basic(pos, data, '<H')


def parse_int(pos: int, data) -> int:
    return parse_basic(pos, data, '<I')


def parse_int64(pos: int, data) -> int:
    # off_t, signed or unsigned?
    return parse_basic(pos, data, '<Q')


def parse_uchar(pos: int, data) -> int:
    return parse_basic(pos, data, '<B')


def parse_bool(pos: int, data) -> bool:
    return parse_basic(pos, data, '<?')


def parse_string(pos: int, data) -> str:
    # Length of a string is in nibbles
    pos_after_len, length = parse_int(pos, data)
    data_type = '<{}s'.format(length)
    value = struct.unpack(
        data_type, data[pos_after_len:pos_after_len + length])[0]
    return pos_after_len + length, value


def parse_ip(pos: int, data) -> str:
    length = 4
    data_type = '<{}s'.format(length)
    value = struct.unpack(data_type, data[pos:pos + length])[0]
    ip_addr = socket.inet_ntoa(bytes(reversed(value)))
    return pos + length, ip_addr


def parse_list(pos: int, data, item_parser: Callable = parse_string) -> list:
    items = []
    pos_after_list_len, list_len = parse_int(pos, data)
    current_item_pos = pos_after_list_len
    for _ in range(list_len):
        current_item_pos, item = item_parser(current_item_pos, data)
        items.append(item)
    return current_item_pos, items


def parse_attribute(pos: int, data) -> Tuple[int, Tuple[int, int]]:
    pos, position = parse_int(pos, data)
    pos, value = parse_int(pos, data)
    return pos, (position, value, )


def parse_room_list(pos: int, data):
    pos, room_names = parse_list(pos, data, item_parser=parse_string)
    pos, room_user_counts = parse_list(pos, data, item_parser=parse_int)
    return pos, dict(list(zip(room_names, room_user_counts)))


def parse_net_info_entry(pos: int, message):
    pos, user = parse_string(pos, message)
    pos, ip = parse_ip(pos, message)
    pos, port = parse_int(pos, message)
    return pos, (user, ip, port, )


def parse_user_data_entry(pos: int, message):
    pos, avg_speed = parse_int(pos, message)
    pos, download_num = parse_int64(pos, message)
    pos, file_count = parse_int(pos, message)
    pos, dir_count = parse_int(pos, message)
    return pos, (avg_speed, download_num, file_count, dir_count)


def parse_file(pos: int, message) -> Tuple[int, FileData]:
    pos, unknown = parse_uchar(pos, message)
    pos, filename = parse_string(pos, message)
    pos, filesize = parse_int64(pos, message)
    pos, extension = parse_string(pos, message)
    pos, attributes = parse_list(pos, message, item_parser=parse_attribute)

    file_data = FileData(
        unknown=unknown,
        filename=filename,
        filesize=filesize,
        extension=extension,
        attributes=attributes
    )

    return pos, file_data


def parse_directory(pos: int, message) -> Tuple[int, DirectoryData]:
    pos, name = parse_string(pos, message)
    pos, files = parse_list(pos, message, item_parser=parse_file)
    return pos, DirectoryData(name=name, files=files)


def parse_similar_user(pos: int, message):
    pos, username = parse_string(pos, message)
    pos, status = parse_int(pos, message)
    return pos, (username, status, )


def parse_item_recommendation(pos: int, message):
    pos, recommendation = parse_string(pos, message)
    # FIXME: The museek docs say this can be negative, however we are parsing
    # everything as unsigned. (I actually don't know what this number means
    # right now)
    pos, recommendation_num = parse_int(pos, message)
    return pos, (recommendation, recommendation_num, )


# Packing functions
def pack_int(value: int) -> bytes:
    return struct.pack('<I', value)


def pack_int64(value: int) -> bytes:
    return struct.pack('<Q', value)


def pack_uchar(value: str) -> bytes:
    return struct.pack('<B', value)


def pack_string(value: str, encoding='utf-8') -> bytes:
    if not isinstance(value, bytes):
        value = value.encode(encoding)

    length = len(value)
    return (pack_int(length) + value)


def pack_bool(value: bool) -> bytes:
    return struct.pack('<?', value)


def pack_ip(value: str) -> bytes:
    ip_b = socket.inet_aton(value)
    return struct.pack('<4s', bytes(reversed(ip_b)))


def pack_list(values, pack_func: Callable = pack_string):
    body = pack_int(len(values))
    for value in values:
        body += pack_func(value)
    return body


def pack_attribute(value: Tuple[int, int]) -> bytes:
    return pack_int(value[0]) + pack_int(value[1])


def pack_message(message_id: int, value: bytes, id_as_uchar: bool = False) -> bytes:
    """Adds the header (length + message ID) to a message body

    @param id_as_uchar: Packs the L{message_id} as uchar instead of int, used
        for L{PeerInit}, L{PierceFirewall} and distributed messages
    """
    # Add message ID
    if id_as_uchar:
        full_body = pack_uchar(message_id) + value
    else:
        full_body = pack_int(message_id) + value
    # Add length
    return struct.pack('<I', len(full_body)) + full_body


def warn_on_unparsed_bytes(parse_func):
    """Decorator that logs a warning messages when some bytes haven't been
    parsed yet after the given L{parse_func} has been executed.
    """
    @functools.wraps(parse_func)
    def check_for_unparsed_bytes(message):
        results = parse_func(message)
        unparsed_bytes = message.get_unparsed_bytes()
        if len(unparsed_bytes) > 0:
            logger.warning(
                f"{message.__class__.__name__} has {len(unparsed_bytes)} unparsed bytes : {unparsed_bytes.hex()!r}")
        return results
    return check_for_unparsed_bytes


def decode_string(value):
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('cp1252')


class Message:
    MESSAGE_ID = 0x0

    def __init__(self, message):
        self._pos: int = 0
        self.message: bytes = message
        if not isinstance(self.message, bytes):
            self.message = bytes.fromhex(self.message)

    def reset(self):
        self._pos = 0

    def has_unparsed_bytes(self):
        return len(self.message[self._pos:]) > 0

    def get_unparsed_bytes(self):
        return self.message[self._pos:]

    def parse_string(self):
        self._pos, value = parse_string(self._pos, self.message)
        return value

    def parse_short(self):
        self._pos, value = parse_short(self._pos, self.message)
        return value

    def parse_int(self):
        self._pos, value = parse_int(self._pos, self.message)
        return value

    def parse_int64(self):
        self._pos, value = parse_int64(self._pos, self.message)
        return value

    def parse_uchar(self):
        self._pos, value = parse_uchar(self._pos, self.message)
        return value

    def parse_bool(self):
        self._pos, value = parse_bool(self._pos, self.message)
        return value

    def parse_ip(self):
        self._pos, value = parse_ip(self._pos, self.message)
        return value

    def parse_list(self, item_parser: Callable):
        self._pos, value = parse_list(
            self._pos, self.message, item_parser=item_parser)
        return value

    def parse_room_list(self):
        self._pos, value = parse_room_list(self._pos, self.message)
        return value

    def parse(self):
        length = self.parse_int()
        message_id = self.parse_int()
        return length, message_id

    @classmethod
    def create(cls):
        return pack_message(cls.MESSAGE_ID, b'')


class ServerMessage(Message):
    pass


class Login(Message):
    MESSAGE_ID = 0x01

    @classmethod
    def create(cls, username, password, client_version, minor_version=100):
        md5_hash = calc_md5(username + password)
        message_body = (
            pack_string(username) +
            pack_string(password) +
            pack_int(client_version) +
            pack_string(md5_hash) +
            pack_int(minor_version)
        )
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        success = self.parse_bool()
        if success:
            greet = self.parse_string()
            ip = self.parse_ip()
            md5hash = self.parse_string()
            unknown = self.parse_uchar()
            return success, greet, ip, md5hash, unknown
        else:
            reason = self.parse_string()
            return success, reason

    def parse_server(self):
        super().parse()
        username = self.parse_string()
        password = self.parse_string()
        version_number = self.parse_int()
        md5_hash = self.parse_string()
        minor_version = self.parse_int()
        return username, password, version_number, md5_hash, minor_version


class SetListenPort(Message):
    MESSAGE_ID = 0x02

    @classmethod
    def create(cls, port, obfuscated_port=None):
        message_body = pack_int(port)
        if obfuscated_port is None:
            message_body += pack_int(0) + pack_int(0)
        else:
            message_body += pack_int(1) + pack_int(obfuscated_port)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        port = self.parse_int()
        if self.has_unparsed_bytes():
            unknown = self.parse_int()
            obfuscated_port = self.parse_int()
        else:
            unknown = None
            obfuscated_port = None
        return port, unknown, obfuscated_port


class GetPeerAddress(Message):
    MESSAGE_ID = 0x03

    @classmethod
    def create(cls, username: str) -> bytes:
        return pack_message(cls.MESSAGE_ID, pack_string(username))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        # In case user does not exist all values will be 0
        ip_addr = self.parse_ip()
        port = self.parse_int()
        if self.has_unparsed_bytes():
            unknown = self.parse_int()
            obfuscated_port = self.parse_short()
        else:
            unknown = None
            obfuscated_port = None
        return username, ip_addr, port, unknown, obfuscated_port

    def parse_server(self):
        super().parse()
        username = self.parse_string()
        return username


class AddUser(Message):
    MESSAGE_ID = 0x05

    @classmethod
    def create(cls, username: str) -> bytes:
        return pack_message(cls.MESSAGE_ID, pack_string(username))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        exists = self.parse_uchar()
        if exists != 1:
            return username, exists, 0, 0, 0, 0, 0, None
        status = self.parse_int()
        avg_speed = self.parse_int()
        download_num = self.parse_int64()
        file_count = self.parse_int()
        dir_count = self.parse_int()
        if self.has_unparsed_bytes():
            country_code = self.parse_string()
        else:
            country_code = None
        return username, exists, status, avg_speed, download_num, file_count, dir_count, country_code

    def parse_server(self):
        super().parse()
        username = self.parse_string()
        return username


class GetUserStatus(Message):
    MESSAGE_ID = 0x07

    @classmethod
    def create(cls, username: str):
        return pack_message(cls.MESSAGE_ID, pack_string(username))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        status = self.parse_int()
        privileged = self.parse_bool()
        return username, status, privileged


class ChatRoomMessage(Message):
    MESSAGE_ID = 0x0D

    @classmethod
    def create(cls, room: str, message: str):
        return pack_message(cls.MESSAGE_ID, pack_string(room) + pack_string(message))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        username = self.parse_string()
        message = self.parse_string()
        return room, username, message


class ChatJoinRoom(Message):
    MESSAGE_ID = 0x0E

    @classmethod
    def create(cls, room: str):
        return pack_message(cls.MESSAGE_ID, pack_string(room))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        users = self.parse_list(parse_string)
        users_status = self.parse_list(parse_int)
        users_data = self.parse_list(parse_user_data_entry)
        users_slots_free = self.parse_list(parse_int)
        users_countries = self.parse_list(parse_string)

        if self.has_unparsed_bytes():
            owner = self.parse_string()
            operators = self.parse_list(parse_string)
        else:
            owner = None
            operators = []

        return room, users, users_status, users_data, users_slots_free, users_countries, owner, operators


class ChatLeaveRoom(Message):
    MESSAGE_ID = 0x0F

    @classmethod
    def create(cls, room: str):
        return pack_message(cls.MESSAGE_ID, pack_string(room))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        return room


class ChatUserJoinedRoom(Message):
    MESSAGE_ID = 0x10

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        username = self.parse_string()
        status = self.parse_int()
        avg_speed = self.parse_int()
        download_num = self.parse_int64()
        file_count = self.parse_int()
        dir_count = self.parse_int()
        slots_free = self.parse_int()
        country = self.parse_string()
        return room, username, status, avg_speed, download_num, file_count, dir_count, slots_free, country


class ChatUserLeftRoom(Message):
    MESSAGE_ID = 0x11

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        username = self.parse_string()
        return room, username


class ConnectToPeer(Message):
    MESSAGE_ID = 0x12

    @classmethod
    def create(cls, ticket: int, username: str, typ: str) -> bytes:
        message_body = pack_int(ticket) + pack_string(username) + pack_string(typ)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        typ = self.parse_string()
        ip_addr = self.parse_ip()
        port = self.parse_int()
        ticket = self.parse_int()
        privileged = self.parse_uchar()

        # The following 2 integers aren't described in the Museek documentation:
        # the second of these 2 is the obfuscated port. I'm not sure about the
        # meaning of the first one, but possibly it's just to indicate there is
        # an obfuscated port (I've only ever seen it as being '1' with and an
        # obfuscated port
        if self.has_unparsed_bytes():
            unknown = self.parse_int()
            obfuscated_port = self.parse_int()
            return username, typ, ip_addr, port, ticket, privileged, unknown, obfuscated_port
        else:
            return username, typ, ip_addr, port, ticket, privileged, None, None

    def parse_server(self):
        super().parse()
        ticket = self.parse_int()
        username = self.parse_string()
        typ = self.parse_string()
        return ticket, username, typ


class ChatPrivateMessage(Message):
    MESSAGE_ID = 0x16

    @classmethod
    def create(cls, username: str, message: str):
        message_body = pack_string(username) + pack_string(message)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        chat_id = self.parse_int()
        timestamp = self.parse_int()
        username = self.parse_string()
        message = self.parse_string()
        if self.has_unparsed_bytes():
            is_admin = self.parse_bool()
        else:
            is_admin = False
        return chat_id, timestamp, username, message, is_admin


class ChatAckPrivateMessage(Message):
    MESSAGE_ID = 0x17

    @classmethod
    def create(cls, chat_id: int):
        return pack_message(cls.MESSAGE_ID, pack_int(chat_id))


class FileSearch(Message):
    MESSAGE_ID = 0x1A

    @classmethod
    def create(cls, ticket: int, query: str):
        message_body = pack_int(ticket) + pack_string(query)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        # This from another user? Doesn't seem like a response to our query
        super().parse()
        username = self.parse_string()
        ticket = self.parse_int()
        query = self.parse_string()
        return username, ticket, query

    def parse_server(self):
        super().parse()
        ticket = self.parse_int()
        query = self.parse_string()
        return ticket, query


class SetStatus(Message):
    MESSAGE_ID = 0x1C

    @classmethod
    def create(cls, status: int):
        """1 for away, 2 for online"""
        message_body = pack_int(status)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        status = self.parse_int()
        return status


class Ping(Message):
    MESSAGE_ID = 0x20

    @classmethod
    def create(cls):
        return pack_message(cls.MESSAGE_ID, b'')

    def parse_server(self):
        super().parse()


class SharedFoldersFiles(Message):
    MESSAGE_ID = 0x23

    @classmethod
    def create(cls, dir_count: int, file_count: int) -> bytes:
        message_body = pack_int(dir_count) + pack_int(file_count)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        dir_count = self.parse_int()
        file_count = self.parse_int()
        return dir_count, file_count


class GetUserStats(Message):
    MESSAGE_ID = 0x24

    @classmethod
    def create(cls, username: str) -> bytes:
        message_body = pack_string(username)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        avg_speed = self.parse_int()
        download_num = self.parse_int64()
        files = self.parse_int()
        dirs = self.parse_int()
        return username, avg_speed, download_num, files, dirs

    def parse_server(self):
        super().parse()
        username = self.parse_string()
        return username


class UserSearch(Message):
    MESSAGE_ID = 0x2A

    @classmethod
    def create(cls, username: str, ticket: int, query: str):
        message_body = (
            pack_string(username) + pack_int(ticket) + pack_string(query))
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        username = self.parse_string()
        ticket = self.parse_int()
        query = self.parse_string()
        return username, ticket, query


class RoomList(Message):
    MESSAGE_ID = 0x40

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        rooms = self.parse_room_list()
        rooms_private_owned = self.parse_room_list()
        rooms_private = self.parse_room_list()
        rooms_private_operated = self.parse_list(parse_string)
        return rooms, rooms_private_owned, rooms_private, rooms_private_operated


class PrivilegedUsers(Message):
    MESSAGE_ID = 0x45

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_list(parse_string)


class HaveNoParent(Message):
    MESSAGE_ID = 0x47

    @classmethod
    def create(cls, have_parents: bool) -> bytes:
        message_body = pack_bool(have_parents)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        have_parents = self.parse_uchar()
        return have_parents


class ParentIP(Message):
    MESSAGE_ID = 0x49

    @classmethod
    def create(cls, ip_addr: str) -> bytes:
        message_body = pack_ip(ip_addr)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        ip_addr = self.parse_ip()
        return ip_addr


class ParentMinSpeed(Message):
    MESSAGE_ID = 0x53

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class ParentSpeedRatio(Message):
    MESSAGE_ID = 0x54

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class SearchInactivityTimeout(Message):
    MESSAGE_ID = 0x57

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class MinParentsInCache(Message):
    MESSAGE_ID = 0x58

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class DistributedAliveInterval(Message):
    MESSAGE_ID = 0x5A

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class AddPrivilegedUser(Message):
    MESSAGE_ID = 0x5B

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_string()


class CheckPrivileges(Message):
    MESSAGE_ID = 0x5C

    @classmethod
    def create(cls):
        return pack_message(cls.MESSAGE_ID, b'')

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        time_left = self.parse_int()
        return time_left

    def parse_server(self):
        super().parse()


class ServerSearchRequest(Message):
    MESSAGE_ID = 0x5D

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        distrib_code = self.parse_uchar()
        unknown = self.parse_int()
        username = self.parse_string()
        ticket = self.parse_int()
        query = self.parse_string()
        return distrib_code, unknown, username, ticket, query


class AcceptChildren(Message):
    MESSAGE_ID = 0x64

    @classmethod
    def create(cls, accept: bool) -> bytes:
        message_body = pack_bool(accept)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        accept = self.parse_uchar()
        return accept


class NetInfo(Message):
    MESSAGE_ID = 0x66

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_list(item_parser=parse_net_info_entry)


class WishlistSearch(Message):
    MESSAGE_ID = 0x67

    @classmethod
    def create(cls, ticket: int, query: str):
        message_body = pack_int(ticket) + pack_string(query)
        return pack_message(cls.MESSAGE_ID, message_body)


class WishlistInterval(Message):
    MESSAGE_ID = 0x68

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class SimilarUsers(Message):
    MESSAGE_ID = 0x6E

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_list(item_parser=parse_similar_user)


class ItemRecommendations(Message):
    MESSAGE_ID = 0x6F

    @classmethod
    def create(cls, recommendation: str):
        return pack_message(cls.MESSAGE_ID, pack_string(recommendation))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        item = self.parse_string()
        recommendations = self.parse_list(item_parser=parse_item_recommendation)
        return item, recommendations


class ChatRoomTickers(Message):
    MESSAGE_ID = 0x71

    @staticmethod
    def parse_ticker(pos: int, value: bytes):
        pos, user = parse_string(pos, value)
        pos, tickers = parse_string(pos, value)
        return pos, (user, tickers)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        tickers = self.parse_list(self.parse_ticker)
        return room, tickers


class ChatRoomTickerAdd(Message):
    MESSAGE_ID = 0x72

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        user = self.parse_string()
        ticker = self.parse_string()
        return room, user, ticker


class ChatRoomTickerRemove(Message):
    MESSAGE_ID = 0x73

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        user = self.parse_string()
        return room, user


class ChatRoomTickerSet(Message):
    MESSAGE_ID = 0x74

    @classmethod
    def create(cls, room: str, ticker: str):
        message_body = pack_string(room) + pack_string(ticker)
        return pack_message(cls.MESSAGE_ID, message_body)


class ChatRoomSearch(Message):
    MESSAGE_ID = 0x78

    @classmethod
    def create(cls, room: str, ticket: str, query: str):
        message_body = pack_string(room) + pack_string(ticket) + pack_string(query)
        return pack_message(cls.MESSAGE_ID, message_body)


class SendUploadSpeed(Message):
    MESSAGE_ID = 0x79

    @classmethod
    def create(cls, speed: int) -> bytes:
        message_body = pack_int(speed)
        return pack_message(cls.MESSAGE_ID, message_body)


class GivePrivileges(Message):
    MESSAGE_ID = 0x7B

    @classmethod
    def create(cls, username, days):
        message_body = pack_string(username) + pack_int(days)
        return pack_message(cls.MESSAGE_ID, message_body)


class PrivilegesNotification(Message):
    MESSAGE_ID = 0x7C

    @classmethod
    def create(cls, ticket: int, username: str):
        message_body = (
            pack_int(ticket) + pack_string(username))
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        ticket = self.parse_int()
        username = self.parse_string()
        return ticket, username


class PrivilegesNotificationAck(Message):
    MESSAGE_ID = 0x7D

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        ticket = self.parse_int()
        return ticket


class BranchLevel(Message):
    MESSAGE_ID = 0x7E

    @classmethod
    def create(cls, branch_level: int) -> bytes:
        message_body = pack_int(branch_level)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        level = self.parse_int()
        return level


class BranchRoot(Message):
    MESSAGE_ID = 0x7F

    @classmethod
    def create(cls, branch_root: str) -> bytes:
        message_body = pack_string(branch_root)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        root = self.parse_string()
        return root


class ChildDepth(Message):
    MESSAGE_ID = 0x81

    @classmethod
    def create(cls, child_depth: int) -> bytes:
        message_body = pack_int(child_depth)
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        child_depth = self.parse_int()
        return child_depth


class PrivateRoomUsers(Message):
    MESSAGE_ID = 0x85

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room_name = self.parse_string()
        usernames = self.parse_list(item_parser=parse_string)
        return room_name, usernames


class PrivateRoomAddUser(Message):
    MESSAGE_ID = 0x86

    @classmethod
    def create(cls, room: str, user: str):
        message_body = pack_string(room) + pack_string(user)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        user = self.parse_string()
        return room, user


class ChatPrivateRoomRemoveUser(Message):
    MESSAGE_ID = 0x87

    @classmethod
    def create(cls, room: str, user: str):
        message_body = pack_string(room) + pack_string(user)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        user = self.parse_string()
        return room, user


class PrivateRoomDropMembership(Message):
    MESSAGE_ID = 0x87

    @classmethod
    def create(cls, room: str):
        return pack_message(cls.MESSAGE_ID, pack_string(room))


class PrivateRoomDropOwnership(Message):
    MESSAGE_ID = 0x88

    @classmethod
    def create(cls, room: str):
        return pack_message(cls.MESSAGE_ID, pack_string(room))


class PrivateRoomAdded(Message):
    MESSAGE_ID = 0x8B

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        return room


class PrivateRoomRemoved(Message):
    MESSAGE_ID = 0x8C

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        return room


class PrivateRoomToggle(Message):
    MESSAGE_ID = 0x8D

    @classmethod
    def create(cls, enable: bool):
        return pack_message(cls.MESSAGE_ID, pack_bool(enable))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        enable = self.parse_bool()
        return enable


class NewPassword(Message):
    MESSAGE_ID = 0x8E

    @classmethod
    def create(cls, password: str):
        return pack_message(cls.MESSAGE_ID, pack_string(password))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        password = self.parse_string()
        return password


class PrivateRoomAddOperator(Message):
    MESSAGE_ID = 0x8F

    @classmethod
    def create(cls, room: str, operator: str):
        message_body = pack_string(room) + pack_string(operator)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        operator = self.parse_string()
        return room, operator


class PrivateRoomRemoveOperator(Message):
    MESSAGE_ID = 0x90

    @classmethod
    def create(cls, room: str, operator: str):
        message_body = pack_string(room) + pack_string(operator)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        operator = self.parse_string()
        return room, operator


class PrivateRoomOperatorAdded(Message):
    MESSAGE_ID = 0x91

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        return room


class PrivateRoomOperatorRemoved(Message):
    MESSAGE_ID = 0x92

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        return room


class PrivateRoomOperators(Message):
    MESSAGE_ID = 0x94

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room = self.parse_string()
        operators = self.parse_list(parse_string)
        return room, operators


class ChatMessageUsers(Message):
    MESSAGE_ID = 0x95

    @classmethod
    def create(cls, users, message: str):
        message_body = pack_list(users, pack_func=pack_string) + pack_string(message)
        return pack_message(cls.MESSAGE_ID, message_body)


class ChatEnablePublic(Message):
    MESSAGE_ID = 0x96


class ChatDisablePublic(Message):
    MESSAGE_ID = 0x97


class ChatServerMessage(Message):
    MESSAGE_ID = 0x98

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        room_name = self.parse_string()
        username = self.parse_string()
        message = self.parse_string()
        return room_name, username, message


class FileSearchEx(Message):
    """File search sent by SoulSeekQT, the message received from the server
    seems to be some kind of acknowledgement. The query is repeated and what
    looks like an integer (always seems to be 0)
    """
    MESSAGE_ID = 0x99

    @classmethod
    def create(cls, query):
        message_body = pack_string(query)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        query = self.parse_string()
        unknown = self.parse_int()
        return query, unknown

    def parse_server(self):
        super().parse()
        query = self.parse_string()
        return query


class CannotConnect(Message):
    MESSAGE_ID = 0x3E9

    @classmethod
    def create(cls, ticket: int, username: str) -> bytes:
        message_body = pack_int(ticket) + pack_string(username)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        ticket = self.parse_int()
        # Username appears to be optional
        if self.has_unparsed_bytes():
            username = self.parse_string()
        else:
            username = None
        return ticket, username

    def parse_server(self):
        super().parse()
        ticket = self.parse_int()
        username = self.parse_string()
        return ticket, username


# Distributed messages

class DistributedMessage(Message):
    pass


class DistributedSearchRequest(DistributedMessage):
    MESSAGE_ID = 0x03

    @classmethod
    def create_from_body(cls, body: bytes):
        return pack_message(cls.MESSAGE_ID, body, id_as_uchar=True)

    @classmethod
    def create(cls, username: str, ticket: int, query: str, unknown=0) -> bytes:
        message_body = (
            pack_int(unknown) + pack_string(username) + pack_int(ticket) + pack_string(query))
        return pack_message(cls.MESSAGE_ID, message_body, id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Parse Length + Message ID
        self.parse_int()
        self.parse_uchar()
        # Contents
        unknown = self.parse_int()  # Always 0x31
        username = self.parse_string()
        ticket = self.parse_int()
        query = self.parse_string()
        return unknown, username, ticket, query


class DistributedBranchLevel(DistributedMessage):
    MESSAGE_ID = 0x04

    @classmethod
    def create(cls, level: int) -> bytes:
        message_body = pack_int(level)
        return pack_message(cls.MESSAGE_ID, message_body, id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Parse Length + Message ID
        self.parse_int()
        self.parse_uchar()
        # Contents
        level = self.parse_int()
        return level


class DistributedBranchRoot(DistributedMessage):
    MESSAGE_ID = 0x05

    @classmethod
    def create(cls, root: str) -> bytes:
        message_body = pack_string(root)
        return pack_message(cls.MESSAGE_ID, message_body, id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Parse Length + Message ID
        self.parse_int()
        self.parse_uchar()
        # Contents
        root = self.parse_string()
        return root


class DistributedChildDepth(DistributedMessage):
    MESSAGE_ID = 0x07

    @classmethod
    def create(cls, child_depth: int) -> bytes:
        message_body = pack_int(child_depth)
        return pack_message(cls.MESSAGE_ID, message_body, id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Parse Length + Message ID
        self.parse_int()
        self.parse_uchar()
        # Contents
        child_depth = self.parse_int()
        return child_depth


class DistributedServerSearchRequest(DistributedMessage):
    MESSAGE_ID = 0x5D

    @classmethod
    def create(cls, distrib_code: int, username: str, ticket: int, query: str, unknown: int = 49):
        message_body = (
            pack_uchar(distrib_code) +
            pack_int(unknown) +
            pack_string(username) +
            pack_int(ticket) +
            pack_string(query)
        )
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse(self):
        super().parse()
        distrib_code = self.parse_uchar()
        # This is a list of bytes as is
        message = self.get_unparsed_bytes()
        return distrib_code, message


# Peer messages
# PeerPierceFirewall and PeerInit are the only messages that use a uchar for
# the message_id. Remainder of the message types use int.

class PeerMessage(Message):

    pass


# Init messages

class PeerPierceFirewall(PeerMessage):
    MESSAGE_ID = 0x00

    @classmethod
    def create(cls, ticket: int) -> bytes:
        return pack_message(cls.MESSAGE_ID, pack_int(ticket), id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Parse Length + Message ID
        self.parse_int()
        self.parse_uchar()
        ticket = self.parse_int()
        return ticket


class PeerInit(PeerMessage):
    MESSAGE_ID = 0x01

    @classmethod
    def create(cls, user: str, typ: str, ticket: int) -> bytes:
        message_body = (pack_string(user) + pack_string(typ) + pack_int(ticket))
        return pack_message(cls.MESSAGE_ID, message_body, id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Parse Length + Message ID
        self.parse_int()
        self.parse_uchar()
        user = self.parse_string()
        typ = self.parse_string()
        if len(self.get_unparsed_bytes()) == 4:
            ticket = self.parse_int()
        else:
            ticket = self.parse_int64()
        return user, typ, ticket


class PeerSharesRequest(PeerMessage):
    MESSAGE_ID = 0x04


class PeerSharesReply(PeerMessage):
    MESSAGE_ID = 0x05

    @classmethod
    def create(cls, directories: List[DirectoryData]):
        body = pack_list(directories, pack_func=lambda d: d.pack())
        return pack_message(cls.MESSAGE_ID, zlib.compress(body))

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        shares_message = zlib.decompress(self.message[self._pos:])
        self._pos = len(self.message)
        _, directories = parse_list(0, shares_message, item_parser=parse_directory)
        return directories


class PeerSearchReply(PeerMessage):
    MESSAGE_ID = 0x09

    @classmethod
    def create(
            cls, username: str, ticket: int, results: List[FileData],
            has_slots_free: bool, avg_speed: int, queue_size: int,
            locked_results: List[FileData] = None):
        message_body = (
            pack_string(username) +
            pack_int(ticket) +
            pack_list(results, pack_func=lambda f: f.pack()) +
            pack_bool(has_slots_free) +
            pack_int(avg_speed) +
            pack_int(queue_size)
        )

        if locked_results:
            message_body += pack_list(locked_results, pack_func=lambda f: f.pack())

        # Locked results not properly tested
        # TODO: Require some investigation if these locked results actually
        # exist or if the 'one' is actually used to indicate this (could also
        # be both)

        return pack_message(cls.MESSAGE_ID, zlib.compress(message_body))

    @warn_on_unparsed_bytes
    def parse(self):
        length, _ = super().parse()

        # Decompress the contents and treat it as a new message
        # The length of the message contained in the message excludes the length
        # itself. Thus we need to add 4 bytes (the length indicator) as we are
        # getting data from the entire message
        message = PeerSearchReply(zlib.decompress(self.message[self._pos:length + 4]))
        # Upon success store the new _pos
        self._pos += length + 4

        username = message.parse_string()
        token = message.parse_int()
        results = message.parse_list(item_parser=parse_file)
        has_free_slots = message.parse_bool()
        avg_speed = message.parse_int()
        queue_size = message.parse_int64()
        if len(message.message[message._pos:]) > 0:
            locked_results = message.parse_list(item_parser=parse_file)
        else:
            locked_results = []
        return username, token, results, has_free_slots, avg_speed, queue_size, locked_results


class PeerUserInfoRequest(PeerMessage):
    MESSAGE_ID = 0x0F

    @classmethod
    def create(cls) -> bytes:
        return pack_message(cls.MESSAGE_ID, bytes())

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return None


class PeerUserInfoReply(PeerMessage):
    MESSAGE_ID = 0x10

    @classmethod
    def create(cls, description: str, upload_slots: int, queue_size: int, has_slots_free: bool, picture: str = None) -> bytes:
        message_body = pack_string(description)

        has_picture = bool(picture)
        message_body += pack_bool(has_picture)
        if has_picture:
            message_body += pack_string()

        message_body += (
            pack_int(upload_slots) +
            pack_int(queue_size) +
            pack_bool(has_slots_free)
        )
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        description = self.parse_string()
        has_picture = self.parse_bool()
        if has_picture:
            picture = self.parse_string()
        else:
            picture = None
        # upload slots = total amount of slots, queue_size = queued uploads,
        # has_slots_free
        upload_slots = self.parse_int()
        queue_size = self.parse_int()
        has_slots_free = self.parse_bool()
        return description, picture, upload_slots, queue_size, has_slots_free


class PeerDirectoryContentsRequest(PeerMessage):
    MESSAGE_ID = 0x24

    @classmethod
    def create(cls, directories: List[str]):
        message_body = pack_list(directories, pack_func=pack_string)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        directories = self.parse_list(item_parser=parse_string)
        return directories


class PeerDirectoryContentsReply(PeerMessage):
    MESSAGE_ID = 0x24

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        directories = self.parse_list(item_parser=parse_directory)
        return directories


class PeerTransferRequest(PeerMessage):
    MESSAGE_ID = 0x28

    @classmethod
    def create(cls, direction: int, ticket: int, filename: str, filesize: int = None):
        message_body = (
            pack_int(direction) + pack_int(ticket) + pack_string(filename))
        if filesize is not None:
            message_body += pack_int64(filesize)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        direction = self.parse_int()
        ticket = self.parse_int()
        filename = self.parse_string()
        # Museek docs say that if transfer direction is 1 (download) then
        # the file size will be sent. That's not what I saw, simply check if we
        # have unparsed bytes instead of checking direction. It is true that the
        # filesize always seems to be 0 if direction == 0
        if self.has_unparsed_bytes():
            filesize = self.parse_int64()
        else:
            filesize = 0
        return direction, ticket, filename, filesize


class PeerTransferReply(PeerMessage):
    MESSAGE_ID = 0x29

    @classmethod
    def create(cls, ticket: int, allowed: bool, filesize: int = None, reason: str = None):
        message_body = pack_int(ticket) + pack_bool(allowed)
        if filesize is not None:
            message_body += pack_int64(filesize)
        if reason is not None:
            message_body += pack_string(reason)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        # Error in the specification for 2 reasons:
        # 1. Ticket should be an int and not a string
        # 2. The filesize and reason are only optionally returned
        ticket = self.parse_int()
        allowed = self.parse_bool()
        if not self.has_unparsed_bytes():
            return ticket, allowed, 0, None
        else:
            if allowed:
                filesize = self.parse_int64()
                return ticket, allowed, filesize, None
            else:
                reason = self.parse_string()
                return ticket, allowed, 0, reason


class PeerTransferQueue(PeerMessage):
    MESSAGE_ID = 0x2B

    @classmethod
    def create(cls, filename: str) -> bytes:
        message_body = pack_string(filename)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        filename = self.parse_string()
        return filename


class PeerPlaceInQueueReply(PeerMessage):
    MESSAGE_ID = 0x2C

    @classmethod
    def create(cls, filename: str, place: int) -> bytes:
        message_body = pack_string(filename) + pack_int(place)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        filename = self.parse_string()
        place = self.parse_int()
        return filename, place


class PeerUploadFailed(PeerMessage):
    MESSAGE_ID = 0x2E

    @classmethod
    def create(cls, filename: str) -> bytes:
        message_body = pack_string(filename)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        filename = self.parse_string()
        return filename


class PeerTransferQueueFailed(PeerMessage):
    MESSAGE_ID = 0x32

    @classmethod
    def create(cls, filename: str, reason: str) -> bytes:
        message_body = pack_string(filename) + pack_string(reason)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        filename = self.parse_string()
        reason = self.parse_string()
        return filename, reason


class PeerPlaceInQueueRequest(PeerMessage):
    MESSAGE_ID = 0x33

    @classmethod
    def create(cls, filename: str) -> bytes:
        message_body = pack_string(filename)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        filename = self.parse_string()
        return filename


def parse_message(message):
    """Attempts to parse a server message"""
    pos, length = parse_int(0, message)
    pos, message_id = parse_int(pos, message)
    for msg_class in Message.__subclasses__():
        if msg_class.MESSAGE_ID == message_id:
            return msg_class(message)
    raise UnknownMessageError(message_id, message, "Failed to parse server message")


def parse_server_messages(message):
    """Parses multiple messages from a single message"""
    current_message = message
    message_objects = []
    while len(current_message) > 0:
        message_object = parse_message(current_message)
        # Call parse to get unparsed bytes, remove the unparsed bytes from the
        # current message object
        message_object.parse()
        unparsed_bytes = message_object.get_unparsed_bytes()
        if message_object.has_unparsed_bytes():
            message_object.message = message_object.message[:-len(unparsed_bytes)]

        # Call reset and append to the list
        message_object.reset()
        message_objects.append(message_object)

        # Set current message to the unparsed bytes
        current_message = unparsed_bytes
    return message_objects


def parse_distributed_message(message):
    """Attempts to parse a distributed message"""
    pos, length = parse_int(0, message)
    pos, message_id = parse_uchar(pos, message)
    for msg_class in DistributedMessage.__subclasses__():
        if msg_class.MESSAGE_ID == message_id:
            return msg_class(message)
    raise UnknownMessageError(message_id, message, "Failed to parse distributed message")


def parse_peer_message(message):
    """Attempts to parse a peer message"""
    pos, length = parse_int(0, message)
    pos, message_id = parse_uchar(pos, message)
    for msg_class in PeerMessage.__subclasses__():
        if msg_class.MESSAGE_ID == message_id:
            return msg_class(message)
    raise UnknownMessageError(message_id, message, "Failed to parse peer message")


def parse_peer_messages(message):
    """Parses multiple messages from a single message"""
    current_message = message
    message_objects = []
    while len(current_message) > 0:
        message_object = parse_peer_message(current_message)
        # Call parse to get unparsed bytes, remove the unparsed bytes from the
        # current message object
        message_object.parse()
        unparsed_bytes = message_object.get_unparsed_bytes()
        if message_object.has_unparsed_bytes():
            message_object.message = message_object.message[:-len(unparsed_bytes)]

        # Call reset and append to the list
        message_object.reset()
        message_objects.append(message_object)

        # Set current message to the unparsed bytes
        current_message = unparsed_bytes
    return message_objects
