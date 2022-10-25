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

* 'condition': <callable>
** serialization : value is determined based on another variable. The object to
    serialize will be passed to the callable
** deserialization : not used

* 'optional': True
** serialization : only pack this field if its value is anything other than None
** deserialization : during deserialization the code will determine if the message
    has been fully parsed. If not it will parse this field
"""
from dataclasses import dataclass, field
import logging
from typing import List, ClassVar

from pyslsk.protocol.primitives import (
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


logger = logging.getLogger()


class Login:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
        username: str = field(metadata={'type': string})
        password: str = field(metadata={'type': string})
        client_version: int = field(metadata={'type': uint32})
        password_md5: str = field(metadata={'type': string})
        minor_version: int = field(metadata={'type': uint32})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
        success: bool = field(metadata={'type': boolean})
        greeting: str = field(default=None, metadata={'type': string, 'if_true': 'success'})
        ip: str = field(default=None, metadata={'type': ipaddr, 'if_true': 'success'})
        md5hash: str = field(default=None, metadata={'type': string, 'if_true': 'success'})
        unknown: int = field(default=None, metadata={'type': int, 'if_true': 'success'})
        reason: str = field(default=None, metadata={'type': string, 'if_false': 'success'})


class SetListenPort:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x02)
        port: int = field(metadata={'type': uint32})
        obfuscated_ports: List[int] = field(
            default=None,
            metadata={
                'type': array,
                'subtype': uint32,
                'optional': True
            }
        )


class GetPeerAddress:

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
        obfuscated_ports: List[int] = field(
            default=None,
            metadata={
                'type': array,
                'subtype': uint16,
                'optional': True
            }
        )


class AddUser:

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


class RemoveUser:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x06)
        username: str = field(metadata={'type': string})


class GetUserStatus:

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


class ChatRoomMessage:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0D)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class ChatJoinRoom:

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
        users_slots_free: List[int] = field(metadata={'type': array, 'subtype': uint32})
        users_data: List[UserData] = field(metadata={'type': array, 'subtype': UserData})
        users_countries: List[str] = field(metadata={'type': array, 'subtype': string})
        owner: str = field(metadata={'type': string, 'optional': True})
        operators: List[str] = field(
            default_factory=list,
            metadata={
                'type': array,
                'subtype': string,
                'optional': True
            })


class ChatLeaveRoom:
    MESSAGE_ID = 0x0F

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})


class ChatUserJoinedRoom:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x10)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        status: int = field(metadata={'type': uint32})
        user_data: UserData = field(metadata={'type': UserData})
        slots_free: int = field(metadata={'type': uint32})
        country_code: str = field(metadata={'type': string})


class ChatUserLeftRoom:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x11)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class ConnectToPeer:

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


class ChatPrivateMessage:

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


class ChatAckPrivateMessage:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x17)
        chat_id: int = field(metadata={'type': uint32})


class FileSearch:

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


class SetStatus:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1C)
        status: int = field(metadata={'type': uint32})


class Ping:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x20)


class SharedFolderFiles:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x20)
        dir_count: int = field(metadata={'type': uint32})
        file_count: int = field(metadata={'type': uint32})


class GetUserStats:

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


class UserSearch:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2A)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class RoomList:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x40)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x40)
        rooms: List[str] = field(metadata={'type': array, 'subtype': string})
        rooms_user_count: int = field(metadata={'type': uint32})
        rooms_private_owned: List[str] = field(metadata={'type': array, 'subtype': string})
        rooms_private_owned_user_count: int = field(metadata={'type': uint32})
        rooms_private: List[str] = field(metadata={'type': array, 'subtype': string})
        rooms_private_user_count: int = field(metadata={'type': uint32})
        rooms_private_operated: List[str] = field(metadata={'type': array, 'subtype': string})


class PrivilegedUsers:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x45)
        users: List[str] = field(metadata={'type': array, 'subtype': string})


class ToggleParentSearch:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x47)
        enabled: bool = field(metadata={'type': boolean})


class ParentIP:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x49)
        ip: str = field(metadata={'type': ipaddr})

class ParentMinSpeed:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x53)
        speed: int = field(metadata={'type': uint32})

class ParentSpeedRatio:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x54)
        ratio: int = field(metadata={'type': uint32})


class ParentInactivityTimeout:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x56)
        timeout: int = field(metadata={'type': uint32})


class SearchInactivityTimeout:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x57)
        timeout: int = field(metadata={'type': uint32})


class MinParentsInCache:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x58)
        amount: int = field(metadata={'type': uint32})


class DistributedAliveInterval:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5A)
        interval: int = field(metadata={'type': uint32})


class AddPrivilegedUser:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5B)
        username: str = field(metadata={'type': string})


class CheckPrivileges:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5C)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5C)
        time_left: int = field(metadata={'type': uint32})


class ServerSearchRequest:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5D)
        distributed_code: int = field(metadata={'type': uint8})
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class AcceptChildren:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x64)
        accept: bool = field(metadata={'type': boolean})


class PotentialParents:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x66)
        entries: List[PotentialParent] = field(metadata={'type': array, 'subtype': PotentialParent})


class WishlistSearch:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x67)
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class WishlistInterval:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x68)
        interval: int = field(metadata={'type': uint32})


class GetSimilarUsers:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6E)

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6E)
        users: List[SimilarUser] = field(metadata={'type': array, 'subtype': SimilarUser})


class GetItemRecommendations:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        recommendation: str = field(metadata={'type': string})

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        recommendations: List[ItemRecommendation] = field(metadata={'type': array, 'subtype': ItemRecommendation})


class ChatRoomTickers:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x71)
        room: str = field(metadata={'type': string})
        tickers: List[RoomTicker] = field(metadata={'type': array, 'subtype': RoomTicker})


class ChatRoomTickerAdded:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x72)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class ChatRoomTickerRemoved:

    @dataclass(order=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x73)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class ChatRoomTickerSet:

    @dataclass(order=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x74)
        room: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class ChatRoomSearch:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x78)
        room: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class SendUploadSpeed:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x79)
        speed: int = field(metadata={'type': uint32})


class GetUserPrivileges:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7A)
        username: int = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7A)
        username: int = field(metadata={'type': string})
        privileged: bool = field(metadata={'type': boolean})


class GiveUserPrivileges:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7B)
        username: str = field(metadata={'type': string})
        days: int = field(metadata={'type': uint32})


class PrivilegesNotification:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7C)
        notification_id: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})


class PrivilegesNotificationAck:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7D)
        notification_id: int = field(metadata={'type': uint32})


class BranchLevel:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7E)
        level: int = field(metadata={'type': uint32})


class BranchRoot:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7F)
        username: str = field(metadata={'type': string})


class ChildDepth:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x81)
        depth: int = field(metadata={'type': uint32})


class PrivateRoomUsers:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x85)
        room: str = field(metadata={'type': string})
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})


class PrivateRoomAddUser:

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


class PrivateRoomRemoveUser:

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


class PrivateRoomDropMembership:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x88)
        room: str = field(metadata={'type': string})


class PrivateRoomDropOwnership:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x89)
        room: str = field(metadata={'type': string})


class PrivateRoomAdded:

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8B)
        room: str = field(metadata={'type': string})


class PrivateRoomRemoved:

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8C)
        room: str = field(metadata={'type': string})


class TogglePrivateRooms:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8D)
        enable: bool = field(metadata={'type': boolean})


class NewPassword:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8E)
        password: str = field(metadata={'type': string})


class PrivateRoomAddOperator:

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


class PrivateRoomRemoveOperator:

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


class PrivateRoomOperatorAdded:

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x91)
        room: str = field(metadata={'type': string})


class PrivateRoomOperatorRemoved:

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x92)
        room: str = field(metadata={'type': string})


class PrivateRoomOperators:

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x94)
        room: str = field(metadata={'type': string})
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})


class ChatMessageUsers:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x95)
        usernames: List[str] = field(metadata={'type': array, 'subtype': string})
        message: str = field(metadata={'type': string})


class ChatEnablePublic:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x96)


class ChatDisablePublic:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x97)


class ChatPublicMessage:

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x98)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class FileSearchEx:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})

    @dataclass
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})
        unknown: int = field(metadata={'type': uint32})


class CannotConnect:

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

class PeerPierceFirewall:

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


class PeerInit:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x01)
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': _PeerInitTicket})


# Peer messages

class PeerSharesRequest:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x04)


class PeerSharesReply:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x05)
        directories: List[DirectoryData] = field(
            metadata={'type': array, 'subtype': DirectoryData}
        )
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


class PeerSearchReply:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x09)
        username: str = field(metadata={'type': string})
        ticket: str = field(metadata={'type': uint32})
        results: List[FileData] = field(metadata={'type': array, 'subtype': FileData})
        has_slots_free: bool = field(metadata={'type': boolean})
        avg_speed: int = field(metadata={'type': uint32})
        queue_size: int = field(metadata={'type': uint64})
        locked_results: List[FileData] = field(
            default=None,
            metadata={'type': array, 'subtype': DirectoryData, 'optional': True}
        )

        def serialize(self, compress: bool = True) -> bytes:
            return super().serialize(compress)

        @classmethod
        def deserialize(cls, message: bytes, decompress: bool = True):
            return super().deserialize(message, decompress)


class PeerUserInfoRequest:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)


class PeerUserInfoReply:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x10)
        has_picture: bool = field(metadata={'type': boolean})
        picture: str = field(default=None, metadata={'type': string, 'if_true': 'has_picture'})
        upload_slots: int = field(default=0, metadata={'type': uint32})
        queue_size: int = field(default=0, metadata={'type': uint32})
        has_slots_free: bool = field(default=False, metadata={'type': boolean})


class PeerDirectoryContentsRequest:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        directories: List[str] = field(metadata={'type': array, 'subtype': string})


class PeerDirectoryContentsReply:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x25)
        directories: List[DirectoryData] = field(metadata={'type': array, 'subtype': DirectoryData})
        # TODO: Investigate locked results (see PeerSharesReply)

        def serialize(self, compress: bool = True) -> bytes:
            return super().serialize(compress)

        @classmethod
        def deserialize(cls, message: bytes, decompress: bool = True):
            return super().deserialize(message, decompress)


class PeerTransferRequest:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x28)
        direction: int = field(metadata={'type': uint32})
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        filesize: int = field(default=None, metadata={'type': uint32, 'optional': True})


class PeerTransferReply:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x29)
        ticket: int = field(metadata={'type': uint32})
        allowed: bool = field(metadata={'type': boolean})
        filesize: int = field(default=None, metadata={'type': uint32, 'optional': True, 'if_true': 'allowed'})
        reason: str = field(default=None, metadata={'type': string, 'optional': True, 'if_false': 'allowed'})


class PeerTransferQueue:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2B)
        filename: str = field(metadata={'type': string})


class PeerPlaceInQueueReply:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2C)
        filename: str = field(metadata={'type': string})
        place: int = field(metadata={'type': uint32})


class PeerUploadFailed:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2E)
        filename: str = field(metadata={'type': string})


class PeerTransferQueueFailed:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        filename: str = field(metadata={'type': string})
        reason: str = field(metadata={'type': string})


class PeerPlaceInQueueRequest:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x33)
        filename: str = field(metadata={'type': string})


class PeerUploadQueueNotification:

    @dataclass
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x34)
