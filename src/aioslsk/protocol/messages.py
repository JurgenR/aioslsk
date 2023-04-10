"""Definition of all SoulSeek protocol messages.

This file contains 3 types of messages:

* Server

    Request : used from client to server. A client will only use the
        `serialize` method of these messages
    Response : used from server to client. A client will only use the
        `deserialize` method of these messages


Field metadata:

The `Serializer` and `Deserializer` use the `metadata` parameter of the
`dataclasses.field` function to control how to perform (de)serialization.

These metadata keys are implemented:

* 'if_true': <field_name>
** serialization : only pack this field if the field in the value evaluates to True
** deserialization : only parse this field if the field in the value evaluates to True

* 'if_false': <field_name>
** serialization : only pack this field if the field in the value evaluates to False
** deserialization : only parse this field if the field in the value evaluates to False

* 'optional': True
** serialization : only pack this field if its value is anything other than None
** deserialization : during deserialization the code will determine if the message
    has been fully parsed. If not it will parse this field
"""
from dataclasses import dataclass, field
import logging
from typing import ClassVar, List

from ..exceptions import UnknownMessageError
from .primitives import (
    boolean,
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
    UserData,
    PotentialParent,
    SimilarUser,
    ItemRecommendation,
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
        greeting: str = field(default=None, metadata={'type': string, 'if_true': 'success'})
        ip: str = field(default=None, metadata={'type': ipaddr, 'if_true': 'success'})
        md5hash: str = field(default=None, metadata={'type': string, 'if_true': 'success'})
        privileged: bool = field(default=None, metadata={'type': boolean, 'if_true': 'success'})
        reason: str = field(default=None, metadata={'type': string, 'if_false': 'success'})


class SetListenPort(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x02)
        port: int = field(metadata={'type': uint32})
        obfuscated_port_amount: int = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: int = field(default=None, metadata={'type': uint32, 'optional': True})


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
        obfuscated_port_amount: int = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: int = field(default=None, metadata={'type': uint16, 'optional': True})


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
        status: int = field(default=None, metadata={'type': uint32, 'if_true': 'exists'})
        avg_speed: int = field(default=None, metadata={'type': uint32, 'if_true': 'exists'})
        download_num: int = field(default=None, metadata={'type': uint64, 'if_true': 'exists'})
        file_count: int = field(default=None, metadata={'type': uint32, 'if_true': 'exists'})
        dir_count: int = field(default=None, metadata={'type': uint32, 'if_true': 'exists'})
        country_code: str = field(
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


class ChatRoomMessage(ServerMessage):

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


class ChatJoinRoom(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0E)
        room: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0E)
        room: str = field(metadata={'type': string})
        users: List[str] = field(metadata={'type': array, 'subtype': string})
        users_status: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_data: List[UserData] = field(metadata={'type': array, 'subtype': UserData})
        users_slots_free: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_countries: List[str] = field(metadata={'type': array, 'subtype': string})
        owner: str = field(default=None, metadata={'type': string, 'optional': True})
        operators: List[str] = field(
            default=None,
            metadata={
                'type': array,
                'subtype': string,
                'optional': True
            })


class ChatLeaveRoom(ServerMessage):
    MESSAGE_ID = 0x0F

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})


class ChatUserJoinedRoom(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x10)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        status: int = field(metadata={'type': uint32})
        user_data: UserData = field(metadata={'type': UserData})
        slots_free: int = field(metadata={'type': uint32})
        country_code: str = field(metadata={'type': string})


class ChatUserLeftRoom(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x11)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class ConnectToPeer(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x12)
        ticket: str = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x12)
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})
        ip: str = field(metadata={'type': ipaddr})
        port: int = field(metadata={'type': uint32})
        ticket: str = field(metadata={'type': uint32})
        privileged: bool = field(metadata={'type': boolean})
        obfuscated_port_amount: int = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: int = field(default=None, metadata={'type': uint32, 'optional': True})


class ChatPrivateMessage(ServerMessage):

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
        is_admin: bool = field(default=False, metadata={'type': boolean, 'optional': True})


class ChatAckPrivateMessage(ServerMessage):

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


class SharedFoldersFiles(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x23)
        directory_count: int = field(metadata={'type': uint32})
        file_count: int = field(metadata={'type': uint32})


class GetUserStats(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        username: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        username: str = field(metadata={'type': string})
        avg_speed: int = field(metadata={'type': uint32})
        download_num: int = field(metadata={'type': uint64})
        file_count: int = field(metadata={'type': uint32})
        dir_count: int = field(metadata={'type': uint32})


class UserSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2A)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


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


class PrivilegedUsers(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x45)
        users: List[str] = field(metadata={'type': array, 'subtype': string})


class ToggleParentSearch(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x47)
        enabled: bool = field(metadata={'type': boolean})


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
        recommendation: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        recommendations: List[ItemRecommendation] = field(metadata={'type': array, 'subtype': ItemRecommendation})


class ChatRoomTickers(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x71)
        room: str = field(metadata={'type': string})
        tickers: List[RoomTicker] = field(metadata={'type': array, 'subtype': RoomTicker})


class ChatRoomTickerAdded(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x72)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class ChatRoomTickerRemoved(ServerMessage):

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x73)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class ChatRoomTickerSet(ServerMessage):

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x74)
        room: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class ChatRoomSearch(ServerMessage):

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


class PrivateRoomUsers(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x85)
        room: str = field(metadata={'type': string})
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})


class PrivateRoomAddUser(ServerMessage):

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


class PrivateRoomRemoveUser(ServerMessage):

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


class PrivateRoomAdded(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8B)
        room: str = field(metadata={'type': string})


class PrivateRoomRemoved(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8C)
        room: str = field(metadata={'type': string})


class TogglePrivateRooms(ServerMessage):

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


class PrivateRoomAddOperator(ServerMessage):

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


class PrivateRoomRemoveOperator(ServerMessage):

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


class PrivateRoomOperatorAdded(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x91)
        room: str = field(metadata={'type': string})


class PrivateRoomOperatorRemoved(ServerMessage):

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


class ChatMessageUsers(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x95)
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})
        message: str = field(metadata={'type': string})


class ChatEnablePublic(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x96)


class ChatDisablePublic(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x97)


class ChatPublicMessage(ServerMessage):

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x98)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class FileSearchEx(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})
        unknown: int = field(metadata={'type': uint32})


class CannotConnect(ServerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03E9)
        ticket: int = field(metadata={'type': uint32})
        username: str = field(default=None, metadata={'type': string, 'optional': True})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03E9)
        ticket: int = field(metadata={'type': uint32})
        username: str = field(default=None, metadata={'type': string, 'optional': True})


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
        ticket: int = field(default=None, metadata={'type': uint32, 'optional': True})


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
        locked_directories: List[DirectoryData] = field(
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
        unknown: int = field(default=0, metadata={'type': uint32})
        locked_results: List[FileData] = field(
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
        picture: str = field(default=None, metadata={'type': string, 'if_true': 'has_picture'})
        upload_slots: int = field(default=0, metadata={'type': uint32})
        queue_size: int = field(default=0, metadata={'type': uint32})
        has_slots_free: bool = field(default=False, metadata={'type': boolean})


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
        filesize: int = field(default=None, metadata={'type': uint64, 'optional': True})


class PeerTransferReply(PeerMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x29)
        ticket: int = field(metadata={'type': uint32})
        allowed: bool = field(metadata={'type': boolean})
        filesize: int = field(default=None, metadata={'type': uint64, 'optional': True, 'if_true': 'allowed'})
        reason: str = field(default=None, metadata={'type': string, 'optional': True, 'if_false': 'allowed'})


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

class DistributedSearchRequest(DistributedMessage):

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x03)
        # Should always be 0x31
        unknown: int = field(metadata={'type': uint32})
        username: int = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: int = field(metadata={'type': string})


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
