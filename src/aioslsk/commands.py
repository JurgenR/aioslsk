from __future__ import annotations
from abc import ABC, abstractmethod
import time
from typing import Generic, List, Optional, TypeVar, Union, Tuple, TYPE_CHECKING

from .exceptions import NoSuchUserError
from .protocol.messages import (
    AddHatedInterest,
    AddInterest,
    AddUser,
    CheckPrivileges,
    DisablePublicChat,
    EnablePublicChat,
    FileSearch,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetPeerAddress,
    GetRecommendations,
    GetSimilarUsers,
    GetUserInterests,
    GetUserStats,
    GetUserStatus,
    GiveUserPrivileges,
    JoinRoom,
    LeaveRoom,
    NewPassword,
    PeerDirectoryContentsReply,
    PeerDirectoryContentsRequest,
    PeerSharesReply,
    PeerSharesRequest,
    PeerUserInfoReply,
    PeerUserInfoRequest,
    PrivateChatMessage,
    PrivateChatMessageUsers,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
    PrivateRoomGrantMembership,
    PrivateRoomGrantOperator,
    PrivateRoomMembershipRevoked,
    PrivateRoomRevokeMembership,
    PrivateRoomRevokeOperator,
    RemoveHatedInterest,
    RemoveInterest,
    RoomChatMessage,
    RoomList,
    RoomSearch,
    RoomTickerAdded,
    SetRoomTicker,
    SetStatus,
    TogglePrivateRoomInvites,
    UserSearch,
)
from .protocol.primitives import (
    DirectoryData,
    Recommendation,
    MessageDataclass,
    UserStats
)
from .network.network import ExpectedResponse
from .network.connection import PeerConnection, ServerConnection
from .user.model import User, UserStatus
from .room.model import Room, RoomMessage

if TYPE_CHECKING:
    from .client import SoulSeekClient


RC = TypeVar('RC', bound=Union[MessageDataclass, None])
"""Response class type"""
RT = TypeVar('RT')
"""Response value type"""

Recommendations = Tuple[List[Recommendation], List[Recommendation]]
UserInterests = Tuple[List[str], List[str]]


class BaseCommand(ABC, Generic[RC, RT]):

    def __init__(self):
        self.response_future: Optional[ExpectedResponse] = None

    @abstractmethod
    async def send(self, client: SoulSeekClient):
        ...

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


class JoinRoomCommand(BaseCommand[JoinRoom.Response, Room]):

    def __init__(self, room: str, private: bool = False):
        super().__init__()
        self.room: str = room
        self.private: bool = private

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            JoinRoom.Request(self.room, is_private=self.private)
        )

    def response(self) -> 'JoinRoomCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            JoinRoom.Response,
            fields={
                'room': self.room
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: JoinRoom.Response) -> Room:
        return client.rooms.get_or_create_room(response.room)


class LeaveRoomCommand(BaseCommand[LeaveRoom.Response, Room]):

    def __init__(self, room: str):
        super().__init__()
        self.room: str = room

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            LeaveRoom.Request(self.room)
        )

    def response(self) -> 'LeaveRoomCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            LeaveRoom.Response,
            fields={
                'room': self.room
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: LeaveRoom.Response) -> Room:
        return client.rooms.get_or_create_room(response.room)


class GrantRoomMembershipCommand(BaseCommand[PrivateRoomGrantMembership.Response, Tuple[Room, User]]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomGrantMembership.Request(self.room, self.username)
        )

    def response(self) -> 'GrantRoomMembershipCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomGrantMembership.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomGrantMembership.Response) -> Tuple[Room, User]:
        return (
            client.rooms.get_or_create_room(response.room),
            client.users.get_or_create_user(response.username)
        )


class RevokeRoomMembershipCommand(BaseCommand[PrivateRoomRevokeMembership.Response, Tuple[Room, User]]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomRevokeMembership.Request(self.room, self.username)
        )

    def response(self) -> 'RevokeRoomMembershipCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomRevokeMembership.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomRevokeMembership.Response) -> Tuple[Room, User]:
        return (
            client.rooms.get_or_create_room(response.room),
            client.users.get_or_create_user(response.username)
        )


class DropRoomMembershipCommand(BaseCommand[PrivateRoomMembershipRevoked.Response, Room]):

    def __init__(self, room: str):
        super().__init__()
        self.room: str = room
        self._username: Optional[str] = None

    async def send(self, client: SoulSeekClient):
        self._username = client.session.user.name
        await client.network.send_server_messages(
            PrivateRoomDropMembership.Request(self.room)
        )

    def response(self) -> 'DropRoomMembershipCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomMembershipRevoked.Response,
            fields={
                'room': self.room,
                'username': self._username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomMembershipRevoked.Response) -> Room:
        return client.rooms.get_or_create_room(response.room)


class DropRoomOwnershipCommand(BaseCommand[None, None]):

    def __init__(self, room: str):
        super().__init__()
        self.room: str = room

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomDropOwnership.Request(self.room)
        )


class GetItemRecommendationsCommand(BaseCommand[GetItemRecommendations.Response, List[Recommendation]]):

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

    def process_response(self, client: SoulSeekClient, response: GetItemRecommendations.Response) -> List[Recommendation]:
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
        return list(map(client.users.get_or_create_user, response.usernames))


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


class GrantRoomOperatorCommand(BaseCommand[PrivateRoomGrantOperator.Response, None]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomGrantOperator.Request(self.room, self.username)
        )

    def response(self) -> 'GrantRoomOperatorCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomGrantOperator.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomGrantOperator.Response) -> None:
        return None


class RevokeRoomOperatorCommand(BaseCommand[PrivateRoomRevokeOperator.Response, None]):

    def __init__(self, room: str, username: str):
        super().__init__()
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomRevokeOperator.Request(self.room, self.username)
        )

    def response(self) -> 'RevokeRoomOperatorCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            PrivateRoomRevokeOperator.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PrivateRoomRevokeOperator.Response) -> None:
        return None


class TogglePublicChatCommand(BaseCommand[None, None]):

    def __init__(self, enable: bool):
        super().__init__()
        self.enable: bool = enable

    async def send(self, client: SoulSeekClient):
        if self.enable:
            message = EnablePublicChat.Request()
        else:
            message = DisablePublicChat.Request()
        await client.network.send_server_messages(message)


class TogglePrivateRoomInvitesCommand(BaseCommand[TogglePrivateRoomInvites.Response, None]):

    def __init__(self, enable: bool):
        super().__init__()
        self.enable: bool = enable

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            TogglePrivateRoomInvites.Request(self.enable)
        )

    def response(self) -> 'TogglePrivateRoomInvitesCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            TogglePrivateRoomInvites.Response,
            fields={
                'enabled': self.enable
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: TogglePrivateRoomInvites.Response) -> None:
        return None


class GlobalSearchCommand(BaseCommand[None, None]):

    def __init__(self, query: str):
        super().__init__()
        self.query: str = query

    async def send(self, client: SoulSeekClient):
        ticket = next(client._ticket_generator)
        await client.network.send_server_messages(
            FileSearch.Request(
                ticket,
                query=self.query
            )
        )


class UserSearchCommand(BaseCommand[None, None]):

    def __init__(self, username: str, query: str):
        super().__init__()
        self.username: str = username
        self.query: str = query

    async def send(self, client: SoulSeekClient):
        ticket = next(client._ticket_generator)
        await client.network.send_server_messages(
            UserSearch.Request(
                self.username,
                ticket,
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
            PrivateChatMessage.Request(
                self.username,
                self.message
            )
        )


class PrivateMessageUsersCommand(BaseCommand[None, None]):
    """Sends a private message to multiple users"""

    def __init__(self, usernames: List[str], message: str):
        super().__init__()
        self.usernames: str = usernames
        self.message: str = message

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateChatMessageUsers.Request(
                self.usernames,
                self.message
            )
        )


class RoomMessageCommand(BaseCommand[RoomChatMessage.Response, RoomMessage]):

    def __init__(self, room: str, message: str):
        super().__init__()
        self.room: str = room
        self.message: str = message
        self._username: Optional[str] = None

    async def send(self, client: SoulSeekClient):
        self._username = client.session.user.name
        await client.network.send_server_messages(
            RoomChatMessage.Request(
                self.room,
                self.message
            )
        )

    def response(self) -> 'RoomMessageCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            RoomChatMessage.Response,
            fields={
                'room': self.room,
                'username': self._username,
                'message': self.message
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: RoomChatMessage.Response) -> RoomMessage:
        return RoomMessage(
            timestamp=int(time.time()),
            user=client.users.get_or_create_user(self._username),
            room=client.rooms.get_or_create_room(self.room),
            message=self.message
        )


class SetRoomTickerCommand(BaseCommand[RoomTickerAdded, None]):

    def __init__(self, room: str, ticker: str):
        super().__init__()
        self.room: str = room
        self.ticker: str = ticker
        self._username: Optional[str] = None

    async def send(self, client: SoulSeekClient):
        self._username = client.session.user.name
        await client.network.send_server_messages(
            SetRoomTicker.Request(
                self.room,
                self.ticker
            )
        )

    def response(self) -> 'SetRoomTickerCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            RoomTickerAdded.Response,
            fields={
                'room': self.room,
                'username': self._username,
                'ticker': self.ticker
            }
        )
        return self


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


class GetUserInterestsCommand(BaseCommand[GetUserInterests.Response, UserInterests]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetUserInterests.Request(self.username)
        )

    def response(self) -> 'GetUserInterestsCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            GetUserInterests.Response,
            fields={
                'username': self.username,
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: GetUserInterests.Response) -> UserInterests:
        return response.interests, response.hated_interests


class SetStatusCommand(BaseCommand[None, None]):

    def __init__(self, status: UserStatus):
        super().__init__()
        self.status: UserStatus = status

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            SetStatus.Request(self.status.value)
        )


class SetNewPasswordCommand(BaseCommand[None, None]):

    def __init__(self, password: str):
        super().__init__()
        self.password: str = password

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            NewPassword.Request(self.password)
        )


class CheckPrivilegesCommand(BaseCommand[CheckPrivileges.Response, int]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(CheckPrivileges.Request())

    def response(self) -> 'CheckPrivilegesCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            CheckPrivileges.Response
        )

    def process_response(self, client: SoulSeekClient, response: CheckPrivileges.Response) -> int:
        return response.time_left


class GivePrivilegesCommand(BaseCommand[None, None]):

    def __init__(self, username: str, days: int):
        super().__init__()
        self.username: str = username
        self.days: int = days

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GiveUserPrivileges.Request(
                username=self.username,
                days=self.days
            )
        )


class AddUserCommand(BaseCommand[AddUser.Response, User]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            AddUser.Request(username=self.username)
        )

    def response(self) -> 'AddUserCommand':
        self.response_future = ExpectedResponse(
            ServerConnection,
            AddUser.Response,
            fields={
                'username': self.username
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: AddUser.Response) -> User:
        if response.exists:
            user = client.users.get_or_create_user(response.username)
            return user
        else:
            raise NoSuchUserError(
                f"user {self.username!r} does not exist on the server")


class PeerGetUserInfoCommand(BaseCommand[PeerUserInfoReply.Request, User]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_peer_messages(
            self.username, PeerUserInfoRequest.Request()
        )

    def response(self) -> 'PeerGetUserInfoCommand':
        self.response_future = ExpectedResponse(
            PeerConnection,
            PeerUserInfoReply.Request,
            peer=self.username
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PeerUserInfoReply.Request) -> User:
        return client.users.get_or_create_user(self.username)


class PeerGetSharesCommand(BaseCommand[PeerSharesReply.Request, Tuple[List[DirectoryData], List[DirectoryData]]]):

    def __init__(self, username: str):
        super().__init__()
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_peer_messages(
            self.username, PeerSharesRequest.Request()
        )

    def response(self) -> 'PeerGetSharesCommand':
        self.response_future = ExpectedResponse(
            PeerConnection,
            PeerSharesReply.Request,
            peer=self.username
        )
        return self

    def process_response(
            self, client: SoulSeekClient, response: PeerSharesReply.Request) -> Tuple[List[DirectoryData], List[DirectoryData]]:
        locked_dirs = response.locked_directories or []
        return response.directories, locked_dirs


class PeerGetDirectoryContentCommand(BaseCommand[PeerDirectoryContentsReply.Request, List[DirectoryData]]):

    def __init__(self, username: str, directory: str):
        super().__init__()
        self.username: str = username
        self.directory: str = directory
        self._ticket: Optional[int] = None

    async def send(self, client: SoulSeekClient):
        self._ticket = next(client._ticket_generator)
        await client.network.send_peer_messages(
            self.username, PeerDirectoryContentsRequest.Request(self._ticket, self.directory)
        )

    def response(self) -> 'PeerGetDirectoryContentCommand':
        self.response_future = ExpectedResponse(
            PeerConnection,
            PeerDirectoryContentsReply.Request,
            peer=self.username,
            fields={
                'ticket': self._ticket,
                'directory': self.directory
            }
        )
        return self

    def process_response(self, client: SoulSeekClient, response: PeerDirectoryContentsReply.Request) -> List[DirectoryData]:
        return response.directories
