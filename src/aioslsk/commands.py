from __future__ import annotations
from abc import ABC, abstractmethod
import time
from typing import Generic, List, Optional, TypeVar, Union, Tuple, TYPE_CHECKING

from .exceptions import AuthenticationError
from .protocol.messages import (
    AddHatedInterest,
    AddInterest,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatPrivateMessage,
    ChatRoomMessage,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetPeerAddress,
    GetRecommendations,
    GetSimilarUsers,
    GetUserStats,
    GetUserStatus,
    Login,
    PrivateRoomAddOperator,
    PrivateRoomRemoveOperator,
    PrivateRoomAddUser,
    PrivateRoomRemoveUser,
    PrivateRoomRemoved,
    PrivateRoomDropMembership,
    RemoveHatedInterest,
    RemoveInterest,
    RoomList,
    RoomSearch,
    SetStatus,
    TogglePrivateRooms,
    UserSearch,
)
from .protocol.primitives import calc_md5, ItemRecommendation, MessageDataclass, UserStats
from .network.network import ExpectedResponse
from .network.connection import ServerConnection
from .user.model import User, UserStatus
from .room.model import Room, RoomMessage

if TYPE_CHECKING:
    from .client import SoulSeekClient


RC = TypeVar('RC', bound=Union[MessageDataclass, None])
"""Response class type"""
RT = TypeVar('RT')
"""Response value type"""

Recommendations = Tuple[List[ItemRecommendation], List[ItemRecommendation]]
LoginValues = Tuple[str, str, bool]
"""Values returned on successful login: greeting, IP address, privileged, """


class BaseCommand(ABC, Generic[RC, RT]):

    def __init__(self):
        self.response_future: Optional[ExpectedResponse] = None

    @abstractmethod
    def send(self, client: SoulSeekClient):
        pass

    def response(self) -> 'BaseCommand':
        return self

    def process_response(self, client: SoulSeekClient, response: RC) -> Optional[RT]:
        return None


class GetUserStatusCommand(BaseCommand[GetUserStatus.Response, UserStatus]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetUserStatus.Request(self.username)
        )

    def response(self) -> 'GetUserStatusCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetUserStatus.Response,
            fields={
                'username': self.username
            }
        )
        return self

    def process_response(
            self, client: SoulSeekClient, response: GetUserStatus.Response) -> UserStatus:
        return UserStatus(response.status)


class GetUserStatsCommand(BaseCommand[GetUserStats.Response, UserStats]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetUserStats.Request(self.username)
        )

    def response(self) -> 'GetUserStatsCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetUserStats.Response,
            fields={
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetUserStats.Response) -> UserStats:
        return response.user_stats


class GetRoomListCommand(BaseCommand[RoomList.Response, List[Room]]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RoomList.Request()
        )

    def response(self) -> 'GetRoomListCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            RoomList.Response
        )
        return self

    def process_response(self, client: SoulSeekClient, response: RoomList.Response) -> List[Room]:
        return [
            room for name, room in client.rooms.rooms.items()
            if name in response.rooms
        ]


class JoinRoomCommand(BaseCommand[ChatJoinRoom.Response, Room]):

    def __init__(self, room: str, private: bool = False):
        super().__init__()
        self.room: str = room
        self.private: bool = private

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            ChatJoinRoom.Request(self.room, is_private=self.private)
        )

    def response(self) -> 'JoinRoomCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            ChatJoinRoom.Response,
            fields={
                'room': self.room
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: ChatJoinRoom.Response) -> Room:
        return client.rooms.get_or_create_room(response.room)


class LeaveRoomCommand(BaseCommand[ChatLeaveRoom.Response, Room]):

    def __init__(self, room: str):
        super().__init__()
        self.room: str = room

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            ChatLeaveRoom.Request(self.room)
        )

    def response(self) -> 'LeaveRoomCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            ChatLeaveRoom.Response,
            fields={
                'room': self.room
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: ChatLeaveRoom.Response) -> Room:
        return client.rooms.get_or_create_room(response.room)


class GrantRoomMembershipCommand(BaseCommand[PrivateRoomAddUser.Response, Tuple[Room, User]]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomAddUser.Request(self.room, self.username)
        )

    def response(self) -> 'GrantRoomMembershipCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomAddUser.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomAddUser.Response) -> Tuple[Room, User]:
        return (
            client.rooms.get_or_create_room(response.room),
            client.users.get_or_create_user(response.username)
        )


class RevokeRoomMembershipCommand(BaseCommand[PrivateRoomRemoveUser.Response, Tuple[Room, User]]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomRemoveUser.Request(self.room, self.username)
        )

    def response(self) -> 'RevokeRoomMembershipCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomRemoveUser.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomRemoveUser.Response) -> Tuple[Room, User]:
        return (
            client.rooms.get_or_create_room(response.room),
            client.users.get_or_create_user(response.username)
        )


class DropRoomMembershipCommand(BaseCommand[PrivateRoomRemoved.Response, Room]):

    def __init__(self, room: str):
        super().__init__()
        self.room: str = room
        self._username: Optional[str] = None

    async def send(self, client: SoulSeekClient):
        self._username = client.settings.credentials.username
        await client.network.send_server_messages(
            PrivateRoomDropMembership.Request(self.room)
        )

    def response(self) -> 'DropRoomMembershipCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomRemoved.Response,
            fields={
                'room': self.room,
                'username': self._username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomRemoved.Response) -> Room:
        return client.rooms.get_or_create_room(response.room)


class GetItemRecommendationsCommand(BaseCommand[GetItemRecommendations.Response, List[ItemRecommendation]]):

    def __init__(self, item: str):
        super().__init__()
        self.item: str = item

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetItemRecommendations.Request(self.item)
        )

    def response(self) -> 'GetItemRecommendationsCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetItemRecommendations.Response,
            fields={
                'item': self.item
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetItemRecommendations.Response) -> List[ItemRecommendation]:
        return response.recommendations


class GetRecommendationsCommand(BaseCommand[GetRecommendations.Response, Recommendations]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetRecommendations.Request()
        )

    def response(self) -> 'GetRecommendationsCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetRecommendations.Response
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetRecommendations.Response) -> Recommendations:
        return response.recommendations, response.unrecommendations


class GetGlobalRecommendationsCommand(BaseCommand[GetGlobalRecommendations.Response, Recommendations]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetGlobalRecommendations.Request()
        )

    def response(self) -> 'GetGlobalRecommendationsCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetGlobalRecommendations.Response
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetGlobalRecommendations.Response) -> Recommendations:
        return response.recommendations, response.unrecommendations


class GetItemSimilarUsersCommand(BaseCommand[GetItemSimilarUsers.Response, List[User]]):

    def __init__(self, item: str):
        super().__init__()
        self.item: str = item

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetItemSimilarUsers.Request(self.item)
        )

    def response(self) -> 'GetItemSimilarUsersCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetItemSimilarUsers.Response,
            fields={
                'item': self.item
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetItemSimilarUsers.Response) -> List[User]:
        return list(map(client.users.get_or_create_user, response.users))


class GetSimilarUsersCommand(BaseCommand[GetSimilarUsers.Response, List[User]]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetSimilarUsers.Request()
        )

    def response(self) -> 'GetSimilarUsersCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetSimilarUsers.Response
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetSimilarUsers.Response) -> List[User]:
        return [
            client.users.get_or_create_user(user.username)
            for user in response.users
        ]


class GetPeerAddressCommand(BaseCommand[GetPeerAddress.Response, Tuple[str, int, int]]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetPeerAddress.Request(self.username)
        )

    def response(self) -> 'GetPeerAddressCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetPeerAddress.Response,
            fields={
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetPeerAddress.Response) -> Tuple[str, int, int]:
        return (response.ip, response.port, response.obfuscated_port)



class GrantRoomOperatorCommand(BaseCommand[PrivateRoomAddOperator.Response, None]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomAddOperator.Request(self.room, self.username)
        )

    def response(self) -> 'GrantRoomOperatorCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomAddOperator.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomAddOperator.Response) -> None:
        return None


class RevokeRoomOperatorCommand(BaseCommand[PrivateRoomRemoveOperator.Response, None]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomRemoveOperator.Request(self.room, self.username)
        )

    def response(self) -> 'RevokeRoomOperatorCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomRemoveOperator.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomRemoveOperator.Response) -> None:
        return None


class TogglePrivateRoomsCommand(BaseCommand[TogglePrivateRooms.Response, None]):

    def __init__(self, enable: bool):
        super().__init__()
        self.enable: bool = enable

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            TogglePrivateRooms.Request(self.enable)
        )

    def response(self) -> 'TogglePrivateRoomsCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            TogglePrivateRooms.Response,
            fields={
                'enabled': self.enable
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: TogglePrivateRooms.Response) -> None:
        return None


class UserSearchCommand(BaseCommand[None, None]):

    def __init__(self, username: str, query: str):
        super().__init__()
        self.username: str = username
        self.query: str = query

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            UserSearch.Request(
                self.username,
                next(client._ticket_generator),
                self.query
            )
        )


class RoomSearchCommand(BaseCommand[None, None]):

    def __init__(self, room: str, query: str):
        super().__init__()
        self.room: str = room
        self.query: str = query

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RoomSearch.Request(
                self.room,
                next(client._ticket_generator),
                self.query
            )
        )


class PrivateMessageCommand(BaseCommand[None, None]):

    def __init__(self, username: str, message: str):
        super().__init__()
        self.username: str = username
        self.message: str = message

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            ChatPrivateMessage.Request(
                self.username,
                self.message
            )
        )


class RoomMessageCommand(BaseCommand[ChatRoomMessage.Response, RoomMessage]):

    def __init__(self, room: str, message: str):
        super().__init__()
        self.room: str = room
        self.message: str = message
        self._username: Optional[str] = None

    async def send(self, client: SoulSeekClient):
        self._username = client.settings.credentials.username
        await client.network.send_server_messages(
            ChatRoomMessage.Request(
                self.room,
                self.message
            )
        )

    def response(self) -> 'RoomMessageCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            ChatRoomMessage.Response,
            fields={
                'room': self.room,
                'username': self._username,
                'message': self.message
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: ChatRoomMessage.Response) -> RoomMessage:
        return RoomMessage(
            timestamp=int(time.time()),
            user=client.users.get_or_create_user(self._username),
            room=client.rooms.get_or_create_room(self.room),
            message=self.message
        )


class AddInterestCommand(BaseCommand[None, None]):

    def __init__(self, interest: str):
        super().__init__()
        self.interest: str = interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            AddInterest.Request(self.interest)
        )


class AddHatedInterestCommand(BaseCommand[None, None]):

    def __init__(self, hated_interest: str):
        super().__init__()
        self.hated_interest: str = hated_interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            AddHatedInterest.Request(self.hated_interest)
        )


class RemoveInterestCommand(BaseCommand[None, None]):

    def __init__(self, interest: str):
        super().__init__()
        self.interest: str = interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RemoveInterest.Request(self.interest)
        )


class RemoveHatedInterestCommand(BaseCommand[None, None]):

    def __init__(self, hated_interest: str):
        super().__init__()
        self.hated_interest: str = hated_interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RemoveHatedInterest.Request(self.hated_interest)
        )


class SetStatusCommand(BaseCommand[None, None]):

    def __init__(self, status: UserStatus):
        super().__init__()
        self.status: UserStatus = status

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            SetStatus.Request(self.status.value)
        )


class LoginCommand(BaseCommand[Login.Response, LoginValues]):

    def __init__(self, username: str, password: str, client_version: int = 157, minor_version: int = 100):
        super().__init__()
        self.username: str = username
        self.password: str = password
        self.client_version: int = client_version
        self.minor_version: int = minor_version

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            Login.Request(
                username=self.username,
                password=self.password,
                client_version=self.client_version,
                md5hash=calc_md5(self.username + self.password),
                minor_version=self.minor_version
            )
        )

    def response(self) -> 'LoginCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            Login.Response
        )
        return self

    def process_response(self, client: SoulSeekClient, response: Login.Response) -> LoginValues:
        if response.success:
            return (response.greeting, response.ip, response.privileged)
        else:
            raise AuthenticationError(
                response.reason, f"failed to login with username {self.username!r}")
