from __future__ import annotations
from abc import ABC, abstractmethod
import time
from typing import (
    Generic,
    NamedTuple,
    Optional,
    Union,
    TypeVar,
    TYPE_CHECKING,
)

from .exceptions import InvalidSessionError, NoSuchUserError
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
from .protocol.primitives import DirectoryData, Recommendation, MessageDataclass
from .network.network import ExpectedResponse
from .network.connection import PeerConnection, ServerConnection
from .room.model import Room, RoomMessage
from .user.model import User, UserStatus, TrackingFlag, UploadPermissions
from .search.model import SearchRequest, SearchType


if TYPE_CHECKING:
    from .client import SoulSeekClient


RC = TypeVar('RC', bound=Union[MessageDataclass, None])
"""Response class type"""
RT = TypeVar('RT')
"""Response value type"""

Recommendations = tuple[list[Recommendation], list[Recommendation]]
UserInterests = tuple[list[str], list[str]]
SharesReply = tuple[list[DirectoryData], list[DirectoryData]]


class UserStatusInfo(NamedTuple):
    status: UserStatus
    privileged: bool


class UserStatsInfo(NamedTuple):
    avg_speed: int
    uploads: int
    shared_file_count: int
    shared_folder_count: int


class UserInfo(NamedTuple):
    description: str
    picture: Optional[bytes]
    has_slots_free: bool
    upload_slots: int
    queue_length: int
    upload_permissions: UploadPermissions


class BaseCommand(ABC, Generic[RC, RT]):

    @abstractmethod
    async def send(self, client: SoulSeekClient):
        ...

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return None

    def handle_response(self, client: SoulSeekClient, response: RC) -> Optional[RT]:
        return None


class GetUserStatusCommand(BaseCommand[GetUserStatus.Response, UserStatusInfo]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetUserStatus.Request(self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetUserStatus.Response,
            fields={
                'username': self.username
            }
        )

    def handle_response(
            self, client: SoulSeekClient, response: GetUserStatus.Response) -> UserStatusInfo:

        return UserStatusInfo(
            UserStatus(response.status),
            response.privileged
        )


class GetUserStatsCommand(BaseCommand[GetUserStats.Response, UserStatsInfo]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetUserStats.Request(self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetUserStats.Response,
            fields={
                'username': self.username
            }
        )

    def handle_response(self, client: SoulSeekClient, response: GetUserStats.Response) -> UserStatsInfo:
        return UserStatsInfo(
            response.user_stats.avg_speed,
            response.user_stats.uploads,
            response.user_stats.shared_file_count,
            response.user_stats.shared_folder_count,
        )


class GetRoomListCommand(BaseCommand[RoomList.Response, list[Room]]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RoomList.Request()
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            RoomList.Response
        )

    def handle_response(self, client: SoulSeekClient, response: RoomList.Response) -> list[Room]:
        return [
            room for name, room in client.rooms.rooms.items()
            if name in response.rooms
        ]


class JoinRoomCommand(BaseCommand[JoinRoom.Response, Room]):

    def __init__(self, room: str, private: bool = False):
        self.room: str = room
        self.private: bool = private

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            JoinRoom.Request(self.room, is_private=self.private)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            JoinRoom.Response,
            fields={
                'room': self.room
            }
        )

    def handle_response(self, client: SoulSeekClient, response: JoinRoom.Response) -> Room:
        return client.rooms.rooms[response.room]


class LeaveRoomCommand(BaseCommand[LeaveRoom.Response, Room]):

    def __init__(self, room: str):
        self.room: str = room

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            LeaveRoom.Request(self.room)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            LeaveRoom.Response,
            fields={
                'room': self.room
            }
        )

    def handle_response(self, client: SoulSeekClient, response: LeaveRoom.Response) -> Room:
        return client.rooms.rooms[response.room]


class GrantRoomMembershipCommand(BaseCommand[PrivateRoomGrantMembership.Response, tuple[Room, User]]):

    def __init__(self, room: str, username: str):
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomGrantMembership.Request(self.room, self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            PrivateRoomGrantMembership.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )

    def handle_response(
            self, client: SoulSeekClient, response: PrivateRoomGrantMembership.Response) -> tuple[Room, User]:
        return (
            client.rooms.rooms[response.room],
            client.users.get_user_object(response.username)
        )


class RevokeRoomMembershipCommand(BaseCommand[PrivateRoomRevokeMembership.Response, tuple[Room, User]]):

    def __init__(self, room: str, username: str):
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomRevokeMembership.Request(self.room, self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            PrivateRoomRevokeMembership.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )

    def handle_response(
            self, client: SoulSeekClient, response: PrivateRoomRevokeMembership.Response) -> tuple[Room, User]:
        return (
            client.rooms.rooms[response.room],
            client.users.get_user_object(response.username)
        )


class DropRoomMembershipCommand(BaseCommand[PrivateRoomMembershipRevoked.Response, Room]):

    def __init__(self, room: str):
        self.room: str = room
        self._username: Optional[str] = None

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomDropMembership.Request(self.room)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            PrivateRoomMembershipRevoked.Response,
            fields={'room': self.room}
        )

    def handle_response(self, client: SoulSeekClient, response: PrivateRoomMembershipRevoked.Response) -> Room:
        return client.rooms.rooms[response.room]


class DropRoomOwnershipCommand(BaseCommand[None, None]):

    def __init__(self, room: str):
        self.room: str = room

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomDropOwnership.Request(self.room)
        )


class GetItemRecommendationsCommand(BaseCommand[GetItemRecommendations.Response, list[Recommendation]]):

    def __init__(self, item: str):
        self.item: str = item

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetItemRecommendations.Request(self.item)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetItemRecommendations.Response,
            fields={
                'item': self.item
            }
        )

    def handle_response(
            self, client: SoulSeekClient, response: GetItemRecommendations.Response) -> list[Recommendation]:
        return response.recommendations


class GetRecommendationsCommand(BaseCommand[GetRecommendations.Response, Recommendations]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetRecommendations.Request()
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetRecommendations.Response
        )

    def handle_response(self, client: SoulSeekClient, response: GetRecommendations.Response) -> Recommendations:
        return response.recommendations, response.unrecommendations


class GetGlobalRecommendationsCommand(BaseCommand[GetGlobalRecommendations.Response, Recommendations]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetGlobalRecommendations.Request()
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetGlobalRecommendations.Response
        )

    def handle_response(self, client: SoulSeekClient, response: GetGlobalRecommendations.Response) -> Recommendations:
        return response.recommendations, response.unrecommendations


class GetItemSimilarUsersCommand(BaseCommand[GetItemSimilarUsers.Response, list[User]]):

    def __init__(self, item: str):
        self.item: str = item

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetItemSimilarUsers.Request(self.item)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetItemSimilarUsers.Response,
            fields={
                'item': self.item
            }
        )

    def handle_response(self, client: SoulSeekClient, response: GetItemSimilarUsers.Response) -> list[User]:
        return list(map(client.users.get_user_object, response.usernames))


class GetSimilarUsersCommand(BaseCommand[GetSimilarUsers.Response, list[tuple[User, int]]]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetSimilarUsers.Request()
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetSimilarUsers.Response
        )

    def handle_response(self, client: SoulSeekClient, response: GetSimilarUsers.Response) -> list[tuple[User, int]]:
        similar_users = []
        for similar_user in response.users:
            similar_users.append(
                (
                    client.users.get_user_object(similar_user.username),
                    similar_user.score
                )
            )

        return similar_users


class GetPeerAddressCommand(BaseCommand[GetPeerAddress.Response, tuple[str, int, Optional[int]]]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetPeerAddress.Request(self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetPeerAddress.Response,
            fields={
                'username': self.username
            }
        )

    def handle_response(
            self, client: SoulSeekClient, response: GetPeerAddress.Response) -> tuple[str, int, Optional[int]]:
        return (response.ip, response.port, response.obfuscated_port)


class GrantRoomOperatorCommand(BaseCommand[PrivateRoomGrantOperator.Response, None]):

    def __init__(self, room: str, username: str):
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomGrantOperator.Request(self.room, self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            PrivateRoomGrantOperator.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )

    def handle_response(self, client: SoulSeekClient, response: PrivateRoomGrantOperator.Response) -> None:
        return None


class RevokeRoomOperatorCommand(BaseCommand[PrivateRoomRevokeOperator.Response, None]):

    def __init__(self, room: str, username: str):
        self.room: str = room
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            PrivateRoomRevokeOperator.Request(self.room, self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            PrivateRoomRevokeOperator.Response,
            fields={
                'room': self.room,
                'username': self.username
            }
        )

    def handle_response(self, client: SoulSeekClient, response: PrivateRoomRevokeOperator.Response) -> None:
        return None


class TogglePublicChatCommand(BaseCommand[None, None]):

    def __init__(self, enable: bool):
        self.enable: bool = enable

    async def send(self, client: SoulSeekClient):
        if self.enable:
            message: MessageDataclass = EnablePublicChat.Request()
        else:
            message = DisablePublicChat.Request()
        await client.network.send_server_messages(message)


class TogglePrivateRoomInvitesCommand(BaseCommand[TogglePrivateRoomInvites.Response, None]):

    def __init__(self, enable: bool):
        self.enable: bool = enable

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            TogglePrivateRoomInvites.Request(self.enable)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            TogglePrivateRoomInvites.Response,
            fields={
                'enabled': self.enable
            }
        )

    def handle_response(self, client: SoulSeekClient, response: TogglePrivateRoomInvites.Response) -> None:
        return None


class GlobalSearchCommand(BaseCommand[None, None]):

    def __init__(self, query: str):
        self.query: str = query
        self._ticket: Optional[int] = None

    async def send(self, client: SoulSeekClient):
        self._ticket = next(client.ticket_generator)
        await client.network.send_server_messages(
            FileSearch.Request(
                self._ticket,
                query=self.query
            )
        )
        client.searches.requests[self._ticket] = SearchRequest(
            ticket=self._ticket,
            query=self.query,
            search_type=SearchType.NETWORK
        )


class UserSearchCommand(BaseCommand[None, None]):

    def __init__(self, username: str, query: str):
        self.username: str = username
        self.query: str = query
        self._ticket: Optional[int] = None

    async def send(self, client: SoulSeekClient):
        self._ticket = next(client.ticket_generator)
        await client.network.send_server_messages(
            UserSearch.Request(
                self.username,
                self._ticket,
                self.query
            )
        )
        client.searches.requests[self._ticket] = SearchRequest(
            ticket=self._ticket,
            query=self.query,
            username=self.username,
            search_type=SearchType.USER
        )


class RoomSearchCommand(BaseCommand[None, None]):

    def __init__(self, room: str, query: str):
        self.room: str = room
        self.query: str = query
        self._ticket: Optional[int] = None

    async def send(self, client: SoulSeekClient):
        self._ticket = next(client.ticket_generator)
        await client.network.send_server_messages(
            RoomSearch.Request(
                self.room,
                self._ticket,
                self.query
            )
        )
        client.searches.requests[self._ticket] = SearchRequest(
            ticket=self._ticket,
            query=self.query,
            room=self.room,
            search_type=SearchType.ROOM
        )


class PrivateMessageCommand(BaseCommand[None, None]):

    def __init__(self, username: str, message: str):
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

    def __init__(self, usernames: list[str], message: str):
        self.usernames: list[str] = usernames
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
        self.room: str = room
        self.message: str = message

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RoomChatMessage.Request(
                self.room,
                self.message
            )
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        if not client.session:  # pragma: no cover
            raise InvalidSessionError("user is not logged in")

        return ExpectedResponse(
            ServerConnection,
            RoomChatMessage.Response,
            fields={
                'room': self.room,
                'username': client.session.user.name,
                'message': self.message
            }
        )

    def handle_response(self, client: SoulSeekClient, response: RoomChatMessage.Response) -> RoomMessage:
        if not client.session:  # pragma: no cover
            raise InvalidSessionError("user is not logged in")

        return RoomMessage(
            timestamp=int(time.time()),
            user=client.users.get_user_object(client.session.user.name),
            room=client.rooms.get_or_create_room(self.room),
            message=self.message
        )


class SetRoomTickerCommand(BaseCommand[RoomTickerAdded.Response, None]):

    def __init__(self, room: str, ticker: str):
        self.room: str = room
        self.ticker: str = ticker

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            SetRoomTicker.Request(
                self.room,
                self.ticker
            )
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        if not client.session:  # pragma: no cover
            raise InvalidSessionError("user is not logged in")

        return ExpectedResponse(
            ServerConnection,
            RoomTickerAdded.Response,
            fields={
                'room': self.room,
                'username': client.session.user.name,
                'ticker': self.ticker
            }
        )


class AddInterestCommand(BaseCommand[None, None]):

    def __init__(self, interest: str):
        self.interest: str = interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            AddInterest.Request(self.interest)
        )


class AddHatedInterestCommand(BaseCommand[None, None]):

    def __init__(self, hated_interest: str):
        self.hated_interest: str = hated_interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            AddHatedInterest.Request(self.hated_interest)
        )


class RemoveInterestCommand(BaseCommand[None, None]):

    def __init__(self, interest: str):
        self.interest: str = interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RemoveInterest.Request(self.interest)
        )


class RemoveHatedInterestCommand(BaseCommand[None, None]):

    def __init__(self, hated_interest: str):
        self.hated_interest: str = hated_interest

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            RemoveHatedInterest.Request(self.hated_interest)
        )


class GetUserInterestsCommand(BaseCommand[GetUserInterests.Response, UserInterests]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GetUserInterests.Request(self.username)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            GetUserInterests.Response,
            fields={
                'username': self.username,
            }
        )

    def handle_response(self, client: SoulSeekClient, response: GetUserInterests.Response) -> UserInterests:
        return response.interests, response.hated_interests


class SetStatusCommand(BaseCommand[None, None]):

    def __init__(self, status: UserStatus):
        self.status: UserStatus = status

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            SetStatus.Request(self.status.value)
        )
        # Due to a bug in the protocol a GetUserStatus message for ourself is
        # never returned and it needs to be set manually
        client.users.get_self().status = self.status


class SetNewPasswordCommand(BaseCommand[None, None]):

    def __init__(self, password: str):
        self.password: str = password

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            NewPassword.Request(self.password)
        )


class CheckPrivilegesCommand(BaseCommand[CheckPrivileges.Response, int]):

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(CheckPrivileges.Request())

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            CheckPrivileges.Response
        )

    def handle_response(self, client: SoulSeekClient, response: CheckPrivileges.Response) -> int:
        return response.time_left


class GivePrivilegesCommand(BaseCommand[None, None]):

    def __init__(self, username: str, days: int):
        self.username: str = username
        self.days: int = days

    async def send(self, client: SoulSeekClient):
        await client.network.send_server_messages(
            GiveUserPrivileges.Request(
                username=self.username,
                days=self.days
            )
        )


class TrackUserCommand(BaseCommand[AddUser.Response, User]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.users.track_user(self.username, TrackingFlag.REQUESTED)

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            ServerConnection,
            AddUser.Response,
            fields={
                'username': self.username
            }
        )

    def handle_response(self, client: SoulSeekClient, response: AddUser.Response) -> User:
        if response.exists:
            return client.users.get_user_object(response.username)
        else:
            raise NoSuchUserError(
                f"user {self.username!r} does not exist on the server")


class UntrackUserCommand(BaseCommand[None, User]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.users.untrack_user(self.username, TrackingFlag.REQUESTED)


class PeerGetUserInfoCommand(BaseCommand[PeerUserInfoReply.Request, UserInfo]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_peer_messages(
            self.username, PeerUserInfoRequest.Request()
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            PeerConnection,
            PeerUserInfoReply.Request,
            peer=self.username
        )

    def handle_response(self, client: SoulSeekClient, response: PeerUserInfoReply.Request) -> UserInfo:
        if response.upload_permissions is None:
            upload_permissions = UploadPermissions.UNKNOWN
        else:
            upload_permissions = UploadPermissions(response.upload_permissions)
        return UserInfo(
            response.description,
            response.picture if response.has_picture else None,
            response.has_slots_free,
            response.upload_slots,
            response.queue_size,
            upload_permissions
        )


class PeerGetSharesCommand(BaseCommand[PeerSharesReply.Request, SharesReply]):

    def __init__(self, username: str):
        self.username: str = username

    async def send(self, client: SoulSeekClient):
        await client.network.send_peer_messages(
            self.username, PeerSharesRequest.Request()
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            PeerConnection,
            PeerSharesReply.Request,
            peer=self.username
        )

    def handle_response(
            self, client: SoulSeekClient, response: PeerSharesReply.Request) -> SharesReply:
        locked_dirs = response.locked_directories or []
        return response.directories, locked_dirs


class PeerGetDirectoryContentCommand(BaseCommand[PeerDirectoryContentsReply.Request, list[DirectoryData]]):

    def __init__(self, username: str, directory: str):
        self.username: str = username
        self.directory: str = directory
        self._ticket: Optional[int] = None

    async def send(self, client: SoulSeekClient):
        self._ticket = next(client.ticket_generator)
        await client.network.send_peer_messages(
            self.username, PeerDirectoryContentsRequest.Request(self._ticket, self.directory)
        )

    def build_expected_response(self, client: SoulSeekClient) -> Optional[ExpectedResponse]:
        return ExpectedResponse(
            PeerConnection,
            PeerDirectoryContentsReply.Request,
            peer=self.username,
            fields={
                'ticket': self._ticket,
                'directory': self.directory
            }
        )

    def handle_response(
            self, client: SoulSeekClient, response: PeerDirectoryContentsReply.Request) -> list[DirectoryData]:
        return response.directories
