import functools
import hashlib
import logging
from pydoc import classname
import socket
import struct
from typing import Callable
import zlib

from exceptions import UnknownMessageError


logger = logging.getLogger()


def calc_md5(value: bytes):
    enc = hashlib.md5()
    enc.update(value.encode('ascii'))
    return enc.hexdigest()


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


def parse_list(pos: int, data, item_parser: Callable=parse_string) -> list:
    items = []
    pos_after_list_len, list_len = parse_int(pos, data)
    current_item_pos = pos_after_list_len
    for idx in range(list_len):
        current_item_pos, item = item_parser(current_item_pos, data)
        items.append(item)
    return current_item_pos, items


def parse_room_list(pos: int, data):
    pos, room_names = parse_list(pos, data, item_parser=parse_string)
    pos, room_user_counts = parse_list(pos, data, item_parser=parse_int)
    return pos, dict(list(zip(room_names, room_user_counts)))


def parse_net_info_entry(pos: int, message):
    pos, user = parse_string(pos, message)
    pos, ip = parse_ip(pos, message)
    pos, port = parse_int(pos, message)
    return pos, (user, ip, port, )


# Packing functions
def pack_int(value: int) -> bytes:
    return struct.pack('<I', value)


def pack_int64(value: int) -> bytes:
    return struct.pack('<Q', value)


def pack_uchar(value: str) -> bytes:
    return struct.pack('<B', value)


def pack_string(value: str) -> bytes:
    length = len(value)
    if isinstance(value, bytes):
        return (
            pack_int(length) + value)
    else:
        return (
            pack_int(length) + struct.pack('{}s'.format(length), value.encode('utf-8')))


def pack_bool(value: bool) -> bytes:
    return struct.pack('<?', value)


def pack_ip(value: str) -> bytes:
    ip_b = socket.inet_aton(value)
    return struct.pack('<4s', bytes(reversed(ip_b)))


def pack_message(message_id: int, value: bytes, id_as_uchar=False) -> bytes:
    """Adds the header (length + message ID) to a message body

    @param id_as_uchar: Packs the L{message_id} as uchar instead of int, used
        for L{PeerInit} and L{PierceFirewall}
    """
    # Add message ID
    if id_as_uchar:
        full_body = pack_uchar(message_id) + value
    else:
        full_body = pack_int(message_id) + value
    # Add length
    return struct.pack('<I', len(full_body)) + full_body


def warn_on_unparsed_bytes(parse_func):
    @functools.wraps(parse_func)
    def check_for_unparsed_bytes(message):
        results = parse_func(message)
        unparsed_bytes = message.get_unparsed_bytes()
        if len(unparsed_bytes) > 0:
            logger.warning(
                f"{message.__class__.__name__} has {len(unparsed_bytes)} unparsed bytes : {unparsed_bytes.hex()!r}")
        return results
    return check_for_unparsed_bytes


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
            pack_string(username) + pack_string(password) +
            pack_int(client_version) + pack_string(md5_hash) + pack_int(minor_version))
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        result = self.parse_uchar()
        if result == 1:
            greet = self.parse_string()
            ip = self.parse_ip()
            md5hash = self.parse_string()
            unknown = self.parse_uchar()
            return result, greet, ip, md5hash, unknown
        else:
            reason = self.parse_string()
            return result, reason

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

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        status = self.parse_int()
        privileged = self.parse_uchar()
        return username, status, privileged


class ConnectToPeer(Message):
    MESSAGE_ID = 0x12

    @classmethod
    def create(cls, token: int, username: str, typ: str) -> bytes:
        message_body = pack_int(token) + pack_string(username) + pack_string(typ)
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        username = self.parse_string()
        typ = self.parse_string()
        ip_addr = self.parse_ip()
        port = self.parse_int()
        token = self.parse_int()
        privileged = self.parse_uchar()

        # The following 2 integers aren't described in the Museek documentation:
        # the second of these 2 is the obfuscated port. I'm not sure about the
        # meaning of the first one, but possibly it's just to indicate there is
        # an obfuscated port (I've only ever seen it as being '1' with and an
        # obfuscated port
        if self.has_unparsed_bytes():
            unknown = self.parse_int()
            obfuscated_port = self.parse_int()
            return username, typ, ip_addr, port, token, privileged, unknown, obfuscated_port
        else:
            return username, typ, ip_addr, port, token, privileged, None, None

    def parse_server(self):
        super().parse()
        token = self.parse_int()
        username = self.parse_string()
        typ = self.parse_string()
        return token, username, typ


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


class HaveNoParents(Message):
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


class WishlistInterval(Message):
    MESSAGE_ID = 0x68

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        return self.parse_int()


class PrivilegeNotification(Message):
    MESSAGE_ID = 0x7C

    @classmethod
    def create(cls, token: int, username: str):
        message_body = (
            pack_int(token) + pack_string(username))
        return pack_message(cls.MESSAGE_ID, message_body)

    def parse_server(self):
        super().parse()
        token = self.parse_int()
        username = self.parse_string()
        return token, username


class AckPrivilegeNotification(Message):
    MESSAGE_ID = 0x7D

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        token = self.parse_int()
        return token


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


### Distributed messages

class DistributedMessage(Message):

    pass


class DistributedPing(DistributedMessage):
    MESSAGE_ID = 0x00

    @warn_on_unparsed_bytes
    def parse(self):
        length = self.parse_int()
        message_id = self.parse_uchar()
        # This field is described as 'unknown' in the MuSeek wiki, however it
        # seems to be the ticket number we used when sending our ConnectToPeer
        # message during instantiation of the connection
        if len(self.message[self._pos:]) > 0:
            ticket = self.parse_int()
        else:
            # I don't recall when this occurs again
            # Perhaps None would be better as 0 would be a valid ticket number
            ticket = 0
        return ticket


class DistributedSearchRequest(DistributedMessage):
    MESSAGE_ID = 0x03

    @classmethod
    def create(cls, username: str, ticket: int, query: str, unknown=0) -> bytes:
        message_body = (
            pack_int(unknown) + pack_string(username) + pack_int(ticket) + pack_string(query))
        return pack_message(cls.MESSAGE_ID, message_body, id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Override super as message_id is a uchar for this function
        length = self.parse_int()
        message_id = self.parse_uchar()
        # Contents
        unknown = self.parse_int()
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
        # Override super as message_id is a uchar for this function
        length = self.parse_int()
        message_id = self.parse_uchar()
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
        # Override super as message_id is a uchar for this function
        length = self.parse_int()
        message_id = self.parse_uchar()
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
        # Override super as message_id is a uchar for this function
        length = self.parse_int()
        message_id = self.parse_uchar()
        # Contents
        child_depth = self.parse_int()
        return child_depth


class DistributedServerSearchRequest(DistributedMessage):
    MESSAGE_ID = 0x5D

    @warn_on_unparsed_bytes
    def parse(self):
        length, _ = super().parse()
        distrib_code = self.parse_uchar()
        # This is a list of bytes as is
        message = self.get_unparsed_bytes()
        return distrib_code, message


### Peer messages
# PeerPierceFirewall and PeerInit are the only messages that use a uchar for
# the message_id. Remainder of the message types use int.

class PeerMessage(Message):

    pass


class PeerPierceFirewall(PeerMessage):
    MESSAGE_ID = 0x00

    @classmethod
    def create(cls, ticket: int) -> bytes:
        return pack_message(cls.MESSAGE_ID, pack_int(ticket), id_as_uchar=True)

    @warn_on_unparsed_bytes
    def parse(self):
        # Override super as message_id is a uchar for this function
        length = self.parse_int()
        message_id = self.parse_uchar()
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
        # Override super as message_id is a uchar for this function
        length = self.parse_int()
        message_id = self.parse_uchar()
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

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        raise NotImplementedError()


class PeerSearchReply(PeerMessage):
    MESSAGE_ID = 0x09

    @classmethod
    def create(cls, username: str, ticket: int, results, slotfree: bool, avg_speed: int, queue_len: int):
        message_body = pack_string(username) + pack_int(ticket)

        message_body += pack_int(len(results))

        results_body = bytes()
        for result in results:
            results_body += (
                pack_uchar(1) +
                pack_string(result['filename']) +
                pack_int64(result['filesize']) +
                pack_string(result['extension'])
            )

            results_body += pack_int(len(results['attributes']))
            for attr_place, attr_value in results['attributes']:
                results_body += pack_int(attr_place) + pack_int(attr_value)

        message_body += results_body

        message_body += (
            pack_bool(slotfree) +
            pack_int(avg_speed) +
            pack_int(queue_len)
        )

        # Locked results not implemented
        # TODO: Require some investigation if these locked results actually
        # exist or if the 'one' is actually used to indicate this (could also
        # be both)

        return pack_message(cls.MESSAGE_ID, zlib.compress(message_body))

    def parse_result_list(self):
        results = []
        result_count = self.parse_int()
        for _ in range(result_count):
            result = {}
            one = self.parse_uchar()
            result['filename'] = self.parse_string()
            result['filesize'] = self.parse_int64()
            result['extension'] = self.parse_string()
            result['attributes'] = []
            attr_count = self.parse_int()
            for _ in range(attr_count):
                attr_place = self.parse_int()
                attr = self.parse_int()
                result['attributes'].append((attr_place, attr, ))
            results.append(result)
        return results

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
        results = message.parse_result_list()
        free_slots = message.parse_uchar()
        avg_speed = message.parse_int()
        queue_len = message.parse_int64()
        if len(message.message[message._pos:]) > 0:
            locked_results = message.parse_result_list()
        else:
            locked_results = []
        return username, token, results, free_slots, avg_speed, queue_len, locked_results


class PeerTransferRequest(PeerMessage):
    MESSAGE_ID = 0x28

    @classmethod
    def create(cls, direction: int, ticket: int, filename: str):
        message_body = (
            pack_int(direction) + pack_int(ticket) + pack_string(filename))
        return pack_message(cls.MESSAGE_ID, message_body)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        direction = self.parse_int()
        ticket = self.parse_int()
        filename = self.parse_string()
        if direction == 1:
            filesize = self.parse_int64()
            return direction, ticket, filename, filesize
        else:
            return direction, ticket, filename, 0


class PeerTransferReply(PeerMessage):
    MESSAGE_ID = 0x29

    @classmethod
    def create(cls, ticket: int, allowed: bool, filesize: int=None, reason: str=None):
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
        allowed = self.parse_uchar()
        if self.has_unparsed_bytes():
            return ticket, allowed, 0, None
        else:
            if allowed == 1:
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
    def create(cls) -> bytes:
        return pack_message(cls.MESSAGE_ID)

    @warn_on_unparsed_bytes
    def parse(self):
        super().parse()
        description = self.parse_string()
        has_picture = self.parse_bool()
        if has_picture:
            picture = self.parse_string()
        else:
            picture = None
        total_uploads = self.parse_int()
        queue_size = self.parse_int()
        has_slots_free = self.parse_bool()
        return description, picture, total_uploads, queue_size, has_slots_free



def parse_distributed_message(message):
    """Attempts to parse a distributed message"""
    pos, length = parse_int(0, message)
    pos, message_id = parse_uchar(pos, message)
    for msg_class in DistributedMessage.__subclasses__():
        if msg_class.MESSAGE_ID == message_id:
            return msg_class(message)
    raise UnknownMessageError(message_id, message, "Failed to parse distributed message")


def parse_distributed_messages(message):
    """Parses multiple messages from a single message"""
    current_message = message
    message_objects = []
    while len(current_message) > 0:
        message_object = parse_distributed_message(current_message)
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


def attempt_unpack(data):
    pos = 0
    msgs = []
    while pos < len(data):
        new_pos, msg_len = parse_int(pos, data)
        _, msg_type = parse_int(new_pos, data)
        msg = data[pos:new_pos + msg_len]
        msgs.append(msg)
        print("Length {}, message type {}, msg {}".format(msg_len, msg_type, msg.hex()))
        pos = new_pos + msg_len
    return msgs


if __name__ == "__main__":
    import pdb; pdb.set_trace()
    destination = ('server.slsknet.org', 2416, )

    username = "Khyle999"
    password = "Test1234"
    packet = Login.create(username, password, 168)
    # print ">>>>> {}".format(packet.encode('hex'))
    # response = send(destination, packet)
    # print "<<<<< {}".format(response.encode('hex'))
    logon_resp =  Login(bytes.fromhex('2200000001140000003940242356425a66642e436c31654870624d7534010000005000000000a400000009000000789c13616060b07450510e738a4a4bd173ce314cf52848f22d3561048a83713c90b830e762f385ed17bb2fecbab021262435b1a858212dbf48c10dc48a09cecf4b2f56702bcacf5528c9485570ca4c5770ce48cc2c8a313056702d4b2daa4cca4fa954084fcc2b295628c957082acd49052b0ccf2fca49d14bcb494c9edf7d0f6415033310e7161883281078c10c71c22f2066828a31a4384b810501997d3240')).parse()
    password_hash = calc_md5(password)
    roomlist_resp = RoomList(bytes.fromhex('360d000040000000ae0000001300000021202120536c736b204964696f7473202120210d00000021204974616c6f20446973636f1500000021212044796e616d69632d4d75736971756520212118000000212121203930277320526172652052696464696d202121210a000000212152494444494d21210d0000002152654747616547614c6158790b00000023486f72726f72636f72650a000000234c61204672616e636513000000236963696c6f6d6272652d68617264636f72650700000023706f6c736b6107000000237465716e69780a000000284129202f2f202845290a0000002a2a52494444494d2a2a0c0000002b426c61636b4d6574616c2b180000002b4849505f484f505f5343454e455f52454c45415345532b050000002d5126412d030000002e7275040000002f6d752f170000003139353020746f203139373520616b61207468652036300700000036306c6f76657218000000373020526172652067726f6f766520536f756c204a617a7a150000003830277320313220496e636865732026204d6f7265080000003930277320656d6f030000003a2d29160000003c3e456c656374726f6e696373204c6162656c733c3e02000000412b04000000414349440400000041436c4409000000415247454e54494e41090000004155535452414c494107000000416c636f686f6c07000000416d6269656e7405000000416e696d650a000000417564696f626f6f6b730a0000004176616e74676172646512000000424c5545532042554e4b4552204d555349430e000000424f422044594c414e20524f4f4d1000000042525554414c44454154484d4554414c0a000000426c75657326536f756c0600000042726173696c09000000427265616b636f7265050000004348494c450600000043616e6164610a0000004368696e6120526f6f6d090000004368697074756e65730a00000043687269737469616e7309000000436c6173736963616c09000000436f6d6d756e69736d100000004445415448204d4554414c20434c5542030000004455420c0000004461726b20416d6269656e740e0000004465204b6f666669652053686f70080000004465204b726f65670e000000446973636f20436c6173736963730a000000446f6f6d204d6574616c0a00000044756220546563686e6f07000000447562737465701500000045424d2d474f544849432d494e445553545249414c0600000045426f6f6b730a00000045617274686d75736963090000004575726f64616e6365170000004575726f766973696f6e20536f6e6720436f6e74657374180000004578706572696d656e74616c20456c656374726f6e6963610b00000046554e4b204652414e43450900000046726565204a617a7a0300000047617906000000476f74686963090000004772696e64636f726517000000484f555345204d55534943204c4f5645525320284147290e00000048617070792048617264636f72650b00000048617264636f7265204e4c0d00000048617264636f72652f70756e6b12000000486561727473206f662053706163652049490700000048697020486f700300000049444d0a000000494e445553545249414c18000000496e6372656469626c7920537472616e6765204d757369630600000049737261656c060000004974616c6961120000004974616c69616e5f64616e6365666c6f6f72040000004a617a7a0f0000004a617a7a202846756c6c2043447329170000004a617a7a2d526f636b2d467573696f6e2d4775697461720e0000004a756767616c6f2046616d696c79060000004a756e676c650a0000004b726175742d726f636b160000004c414e47554147452045584348414e47452068657265070000004c6173742e666d050000004c696e75780f0000004c6f73736c6573732053636f726573060000004d4f56494553050000004d6574616c0a0000004d6f62697573205069740a0000004d6f7669654d75736963060000004e4f52574159160000004e6577204372797374616c20566962726174696f6e73080000004e657720576176650b0000004e6577205a65616c616e640f0000004f4c445343484f4f4c2038382d39340c0000004f4c44534b4f4f4c20474f41030000004f69210b00000050535943484544454c49411300000050554e4b2f48415244434f52452f4752494e4408000000506f72747567616c09000000506f73742050756e6b1000000050726f677265737369766520526f636b1500000050737963686564656c69632f4163696420526f636b090000005073797472616e63650300000052414306000000524547474145060000005255535349410a00000052617265204d757369630c000000526574726f2047616d696e6707000000534b3853484f5007000000534c554447452118000000534f554c20273730732046554e4b59202620444953434f21090000005363656e655f5269700600000053636f72657312000000536f756e64747261636b732653636f72657305000000537061696e0b00000053746f6e657220486956650b00000053746f6e657220526f636b0d000000537472616e6765204d7573696317000000544543484e4f2c204d6978657320616e642054756e65730300000054484304000000544845581100000054686520363027732043617665526f6f6d150000005468652044616e6765726f7573204b69746368656e100000005468652057616c6b696e6720446561640c00000054686553636f72655a6f6e650c000000546872617368204d6574616c08000000547269702d486f700a0000005477656520466f6c6b7306000000554b2044554212000000556e64657267726f756e6420486970686f700f000000566964656f2047616d6520436861740d00000056696e796c20416464696374730700000057484154434473090000005748415443447a7a7a0e000000576861742e4344205265667567650b000000576f726c64204d75736963130000005d5b4765726d616e5d5b446575747363685d5b150000005e494c4c554d494e4154495e61776172656e65737309000000627265616b6265617406000000636f6d696373150000006465657020686f75736520636f6e6e656374696f6e0b0000006472756d276e27626173730b0000006565737469206d6568656407000000656c656374726f09000000666c61636669656c6404000000666f6f640e00000067617261676570756e6b2e636f6d0200000068690700000068756e6761727905000000696e6469650e0000006a6170616e657365206d757369630d0000006c696272617279206d75736963080000006c6f73736c6573730d0000006d696e696d616c206d75736963060000006d757365656b050000006e6f69736508000000706f7374726f636b0b00000070726f6772616d6d696e671100000070726f677265737369766520686f7573650300000072796d0800000073686f6567617a650e000000736f75746865726e4f7261636c6510000000737570657220626c75657320726f6f6d0c0000007472616e63456164646963740c00000076696265732063617274656c07000000776861742e636412000000776861742e636420656c656374726f6e69630c000000776861742e63642d666c6163140000007b7b7b7b7b204e45572042454154207d7d7d7d7dae000000150000001f0000000500000017000000120000002100000009000000300000000900000018000000050000000c0000000a000000650000000500000017000000090000005e0000000900000007000000120000000a0000001000000030000000240000000a0000000e000000110000000f00000006000000080000004d000000120000000a000000080000002d00000008000000050000000c0000001f000000100000000d0000000d00000005000000090000000a0000000f0000000f000000220000000a000000110000000d00000014000000080000000f0000000c00000011000000110000002200000007000000050000000c0000000e0000000c0000000b0000000a00000012000000090000002100000013000000100000002900000006000000190000002500000015000000090000000b0000000c000000070000000900000020000000060000000e0000000b00000005000000150000000500000013000000180000000e0000001a0000000600000014000000060000000a00000007000000090000002100000005000000060000000c0000000e0000000b0000000e000000140000000a0000002100000007000000100000002c0000003c0000000c00000005000000070000000c00000007000000200000001d00000010000000070000001c000000120000004e000000200000000600000005000000060000000700000008000000060000000900000007000000060000001c00000014000000170000001f00000006000000090000000700000016000000420000000e000000090000000f000000500000001400000012000000060000002a000000050000000a0000000c00000092000000240000000c0000002a000000150000001e0000000e0000000f000000090000000f000000190000000f0000001300000005000000150000000700000079000000080000000c000000050000000000000000000000000000000000000000000000')).parse()
    privileged_users_resp = PrivilegedUsers(bytes.fromhex('fa420000450000000e05000006000000646576616e740a000000617072696c383139373207000000646a6a75726e690a000000477265656e6261756e5f0b000000636f726e696c696b656974040000006b747a610e0000004865646c65795f4c616d6d6172720a0000007573657235373737373703000000617267090000006f7665726e696768370400000063616d620c000000646f6e6e69656f68796561680300000064646604000000444a4c58080000006d6f7365736d35381300000063616d65776974686f7574617761726e696e6717000000746865206576696c206f6e6520776869636820736f62730c0000005a6f6d626965526f62623133100000006172616e6369615f6d6563616e6963610800000064617665747562610300000032343707000000736e616767656c07000000636f7265796b3107000000736869656b696506000000617564656f73040000006e6972330c00000064616e626c61626c61626c61030000006e3467090000006c65657361796e6f720b000000617374726f6d61646469650d00000063617074706c616e6e6564697404000000626967440900000079616c6f7365706961060000006c646c646c64070000006d6170656e7a690900000048696465626f756e640800000069616d66656d656c08000000736f756c76656e74060000007768697a686f060000007375747572650c00000069616e684073636e2e6f726706000000646f756764691400000047617264656e4f66466f726b696e675061746873060000004a616550656108000000736861647265636b0c00000074616c76656e61696b6133360b00000044616e69656c4d617269610b0000007361646e696c6d75736963090000006c617573646f77657211000000436f6d70616e7950726f63657373696e67090000004d696e696c6f67756506000000736f706869650800000061676c6f78746f6e0800000078706879736963730a00000041445249414e313935380b00000064656570656e64616e636505000000472d4d616e05000000616c616e6d0500000074616d6f6b0300000065676c05000000766564726f1300000064616e636577697468746865737065616b657208000000446a53696d6f6e6408000000617374726f6775690a0000006e61747574676176616e07000000736c6f6d6f3137050000007276727a6c0700000050656571756f64060000006a7973333930030000006667620f00000070737963686f636572656272616c6c0a000000737572636f7566203433060000006b686e7963310b00000044657264792053657264790a0000004472696e6b7943726f7707000000736368697a6d610c0000006a6566666d696c6c65723435070000006e326d757369630700000064726672616e640700000063686177616b730a00000048656d6f676f626c696e0b0000006a6f657966616c6475746f0a000000656c6173746963626f7908000000726169647a5f31320b00000069616d7468656c617365720d000000626664736361726563726f77310600000044657563653109000000416e677279596574690a0000002e2e3a7261696e3a2e2e07000000494b4f50494b450a0000003331343135393236333808000000626c757a6461776708000000737765655f7065650c0000003c3c3c2043686164203e3e3e0700000077696e6b7932330900000074656574686e65636b0b00000079756e67616c6765627261030000006a61420800000050696770656e554b0700000069616d646a61720600000066756e6b797009000000666f787878786d616e040000006e7063350e000000636f6e6465646562617261636f6105000000444a47656508000000536577657252617408000000416c72616f6d6f6e050000006976616e64070000004475626d616e7a0a0000004f6e654372617a79444a0c00000042657274204973204576696c0e00000067756e74686572736861626164750800000062747377726b6e67080000006f7574636173743109000000566972756e67613038060000007175697474790c0000006361726579736865726d616e090000006f64656d70726573730b00000062696772656c6174697665050000006e69636f63120000006e696768746d617265636f6e74696e756573040000004a3831300800000053616d736f6e484208000000766173696d616e7506000000466f676173730a0000007368656c6c667269636b0e0000007072696f7279206f6620696f6e73090000006a61666c6f7269616e090000004d6f636872696539390b0000004d69636861656c37303531080000005046756e6b46616e070000007363686c6f636b090000006861696661313931390a00000077696c626572333139320c0000007265616c70726f626c656d730b0000006772697a7a6c793937333109000000796f67757274696e670a0000005371756964746f706961120000004f7574646f6f726d6574616c726f636b6572030000006a6d3307000000616c6966756e6b0700000070666d70734949070000006d75727261636906000000787077666c610b0000004f6c644d616e5361636b73070000004841574b33393908000000696c6c62696c6c7907000000616a6f6e7469760c0000006d6163726f6d756e636865720800000048617469626162610c0000006261726d6963736f646131320b0000004a6f686e20486f6c64656e06000000784c6f756965140000004672696e676562697463687468616e6b73796f750a000000646a616e616c6f6775650b0000004d726b6e7368746b6161680d0000006e69636f6c6173626f69746f6e0c00000053706163654d696c6b413739080000006d616c65646f726f0600000074756975646a0e00000044616d69616e204c656a65756e650d0000006a61636b746865647269766572080000006c756369616e697806000000657572615f620b00000072696c6579686f6f6b65720e00000067656f72676570616e6f726d6f730800000076696e63656e746d0b00000079657273616b706176656c06000000445374796c7a09000000546865205468616e670700000063687269737368070000006b6172616b616c060000004d616c6973680600000066363963757409000000736f6c72616d626c65090000005069742056697065720500000063616e64650e000000536e7566666c65686f756e64323007000000626162756a696208000000636f6272613431370c0000007468655f6f726967696e616c0d0000006d617469735f6b65796e656c6c08000000726f70656472616707000000676d616c76696d060000004c5f446f70610800000069736870656573680a0000006f306f616d656e6f306f060000006c6f65736572090000004c697a742d31393436080000004b61746f6f4b617405000000726e656b6f09000000736b697070795f64630600000072616c70686f0e000000727562626572736f756c3132313206000000736c746672720e00000066616d6f75736d6f7274696d6572090000006675737379667265640c000000736164697366616374696f6e090000006174736368656565790b00000074696d6d65746a65323261050000006b757478610b0000006e69636b656c6f64656f6e0900000067656d7365656b6572070000005265747265616406000000646262616e640a00000066617368696f6e646f670c000000736172696f6674686570696507000000636c61766572611500000068756163686973696e64616a6175736f667061696e0b0000006d617269655f626c756535080000006a62666f7265616c0a0000007761726d6e66757a7a79090000006e6f747265616c6c790e0000007475726b69736864656c6967687406000000636869636f670700000061737279646572100000006175746f6d6174696362617a6f6f747906000000636d666f7572030000006c76380f000000647a6162656d6562616e69726174650c00000073686572616b61706f6449490f0000004a6f68616e204b6c696d6f766963680800000072616d657368373105000000646a676a6504000000787a7a7a08000000616964616e683331080000006d722e736f6c69640b0000006868656e77696b3139383804000000316c7576060000004d6174476177040000007a7566660700000066696c6c696f750700000064697363726f770b00000062616e617073636f74636819000000446973636f6e74696e756564204542542042656e6566697473030000006d6a6e0d00000048656c656e6d63677265617279030000006b756e080000006a616d65736d33340e000000486177616969616e205374796c650d00000062656e6e792070726f66616e650a0000006e69636b7072696e63650800000053616176656472610900000074616368746f756368060000006772656d7a6910000000546563686e6963616c54726f75626c6507000000692d62656c2053080000006c65696a7374656e080000006372756365313233070000004775696c616c610a0000007368795f7475636b65720b0000004d697374657259652d59650d000000436865737465724d657274656e08000000427265747469746f080000006d696b65373035310800000064696d6d6974727904000000666a3839040000006e7274660a0000006465656a61796b65656e110000004d757368726f6f6d4b6c6f75644b756c740c0000007572696e616c73686f776572070000006a6172656e383008000000476f6e7a6f393331070000004b616c65767261070000006167776f6c66660b000000686f6c7966696e676572730c000000546563686e6f6d6563726f6e09000000747269636b7958584c09000000616369646461646479080000006d61726b616e37300a0000004e6f6973795f536f636b050000006a706c756d090000006d617263656c303037060000006b6a686b6a680a00000046616c6c656e536f6c6f12000000686f7463616b657340686162616e65726f73090000007a65656275726769610b0000005f70726f6a75696365725f050000006a646b726f0b000000534d4f4f5448544f5543480800000066756c6c74657874080000004d723133333838340d000000616e64726561732064657669670c0000004e696d204368696d70736b790d0000006d65646c65795f656c663432300500000077616c65780f00000061646d6972616c5f73616e616e64610e00000030302d6461792072656c656173650d0000004d7973746963616c3138313135070000006b696d636830300a000000626967726167757064780b0000004769616e742053746570730d0000007461747476616d6173692d756b0900000074616368616c6f7578050000006269626f7007000000636177616d6f72080000004240406d4240406d080000004d69726f736c61760c0000005469736b65745461736b6574140000007465746f6e696b6f313740676d61696c2e636f6d0b000000377570436f6f6c53706f74120000006b6973736d656b6973736d656b6973736d65070000006361726365726907000000686172726f6c7a0b00000077617679636f6e74656e7408000000666d5f73796e7468110000006d6164656d6f6973656c6c656d616272790800000063616c6c7939393908000000766f6c746167657808000000686563746f74656d1100000074686520627269636162726163206d616e05000000726f68616e0c000000676174657373747564696f7307000000736c61766c6162060000007667736f6e6708000000736f66746c6f726408000000616c657863696a750500000072616d70790c00000064696767657264617669657312000000656d696c652e6331343840667265652e667210000000736f6d656f6e65736f6d657768657265080000006a75737466756e6b0500000070776f726d09000000766164657277696e730a0000006a6f686f76616e696e6507000000706a6f74723536080000006d72776869747469070000007461636f627573080000006a616b6570756c73080000006c756469636b69640d00000048656e64657273686f743937380800000043686573746e757408000000726176656e6a6f72040000006372616c0700000076616e67616d61070000007261696b6f666608000000626d65737369657205000000426f4861470a000000717561646b6972696c6c0e0000007370697269745f6c6f676963616c09000000746865206d6f7765720a0000007377696e677477696e730c00000070726f666573736f727037390a000000646563617475723535350b00000050737963686543616e6479090000006d636a6f65333635320b00000074797269616e36323032330b000000436974697a656e4b68616e0f00000064616e6e7977696c736f6e313937390d000000686f77326d696e6534666973680c000000626973717569746f646f6f6d080000005072696e6365707307000000726556657273650700000073626c736c736b0700000064727370696465090000006a6f686e2067616c740b0000005f6d6f696d656d65646a5f0b00000066726564646965363034300a0000006b696464797261766572080000006d616e616e6d616e070000006a72756675736a050000006162627572090000006d6574616c6178697309000000466c61636d616e515407000000535469454b554d040000006275736811000000616c6578616e64657277696c65726d616e0d000000617a77657468696e6b7765697a1400000064656c6170737963686540676d61696c2e636f6d0b00000070657465726d757272696e08000000436875636b696542080000006d6172697573626f070000006c6973656e6f6b050000006b6e65646507000000776163687269730a0000007368656c6c66696368650c000000426c61636b466561746865720d00000068656c6d65746e6f72666f6c6b0a00000064617274686a616262790900000067616c6c6977617370080000006d657465747a6b79100000006265746f6265746f6265746f6265746f0f00000042696e6172794e6575726f6e6175740a0000006c756d6265726a61636b0800000053696c656e63696f0b000000736c61636b7765726b657208000000726472316c6b72310e00000053746f726d626c61737438323138060000006261727563680800000074656c6573746172090000004b6174616c797a65720a000000677265656e6368696c650d0000007468655f736872696c6c6573740d00000036687562657274737472656574070000006f27627279616e0a0000006a6572656d793236323905000000776e6b72730b00000047726f6f76696e20596f75070000006c6f6669333033080000006d69616d6966616e0d000000656c7669735f74656c65636f6d0700000043617264687532080000005061706572426f790b000000617374726f6e6f76697374060000006d736f6d33370c00000066726f6767656e737465696e090000004269746d6f6e6b657907000000726567746f6e650a0000007473636869676765726c050000006574616e610a000000616c61736b616e626f790800000074696d307468796208000000616e64797275736809000000626f657a69656265650b000000686f757365686561643532070000006973726168696d0b00000061726368616e616d697961080000006167656e646138350d0000004d617569205261676e61726f6b12000000546967726f7520647520526f75657267756506000000444a4a524a52070000006a617a7a6d656e04000000646d73700b00000064757374656476696e796c07000000446565706d69780b000000726f79616c20726f6f7374050000002e2e302e2e120000006f6363616d75732073696d706c696369757309000000626c61636b646f76650600000074726f6e6e79070000007469746f636c6f0d000000636f6c6f6e656c20616e6775730a00000062616e676f6e6163616e0a00000069676e61747a6d6f75730a0000006572726f725f636f646507000000526564526f7578080000006c6974656265617406000000646a5f6b6f6904000000686837330700000054686520476f640900000047726168616d65554b0a0000007075736877696c736f6e0b0000004d61726b4d69777572647a04000000656c6374090000006d617263646f726961060000006d72686168610d000000736f636b65746d616e33303030090000006e736f6e6773746572060000006d6f746f6b6f0b00000074687265657468726565651100000072616c706877616c646f656d6572736f6e0a00000064697661696e6163616e0a0000006b656e6861727473656c080000006175746f7073793404000000647261700f000000737570657267726f766572323034360b0000007a65726f63656e7472616c0d000000476f626c696e7072696e6365380b0000006772617967686f73743533090000004b68616c696e6f72650d0000007461796c6f72737769667439320b0000006d617468666f72666f6f640800000070697a7a612e313504000000333c3d380a0000006d61786d61726b657473080000006c6f7376656e67650600000052656732333708000000746f7068616d6f6e090000007468756d70657231330700000077616c646f34360b0000007965726261206461646479090000006a69766566726573680b0000004d7973746963466f7263651000000061726d696e2076616e2062757572656e0800000068617264796b75650600000067676f626f79080000004a6f68616e2036300a0000004a6566666572646572700b0000006f70656e736f63696574790a00000074686563726561746f7206000000646731393532070000005f4b6f7270735f0500000066627437380a000000656c656374726f6e69630a0000006d6564666f72746837380d000000646f63746f72737472616e6765060000003134323039360a0000006761627269656c6c616b090000006d726d6f6f73657273070000006b6f646574776f0900000072656566736861726b0d000000746865636c6f7365746e6f6f6b05000000416d6d6f6e0d0000006b696c6c69616e2077616c73680a00000078326d75326368327878080000005665726966457965080000006f756d61726d616e0a0000005348595f5455434b455207000000646f63796465650800000049736b3870726563070000006277616e613233040000004d696e650c00000077696c64776f6f646461797306000000694c6361506f070000006970686f6e65350e00000062616c736f2d736e656c6c3931310f00000072657475726e666f7265766572313605000000616f657569090000004b61746f6f6b617473080000007477696e6b6c65720d000000546865204173736e61706b696e06000000707563696e6905000000726f6e697806000000637632333137070000007472656e646172070000004040407573657209000000646961766f6c696e6f06000000686f6974656c090000004d442053414c4c4548070000006c6f6e676f39380900000074696d686f6562656e0d0000006974736d79757365726e616d650a000000706c61796564636f6c64070000006170707a657230080000006d656f7768756773050000006776686a6b0c0000006b696d617269736b6f62616c06000000636f7774656b0b0000006a61636b73706172726f770c0000006b6576696e736b7966616c6c060000007375703139310e00000052696368726f642044204a616d730800000077636f6f6d657273100000007468656c6174657065746572636f6f6b0700000067656f776f6c6609000000526f626f44726f696404000000726879730f0000006261696c65796477696c6c69616d730b0000004162616e64616e6443617416000000656c6368696e676f6c617a6f407961686f6f2e636f6d09000000726f72796461726379080000006368337368797265070000006b656567656c730e0000007472697070696e67636f727073651000000063756c74757261636f6d6261746976610d0000007061626c6f706f7175656e6f3108000000546f706865724e4c0b000000736e6f7762616c6c696e6709000000666f726b6265617264060000006d6f7376766d050000004d6f6e6f73090000006d61686172616a6168060000006d696368686f080000006e656f796f756e670c000000746865616d63616464696374080000006d7273656371756f09000000676f726b656d6265720c0000007269626569726166756e646108000000646176696573666a070000004d756b656e696f0900000074726178783132333405000000486f7269610b00000068617272796d6f736562790b0000004d656e646f7a616d61796f060000005369724379670a0000006b757274686572626965060000007073796d6f6e050000007765636f670a000000736e6f727468383535340c000000506c65617375726550756e6b0800000054776f556e6974730a00000073636f6f6e6475636b790400000073687633120000006675636b796561682d6974732d6a756c69650d000000626173686d656e7420626f7973060000006176636c6862050000007465716e610c0000006261626167616e6f75636865080000004e4b444d757369630800000071616c6f6d6f74610c00000074617261737465773230303608000000616c6578343739310600000066656e6465720c0000004b6e696768744e42756464790a00000064696767657264656570060000004e6f76616537070000007a61626164616b080000004a6566666f64656c0900000068616c665f6c6966650b0000007375706572756e6469657312000000726b666f737340686f746d61696c2e636f6d0c000000626c61636b746561323435360900000056696e63656e7448320800000074617572757366670a00000073626c61636b6d616e31150000006170706c6573637275666673406c6976652e636f6d070000006a6c6d3333333309000000796561686862757a7a0600000046617462617409000000727778722d78722d780a00000067616c6c69776173703209000000544a2d5468656d65730800000079617264627972641100000069662e7468656e2e6f746865727769736506000000616e6477657205000000626972636b09000000686f6e6579636f72650a000000636174626f74393030300700000064756b6576696e070000006f70756e7469610500000072656573790c00000048656e7461696d617374657206000000626c617a6172120000004561737456696c6c6167655265636f7264730b000000426162796c6f6e536f756c080000006c7563617373736f08000000536b617465653939080000006361726c6f6465650800000070686f6e6f6d69720d000000576578666f726452616964657204000000746865410a0000006d697373696e6768616d0c000000686f76657270726f6a6563740900000073616e646961626c6f0400000068656661050000006d656b61730a00000079656c6c6f7762656c7404000000736c65641800000069776973686972656d656d6265726d79757365726e616d65030000004e2f410b0000006c7364667269656e646c79080000004f726669323031390900000062696c6c7964656532060000004368696c616d060000007461713636360b000000486572625f4461776f6f640c000000646973697a6c617065737465080000006d6f6e74796361740b0000006d617878626173733232320b000000536f756c205369737465720c000000446f6374657572204c6f7665060000006261626131300e0000005068616e746f6d506861727465720900000065636c656374696b610900000067726f6f7665735f31090000006c6968616d626f6e651300000067617279736579657340676d61696c2e636f6d0a000000746865646a6b796c656a0a0000006a6c616e67653137303707000000326e646c696e650b000000446976696e652057696e640800000062696c6c787530390b000000546f6d6d796b623367727a0d00000049746f72795f56696c6c616765080000004d617274766c61740500000072656d64330b000000626c6f636b65646d696e64080000007073616c6d6973740a0000006570736f6e73616c74730a0000006161726f6e6d756e726f0c000000616e746f6e2e7374796c657309000000706f6d32746572726505000000646f6272300a0000004d6f73737948796e65730b000000616d6f72676f726469746f0800000063726f6e6f734e530c000000616e656e63657068616c6963080000006e6f6e636170657407000000747265787765620b0000006e6f7474686174656173790c00000073796c76657266616c636f6e0f000000776f757475697464656c66676175770b000000616c617572656e636539360d00000072687974686d6963666563657307000000616c69313233340b00000044616e636574726f6e6963080000004c65776973673032070000006c756d696e757308000000706564726f726e640900000071756f7274686f6e790a00000061776169796f73756b650600000067616a6465720900000073616d6d79673132330500000048656b6b790b000000536865666669656c646965040000005558323107000000696d756e6e656e06000000736f756c696f0b000000736f6e69635f6c655f67670900000076656e64696d69616f06000000646a6d6f6e6105000000466f6e616b05000000736c6f626505000000736e65616b0a0000006a61636b68617276657905000000676b696e67070000004469674465657006000000686f6261677a0a000000636861726c69656639370800000073757262657374610a00000053756e6e706f7274616c130000004e6f626f647949735374696c6c4d794e616d650800000068616c69627574740e0000005069616767696f4369616f426f790b00000064757268616d69746537340c00000043616e75636b697374616e6908000000457570686f6e696311000000646a5f67656f7267655f77696c6c69616d060000006d61746572730a000000486f6d65436f6f6b696e0c00000073696c656e74706c756d65740b00000070656e6e6e69656e6e6965080000006b6162726169746806000000626c657733310b00000041737069726174696f6e73080000004272757465737164090000004b696e674a69726568080000004b696d6d56616e6e0b00000064656e6e697371756169640d00000050696f7472686172746d616e6e110000005472616e736665725f66756e6374696f6e070000006c6973696d626107000000536f756c66756c0800000074756e65766f6964050000007061776e3105000000726f786c790b000000636861757a6d616e75616c1400000073747265657477616c6b696e2763686565746168040000007275696e080000007369676f6365616e0e000000636c616e20676174686572696e6709000000646461726b62616e640c00000067616c6c656865726a617a7a120000006c6974746c65666c75666679636c6f756473070000007a79636c6f6e650e000000616e647265776273757061666c790600000053776f70707908000000576172686f756e64050000005475666661060000006d61746a61730b0000007375627665727369626c650a0000006a7730313163343137340a000000676174746f7665726465080000006c696e6b5f726165090000007468656e65777363690f0000004275726e696e675f4f7263686964730800000061747479383838380300000045746304000000506865660d000000526576656c6174696f6e4e6f390b0000005a796b6c6f70526f626f740d0000006d61796c6f7665736d6574616c0a0000006d61676e756d323630360400000069647269090000004361706974616e204e1000000046696c746879426c61737068656d6572030000004d52500c0000004b4944726f727363686163680800000066617578666175780800000051616c6c756e61740800000061736369696d6f76080000007072696f6c656175030000004e4d57080000006d69786f666c697807000000436f6d6d756e6503000000553331030000004f4c4a0d000000616e6f6d6f6c6f75737573657207000000666173686f6f6d0b000000486f7573656d616e696163080000004f62656f6e6537340c0000003162656e67617264696e657207000000426162626c657207000000706164736d63630900000073656969627574737506000000426f626279310c00000073747265657466726967687407000000427265696c31370b00000070726573746f6e7370616c0b0000006b6f6f74656e61796361740e0000006e6174617368612e6861727269730b0000006d69737465726d616c6479070000006e657a75726563050000006461726b300800000075676c796261636b0a000000646f6e73616d75656c6c04000000436c6970070000007061746f636865060000004a616d486f740c00000065617374656e646572313031070000006d6f76657230310b000000484f4c4c4f575452564345060000005468656c69730b0000007472616d707366696c6573060000004b617368696b0d0000007065746572736f6e3332353634090000006d6172706f696e74650b000000676c69747465727469747306000000532e482e512e0500000043726f6e6f080000006669646c7374696b0b00000041656e6775732e4b616e650800000043616c76696e31370b0000006368726973637a61727261070000006465616d736f6e08000000446a4e6f4e616d65090000006132323333343536370b000000646f75626c65646f766532100000006865736e6f747468656d6573736961680c00000050617261626f6c46696c6d73040000006b6b343907000000736f686f6d616e0e0000007068696c6c6c6c6c6c6c6c6c6c6c08000000766f6c616e7436360b00000064656b617374656c65696e0c000000526f6d65797572686f6d657907000000646a686f6c6c790700000067646f636869610c0000007468656265656b65657065720d00000046696e616c4c6576656c44616408000000776f6d6261743630080000004e6f7a6f6e79616e08000000736f6d656567677306000000646a64646f740a00000073746576656d617837380a000000677261796a6179313033080000006d6174736f616b610800000067627666616e373807000000736b697a6d3633050000006964616e670500000046726564790e0000007269636172646f726f6c616e646f090000006d6f7274733239383606000000486172727943100000007061736375616c6c616472696c6c6f370d0000005368616773746572656c6c6c6109000000646b6c65656e3531320700000074696d626f6f6909000000776a686f66666d616e050000004d6f7a7a790b00000050696e6b666c6f696437390e000000546861746d7573696367757931310e0000007878446561644469736e65797878080000007375626465617468070000006d6861313031320a00000050657269636f6c6f736f0a00000073717565616b286f7a29100000006e7962683737407961686f6f2e636f6d100000004f7074696d75735f5072696d655f3739080000006772696775746973070000004368617264656e090000006e6563726f6e33313309000000736f756e64617265610c000000436f70706572746f703431380400000052616f6d09000000444a204d6f62697573050000006461727269090000006e61746261746361740900000047554c4c5920474f440a0000004c494e4f5351554152450a0000006167757963616c6c65640b00000041736572656d6f7267616e070000006d6c6832303136060000004e6f6d6930340a00000061636574657272696572070000006d7266756e6b73090000006d757a696b697a756d080000006d6c6172736f6e31040000007374767709000000736b796b6964666c79050000006372756c741300000074686573696c7665726d696c6c656e6e69616c0f000000647265616d73696e6469676974616c09000000616c69616e7a613934070000007079726f7369730700000062726574373137070000006d6367756e64790b0000007269636b7370656e6365720b000000676f6a6b6f646a696c61731600000073746861746368657236363640676d61696c2e636f6d0900000064616e69656c7362330a0000005377696e676b69643635090000006d7a656174777a6164080000006368656d6f7279330a00000048616d4e4368656573650a000000727370696e6f7a613939090000006a6f616e7a61727a7506000000646a656465790a00000063686f636f63686f636f080000006465626563746f720d00000053746172734f765468654c696407000000456c6e696c696f05000000787972697807000000616e74686f6d700d000000626c757368726573706f6e73650600000063623637363908000000746f7276696c6c6505000000636967657309000000646f6f667978707174050000006f53636172090000006e3030626d6172696f0b000000444a5f4655545552414d41100000006c69666573756e6365727461696e747906000000537445655a790c00000064726f736f7068696c613731100000007368617265756e64657267726f756e640a000000646a6c617572656e7a6f0a00000070697a7a61706965323211000000426f626269652047656e7472792046616e0a0000007a656e636869636b656e080000006465725f6765636b0600000067726f6734750900000042616c204d6f72616c05000000436f4c4c790b000000486f7273657368697437300b00000053656e6e616368657269620c00000065696e737475727a656e646506000000646a6f6e79630c000000666f7862617365616c7068610600000072756765726f0b0000006a616d6573627269616e630c000000636861726c69655f676f6c640d0000006a61726a6172746865647564650b0000006d61676e6174696370726f090000006661726574726164650f00000066757a7a6772617669746174696f6e0a000000736f756c74656b6e796305000000547765656b100000006b656c76696e7468656d61727469616e060000006177633237390700000042656c6d6f6e7409000000686f64676579626f790c0000006167656e74736d6974683434070000006d72626f757a680a00000068756d616e7472617368070000005472616e6365740f000000537475646562616b65724861776b65090000007370656369616c3233080000006e6f7261636174320a00000042756f6e67696f726e6f130000005061747269636b40706d75727068792e6f7267070000006461686963616e060000004b616964656e0700000070616e746d616e0f0000004365736172546164616c6166696c610b000000706f70737461723230303009000000436f7276757320435a0b0000007365726f746f6e696e38360900000073686172616661656c090000006a326d637275736f65060000004a61426c757a0800000066616972636974790a0000006c6f756c616761747461040000006b6569720a00000070616e6e79746869656608000000646a636875636b79040000006c626266080000006672336b736830770a000000706170657274696765720b000000736f6e6963736f756c617211000000736f6d656f6e6520736f6d6577686572650a0000006c6f63616c67686f73740c000000444a44616e636564616464790e000000536c656570696e676265617574790c000000626c696e676f626c616e676f0c00000066756e6b64616d656e74616c0a000000706f747379626f7936390700000067726f6d62756e090000006368696e7375383736050000007573636c6d12000000444a5f47656f726765526f6472696775657a050000007468756e6b080000006661206365206c6107000000706765797365720700000063686173313233060000004d2e4c2e462e0b00000070617261646f786963616c08000000696d3271756965740600000042616c3335360e0000006e6f757365726e616d65686572650600000062696c626f390c00000044414444494553534155434508000000506f6c79726f636b0f0000007269636b737072696e676669656c64060000004a626f6e6963080000007333336d33733333080000006472796669737432060000006d66687361720e0000006d69737366756e6b6b79666c79790900000076656c6f63696665720d0000004b69644d6f746f44726167656e0b0000007a616d70616e6f323030340a00000064737472656c696f66660c000000476f6c64656e43726174657305000000484b5230310a00000073757065726c6f74656b080000004e756d6265723531060000006c6c657630310600000073796c6575730b000000426c75657374626c6f6f640c0000006672616e6b5f626c6f74746f070000004f6e6965726f730a00000061726c75636173696e631400000070726f6665737365645f696e74656e74696f6e73080000006861616d706969680b000000574f57484947484755595a0f000000626974636866726f6d717565656e73070000006d65696d656e7a0900000043616e746f6e373131070000006d6174747835370600000067347a7a337208000000666c79677579727906000000416b79616b610b0000006d7973746963776f726b730c00000061757374696e6c75636b79370800000061626572676172790a000000536d697468536d6974680e00000044756b6144696573656c31323035050000006c616e65620a00000073686f6567617a6536330b00000065786974706c6f747465720800000072676172636961640800000070686f74306e6963080000006869746a616765720900000044616e4d6178537564090000007265766572736532310900000072616d6f6e6465726f0a000000616c746f6e656e7472650800000069636577617665730e00000066756e6b796275646468613432300b00000066757a7a746f6e657262650d00000046756c6c506c6174654d65616c0900000070616e6e6f6e6963610600000061617061657309000000647265656d73656564080000006e626f6d623232300b000000686f7573657974756e65730a0000006475622e6869742e6267090000004761646765744d616e060000006c65706961660600000070617474656e09000000776173746f6666313107000000636f72646c74780e00000050726163746963616c4368616f730a0000006b696e656c6c3230303206000000776f6f64393307000000776562657474730a00000049726d696e7472756465080000005261745066696e6b0c0000002348714777336f5959316d710d0000004b6f64616b2053757072656d650d0000006f7a746f707573696e746f736807000000626c6b646f7665080000007365726769736572080000006d6265726973736f0a00000062697264706572736f6e060000006d636261726b090000006d696e65636961727a0a000000646f7065736c6f7065730700000047656f72676979080000006472796572617365060000006b616d616b690b000000746f6d62617474736f6e3109000000507572456e65726759090000006e657074726f6e697808000000506574536d696c65100000004a616d657320442e2057696c6b696e730d000000666174616c706f736974696f6e0800000063726f6d626163680600000068616d68616d0d000000697473636f6f6c746f726f636b070000006d64683632363210000000646f6374616540676d61696c2e636f6d0b0000007472756570686f656e6978090000006c696d6f6e636869710900000067776f706f746f31320d000000646a72696368617264676561720a00000054696e746157617a6f6f0b0000004765727269744d75736943090000006e696768747363617207000000626677696c657908000000626f6f7473613232050000006b75636869080000004d6f736573313838080000006d696e6973637573070000006d616c6d656e37050000006a6d656c7a050000006d696e6564080000006171756564756374080000004d75636b795075700b000000696e666f726d61766f7265100000004a616d65735f486172677265617665730f00000047656f66667265792054686f72706506000000646a73656e640a0000007061726b617375636b731100000070737963686f64656c6963617465626f790800000073746f6e653030390d000000706574652e7265616c67616e670a0000006465656a6179646f756708000000696e736964656d650b00000062617465736e6d61746573060000004472697a7a74090000006d6574686f6475733207000000726f6666656c730b000000677265656e5f746f6f746805000000736f7468610700000074736f7269636b0a000000536f756c706574726f6c050000004261736861070000006d626972643931080000006e756c6172756c610900000064656a6173766965770a0000004f7a796d616e646961730d000000626f6e6f626f5f626f6f6d616e0c0000006a6f6f6e736574736669726509000000626f7373747765656408000000686174746f6e31330b0000006769616e6c7563613734300a0000006865726f6963616c6c7906000000426c337373790a0000006b696c6c736b696c6c7a08000000616e6479323633390a0000007a61637a65647a6f6f6d040000006b6f627907000000656e64697376610c000000626f7373616e6f76616b6964040000006d6178740d00000053757065726e696e74656e646f0e00000063617374726174696f6e666561721000000074697a6d3230406e617665722e636f6d0a00000077307733337a3077333305000000536f73656e060000006a646d663632070000006e6563733232320c0000004d617276656c7a6f6d696265070000004c6f75576565640a000000446f6320426f75726e650a00000068657861676f6e73756e0e00000041737061726167757320446176650600000057696562626508000000617368777979796e0d000000486f6f6b65724f6e58616e61780a000000486970507269657374330b00000069732074686174206d653f07000000726f6e313939390900000066756e6b7a696c6c610c000000536f6c6172436f61737465720b0000004d72466f6e6b747261696e0a000000726567616c6d696e6473080000006d63696e646f6f32060000004d6f6e67657207000000616b61696b656d0a00000077316e646f7770616e650700000054727970746f6e080000003739626568696e640a000000726965737461696e69730a0000006b696b6973686d696b6907000000446a20436f726506000000646e79323338040000007a61727410000000666572646179746865756e69636f726e08000000736f756c667265650500000064666b686204000000636738320e0000006a65727279636f6c6275726e3638070000006861726f6c64680e0000006a65727279636f6c6275726e363906000000656b62657267090000004c65656269653330330b000000706163616c5f766f74616e06000000526970706c650900000061726368616e67656c04000000424d534409000000696e6665726e696e6f06000000736c736b36320d0000006d656c616e63686f6c796d616e0c0000006b656570736c656570696e670b0000004c6f7374204d6173746572090000004f70657261746f7247050000004f4c5953480e0000006775696c6865726d65637361657a050000007269706c69080000004d6f64656c3530300c00000076696a6179616e744c4f52440500000078656e61310c00000054686520436f6d70696c6572070000006c656e6e6f78620a0000006a68656c6c667269636b07000000626179626b67650c00000054686541657374686574696b06000000726f6e7935360b00000065646479636f64726f6e3407000000656d69786d616e090000006368696361676f393507000000617364663132350a0000006a6f656a61636b736f6e0f000000536f756e64496e766573746d656e740c00000064616e7261746865726e6f74070000006f6c69766572720800000070726f6c65617274080000006a776c65723431350c00000070756e6b6e6f697365726578050000007a68657869070000006578696c6539390a0000006d6178746865676f6c640900000077696e647963697479090000007061756c5f6d61636b070000006d696b65616972040000006d69657a090000006a6f6666696e313233080000005377697368613939080000004d61756e614c6f61080000007765727374696c6c0a000000796f7572737472756c79080000007065706567756e6e050000006e6f796f750a000000486c6f66686d686868750c0000006d72647273736865706172641000000054686f6d61735f42616e67616c746572090000006769616d7079636563040000006e646d610f000000414e544f4e494f474952414c44455a100000006372617a796d6f7468657266756e6b790c000000466173744e42756c626f7573050000006a617932330b00000070726f746f646f6f6d65720e000000416c636f686f6c6f63617573746f0a0000006a616b65626f6e7365720a00000069676c6f6f5f6661726d07000000686d696b65393908000000636c636d313935320e0000007472696d5f746861745f746173680e0000006869676872657a6f6c7574696f6e070000006a6f65797233310b0000007769636b65647079676d790d0000006d6979616b6f6a696d6164616e0b000000636f6469636f67686c616e06000000616b6d75736f060000006d756b6977610a0000006d697461726d75736963050000006469616c310800000053616c6f686b696e0600000059757269675606000000646a69616e6c0c000000626f62696e6f626f62696e6f080000006461726b63756265060000006c6566656c7a0c000000736f6d652e6f6c642e656e74070000007468657572736f1200000052616e64756d6220417a7a204b6e65657961070000004461626f6f73650900000047726164795461746509000000636f726279656d35320a0000006a6f686e697362616c64080000007265645f626f6f6b110000006d61796265756e6465727468657472656507000000537465766965540500000067726173730c00000073696b6b74656b6b66756b6b060000006761706f38300b000000726f62776f7274683130300500000067706e65740800000064696d61727261790b000000524f414452554e4e45523409000000746f796d616e696374090000005555554265726c696e0800000070696e6b79626f690c0000004772616e6e795768616d6d6f0c000000647276616e737465696e65720e00000073686572696174656c6b656269720800000068656d616573696e060000006d617a67616e0b000000646a736b726174636869740c00000071757474696e6972706161710c0000006a6f6262796d61636265616e06000000726f626f6a6209000000446973636f50756e6b090000006c6176617261743239060000006e67726f75740a000000736f756c646f756769650c0000006469676974616c5f73656c6609000000736372616d626c65720e000000536d616c6c76696c6c65323130360a00000064696e616d6f32323232080000005468726f626265720c000000677261737072656c65617365070000005f766f6f646f6f08000000736d75726669757306000000626c6b66756e0c000000656c6368696e676f6c617a6f060000006368656e64790800000063696e6e616261720b0000004f6c6c69654b697a7a6c650b00000073616e6a6964646577616e')).parse()
    parent_min_speed_resp = ParentMinSpeed(bytes.fromhex('080000005300000001000000')).parse()
    parent_speed_ratio_resp = ParentSpeedRatio(bytes.fromhex('080000005400000032000000')).parse()
    wishlist_interval_resp = WishlistInterval(bytes.fromhex('0800000068000000d0020000')).parse()
    import pdb; pdb.set_trace()
