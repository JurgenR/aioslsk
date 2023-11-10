"""Definition of all SoulSeek protocol messages.

This file contains 2 types of messages:

* Server

    Request : used from client to server. A client will only use the
        `serialize` method of these messages
    Response : used from server to client. A client will only use the
        `deserialize` method of these messages

* Peer

    Request : peer messages only consist of request type messages. The client
        should use the `deserialize` method of these messages upon receiving
        data from another peer and the `serialize` method when sending to
        another peer
"""
from dataclasses import dataclass, field
import logging
from typing import ClassVar, List, Optional

from ..exceptions import UnknownMessageError
from .primitives import (
    boolean,
    bytearr,
    uint8,
    uint16,
    uint32,
    uint64,
    string,
    array,
    ipaddr,
    FileData,
    DirectoryData,
    MessageDataclass,
    UserStats,
    PotentialParent,
    SimilarUser,
    Recommendation,
    RoomTicker,
)


logger = logging.getLogger(__name__)


class ServerMessage:
    """Class for identifying server messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint32.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(message)

        raise UnknownMessageError(msg_id, message, "Unknown server request message")

    @classmethod
    def deserialize_response(cls, message):
        _, msg_id = uint32.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            response_cls = getattr(msg_class, 'Response', None)
            if response_cls and response_cls.MESSAGE_ID == msg_id:
                return response_cls.deserialize(message)

        raise UnknownMessageError(msg_id, message, "Unknown server response message")


class PeerInitializationMessage:
    """Class for identifying peer initialization messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint8.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(message)

        raise UnknownMessageError(msg_id, message, "Unknown peer initialization message")


class PeerMessage:
    """Class for identifying peer messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint32.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(message)

        raise UnknownMessageError(msg_id, message, "Unknown peer message")


class DistributedMessage:
    """Class for identifying distributed messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint8.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(message)

        raise UnknownMessageError(msg_id, message, "Unknown distributed message")


class Login(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
        username: str = field(metadata={'type': string})
        password: str = field(metadata={'type': string})
        client_version: int = field(metadata={'type': uint32})
        md5hash: str = field(metadata={'type': string})
        minor_version: int = field(metadata={'type': uint32})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
        success: bool = field(metadata={'type': boolean})
        greeting: Optional[str] = field(default=None, metadata={'type': string, 'if_true': 'success'})
        ip: Optional[str] = field(default=None, metadata={'type': ipaddr, 'if_true': 'success'})
        md5hash: Optional[str] = field(default=None, metadata={'type': string, 'if_true': 'success'})
        privileged: bool = field(default=None, metadata={'type': boolean, 'if_true': 'success'})
        reason: Optional[str] = field(default=None, metadata={'type': string, 'if_false': 'success'})


class SetListenPort(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x02)
        port: int = field(metadata={'type': uint32})
        obfuscated_port_amount: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})


class GetPeerAddress(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03)
        username: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03)
        username: str = field(metadata={'type': string})
        ip: str = field(metadata={'type': ipaddr})
        port: int = field(metadata={'type': uint32})
        obfuscated_port_amount: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: Optional[int] = field(default=None, metadata={'type': uint16, 'optional': True})


class AddUser(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x05)
        username: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x05)
        username: str = field(metadata={'type': string})
        exists: bool = field(metadata={'type': boolean})
        status: Optional[int] = field(default=None, metadata={'type': uint32, 'if_true': 'exists'})
        user_stats: Optional[UserStats] = field(default=None, metadata={'type': UserStats, 'if_true': 'exists'})
        country_code: Optional[str] = field(
            default=None,
            metadata={
                'type': string,
                'if_true': 'exists',
                'optional': True
            })


class RemoveUser(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x06)
        username: str = field(metadata={'type': string})


class GetUserStatus(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x07)
        username: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x07)
        username: str = field(metadata={'type': string})
        status: int = field(metadata={'type': uint32})
        privileged: bool = field(metadata={'type': boolean})


class RoomChatMessage(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0D)
        room: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0D)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class JoinRoom(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0E)
        room: str = field(metadata={'type': string})
        is_private: bool = field(default=False, metadata={'type': uint32, 'optional': True})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0E)
        room: str = field(metadata={'type': string})
        users: List[str] = field(metadata={'type': array, 'subtype': string})
        users_status: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_stats: List[UserStats] = field(metadata={'type': array, 'subtype': UserStats})
        users_slots_free: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_countries: List[str] = field(metadata={'type': array, 'subtype': string})
        owner: Optional[str] = field(default=None, metadata={'type': string, 'optional': True})
        operators: Optional[List[str]] = field(
            default=None,
            metadata={
                'type': array,
                'subtype': string,
                'optional': True
            })


class LeaveRoom(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})


class UserJoinedRoom(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x10)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        status: int = field(metadata={'type': uint32})
        user_stats: UserStats = field(metadata={'type': UserStats})
        slots_free: int = field(metadata={'type': uint32})
        country_code: str = field(metadata={'type': string})


class UserLeftRoom(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x11)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class ConnectToPeer(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x12)
        ticket: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x12)
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})
        ip: str = field(metadata={'type': ipaddr})
        port: int = field(metadata={'type': uint32})
        ticket: int = field(metadata={'type': uint32})
        privileged: bool = field(metadata={'type': boolean})
        obfuscated_port_amount: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})


class PrivateChatMessage(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x16)
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x16)
        chat_id: int = field(metadata={'type': uint32})
        timestamp: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})
        is_admin: Optional[bool] = field(default=False, metadata={'type': boolean, 'optional': True})


class PrivateChatMessageAck(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x17)
        chat_id: int = field(metadata={'type': uint32})


class FileSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1A)
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1A)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class SetStatus(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1C)
        status: int = field(metadata={'type': uint32})


class Ping(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x20)


class SendConnectTicket(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x21)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x21)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})


class SendDownloadSpeed(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x22)
        username: str = field(metadata={'type': string})
        speed: int = field(metadata={'type': uint32})


class SharedFoldersFiles(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x23)
        shared_folder_count: int = field(metadata={'type': uint32})
        shared_file_count: int = field(metadata={'type': uint32})


class GetUserStats(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        username: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        username: str = field(metadata={'type': string})
        user_stats: UserStats = field(metadata={'type': UserStats})


class Kicked(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x29)


class UserSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2A)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class DeprecatedGetItemRecommendations(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        item: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        item: str = field(metadata={'type': string})
        recommendations: List[str] = field(metadata={'type': array, 'subtype': string})


class AddInterest(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x33)
        interest: str = field(metadata={'type': string})


class RemoveInterest(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x34)
        interest: str = field(metadata={'type': string})


class GetRecommendations(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x36)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x36)
        recommendations: List[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )
        unrecommendations: List[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )


class GetInterests(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x37)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x37)
        interests: List[str] = field(metadata={'type': array, 'subtype': string})


class GetGlobalRecommendations(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x38)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x38)
        recommendations: List[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )
        unrecommendations: List[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )


class GetUserInterests(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x39)
        username: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x39)
        username: str = field(metadata={'type': string})
        interests: List[str] = field(metadata={'type': array, 'subtype': string})
        hated_interests: List[str] = field(metadata={'type': array, 'subtype': string})


class ExecuteCommand(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x3A)
        command_type: str = field(metadata={'type': string})
        arguments: List[str] = field(metadata={'type': array, 'subtype': string})


class RoomList(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x40)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x40)
        rooms: List[str] = field(metadata={'type': array, 'subtype': string})
        rooms_user_count: List[int] = field(metadata={'type': array, 'subtype': uint32})
        rooms_private_owned: List[str] = field(metadata={'type': array, 'subtype': string})
        rooms_private_owned_user_count: List[int] = field(metadata={'type': array, 'subtype': uint32})
        rooms_private: List[str] = field(metadata={'type': array, 'subtype': string})
        rooms_private_user_count: List[int] = field(metadata={'type': array, 'subtype': uint32})
        rooms_private_operated: List[str] = field(metadata={'type': array, 'subtype': string})


class ExactFileSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x41)
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        pathname: str = field(metadata={'type': string})
        filesize: int = field(metadata={'type': uint64})
        checksum: int = field(metadata={'type': uint32})
        unknown: int = field(metadata={'type': uint8})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x41)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        pathname: str = field(metadata={'type': string})
        filesize: int = field(metadata={'type': uint64})
        checksum: int = field(metadata={'type': uint32})


class AdminMessage(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x42)
        message: str = field(metadata={'type': string})


class GetUserList(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x43)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x43)
        users: List[str] = field(metadata={'type': array, 'subtype': string})
        users_status: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_stats: List[UserStats] = field(metadata={'type': array, 'subtype': UserStats})
        users_slots_free: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_countries: List[str] = field(metadata={'type': array, 'subtype': string})


class TunneledMessage(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x44)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        code: int = field(metadata={'type': uint32})
        message: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x44)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        code: int = field(metadata={'type': uint32})
        ip: str = field(metadata={'type': ipaddr})
        port: int = field(metadata={'type': uint32})
        message: str = field(metadata={'type': string})


class PrivilegedUsers(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x45)
        users: List[str] = field(metadata={'type': array, 'subtype': string})


class ToggleParentSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x47)
        enable: bool = field(metadata={'type': boolean})


class ParentIP(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x49)
        ip: str = field(metadata={'type': ipaddr})


class ParentMinSpeed(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x53)
        speed: int = field(metadata={'type': uint32})


class ParentSpeedRatio(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x54)
        ratio: int = field(metadata={'type': uint32})


class ParentInactivityTimeout(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x56)
        timeout: int = field(metadata={'type': uint32})


class SearchInactivityTimeout(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x57)
        timeout: int = field(metadata={'type': uint32})


class MinParentsInCache(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x58)
        amount: int = field(metadata={'type': uint32})


class DistributedAliveInterval(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5A)
        interval: int = field(metadata={'type': uint32})


class AddPrivilegedUser(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5B)
        username: str = field(metadata={'type': string})


class CheckPrivileges(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5C)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5C)
        time_left: int = field(metadata={'type': uint32})


class ServerSearchRequest(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5D)
        distributed_code: int = field(metadata={'type': uint8})
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class AcceptChildren(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x64)
        accept: bool = field(metadata={'type': boolean})


class PotentialParents(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x66)
        entries: List[PotentialParent] = field(metadata={'type': array, 'subtype': PotentialParent})


class WishlistSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x67)
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class WishlistInterval(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x68)
        interval: int = field(metadata={'type': uint32})


class GetSimilarUsers(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6E)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6E)
        users: List[SimilarUser] = field(metadata={'type': array, 'subtype': SimilarUser})


class GetItemRecommendations(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        item: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        item: str = field(metadata={'type': string})
        recommendations: List[Recommendation] = field(metadata={'type': array, 'subtype': Recommendation})


class GetItemSimilarUsers(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x70)
        item: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x70)
        item: str = field(metadata={'type': string})
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})


class RoomTickers(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x71)
        room: str = field(metadata={'type': string})
        tickers: List[RoomTicker] = field(metadata={'type': array, 'subtype': RoomTicker})


class RoomTickerAdded(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x72)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class RoomTickerRemoved(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x73)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class SetRoomTicker(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x74)
        room: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class AddHatedInterest(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x75)
        hated_interest: str = field(metadata={'type': string})


class RemoveHatedInterest(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x76)
        hated_interest: str = field(metadata={'type': string})


class RoomSearch(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x78)
        room: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class SendUploadSpeed(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x79)
        speed: int = field(metadata={'type': uint32})


class GetUserPrivileges(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7A)
        username: int = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7A)
        username: int = field(metadata={'type': string})
        privileged: bool = field(metadata={'type': boolean})


class GiveUserPrivileges(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7B)
        username: str = field(metadata={'type': string})
        days: int = field(metadata={'type': uint32})


class PrivilegesNotification(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7C)
        notification_id: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})


class PrivilegesNotificationAck(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7D)
        notification_id: int = field(metadata={'type': uint32})


class BranchLevel(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7E)
        level: int = field(metadata={'type': uint32})


class BranchRoot(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7F)
        username: str = field(metadata={'type': string})


class ChildDepth(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x81)
        depth: int = field(metadata={'type': uint32})


class ResetDistributed(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x82)


class PrivateRoomMembers(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x85)
        room: str = field(metadata={'type': string})
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})


class PrivateRoomGrantMembership(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x86)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x86)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomRevokeMembership(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x87)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x87)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomDropMembership(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x88)
        room: str = field(metadata={'type': string})


class PrivateRoomDropOwnership(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x89)
        room: str = field(metadata={'type': string})


class PrivateRoomMembershipGranted(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8B)
        room: str = field(metadata={'type': string})


class PrivateRoomMembershipRevoked(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8C)
        room: str = field(metadata={'type': string})


class TogglePrivateRoomInvites(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8D)
        enable: bool = field(metadata={'type': boolean})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8D)
        enabled: bool = field(metadata={'type': boolean})


class NewPassword(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8E)
        password: str = field(metadata={'type': string})


class PrivateRoomGrantOperator(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8F)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8F)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomRevokeOperator(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x90)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x90)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomOperatorGranted(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x91)
        room: str = field(metadata={'type': string})


class PrivateRoomOperatorRevoked(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x92)
        room: str = field(metadata={'type': string})


class PrivateRoomOperators(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x94)
        room: str = field(metadata={'type': string})
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})


class PrivateChatMessageUsers(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x95)
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})
        message: str = field(metadata={'type': string})


class EnablePublicChat(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x96)


class DisablePublicChat(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x97)


class PublicChatMessage(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x98)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class GetRelatedSearches(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})
        related_searches: List[str] = field(metadata={'type': array, 'subtype': string})


class CannotConnect(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03E9)
        ticket: int = field(metadata={'type': uint32})
        username: Optional[str] = field(default=None, metadata={'type': string, 'optional': True})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03E9)
        ticket: int = field(metadata={'type': uint32})
        username: Optional[str] = field(default=None, metadata={'type': string, 'optional': True})


class CannotCreateRoom(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03EB)
        room: str = field(metadata={'type': string})


# Peer Initialization messages

class PeerPierceFirewall(PeerInitializationMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x00)
        ticket: int = field(metadata={'type': uint32})


class _PeerInitTicket(uint32):
    # Hacky type here: sometimes people will send a uint64 instead of uint32 as
    # the ticket for a PeerInit message

    @classmethod
    def deserialize(cls, pos: int, data: bytes):
        if len(data[pos:]) == 4:
            return super().deserialize(pos, data)
        else:
            return uint64.deserialize(pos, data)


class PeerInit(PeerInitializationMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x01)
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': _PeerInitTicket})


# Peer messages

class PeerSharesRequest(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x04)
        # Museek docs: PeerSharesReply has an unknown uint32. The assumption is
        # that this is actually a ticket number that was supposed to be passed
        # with this message. The Windows clients appear to accept this ticket
        # number: they will send a reply if a ticket is set but only if this
        # ticket is a uint32, sending the ticket as a uint64 will be rejected.
        # Sending this ticket has no impact on the ticket in PeerSharesReply: it
        # will always be 0
        ticket: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})


class PeerSharesReply(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x05)
        directories: List[DirectoryData] = field(
            metadata={'type': array, 'subtype': DirectoryData}
        )
        # Unknown field that always seems to be 0, possibilities:
        # * This was another list, but it always empty (not tested)
        # * This is a ticket: See explanation of ticket in PeerSharesRequest
        unknown: int = field(default=0, metadata={'type': uint32})
        locked_directories: Optional[List[DirectoryData]] = field(
            default=None,
            metadata={'type': array, 'subtype': DirectoryData, 'optional': True}
        )

        def serialize(self, compress: bool = True) -> bytes:
            return super().serialize(compress)

        @classmethod
        def deserialize(cls, message: bytes, decompress: bool = True):
            return super().deserialize(message, decompress)


class PeerSearchReply(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x09)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        results: List[FileData] = field(metadata={'type': array, 'subtype': FileData})
        has_slots_free: bool = field(metadata={'type': boolean})
        avg_speed: int = field(metadata={'type': uint32})
        # Note: queue_size and unknown. queue_size is described as uint64 in the
        # museek documentation. However I believe that this is actually just a
        # uint32. The other 4 bytes are for an unknown uint32 right before the
        # locked results: the same can be seen in PeerSharesReply
        queue_size: int = field(metadata={'type': uint32})
        unknown: Optional[int] = field(default=0, metadata={'type': uint32})
        locked_results: Optional[List[FileData]] = field(
            default=None,
            metadata={'type': array, 'subtype': FileData, 'optional': True}
        )

        def serialize(self, compress: bool = True) -> bytes:
            return super().serialize(compress)

        @classmethod
        def deserialize(cls, message: bytes, decompress: bool = True):
            return super().deserialize(message, decompress)


class PeerUserInfoRequest(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)


class PeerUserInfoReply(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x10)
        description: str = field(metadata={'type': string})
        has_picture: bool = field(metadata={'type': boolean})
        picture: Optional[bytes] = field(default=None, metadata={'type': bytearr, 'if_true': 'has_picture'})
        upload_slots: int = field(default=0, metadata={'type': uint32})
        queue_size: int = field(default=0, metadata={'type': uint32})
        has_slots_free: bool = field(default=False, metadata={'type': boolean})
        upload_permissions: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})


class PeerDirectoryContentsRequest(PeerMessage):
    """Request the contents of a directory"""

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        ticket: int = field(metadata={'type': uint32})
        directory: str = field(metadata={'type': string})


class PeerDirectoryContentsReply(PeerMessage):
    """Reply to a directory contents request. Although the returned directories
    is a list it will only contain one element, the intention was probably to
    let this method recurse down but doesn't seem like they ever did.

    :todo: verify was happens if we pass multiple directories
    """

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x25)
        ticket: int = field(metadata={'type': uint32})
        directory: str = field(metadata={'type': string})
        directories: List[DirectoryData] = field(metadata={'type': array, 'subtype': DirectoryData})

        def serialize(self, compress: bool = True) -> bytes:
            return super().serialize(compress)

        @classmethod
        def deserialize(cls, message: bytes, decompress: bool = True):
            return super().deserialize(message, decompress)


class PeerTransferRequest(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x28)
        direction: int = field(metadata={'type': uint32})
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        filesize: Optional[int] = field(default=None, metadata={'type': uint64, 'optional': True})


class PeerTransferReply(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x29)
        ticket: int = field(metadata={'type': uint32})
        allowed: bool = field(metadata={'type': boolean})
        filesize: Optional[int] = field(default=None, metadata={'type': uint64, 'optional': True, 'if_true': 'allowed'})
        reason: Optional[str] = field(default=None, metadata={'type': string, 'optional': True, 'if_false': 'allowed'})


class PeerTransferQueue(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2B)
        filename: str = field(metadata={'type': string})


class PeerPlaceInQueueReply(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2C)
        filename: str = field(metadata={'type': string})
        place: int = field(metadata={'type': uint32})


class PeerUploadFailed(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2E)
        filename: str = field(metadata={'type': string})


class PeerTransferQueueFailed(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        filename: str = field(metadata={'type': string})
        reason: str = field(metadata={'type': string})


class PeerPlaceInQueueRequest(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x33)
        filename: str = field(metadata={'type': string})


class PeerUploadQueueNotification(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x34)


# Distributed messages

class DistributedPing(DistributedMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x00)


class DistributedSearchRequest(DistributedMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x03)
        # Should always be 0x31
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class DistributedBranchLevel(DistributedMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x04)
        level: int = field(metadata={'type': uint32})


class DistributedBranchRoot(DistributedMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x05)
        username: str = field(metadata={'type': string})


class DistributedChildDepth(DistributedMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x07)
        depth: int = field(metadata={'type': uint32})


class DistributedServerSearchRequest(DistributedMessage):
    """The branch root should just pass the ServerSearchRequest as-is to all its
    children; meaning we will get this message if we are at level 1. If we get
    this message we should translate it to a proper DistributedSearchRequest
    message.

    This message might need to be revisited, as it's only currently used for
    parsing
    """

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5D)
        distributed_code: int = field(metadata={'type': uint8})
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})
