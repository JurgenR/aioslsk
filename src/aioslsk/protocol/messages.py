"""Definition of all SoulSeek protocol messages.

This file contains 2 types of messages:

* Server

    Request : used from client to server. A client will only use the
        ``serialize`` method of these messages
    Response : used from server to client. A client will only use the
        ``deserialize`` method of these messages

* Peer

    Request : peer messages only consist of request type messages. The client
        should use the ``deserialize`` method of these messages upon receiving
        data from another peer and the ``serialize`` method when sending to
        another peer
"""
from dataclasses import dataclass, field
import logging
from typing import ClassVar, Optional

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
                return request_cls.deserialize(0, message)

        raise UnknownMessageError(msg_id, message, "Unknown server request message")

    @classmethod
    def deserialize_response(cls, message):
        _, msg_id = uint32.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            response_cls = getattr(msg_class, 'Response', None)
            if response_cls and response_cls.MESSAGE_ID == msg_id:
                return response_cls.deserialize(0, message)

        raise UnknownMessageError(msg_id, message, "Unknown server response message")


class PeerInitializationMessage:
    """Class for identifying peer initialization messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint8.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(0, message)

        raise UnknownMessageError(msg_id, message, "Unknown peer initialization message")


class PeerMessage:
    """Class for identifying peer messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint32.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(0, message)

        raise UnknownMessageError(msg_id, message, "Unknown peer message")


class DistributedMessage:
    """Class for identifying distributed messages"""

    @classmethod
    def deserialize_request(cls, message: bytes):
        _, msg_id = uint8.deserialize(4, message)

        for msg_class in cls.__subclasses__():
            request_cls = getattr(msg_class, 'Request', None)
            if request_cls and request_cls.MESSAGE_ID == msg_id:
                return request_cls.deserialize(0, message)

        raise UnknownMessageError(msg_id, message, "Unknown distributed message")


class Login(ServerMessage):
    """Login into the server, this should be the first message sent to the
    server upon connecting

    * The ``md5hash`` parameter in the request is the MD5 hash of the
      concatenated ``username`` and ``password``
    * The ``md5hash`` parameter in the response is the MD5 hash of the
      ``password``

    .. note::

        Older client versions (at least 149 or below) would not send the
        ``md5hash`` and ``minor_version``

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
        username: str = field(metadata={'type': string})
        password: str = field(metadata={'type': string})
        client_version: int = field(metadata={'type': uint32})
        md5hash: str = field(metadata={'type': string})
        minor_version: int = field(metadata={'type': uint32})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x01)
        success: bool = field(metadata={'type': boolean})
        greeting: Optional[str] = field(default=None, metadata={'type': string, 'if_true': 'success'})
        ip: Optional[str] = field(default=None, metadata={'type': ipaddr, 'if_true': 'success'})
        md5hash: Optional[str] = field(default=None, metadata={'type': string, 'if_true': 'success'})
        privileged: Optional[bool] = field(default=None, metadata={'type': boolean, 'if_true': 'success'})
        reason: Optional[str] = field(default=None, metadata={'type': string, 'if_false': 'success'})


class SetListenPort(ServerMessage):
    """Advertise our listening ports to the server

    Obfuscated port: this part seems to be optional, either it can be omitted
    completely or both values set to ``0``

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x02)
        port: int = field(metadata={'type': uint32})
        obfuscated_port_amount: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})


class GetPeerAddress(ServerMessage):
    """Retrieve the IP address/port of a peer. Obfuscated port: this part is
    optional, either it can be omitted completely or both values set to ``0`` to
    indicate there is no obfuscated port

    If the peer does not exist or is not logged on the server will respond with
    IP address set to ``0.0.0.0``, port set to ``0``

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03)
        username: str = field(metadata={'type': string})
        ip: str = field(metadata={'type': ipaddr})
        port: int = field(metadata={'type': uint32})
        obfuscated_port_amount: Optional[int] = field(default=None, metadata={'type': uint32, 'optional': True})
        obfuscated_port: Optional[int] = field(default=None, metadata={'type': uint16, 'optional': True})


class AddUser(ServerMessage):
    """When a user is added with this message the server will automatically send
    user status updates using the :ref:`GetUserStatus` message.

    When a user sends a message to multiple users using the
    :ref:`PrivateChatMessageUsers` message then this message will only be
    received if the sender was added first using this message.

    To remove a user use the :ref:`RemoveUser` message. Keep in mind that you
    will still receive status updates in case you are joined in the same room
    with the user.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x05)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
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
    """Remove the tracking of user status which was previously added with the
    :ref:`AddUser` message.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x06)
        username: str = field(metadata={'type': string})


class GetUserStatus(ServerMessage):
    """Get the user status. The server will automatically send updates for users
    that we have added with :ref:`AddUser` or which we share a room with.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x07)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x07)
        username: str = field(metadata={'type': string})
        status: int = field(metadata={'type': uint32})
        privileged: bool = field(metadata={'type': boolean})


class IgnoreUser(ServerMessage):
    """Sent when we want to ignore a user. Received when another user ignores us

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0B)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0B)
        username: str = field(metadata={'type': string})


class UnignoreUser(ServerMessage):
    """Sent when we want to unignore a user. Received when another user
    unignores us

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0C)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0C)
        username: str = field(metadata={'type': string})


class RoomChatMessage(ServerMessage):
    """Used when sending a message to a room or receiving a message from someone
    (including self) who sent a message to a room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0D)
        room: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0D)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class JoinRoom(ServerMessage):
    """Used when we want to join a chat room. If the chat room does not exist
    it will be created. Upon successfully joining the room the server will send
    the response message

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0E)
        room: str = field(metadata={'type': string})
        is_private: bool = field(default=False, metadata={'type': uint32, 'optional': True})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0E)
        room: str = field(metadata={'type': string})
        users: list[str] = field(metadata={'type': array, 'subtype': string})
        users_status: list[int] = field(metadata={'type': array, 'subtype': uint32})
        users_stats: list[UserStats] = field(metadata={'type': array, 'subtype': UserStats})
        users_slots_free: list[int] = field(metadata={'type': array, 'subtype': uint32})
        users_countries: list[str] = field(metadata={'type': array, 'subtype': string})
        owner: Optional[str] = field(default=None, metadata={'type': string, 'optional': True})
        operators: Optional[list[str]] = field(
            default=None,
            metadata={
                'type': array,
                'subtype': string,
                'optional': True
            })


class LeaveRoom(ServerMessage):
    """Used when we want to leave a chat room. The receive message is
    confirmation that we left the room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)
        room: str = field(metadata={'type': string})


class UserJoinedRoom(ServerMessage):
    """Received when a user joined a room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x10)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        status: int = field(metadata={'type': uint32})
        user_stats: UserStats = field(metadata={'type': UserStats})
        slots_free: int = field(metadata={'type': uint32})
        country_code: str = field(metadata={'type': string})


class UserLeftRoom(ServerMessage):
    """Received when a user left a room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x11)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class ConnectToPeer(ServerMessage):
    """Received when a peer attempted to connect to us but failed and thus is
    asking us to attempt to connect to them through the server. Likewise when
    we cannot connect to peer we should send this message to indicate to the
    other peer that he should try connecting to us

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x12)
        ticket: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
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
    """Send or receive a private message. The ``chat_id`` should be used in the
    :ref:`PrivateChatMessageAck` message to acknowledge the message has been
    received. If the acknowledgement is not sent the server will repeat the
    message on the next logon.

    The ``is_direct`` boolean indicates whether it is the first attempt to send
    the message, if the server retries then this parameter will be false

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x16)
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x16)
        chat_id: int = field(metadata={'type': uint32})
        timestamp: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})
        is_direct: Optional[bool] = field(default=False, metadata={'type': boolean, 'optional': True})

        @property
        def is_admin(self) -> Optional[bool]:
            """Only kept to keep backward compatibility. Use ``is_direct``

            This property does not actually represent whether the message was sent
            by an admin. Instead it represents whether the message was sent directly
            or was queued on the server before being sent (example, when user was
            offline and came back online)
            """
            return self.is_direct

        @is_admin.setter
        def is_admin(self, value: bool):
            self.is_direct = value


class PrivateChatMessageAck(ServerMessage):
    """Acknowledge we have received a private message after receiving a
    :ref:`PrivateChatMessage`

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x17)
        chat_id: int = field(metadata={'type': uint32})


class FileSearchRoom(ServerMessage):
    """Deprecated message for searching a room

    :Status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x19)
        ticket: int = field(metadata={'type': uint32})
        room_id: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class FileSearch(ServerMessage):
    """This message is received when another user performed a :ref:`RoomSearch`
    or :ref:`UserSearch` request and we are part of the room or we are the user
    the user would like to search in

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1A)
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1A)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class SetStatus(ServerMessage):
    """Used to update the online status. Possible values for ``status``:
    online = 2, away = 1, offline = 0

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x1C)
        status: int = field(metadata={'type': uint32})


class Ping(ServerMessage):
    """Send a ping to the server to let it know we are still alive (every 5
    minutes)

    Older server versions would respond to this message with the response message

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x20)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x20)


class SendConnectTicket(ServerMessage):
    """Deprecated predecessor to :ref:`ConnectToPeer`. A peer would send this
    message to the server when wanting to create a connection to another peer,
    the server would then pass to this to the targeted peer

    The value of the ``ticket`` parameter would be used in the :ref:`PeerInit`
    message.

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x21)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x21)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})


class SendDownloadSpeed(ServerMessage):
    """Sent by old clients after download has completed. :ref:`SendUploadSpeed`
    should be used instead. The ``speed`` value should be in bytes per second

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x22)
        username: str = field(metadata={'type': string})
        speed: int = field(metadata={'type': uint32})


class SharedFoldersFiles(ServerMessage):
    """Let the server know the amount of files and directories we are sharing.
    These would be returned in several messages, for example the
    :ref:`GetUserStats` and :ref:`AddUser` messages

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x23)
        shared_folder_count: int = field(metadata={'type': uint32})
        shared_file_count: int = field(metadata={'type': uint32})


class GetUserStats(ServerMessage):
    """Request a user's transfer statistics. This message will be received
    automatically for users with which we share a room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        username: str = field(metadata={'type': string})
        user_stats: UserStats = field(metadata={'type': UserStats})


class Kicked(ServerMessage):
    """You were kicked from the server. This message is currently only known to
    be sent when the user was logged into at another location

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x29)


class UserSearch(ServerMessage):
    """Search for a file on a specific user, the user will receive this query
    in the form of a :ref:`FileSearch` message

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2A)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class DeprecatedGetItemRecommendations(ServerMessage):
    """Similar to :ref:`GetItemRecommendations` except that no score is returned

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        item: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        item: str = field(metadata={'type': string})
        recommendations: list[str] = field(metadata={'type': array, 'subtype': string})


class AddInterest(ServerMessage):
    """Adds an interest. This is used when requesting recommendations
    (eg.: :ref:`GetRecommendations`, ...)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x33)
        interest: str = field(metadata={'type': string})


class RemoveInterest(ServerMessage):
    """Removes an interest previously added with :ref:`AddInterest` message

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x34)
        interest: str = field(metadata={'type': string})


class GetRecommendations(ServerMessage):
    """Request the server to send a list of recommendations and
    unrecommendations. A maximum of 100 each will be returned. The score can be
    negative.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x36)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x36)
        recommendations: list[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )
        unrecommendations: list[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )


class GetInterests(ServerMessage):
    """Request the server the list of interests it currently has stored for us.
    This was sent by older clients during logon, presumably to sync the
    interests on the client and the server. Deprecated as the client should just
    advertise all interests after logon using the :ref:`AddInterest` and
    :ref:`AddHatedInterest` messages

    Not known whether the server still responds to this command

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x37)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x37)
        interests: list[str] = field(metadata={'type': array, 'subtype': string})


class GetGlobalRecommendations(ServerMessage):
    """Get the global list of recommendations. This does not take into account
    interests or hated interests that were previously added and is just a
    ranking of interests that other users have set

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x38)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x38)
        recommendations: list[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )
        unrecommendations: list[Recommendation] = field(
            metadata={'type': array, 'subtype': Recommendation}
        )


class GetUserInterests(ServerMessage):
    """Get the interests and hated interests of a particular user

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x39)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x39)
        username: str = field(metadata={'type': string})
        interests: list[str] = field(metadata={'type': array, 'subtype': string})
        hated_interests: list[str] = field(metadata={'type': array, 'subtype': string})


class ExecuteCommand(ServerMessage):
    """Send a command to the server.

    The command type has only ever been seen as having value ``admin``, the ``arguments`` array
    contains the subcommand and arguments. Example when banning a user:

    * ``command_type`` : ``admin``
    * ``arguments``

      * 0 : ``ban``
      * 1 : ``some user``
      * 2 : probably some extra args, perhaps time limit in case of ban, ... (optional)

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x3A)
        command_type: str = field(metadata={'type': string})
        arguments: list[str] = field(metadata={'type': array, 'subtype': string})


class RoomList(ServerMessage):
    """Request or receive the list of rooms. This message will be initially sent
    after logging on but can also be manually requested afterwards. The initial
    message after logon will only return a limited number of public rooms (only
    the rooms with 5 or more users).

    Parameter ``rooms_private`` excludes private rooms of which we are owner

    Parameter ``rooms_private_owned_user_count`` / ``rooms_private_user_count``
    should be the amount of users who have joined the private room, not the
    amount of members

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x40)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x40)
        rooms: list[str] = field(metadata={'type': array, 'subtype': string})
        rooms_user_count: list[int] = field(metadata={'type': array, 'subtype': uint32})
        rooms_private_owned: list[str] = field(metadata={'type': array, 'subtype': string})
        rooms_private_owned_user_count: list[int] = field(metadata={'type': array, 'subtype': uint32})
        rooms_private: list[str] = field(metadata={'type': array, 'subtype': string})
        rooms_private_user_count: list[int] = field(metadata={'type': array, 'subtype': uint32})
        rooms_private_operated: list[str] = field(metadata={'type': array, 'subtype': string})


class ExactFileSearch(ServerMessage):
    """Used by older clients but doesn't return anything. The ``pathname`` is
    optional but is still required to be sent.

    For the message sending: The first 4 parameters are verified, the meaning
    of the final 5 bytes is unknown

    For the message receiving: message is never seen and is based on other
    documentation (PySlsk)

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x41)
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        pathname: str = field(metadata={'type': string})
        filesize: int = field(metadata={'type': uint64})
        checksum: int = field(metadata={'type': uint32})
        unknown: int = field(metadata={'type': uint8})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x41)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        pathname: str = field(metadata={'type': string})
        filesize: int = field(metadata={'type': uint64})
        checksum: int = field(metadata={'type': uint32})


class AdminMessage(ServerMessage):
    """Sent by the admin when the server is going down for example

    :status: UNKNOWN
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x42)
        message: str = field(metadata={'type': string})


class GetUserList(ServerMessage):
    """Gets a list of all users on the server

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x43)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x43)
        users: list[str] = field(metadata={'type': array, 'subtype': string})
        users_status: list[int] = field(metadata={'type': array, 'subtype': uint32})
        users_stats: list[UserStats] = field(metadata={'type': array, 'subtype': UserStats})
        users_slots_free: list[int] = field(metadata={'type': array, 'subtype': uint32})
        users_countries: list[str] = field(metadata={'type': array, 'subtype': string})


class TunneledMessage(ServerMessage):
    """Tunnel a message through the server to a user

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x44)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        code: int = field(metadata={'type': uint32})
        message: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x44)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        code: int = field(metadata={'type': uint32})
        ip: str = field(metadata={'type': ipaddr})
        port: int = field(metadata={'type': uint32})
        message: str = field(metadata={'type': string})


class PrivilegedUsers(ServerMessage):
    """List of users with privileges sent after login

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x45)
        users: list[str] = field(metadata={'type': array, 'subtype': string})


class ToggleParentSearch(ServerMessage):
    """Indicates whether we want to receive :ref:`PotentialParents` messages
    from the server. A message should be sent to disable if we have found a
    parent

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x47)
        enable: bool = field(metadata={'type': boolean})


class ParentIP(ServerMessage):
    """IP address of the parent. Not sent by newer clients

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x49)
        ip: str = field(metadata={'type': ipaddr})


class Unknown80(ServerMessage):
    """Unknown message used by old client versions. The client would establish
    2 connections to the server: to one it would send the :ref:`Login` message,
    to the other this message would be sent. This second connection seemed to
    be related to the distributed network as the client would automatically
    disconnect after :ref:`DistributedAliveInterval` had been reached. It would
    seem like the server would be the client's parent in this case.

    After an interval determined by :ref:`DistributedDistributeInterval` the
    client would send another message over this connection which is described
    in :ref:`DistributedInit`. There's many unknowns in this message and even
    the types are unknown as many values were just 0, only known value is the
    last value which is the second listening port these clients used

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x50)


class ParentMinSpeed(ServerMessage):
    """Used for calculating the maximum amount of children we can have in the
    distributed network. If our average upload speed is below this value then
    we should accept no children. The average upload speed should be determined
    by the upload speed returned by :ref:`GetUserStats` (with our own username)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x53)
        speed: int = field(metadata={'type': uint32})


class ParentSpeedRatio(ServerMessage):
    """Used for calculating the maximum amount of children we can have in the
    distributed network

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x54)
        ratio: int = field(metadata={'type': uint32})


class ParentInactivityTimeout(ServerMessage):
    """Timeout for the distributed parent

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x56)
        timeout: int = field(metadata={'type': uint32})


class SearchInactivityTimeout(ServerMessage):

    """Presumably indicates after how much time search responses should no
    longer be accepted

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x57)
        timeout: int = field(metadata={'type': uint32})


class MinParentsInCache(ServerMessage):
    """Amount of parents (received through :ref:`PotentialParents`) we should
    keep in cache. Message has not been seen being sent by the server

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x58)
        amount: int = field(metadata={'type': uint32})


class DistributedDistributeInterval(ServerMessage):

    """Deprecated distributed network related message

    :status: DEPRECATED, DEFUNCT"""

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x59)
        interval: int = field(metadata={'type': uint32})


class DistributedAliveInterval(ServerMessage):
    """Interval at which a :ref:`DistributedPing` message should be sent to the
    children

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5A)
        interval: int = field(metadata={'type': uint32})


class AddPrivilegedUser(ServerMessage):
    """Usage unknown

    :status: UNKNOWN
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5B)
        username: str = field(metadata={'type': string})


class CheckPrivileges(ServerMessage):
    """Checks whether the requesting user has privileges, ``time_left`` will
    be ``0`` in case the user has no privileges, time left in seconds otherwise

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5C)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5C)
        time_left: int = field(metadata={'type': uint32})


class ServerSearchRequest(ServerMessage):
    """Search request sent by another user through the server. Upon receiving
    this the message should be passed on to the distributed children

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5D)
        distributed_code: int = field(metadata={'type': uint8})
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class AcceptChildren(ServerMessage):
    """Tell the server whether or not we are accepting any distributed children,
    the server *should* take this into account when sending
    :ref:`PotentialParents` messages to other peers

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x64)
        accept: bool = field(metadata={'type': boolean})


class PotentialParents(ServerMessage):
    """List of potential parents, used in distributed network

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x66)
        entries: list[PotentialParent] = field(metadata={'type': array, 'subtype': PotentialParent})


class WishlistSearch(ServerMessage):
    """Perform a wishlist search. The interval at which a client should send
    this message is determined by the :ref:`WishlistInterval` message

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x67)
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class WishlistInterval(ServerMessage):
    """The server lets us know at what interval we should perform wishlist
    searches (:ref:`WishlistSearch`). Sent by the server after logon

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x68)
        interval: int = field(metadata={'type': uint32})


class GetSimilarUsers(ServerMessage):
    """Get a list of similar users

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6E)

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6E)
        users: list[SimilarUser] = field(metadata={'type': array, 'subtype': SimilarUser})


class GetItemRecommendations(ServerMessage):
    """Get a list of recommendations based on a single interest

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        item: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x6F)
        item: str = field(metadata={'type': string})
        recommendations: list[Recommendation] = field(metadata={'type': array, 'subtype': Recommendation})


class GetItemSimilarUsers(ServerMessage):
    """Get a list of similar users based on a single interest

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x70)
        item: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x70)
        item: str = field(metadata={'type': string})
        usernames: list[str] = field(metadata={'type': array, 'subtype': string})


class RoomTickers(ServerMessage):
    """List of chat room tickers (room wall)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x71)
        room: str = field(metadata={'type': string})
        tickers: list[RoomTicker] = field(metadata={'type': array, 'subtype': RoomTicker})


class RoomTickerAdded(ServerMessage):
    """A ticker has been added to the room (room wall)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x72)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class RoomTickerRemoved(ServerMessage):
    """A ticker has been removed to the room (room wall)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x73)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class SetRoomTicker(ServerMessage):
    """Add or update a ticker for a room (room wall)

    .. note::

        An empty ``ticker`` value is not allowed in most clients. However, the server does accept
        it and clears the ticker from the room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x74)
        room: str = field(metadata={'type': string})
        ticker: str = field(metadata={'type': string})


class AddHatedInterest(ServerMessage):
    """Adds an hated interest. This is used when requesting recommendations
    (eg.: :ref:`GetRecommendations`, ...)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x75)
        hated_interest: str = field(metadata={'type': string})


class RemoveHatedInterest(ServerMessage):
    """Removes a hated interest previously added with :ref:`AddHatedInterest`
    message

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x76)
        hated_interest: str = field(metadata={'type': string})


class RoomSearch(ServerMessage):
    """Perform a search query on all users in the given room, this can only be
    performed if the room was joined first. The server will send a
    :ref:`FileSearch` to every user in the requested room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x78)
        room: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class SendUploadSpeed(ServerMessage):
    """Sent to the server right after an upload completed. ``speed`` parameter
    should be in bytes per second. This should not be the global average upload
    speed but rather the upload speed for that particular transfer. After this
    message has been sent the server will recalculate the average speed and
    increase the amount of uploads for your user.

    In exception cases, for example if a transfer was failed midway then
    resumed, only the speed of the resumed part is taken into account. However
    this might be client dependent.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x79)
        speed: int = field(metadata={'type': uint32})


class GetUserPrivileges(ServerMessage):
    """Retrieve whether a user has privileges

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7A)
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7A)
        username: str = field(metadata={'type': string})
        privileged: bool = field(metadata={'type': boolean})


class GiveUserPrivileges(ServerMessage):
    """Gift a user privileges. This only works if the user sending the message
    has privileges and needs to be less than what the gifting user has left,
    part of its privileges will be taken

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7B)
        username: str = field(metadata={'type': string})
        days: int = field(metadata={'type': uint32})


class PrivilegesNotification(ServerMessage):

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7C)
        notification_id: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})


class PrivilegesNotificationAck(ServerMessage):

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7D)
        notification_id: int = field(metadata={'type': uint32})


class BranchLevel(ServerMessage):
    """Notify the server which branch level we are at in the distributed network

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7E)
        level: int = field(metadata={'type': uint32})


class BranchRoot(ServerMessage):
    """Notify the server who our branch root user is in the distributed network

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x7F)
        username: str = field(metadata={'type': string})


class ChildDepth(ServerMessage):
    """See :ref:`DistributedChildDepth`

    .. note::

        SoulSeekQt sends the ``depth`` as a ``uint8``

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x81)
        depth: int = field(metadata={'type': uint32})


class ResetDistributed(ServerMessage):
    """Server requests to reset our parent and children

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x82)


class PrivateRoomMembers(ServerMessage):
    """List of all members that are part of the private room (excludes owner)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x85)
        room: str = field(metadata={'type': string})
        usernames: list[str] = field(metadata={'type': array, 'subtype': string})


class PrivateRoomGrantMembership(ServerMessage):
    """Add another user to the private room. Only operators and the owner can
    add members to a private room.

    This message is also received by all other members in the private room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x86)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x86)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomRevokeMembership(ServerMessage):
    """Remove another user from the private room. Operators can remove regular
    members but not other operators or the owner. The owner can remove anyone
    aside from himself (see :ref:`PrivateRoomDropOwnership`).

    This message is also received by all other members in the private room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x87)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x87)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomDropMembership(ServerMessage):
    """Drops membership of a private room, this will not do anything for the
    owner of the room. See :ref:`PrivateRoomDropOwnership` for owners

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x88)
        room: str = field(metadata={'type': string})


class PrivateRoomDropOwnership(ServerMessage):
    """Drops ownership of a private room, this disbands the entire room.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x89)
        room: str = field(metadata={'type': string})


class PrivateRoomMembershipGranted(ServerMessage):
    """Received when the current user has been granted membership to a private
    room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8B)
        room: str = field(metadata={'type': string})


class PrivateRoomMembershipRevoked(ServerMessage):
    """Received when the current user had its membership revoked from a private
    room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8C)
        room: str = field(metadata={'type': string})


class TogglePrivateRoomInvites(ServerMessage):
    """Enables or disables private room invites (through
    :ref:`PrivateRoomGrantMembership`)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8D)
        enable: bool = field(metadata={'type': boolean})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8D)
        enabled: bool = field(metadata={'type': boolean})


class NewPassword(ServerMessage):
    """Modifies the user's password

    :status: USED"""

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8E)
        password: str = field(metadata={'type': string})


class PrivateRoomGrantOperator(ServerMessage):
    """Grant operator privileges to a member in a private room. This message
    will also be received by all other members in the room (irrelevant of if
    they are online or not)

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8F)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x8F)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomRevokeOperator(ServerMessage):
    """Revoke operator privileges from a member in a private room. This message
    will also be received by all other members in the room (irrelevant of if
    they are online or not).

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x90)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x90)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})


class PrivateRoomOperatorGranted(ServerMessage):
    """Received when granted operator privileges in a private room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x91)
        room: str = field(metadata={'type': string})


class PrivateRoomOperatorRevoked(ServerMessage):
    """Received when operator privileges in a private room were revoked

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x92)
        room: str = field(metadata={'type': string})


class PrivateRoomOperators(ServerMessage):
    """List of operators for a private room

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x94)
        room: str = field(metadata={'type': string})
        usernames: list[str] = field(metadata={'type': array, 'subtype': string})


class PrivateChatMessageUsers(ServerMessage):
    """Send a private message to a list of users. This message will only be
    received by users who have added you using the :ref:`AddUser` message first

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x95)
        usernames: list[str] = field(metadata={'type': array, 'subtype': string})
        message: str = field(metadata={'type': string})


class EnablePublicChat(ServerMessage):
    """Enables public chat, see :ref:`PublicChatMessage`

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x96)


class DisablePublicChat(ServerMessage):
    """Disables public chat, see :ref:`PublicChatMessage`

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x97)


class PublicChatMessage(ServerMessage):
    """When public chat is enabled all messages sent to public rooms will also
    be sent to us using this message. Use :ref:`EnablePublicChat` and
    :ref:`DisablePublicChat` to disable or enable receiving these messages.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x98)
        room: str = field(metadata={'type': string})
        username: str = field(metadata={'type': string})
        message: str = field(metadata={'type': string})


class GetRelatedSearches(ServerMessage):
    """Usually this is sent by the client right after the :ref:`FileSearch`
    message using the same `query` to retrieve the related searches for that
    query

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x99)
        query: str = field(metadata={'type': string})
        related_searches: list[str] = field(metadata={'type': array, 'subtype': string})


class ExcludedSearchPhrases(ServerMessage):
    """Optionally sent by the server after logging on. Search results containing
    at least one of the phrases (exact match, case insensitive) should be
    filtered out before being sent.

    It is highly recommended to take this filtering into account as not doing so
    could jeopardize the network

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0xA0)
        phrases: list[str] = field(metadata={'type': array, 'subtype': string})


class CannotConnect(ServerMessage):
    """Send to the server if we failed to connect to a peer after a
    :ref:`ConnectToPeer`

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03E9)
        ticket: int = field(metadata={'type': uint32})
        username: Optional[str] = field(default=None, metadata={'type': string, 'optional': True})

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03E9)
        ticket: int = field(metadata={'type': uint32})
        username: Optional[str] = field(default=None, metadata={'type': string, 'optional': True})


class CannotCreateRoom(ServerMessage):
    """Sent by the server when attempting to create/join a private room which
    already exists or the user is not part of

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Response(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x03EB)
        room: str = field(metadata={'type': string})


# Peer Initialization messages

class PeerPierceFirewall(PeerInitializationMessage):
    """Sent after connection was successfully established in response to a
    :ref:`ConnectToPeer` message. The ``ticket`` used here should be the ticket
    from that :ref:`ConnectToPeer` message

    :status: USED
    """

    @dataclass(order=True, slots=True)
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
    """Sent after direct connection was successfully established (not as a
    response to a :ref:`ConnectToPeer` received from the server)

    The ``ticket`` is usually 0 and was filled in with ``ticket`` value from
    the :ref:`SendConnectTicket` message by older versions of the client

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x01)
        username: str = field(metadata={'type': string})
        typ: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': _PeerInitTicket})


# Peer messages

class PeerSharesRequest(PeerMessage):
    """Request all shared files/directories from a peer

    :status: USED
    """

    @dataclass(order=True, slots=True)
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
    """Response to PeerSharesRequest. The response should include empty parent
    directories.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x05)
        directories: list[DirectoryData] = field(
            metadata={'type': array, 'subtype': DirectoryData}
        )
        # Unknown field that always seems to be 0, possibilities:
        # * This was another list, but it always empty (not tested)
        # * This is a ticket: See explanation of ticket in PeerSharesRequest
        unknown: int = field(default=0, metadata={'type': uint32})
        locked_directories: Optional[list[DirectoryData]] = field(
            default=None,
            metadata={'type': array, 'subtype': DirectoryData, 'optional': True}
        )

        def serialize(self, compress: bool = True) -> bytes:
            return super(type(self), self).serialize(compress)

        @classmethod
        def deserialize(cls, pos: int, message: bytes, decompress: bool = True):
            return super(cls, cls).deserialize(pos, message, decompress)


class PeerSearchReply(PeerMessage):
    """Response to a search request

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x09)
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        results: list[FileData] = field(metadata={'type': array, 'subtype': FileData})
        has_slots_free: bool = field(metadata={'type': boolean})
        avg_speed: int = field(metadata={'type': uint32})
        # Note: queue_size and unknown. queue_size is described as uint64 in the
        # museek documentation. However I believe that this is actually just a
        # uint32. The other 4 bytes are for an unknown uint32 right before the
        # locked results: the same can be seen in PeerSharesReply
        queue_size: int = field(metadata={'type': uint32})
        unknown: Optional[int] = field(default=0, metadata={'type': uint32})
        locked_results: Optional[list[FileData]] = field(
            default=None,
            metadata={'type': array, 'subtype': FileData, 'optional': True}
        )

        def serialize(self, compress: bool = True) -> bytes:
            return super(type(self), self).serialize(compress)

        @classmethod
        def deserialize(cls, pos: int,  message: bytes, decompress: bool = True):
            return super(cls, cls).deserialize(pos, message, decompress)


class PeerUserInfoRequest(PeerMessage):
    """Request information from the peer

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x0F)


class PeerUserInfoReply(PeerMessage):
    """Response to :ref:`PeerUserInfoRequest`. Possible values for
    ``upload_permissions`` can be found :ref:`here <table-upload-permissions>`

    :status: USED
    """

    @dataclass(order=True, slots=True)
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
    """Request the contents of a directory

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x24)
        ticket: int = field(metadata={'type': uint32})
        directory: str = field(metadata={'type': string})


class PeerDirectoryContentsReply(PeerMessage):
    """Reply to :ref:`PeerDirectoryContentsRequest`.

    Although the returned directories is an array it will only contain one
    element and will not list files from subdirectories

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x25)
        ticket: int = field(metadata={'type': uint32})
        directory: str = field(metadata={'type': string})
        directories: list[DirectoryData] = field(metadata={'type': array, 'subtype': DirectoryData})

        def serialize(self, compress: bool = True) -> bytes:
            return super(type(self), self).serialize(compress)

        @classmethod
        def deserialize(cls, pos: int, message: bytes, decompress: bool = True):
            return super(cls, cls).deserialize(pos, message, decompress)


class PeerTransferRequest(PeerMessage):
    """``filesize`` can be omitted if the direction==1 however a value of ``0``
    can be used in this case as well

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x28)
        direction: int = field(metadata={'type': uint32})
        ticket: int = field(metadata={'type': uint32})
        filename: str = field(metadata={'type': string})
        filesize: Optional[int] = field(default=None, metadata={'type': uint64, 'optional': True})


class PeerTransferReply(PeerMessage):
    """Response message to :ref:`PeerTransferRequest`

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x29)
        ticket: int = field(metadata={'type': uint32})
        allowed: bool = field(metadata={'type': boolean})
        filesize: Optional[int] = field(default=None, metadata={'type': uint64, 'optional': True, 'if_true': 'allowed'})
        reason: Optional[str] = field(default=None, metadata={'type': string, 'optional': True, 'if_false': 'allowed'})


class PeerTransferQueue(PeerMessage):
    """Request to place the provided transfer of ``filename`` in the queue

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2B)
        filename: str = field(metadata={'type': string})


class PeerPlaceInQueueReply(PeerMessage):
    """Response to :ref:`PeerPlaceInQueueRequest`

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2C)
        filename: str = field(metadata={'type': string})
        place: int = field(metadata={'type': uint32})


class PeerUploadFailed(PeerMessage):
    """Sent when uploading failed

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x2E)
        filename: str = field(metadata={'type': string})


class PeerTransferQueueFailed(PeerMessage):
    """Sent when placing the transfer in queue failed

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x32)
        filename: str = field(metadata={'type': string})
        reason: str = field(metadata={'type': string})


class PeerPlaceInQueueRequest(PeerMessage):
    """Request the place of the transfer in the queue.

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x33)
        filename: str = field(metadata={'type': string})


class PeerUploadQueueNotification(PeerMessage):
    """Deprecated message

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x34)


# Distributed messages

class DistributedPing(DistributedMessage):
    """Ping request from the parent. Most clients do not send this.

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x00)


class DistributedInit(DistributedMessage):
    """Deprecated distributed network related message

    :status: DEPRECATED, DEFUNCT
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x01)
        unknown1: int = field(metadata={'type': uint32})
        unknown2: int = field(metadata={'type': uint32})
        unknown3: str = field(metadata={'type': uint8})
        port: int = field(metadata={'type': uint32})


class DistributedSearchRequest(DistributedMessage):
    """Search request coming from the parent

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x03)
        # Should always be 0x31
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})


class DistributedBranchLevel(DistributedMessage):
    """Distributed branch level

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x04)
        level: int = field(metadata={'type': uint32})


class DistributedBranchRoot(DistributedMessage):
    """Distributed branch root

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint8] = uint8(0x05)
        username: str = field(metadata={'type': string})


class DistributedChildDepth(DistributedMessage):
    """Used by SoulSeek NS and still passed on by SoulSeekQt, sent to the
    parent upon connecting to that parent (although unclear what happens when
    a peer attaches to another parent while already having children). The parent
    should increase the ``depth`` by 1 until it reaches the branch root, which
    should increase by 1 and send it to the server as a :ref:`ChildDepth`
    message.

    :status: DEPRECATED
    """

    @dataclass(order=True, slots=True)
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

    :status: USED
    """

    @dataclass(order=True, slots=True)
    class Request(MessageDataclass):
        MESSAGE_ID: ClassVar[uint32] = uint32(0x5D)
        distributed_code: int = field(metadata={'type': uint8})
        unknown: int = field(metadata={'type': uint32})
        username: str = field(metadata={'type': string})
        ticket: int = field(metadata={'type': uint32})
        query: str = field(metadata={'type': string})
