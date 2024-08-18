import asyncio
from collections import Counter
from functools import partial
import logging
import re
import socket
import time
from typing import Dict, Generator, List, Optional, Set, Type, TypeVar
import typing

from aioslsk.events import build_message_map
from aioslsk.user.model import UserStatus
from aioslsk.protocol.primitives import (
    calc_md5,
    PotentialParent,
    Recommendation,
    RoomTicker,
    SimilarUser,
    UserStats,
)
from aioslsk.protocol.messages import (
    AcceptChildren,
    AddHatedInterest,
    AddInterest,
    AddUser,
    BranchLevel,
    BranchRoot,
    CannotConnect,
    CannotCreateRoom,
    CheckPrivileges,
    ChildDepth,
    ConnectToPeer,
    DisablePublicChat,
    EnablePublicChat,
    ExactFileSearch,
    ExcludedSearchPhrases,
    FileSearch,
    GetRelatedSearches,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetPeerAddress,
    GetRecommendations,
    GetSimilarUsers,
    GetUserStats,
    GetUserStatus,
    GetUserInterests,
    JoinRoom,
    Kicked,
    LeaveRoom,
    Login,
    MessageDataclass,
    ParentMinSpeed,
    ParentSpeedRatio,
    Ping,
    PotentialParents,
    PrivateChatMessage,
    PrivateChatMessageAck,
    PrivateChatMessageUsers,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
    PrivateRoomGrantMembership,
    PrivateRoomGrantOperator,
    PrivateRoomMembershipGranted,
    PrivateRoomMembershipRevoked,
    PrivateRoomOperatorGranted,
    PrivateRoomOperatorRevoked,
    PrivateRoomOperators,
    PrivateRoomRevokeMembership,
    PrivateRoomRevokeOperator,
    PrivateRoomMembers,
    PrivilegedUsers,
    PublicChatMessage,
    RemoveHatedInterest,
    RemoveInterest,
    RemoveUser,
    ResetDistributed,
    RoomChatMessage,
    RoomList,
    RoomSearch,
    RoomTickerAdded,
    RoomTickerRemoved,
    RoomTickers,
    SendUploadSpeed,
    ServerSearchRequest,
    SetListenPort,
    SetRoomTicker,
    SetStatus,
    SharedFoldersFiles,
    ToggleParentSearch,
    TogglePrivateRoomInvites,
    UserJoinedRoom,
    UserLeftRoom,
    UserSearch,
    WishlistInterval,
)
from tests.e2e.mock.constants import (
    DEFAULT_EXCLUDED_SEARCH_PHRASES,
    MAX_RECOMMENDATIONS,
    MAX_GLOBAL_RECOMMENDATIONS,
)
from tests.e2e.mock.distributed import DistributedStrategy, EveryoneRootStrategy
from tests.e2e.mock.messages import AdminMessage
from tests.e2e.mock.model import (
    DistributedValues,
    MockVariables,
    QueuedPrivateMessage,
    Room,
    RoomStatus,
    Settings,
    User,
)
from tests.e2e.mock.peer import Peer


logging.basicConfig(level=logging.DEBUG)
formatter = logging.Formatter('%(asctime)s [%(name)s] [%(levelname)s] %(message)s')
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    handler.setFormatter(formatter)

logger = logging.getLogger(__name__)


T = TypeVar('T', bound='DistributedStrategy')


def ticket_generator(initial: int = 1) -> Generator[int, None, None]:
    idx = initial
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = initial
        yield idx


def remove_0_values(counter: typing.Counter[str]):
    recommendations_to_remove = [
        key for key, value in counter.items() if value == 0
    ]
    for to_remove in recommendations_to_remove:
        del counter[to_remove]


def on_message(message_class: Type[MessageDataclass], require_user: bool = True):
    """Decorator for methods listening to specific `MessageData` events
    """
    def register(event_func):
        event_func._registered_message = message_class
        event_func._require_user = require_user
        return event_func

    return register


class MockServer:

    def __init__(
            self, hostname: str = '0.0.0.0', ports: Set[int] = {2416},
            excluded_search_phrases: List[str] = DEFAULT_EXCLUDED_SEARCH_PHRASES,
            potential_parent_interval: int = 0,
            distributed_strategy_class: Type[DistributedStrategy] = EveryoneRootStrategy,
            mock_variables: Optional[MockVariables] = None):

        self.hostname: str = hostname
        self.ports: Set[int] = ports
        self.connections: Dict[int, asyncio.Server] = {}
        self.settings: Settings = Settings()

        self.users: List[User] = []
        self.rooms: List[Room] = []
        self.peers: List[Peer] = []
        self.distributed_tree: Dict[str, DistributedValues] = {}

        self.excluded_search_phrases: List[str] = excluded_search_phrases
        self.distributed_strategy: DistributedStrategy = self._create_distributed_strategy(distributed_strategy_class)
        self.mock_variables: MockVariables = mock_variables or MockVariables()

        self.chat_id_gen = ticket_generator()
        self.MESSAGE_MAP = build_message_map(self)

        self.periodic_search_task: Optional[asyncio.Task] = None
        self.distributed_parent_task: Optional[asyncio.Task] = None

        if potential_parent_interval > 0:
            self.distributed_parent_task = asyncio.create_task(
                self.distributed_parent_job(interval=potential_parent_interval))

        if self.mock_variables.search_interval > 0:
            self.periodic_search_task = asyncio.create_task(
                self.search_request_job(interval=self.mock_variables.search_interval))

    def _create_distributed_strategy(self, strategy_cls: Type[T]) -> T:
        return strategy_cls(self.settings, self.peers, self.distributed_tree)

    def set_distributed_strategy(self, strategy_cls: Type[DistributedStrategy]):
        self.distributed_strategy = self._create_distributed_strategy(strategy_cls)

    async def notify_potential_parents(self):
        """Notifies all peers of their potential parents"""
        messages = []
        for peer in self.get_valid_peers():
            if not peer.user.enable_parent_search:
                continue

            potential_parents = self.distributed_strategy.get_potential_parents(peer)
            if not potential_parents:
                logger.debug(f"no potential parents for peer {peer.user.name}")
                continue

            message = PotentialParents.Response(
                entries=[
                    PotentialParent(
                        pot_parent.user.name,
                        pot_parent.hostname,
                        pot_parent.user.port
                    )
                    for pot_parent in potential_parents
                ]
            )
            messages.append(peer.send_message(message))

        await asyncio.gather(*messages, return_exceptions=True)

    async def distributed_parent_job(self, interval: float = 60):
        """Periodic job for sending out potential parents"""
        while True:
            await asyncio.sleep(interval)
            logger.info("sending out potential parents")
            await self.notify_potential_parents()

    async def search_request_job(self, interval: float = 5):
        """Periodic job for sending out dummy search requests"""
        generator = ticket_generator()
        while True:
            await asyncio.sleep(interval)

            ticket = next(generator)
            message = ServerSearchRequest.Response(
                0x03,
                0x31,
                'searching_user',
                ticket,
                f"dummy search request {ticket}"
            )

            await asyncio.gather(
                *[peer.send_message(message) for peer in self.distributed_strategy.get_roots()],
                return_exceptions=True
            )

    async def connect(self, start_serving: bool = False):
        tasks = [
            self.connect_port(port, start_serving)
            for port in self.ports
        ]
        await asyncio.gather(*tasks)

    async def connect_port(self, port: int, start_serving: bool = False):
        logger.info(
            f"open {self.hostname}:{port} : listening connection")

        connection = await asyncio.start_server(
            partial(self.accept_peer, port),
            self.hostname,
            port,
            family=socket.AF_INET,
            start_serving=start_serving
        )
        self.connections[port] = connection

    async def disconnect_peers(self):
        await asyncio.gather(
            *[peer.disconnect() for peer in self.peers], return_exceptions=True)

    async def disconnect(self):
        for port, connection in self.connections.items():
            logger.debug(f"{self.hostname}:{port} : disconnecting")
            try:
                if connection.is_serving():
                    connection.close()
                await connection.wait_closed()

            except Exception as exc:
                logger.warning(
                    f"{self.hostname}:{port} : exception while disconnecting", exc_info=exc)

            finally:
                logger.debug(f"{self.hostname}:{port} : disconnected")

        await self.disconnect_peers()

    async def accept_peer(self, listening_port: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        hostname, port = writer.get_extra_info('peername')
        logger.debug(f"{self.hostname}:{listening_port} : accepted connection {hostname}:{port}")

        peer = Peer(hostname, port, self, reader, writer)
        peer.start_reader_loop()
        peer.connect_time = time.monotonic()

        self.peers.append(peer)

    async def on_peer_disconnected(self, peer: Peer):
        """Called when a peer is disconnected"""
        peer.connect_time = 0.0

        logger.info(f"disconnected peer : {peer!r}")
        if peer in self.peers:
            self.peers.remove(peer)

        if peer.user:
            peer.user.logout()
            self.distributed_tree.pop(peer.user.name, None)

            # Leave all rooms
            for room in self.get_joined_rooms(peer.user):
                await self.leave_room(room, peer)

            # Send a status update
            await self.send_status_update(peer.user)

    async def on_peer_message(self, message, peer: Peer):
        """Called when a peer receives a message"""
        if message.__class__ in self.MESSAGE_MAP:
            method = self.MESSAGE_MAP[message.__class__]

            if method._require_user:
                if not peer.user:
                    logger.debug(f"ignoring message {message}, peer has no valid user : {peer!r}")
                    return

            await method(message, peer)

    def get_valid_peers(self) -> List[Peer]:
        """Returns all peers which are logged in (user set)"""
        return [peer for peer in self.peers if peer.user]

    def find_peer_by_name(self, username: str) -> Optional[Peer]:
        for peer in self.peers:
            if peer.user and peer.user.name == username:
                return peer

    def find_user_by_name(self, username: str) -> Optional[User]:
        for user in self.users:
            if user.name == username:
                return user

    def find_room_by_name(self, name: str) -> Optional[Room]:
        for room in self.rooms:
            if room.name == name:
                return room

    def get_user_private_rooms(self, user: User) -> List[Room]:
        return [room for room in self.rooms if user in room.all_members]

    def get_joined_rooms(self, user: User) -> List[Room]:
        return [room for room in self.rooms if user in room.joined_users]

    async def set_upload_speed(self, username: str, uploads: int, speed: int):
        """This is utility method for testing that sets the upload speed for the
        given user and reports it to the username
        """
        user = self.find_user_by_name(username)
        user.avg_speed = speed
        user.uploads = uploads

        peer = self.find_peer_by_name(username)
        await peer.send_message(
            GetUserStats.Response(
                username,
                user_stats=UserStats(
                    avg_speed=user.avg_speed,
                    uploads=user.uploads,
                    shared_file_count=user.shared_file_count,
                    shared_folder_count=user.shared_folder_count
                )
            )
        )

    async def send_search_request(self, username: str, sender: str, query: str, ticket: int):
        """This is a utility method for testing. To make a peer a root the
        server has to send an initial search message to that user

        :param username: Username to send the query to
        :param query: The query to send
        :param sender: Username of the peer "sending" the query
        :param ticket: Search query ticket
        """
        peer = self.find_peer_by_name(username)

        message = ServerSearchRequest.Response(
            0x03,
            0x31,
            sender,
            ticket,
            query
        )

        await peer.send_message(message)

    async def send_potential_parents(
            self, username: str, potential_parents: List[str] = None):
        """This is a utility method used for testing to send the potential
        parents to the peer with given username

        :param username: Username of the peer to send the potential parents to
        :param potential_parents: List of usernames that should be sent out as
            potential parents. If ``None`` use the distributed strategy to
            determine the users
        """
        peer = self.find_peer_by_name(username)

        if potential_parents is None:
            pparent_peers = self.distributed_strategy.get_potential_parents(peer)
        else:
            pparent_peers = []
            for pparent_username in potential_parents:
                pparent_peer = self.find_peer_by_name(pparent_username)

                if not pparent_peer:
                    raise Exception(f"no peer object for user {pparent_username}")

                pparent_peers.append(pparent_peer)

        message = PotentialParents.Response(
            entries=[
                PotentialParent(
                    username=pparent.user.name,
                    ip=pparent.hostname,
                    port=pparent.user.port
                )
                for pparent in pparent_peers
            ]
        )
        await peer.send_message(message)

    async def send_admin_message(self, message: str, peer: Peer):
        await peer.send_message(
            PrivateChatMessage.Response(
                chat_id=next(self.chat_id_gen),
                timestamp=int(time.time()),
                message=message,
                username='server',
                is_direct=True
            )
        )

    def _create_room_list_message(self, user: User, min_users: int = 1):
        public_rooms: List[Room] = []
        private_rooms: List[Room] = []
        private_rooms_owned: List[Room] = []
        private_rooms_operated: List[Room] = []
        for room in self.rooms:
            if room.status == RoomStatus.PRIVATE:
                if room.owner == user:
                    private_rooms_owned.append(room)

                if user in room.operators:
                    private_rooms_operated.append(room)

                if user in room.members:
                    private_rooms.append(room)

            elif room.status == RoomStatus.PUBLIC:

                if len(room.joined_users) >= min_users:
                    public_rooms.append(room)

        return RoomList.Response(
            rooms=[room.name for room in public_rooms],
            rooms_user_count=[len(room.joined_users) for room in public_rooms],
            rooms_private=[room.name for room in private_rooms],
            rooms_private_user_count=[len(room.joined_users) for room in private_rooms],
            rooms_private_owned=[room.name for room in private_rooms_owned],
            rooms_private_owned_user_count=[len(room.joined_users) for room in private_rooms_owned],
            rooms_private_operated=[room.name for room in private_rooms_operated]
        )

    async def send_room_list(self, peer: Peer, min_users: int = 1):
        """Send the room list for the user

        :param min_users: Optional minimum amount of joined users for public
            rooms. Public rooms with less joined users will be filtered out
        """
        await peer.send_message(
            self._create_room_list_message(peer.user, min_users=min_users)
        )

    async def send_room_list_update(self, user: User, min_users: int = 1):
        """Sends a user an updated room list

        * RoomList
        * PrivateRoomMembers for each private room joined
        * PrivateRoomOperators for each private room joined

        This is sent after:
        * Creation of a private room
        * Getting added as a new member
        * Getting removed as member
        * Getting operator granted
        * Getting operator revoked
        """
        peer = self.find_peer_by_name(user.name)

        messages = [
            self._create_room_list_message(user, min_users=min_users)
        ]

        # Following is done in 2 loops deliberatly to keep order of messages
        # PrivateRoomMembers (excludes owner, includes operators)
        user_private_rooms = self.get_user_private_rooms(user)
        for room in user_private_rooms:
            messages.append(
                PrivateRoomMembers.Response(
                    room=room.name,
                    usernames=[member.name for member in room.members]
                )
            )

        # RoomOperators (only operators)
        for room in user_private_rooms:
            messages.append(
                PrivateRoomOperators.Response(
                    room=room.name,
                    usernames=[operator.name for operator in room.operators]
                )
            )

        for message in messages:
            await peer.send_message(message)

    @on_message(ExactFileSearch.Request)
    async def on_exact_file_search(self, message: ExactFileSearch.Request, peer: Peer):
        pass

    @on_message(Login.Request, require_user=False)
    async def on_login(self, message: Login.Request, peer: Peer):
        # Ignore hash mismatch
        if message.md5hash != calc_md5(message.username + message.password):
            pass

        # Check if username entered is valid
        if not message.username:
            await peer.send_message(
                Login.Response(
                    success=False,
                    reason='INVALIDUSERNAME'
                )
            )
            return

        # Check if we have a user, if so check the password
        user = self.find_user_by_name(message.username)
        if user and message.password != user.password:
            await peer.send_message(
                Login.Response(
                    success=False,
                    reason='INVALIDPASS'
                )
            )
            return

        # Create a new user if we did not have it yet
        if not user:
            user = User(
                name=message.username,
                password=message.password,
                # Assign default values for testing
                avg_speed=self.mock_variables.upload_speed,
                uploads=int(self.mock_variables.upload_speed * 0.05)
            )
            self.users.append(user)

        # Check if there is another peer
        other_peer = self.find_peer_by_name(message.username)
        if other_peer:
            other_peer.user = None
            await other_peer.send_message(Kicked.Response())
            await other_peer.disconnect()

        # Link the user to the peer
        peer.user = user

        user.login()
        self.distributed_tree[user.name] = DistributedValues(root=user.name)

        await self.send_status_update(user)

        await peer.send_message(
            Login.Response(
                success=True,
                greeting='',
                ip=peer.hostname,
                md5hash=calc_md5(message.password),
                privileged=user.privileged
            )
        )

        # Send all post login messages
        # NOTE: the room list should only contain rooms with 5 or more joined
        # users after login. Ignoring for now since there won't be much rooms
        # during testing
        await self.send_queued_private_messages(peer)
        await self.send_room_list_update(user)
        await peer.send_message(
            ParentMinSpeed.Response(self.settings.parent_min_speed))
        await peer.send_message(
            ParentSpeedRatio.Response(self.settings.parent_speed_ratio))
        await peer.send_message(
            WishlistInterval.Response(self.settings.wishlist_interval))
        await peer.send_message(
            PrivilegedUsers.Response([user.name for user in self.users if user.privileged]))
        await peer.send_message(
            ExcludedSearchPhrases.Response(self.excluded_search_phrases))

    @on_message(SetListenPort.Request)
    async def on_listen_port(self, message: SetListenPort.Request, peer: Peer):
        peer.user.port = message.port
        peer.user.obfuscated_port = message.obfuscated_port

    @on_message(CheckPrivileges.Request)
    async def on_check_privileges(self, message: CheckPrivileges.Request, peer: Peer):
        await peer.send_message(CheckPrivileges.Response(
            peer.user.privileges_time_left
        ))

    @on_message(RoomList.Request)
    async def on_room_list(self, message: RoomList.Request, peer: Peer):
        await self.send_room_list(peer)

    @on_message(AddUser.Request)
    async def on_add_user(self, message: AddUser.Request, peer: Peer):
        """
        Behaviour:
        * Empty username -> user cannot exist
        * Track user already tracked -> user only gets 1 update
        """
        if (user := self.find_user_by_name(message.username)) is not None:
            # Add only to the added_users if the user exists and he is not
            # himself
            if message.username != peer.user.name:
                peer.user.added_users[message.username] = user

            await peer.send_message(
                AddUser.Response(
                    message.username,
                    exists=True,
                    status=user.status.value,
                    user_stats=UserStats(
                        avg_speed=user.avg_speed,
                        uploads=user.uploads,
                        shared_file_count=user.shared_file_count,
                        shared_folder_count=user.shared_folder_count
                    ),
                    country_code=user.country
                )
            )

        else:
            await peer.send_message(
                AddUser.Response(
                    message.username,
                    exists=False
                )
            )

    @on_message(PrivateChatMessageUsers.Request)
    async def on_private_chat_message_users(self, message: PrivateChatMessageUsers.Request, peer: Peer):
        """User sends a private message to multiple users"""
        timestamp = int(time.time())
        chat_id = next(self.chat_id_gen)

        tasks = []
        for username in message.usernames:

            # Skip users in the list that do not exist
            if (user_receiver := self.find_user_by_name(username)) is None:
                continue

            # Skip sending a message if sender is not in the added users of the
            # receiver
            if peer.user.name not in user_receiver.added_users:
                continue

            # TODO: Verify if a new chat ID is generated for each user
            private_message = QueuedPrivateMessage(
                chat_id=chat_id,
                username=peer.user.name,
                message=message.message,
                timestamp=timestamp
            )
            user_receiver.queued_private_messages.append(private_message)

            if (peer_receiver := self.find_peer_by_name(username)) is not None:
                tasks.append(
                    peer_receiver.send_message(
                        private_message.to_protocol_message(is_direct=True)
                    )
                )

        await asyncio.gather(*tasks, return_exceptions=True)

    @on_message(PrivateChatMessage.Request)
    async def on_chat_private_message(self, message: PrivateChatMessage.Request, peer: Peer):
        """User sends a private message to a another user"""
        # Do nothing when sending to a user that does not exist
        if (user_receiver := self.find_user_by_name(message.username)) is None:
            return

        private_message = QueuedPrivateMessage(
            chat_id=next(self.chat_id_gen),
            username=peer.user.name,
            message=message.message,
            timestamp=int(time.time())
        )
        user_receiver.queued_private_messages.append(private_message)

        # If there is a peer for that user, send the message with is_direct=True
        if (peer_receiver := self.find_peer_by_name(message.username)) is not None:
            await peer_receiver.send_message(
                private_message.to_protocol_message(is_direct=True)
            )

    @on_message(PrivateChatMessageAck.Request)
    async def on_chat_private_message_ack(
        self, message: PrivateChatMessageAck.Request, peer: Peer):

        to_remove = []
        for queued_message in peer.user.queued_private_messages:
            if queued_message.chat_id == message.chat_id:
                to_remove.append(queued_message)

        peer.user.queued_private_messages = [
            queued_pmessage for queued_pmessage in peer.user.queued_private_messages
            if queued_pmessage not in to_remove
        ]

    @on_message(RoomChatMessage.Request)
    async def on_chat_room_message(self, message: RoomChatMessage.Request, peer: Peer):
        if (room := self.find_room_by_name(message.room)) is None:
            return

        if peer.user not in room.joined_users:
            return

        room_message = RoomChatMessage.Response(
            room=room.name,
            username=peer.user.name,
            message=message.message
        )

        # Send to joined users
        room_futures = []
        for peer in self.get_valid_peers():
            if peer.user in room.joined_users:
                room_futures.append(peer.send_message(room_message))

        if room_futures:
            await asyncio.gather(*room_futures, return_exceptions=True)

        # Send public chat messages to users who have it enabled
        public_futures = []
        if room.status == RoomStatus.PUBLIC:
            public_message = PublicChatMessage.Response(
                room=room.name,
                username=peer.user.name,
                message=message.message
            )
            for peer in self.get_valid_peers():
                if peer.user.enable_public_chat:
                    public_futures.append(public_message)

        if public_futures:
            await asyncio.gather(*public_futures, return_exceptions=True)

    @on_message(RemoveUser.Request)
    async def on_remove_user(self, message: RemoveUser.Request, peer: Peer):
        # Ignore removing self (this check technically isn't necessary because
        # it is not possible to track self but is done for clarity)
        if peer.user.name == message.username:
            return

        if message.username in peer.user.added_users:
            del peer.user.added_users[message.username]

    @on_message(GetUserStatus.Request)
    async def on_get_user_status(self, message: GetUserStatus.Request, peer: Peer):
        if (user := self.find_user_by_name(message.username)) is not None:
            await peer.send_message(
                GetUserStatus.Response(
                    username=message.username,
                    status=user.status.value,
                    privileged=user.privileged
                )
            )
        else:
            await peer.send_message(
                GetUserStatus.Response(
                    username=message.username,
                    status=UserStatus.OFFLINE.value,
                    privileged=False
                )
            )

    @on_message(GetUserStats.Request)
    async def on_get_user_stats(self, message: GetUserStats.Request, peer: Peer):
        if (user := self.find_user_by_name(message.username)) is not None:
            await peer.send_message(
                GetUserStats.Response(
                    username=message.username,
                    user_stats=UserStats(
                        avg_speed=user.avg_speed,
                        uploads=user.uploads,
                        shared_file_count=user.shared_file_count,
                        shared_folder_count=user.shared_folder_count
                    )
                )
            )
        else:
            await peer.send_message(
                GetUserStats.Response(
                    username=message.username,
                    user_stats=UserStats(
                        avg_speed=0,
                        uploads=0,
                        shared_file_count=0,
                        shared_folder_count=0
                    )
                )
            )

    @on_message(SharedFoldersFiles.Request)
    async def on_shared_folders_files(self, message: SharedFoldersFiles.Request, peer: Peer):
        peer.user.shared_folder_count = message.shared_folder_count
        peer.user.shared_file_count = message.shared_file_count

        await self.send_stats_update(peer.user)

    @on_message(SetStatus.Request)
    async def on_set_status(self, message: SetStatus.Request, peer: Peer):
        if message.status not in (UserStatus.AWAY.value, UserStatus.ONLINE.value):
            return

        if peer.user.status == message.status:
            return

        peer.user.status = UserStatus(message.status)
        await self.send_status_update(peer.user)

    @on_message(GetPeerAddress.Request)
    async def on_get_peer_address(self, message: GetPeerAddress.Request, peer: Peer):

        other_peer = self.find_peer_by_name(message.username)

        if other_peer is not None:
            await peer.send_message(
                GetPeerAddress.Response(
                    message.username,
                    other_peer.hostname,
                    port=other_peer.user.port,
                    obfuscated_port_amount=1 if other_peer.user.obfuscated_port else 0,
                    obfuscated_port=other_peer.user.obfuscated_port
                )
            )
        else:
            await peer.send_message(
                GetPeerAddress.Response(
                    message.username,
                    '0.0.0.0',
                    port=0,
                    obfuscated_port_amount=0,
                    obfuscated_port=0
                )
            )

    @on_message(ConnectToPeer.Request)
    async def on_connect_to_peer(self, message: ConnectToPeer.Request, peer: Peer):
        # Tell the target peer defined in the message to connect to the peer
        # sending the message
        if (target_peer := self.find_peer_by_name(message.username)) is not None:
            await target_peer.send_message(
                ConnectToPeer.Response(
                    username=peer.user.name,
                    typ=message.typ,
                    ticket=message.ticket,
                    ip=peer.hostname,
                    port=peer.user.port,
                    obfuscated_port_amount=1 if peer.user.obfuscated_port else 0,
                    obfuscated_port=peer.user.obfuscated_port,
                    privileged=peer.user.privileged
                )
            )

    @on_message(BranchLevel.Request)
    async def on_branch_level(self, message: BranchLevel.Request, peer: Peer):
        self.distributed_tree[peer.user.name].level = message.level

    @on_message(BranchRoot.Request)
    async def on_branch_root(self, message: BranchRoot.Request, peer: Peer):
        if not self.find_peer_by_name(message.username):
            await peer.send_message(ResetDistributed.Response())
            return

        self.distributed_tree[peer.user.name].root = message.username

    @on_message(ChildDepth.Request)
    async def on_child_depth(self, message: ChildDepth.Request, peer: Peer):
        self.distributed_tree[peer.user.name].child_depth = message.depth

    @on_message(CannotConnect.Request)
    async def on_cannot_connect(self, message: CannotConnect.Request, peer: Peer):
        if (peer := self.find_peer_by_name(message.username)) is not None:
            await peer.send_message(
                CannotConnect.Response(
                    username=peer.user.name,
                    ticket=message.ticket
                )
            )

    @on_message(RoomSearch.Request)
    async def on_room_search(self, message: RoomSearch.Request, peer: Peer):
        """
        TODO: Investigate
        * Works for private rooms as well?
        * Room doesn't exist
        * Room is private room but not a member
        * Room is private room but not joined
        * Room is public room but not joined
        * Empty query
        * Empty roomname
        * Is search sent to self?
        """
        if (room := self.find_room_by_name(message.room)) is None:
            return

        if peer.user not in room.all_members:
            return

        message = FileSearch(
            username=peer.user.name,
            ticket=message.ticket,
            query=message.query
        )

        await self.notify_room_joined_users(room, message)

    @on_message(UserSearch.Request)
    async def on_user_search(self, message: UserSearch.Request, peer: Peer):
        """
        TODO: Investigate
        * User does not exist
        * User not online
        * User is self
        * Empty query
        * Empty username
        """
        if (user := self.find_user_by_name(message.username)) is None:
            return

        if (recv_peer := self.find_peer_by_name(message.username)) is None:
            return

        await recv_peer.send_message(
            FileSearch.Response(
                username=peer.user.name,
                ticket=message.ticket,
                query=message.query
            )
        )

    @on_message(FileSearch.Request)
    async def on_file_search(self, message: FileSearch.Request, peer: Peer):
        message = ServerSearchRequest.Response(
            0x03,
            0x31,
            peer.user.name,
            message.ticket,
            message.query
        )

        await asyncio.gather(
            *[peer.send_message(message) for peer in self.distributed_strategy.get_roots()],
            return_exceptions=True
        )

    @on_message(GetRelatedSearches.Request)
    async def on_get_related_searches(self, message: GetRelatedSearches.Request, peer: Peer):
        await peer.send_message(GetRelatedSearches.Response(
            message.query,
            related_searches=[]
        ))

    @on_message(SetRoomTicker.Request)
    async def on_room_ticker_set(self, message: SetRoomTicker.Request, peer: Peer):
        if (room := self.find_room_by_name(message.room)) is None:
            return

        if peer.user not in room.joined_users:
            return

        if len(message.ticker) > 1024:
            return

        # Remove the ticker if user had a ticker set
        if peer.user.name in room.tickers:
            del room.tickers[peer.user.name]
            remove_message = RoomTickerRemoved.Response(
                room=room.name,
                username=peer.user.name
            )
            await self.notify_room_joined_users(room, remove_message)

        # Only set the ticker if it was not an empty string (pure spaces is fine)
        if message.ticker:
            room.tickers[peer.user.name] = message.ticker

            add_message = RoomTickerAdded.Response(
                room=room.name,
                username=peer.user.name,
                ticker=message.ticker
            )

        await self.notify_room_joined_users(room, add_message)

    @on_message(GetGlobalRecommendations.Request)
    async def on_get_global_recommendations(self, message: GetGlobalRecommendations.Request, peer: Peer):
        """
        Recommendations are sorted from highest to lowest
        Recommendations with the same score are not sorted alphabetically
        Unrecommendations are sorted from lowest to highest

        TODO:
        * Checks
        * Does this include the items we have as interests / hated interests (currently yes)
        * Does this include only online users (currently yes)
        """
        rec_counter = self.get_global_recommendations()
        recommendations = [
            Recommendation(rec, score)
            for rec, score in rec_counter.most_common(MAX_GLOBAL_RECOMMENDATIONS)
        ]
        unrecommendations = [
            Recommendation(rec, score)
            for rec, score in rec_counter.most_common()[:-MAX_GLOBAL_RECOMMENDATIONS-1:-1]
        ]

        sorted(recommendations, key=lambda rec: rec.score, reverse=False)
        sorted(unrecommendations, key=lambda rec: rec.score, reverse=True)

        await peer.send_message(
            GetGlobalRecommendations.Response(
                recommendations=recommendations,
                unrecommendations=unrecommendations
            )
        )

    @on_message(GetRecommendations.Request)
    async def on_get_recommendations(self, message: GetRecommendations.Request, peer: Peer):
        """The following implementation makes a lot of assumptions based on some
        small tests:

        * Add all interests from users who share the same interests as you into
          a counter. Subtract all hated interests from the counter
        * Do the opposite where one of your interests is in the hated interests
          Add all hated interests and subtract all interests
        * Drop all interests where the counter is 0


        """
        rec_counter = self.get_recommendations_for_user(peer.user)
        recommendations = [
            Recommendation(rec, score)
            for rec, score in rec_counter.most_common(MAX_RECOMMENDATIONS)
        ]
        unrecommendations = [
            Recommendation(rec, score)
            for rec, score in rec_counter.most_common()[:-MAX_RECOMMENDATIONS-1:-1]
        ]

        sorted(recommendations, key=lambda rec: rec.score, reverse=False)
        sorted(unrecommendations, key=lambda rec: rec.score, reverse=True)

        await peer.send_message(
            GetRecommendations.Response(
                recommendations=recommendations,
                unrecommendations=unrecommendations
            )
        )

    @on_message(GetItemRecommendations.Request)
    async def on_get_item_recommendations(self, message: GetItemRecommendations.Request, peer: Peer):
        """
        * Excludes the item itself
        * Includes the interests of the user

        TODO:
        * What is the max (currently 100)
        """
        rec_counter = self.get_recommendations_for_item(message.item)
        del rec_counter[message.item]

        recommendations: List[Recommendation] = []
        for rec, score in rec_counter.most_common(MAX_RECOMMENDATIONS):
            recommendations.append(Recommendation(rec, score))

        sorted(recommendations, key=lambda rec: rec.score, reverse=False)

        await peer.send_message(
            GetItemRecommendations.Response(
                item=message.item,
                recommendations=recommendations
            )
        )

    @on_message(GetItemSimilarUsers.Request)
    async def on_get_item_similar_users(self, message: GetItemSimilarUsers.Request, peer: Peer):
        """
        Behaviour:
        * Includes self

        TODO:
        * What's the max?
        """
        similar_users = []
        for other_peer in self.get_valid_peers():
            if message.item in other_peer.user.interests:
                similar_users.append(other_peer.user.name)

        await peer.send_message(
            GetItemSimilarUsers.Response(
                message.item,
                usernames=[similar_user for similar_user in similar_users]
            )
        )

    @on_message(GetSimilarUsers.Request)
    async def on_get_similar_users(self, message: GetSimilarUsers.Request, peer: Peer):
        """
        Behaviour:
        * Only online / away users
        * List is returned unsorted
        * Excludes self

        TODO:
        * What's the max? (at least >= 452)
        * There appears to be no sorting (user with more similar interests does
          not go on top of the list). This also needs more investigation
        """
        similar_users = []
        for other_peer in self.get_valid_peers():
            if other_peer == peer:
                continue

            overlap = peer.user.interests.intersection(other_peer.user.interests)
            if overlap:
                similar_users.append((other_peer.user.name, len(overlap), ))

        await peer.send_message(
            GetSimilarUsers.Response(
                users=[
                    SimilarUser(similar_user, overlap_amount)
                    for similar_user, overlap_amount in similar_users
                ]
            )
        )

    @on_message(GetUserInterests.Request)
    async def on_get_user_interests(self, message: GetUserInterests.Request, peer: Peer):
        """
        Behaviour:
        * Empty string is accepted
        * No whitespace trimming is done
        * Non-existing user returns empty recommendations
        """
        if (user := self.find_user_by_name(message.username)) is not None:
            await peer.send_message(
                GetUserInterests.Response(
                    username=message.username,
                    interests=list(user.interests),
                    hated_interests=list(user.hated_interests)
                )
            )

        else:
            await peer.send_message(
                GetUserInterests.Response(
                    username=message.username,
                    interests=[],
                    hated_interests=[]
                )
            )

    @on_message(AddInterest.Request)
    async def on_add_interest(self, message: AddInterest.Request, peer: Peer):
        """
        Behaviour:
        * Returns nothing when accepted
        * Empty string is accepted and returned through GetUserInterests
        * Duplicates are ignored (GetUserInterests will only return 1)

        To investigate:
        * Input error: Longest possible?
        """
        peer.user.interests.add(message.interest)

    @on_message(RemoveInterest.Request)
    async def on_remove_interest(self, message: RemoveInterest.Request, peer: Peer):
        """
        Behaviour:
        * Returns nothing when accepted
        * Removing an interest that is not an interest does nothing (no error)

        To investigate:
        * Input error: Longest possible?
        """
        peer.user.interests.discard(message.interest)

    @on_message(AddHatedInterest.Request)
    async def on_add_hated_interest(self, message: AddHatedInterest.Request, peer: Peer):
        peer.user.hated_interests.add(message.hated_interest)

    @on_message(RemoveHatedInterest.Request)
    async def on_remove_hated_interest(self, message: RemoveHatedInterest.Request, peer: Peer):
        peer.user.hated_interests.discard(message.hated_interest)

    @on_message(SendUploadSpeed.Request)
    async def on_send_upload_speed(self, message: SendUploadSpeed.Request, peer: Peer):
        new_speed = (peer.user.avg_speed * peer.user.uploads) + message.speed
        new_speed /= (peer.user.uploads + 1)
        peer.user.avg_speed = int(new_speed)

        peer.user.uploads += 1

    @on_message(TogglePrivateRoomInvites.Request)
    async def on_toggle_private_rooms(self, message: TogglePrivateRoomInvites.Request, peer: Peer):
        peer.user.enable_private_rooms = message.enable

    @on_message(ToggleParentSearch.Request)
    async def on_toggle_parent_search(self, message: ToggleParentSearch.Request, peer: Peer):
        peer.user.enable_parent_search = message.enable

    @on_message(AcceptChildren.Request)
    async def on_accept_children(self, message: AcceptChildren.Request, peer: Peer):
        peer.user.accept_children = message.accept

    @on_message(EnablePublicChat.Request)
    async def on_chat_enable_public(self, message: EnablePublicChat.Request, peer: Peer):
        peer.user.enable_public_chat = True

    @on_message(DisablePublicChat.Request)
    async def on_chat_disable_public(self, message: DisablePublicChat.Request, peer: Peer):
        peer.user.enable_public_chat = False

    @on_message(Ping.Request)
    async def on_ping(self, message: Ping.Request, peer: Peer):
        peer.last_ping = time.time()

    @on_message(JoinRoom.Request)
    async def on_join_room(self, message: JoinRoom.Request, peer: Peer):
        if not message.room:
            await self.send_admin_message(
                AdminMessage.ROOM_CANNOT_CREATE_EMPTY,
                peer
            )
            return
        elif not message.room.strip() == message.room:
            await self.send_admin_message(
                AdminMessage.ROOM_CANNOT_CREATE_SPACES.format(message.room),
                peer
            )
            return
        elif re.match(r'.*[\s]{2,}.*', message.room) is not None:
            await self.send_admin_message(
                AdminMessage.ROOM_CANNOT_CREATE_SPACES_MULTIPLE.format(message.room),
                peer
            )
            return
        elif not message.room.isascii():
            await self.send_admin_message(
                AdminMessage.ROOM_CANNOT_CREATE_INVALID_CHARACTERS.format(message.room),
                peer
            )
            return

        existing_room = self.find_room_by_name(message.room)
        room = existing_room if existing_room else Room(name=message.room)

        is_private = bool(message.is_private)

        if room.status == RoomStatus.PRIVATE:

            # Check if the user is a member and can join
            if not existing_room.can_join(peer.user):
                await peer.send_message(
                    CannotCreateRoom.Response(message.room)
                )
                await self.send_admin_message(
                    AdminMessage.ROOM_CANNOT_ENTER_PRIVATE_ROOM.format(message.room),
                    peer
                )
                return

        elif room.status == RoomStatus.PUBLIC:

            # User request to join a room: regardless on whether he requested
            # it as private or not, the room should be joined if it is a public
            # room
            pass

        else:
            if room.registered_as_public and is_private:
                # Prevent a public room from becoming a private room if it was
                # registered as public. This results in simply a warning and
                # joining the room anyway

                await self.send_admin_message(
                    AdminMessage.ROOM_CANNOT_CREATE_PUBLIC.format(message.room)
                )

            else:
                # Unclaimed or non-existent room
                room.owner = peer.user if is_private else None
                room.registered_as_public = not is_private
                if room not in self.rooms:
                    self.rooms.append(room)

                if is_private:
                    await self.send_room_list_update(peer.user)

        # Join the user to the room
        if peer.user not in room.joined_users:
            await self.join_room(room, peer)

    @on_message(LeaveRoom.Request)
    async def on_chat_leave_room(self, message: LeaveRoom.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        if room:
            if peer.user in room.joined_users:
                await self.leave_room(room, peer)

    @on_message(PrivateRoomDropMembership.Request)
    async def on_private_room_drop_membership(self, message: PrivateRoomDropMembership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)

        if not room:
            return

        # Handles: public rooms (empty members), owner (not part of members),
        # user not a member
        if peer.user in room.members:
            await self.revoke_membership(room, peer.user)
            await self.revoke_operator(room, peer.user)

    @on_message(PrivateRoomDropOwnership.Request)
    async def on_private_room_drop_ownership(self, message: PrivateRoomDropOwnership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)

        if not room:
            return

        if peer.user != room.owner:
            return

        # Keep a reference to all the current members (excludes owner) then
        # reset all private room related values. Resetting the values will
        # ensure that some messages do not get sent when `revoke_membership` is
        # called for that member.
        # Messages that should be sent:
        # * Send PrivateRoomMembershipRevoked to the member
        # * Execute room leave function -> Because joined_users is not reset
        #   everyone will be informed that the user left the room
        # * The member should get a room list update, because the members list
        #   is reset he will no longer see the room in the list
        # Messages that should not be sent:
        # * members should not get a notification that the member is removed
        #   (PrivateRoomRevokeMembership) because the members list for the room is empty
        # * owner should not get a server notification because owner variable no longer set)
        members = room.members

        room.owner = None
        # TODO: Might need to check if operators actually get reset
        room.operators = []
        room.members = []

        for member in members:
            await self.revoke_membership(room, member)

    @on_message(PrivateRoomGrantMembership.Request)
    async def on_private_room_grant_membership(self, message: PrivateRoomGrantMembership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)
        peer_to_add = self.find_peer_by_name(message.username)

        if not room:
            return

        # Permissions check + also handles attempting to add member to public room
        if not room.can_add(peer.user):
            return

        # Cannot add self
        if peer.user.name == message.username:
            return

        if not user or user.status == UserStatus.OFFLINE:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_OFFLINE.format(message.username),
                peer
            )
            return

        if not peer_to_add:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_OFFLINE.format(message.username),
                peer
            )
            return

        if not user.enable_private_rooms:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_NOT_ACCEPTING_INVITES.format(message.username),
                peer
            )
            return

        if room.owner.name == message.username:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_IS_OWNER.format(message.username, message.room),
                peer
            )
            return

        if user in room.members:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_ALREADY_MEMBER.format(message.username, message.room),
                peer
            )
            return

        await self.grant_membership(room, user, peer.user)

    @on_message(PrivateRoomRevokeMembership.Request)
    async def on_private_room_revoke_membership(self, message: PrivateRoomRevokeMembership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)

        if not user:
            return

        if not room:
            return

        if message.username == peer.user.name:
            return

        if user not in room.all_members:
            return

        if not room.can_remove(peer.user, user):
            return

        await self.revoke_membership(room, user)

    @on_message(PrivateRoomGrantOperator.Request)
    async def on_private_room_grant_operator(self, message: PrivateRoomGrantOperator.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)
        peer_to_add = self.find_peer_by_name(message.username)

        if not user:
            return

        if not room:
            return

        if not user or user.status == UserStatus.OFFLINE:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_OFFLINE.format(message.username),
                peer
            )
            return

        if not peer_to_add:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_OFFLINE.format(message.username),
                peer
            )
            return

        if peer.user != room.owner:
            return

        if user in room.operators:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_OPERATOR_ALREADY_OPERATOR.format(user.name, room.name),
                peer
            )
            return

        if user not in room.members:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_OPERATOR_USER_IS_NOT_MEMBER.format(user.name, room.name),
                peer
            )

        await self.grant_operator(room, user)

    @on_message(PrivateRoomRevokeOperator.Request)
    async def on_private_room_revoke_operator(self, message: PrivateRoomRevokeOperator.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)

        if not user:
            return
        if not room:
            return
        if peer.user != room.owner:
            return

        if user not in room.all_members:
            return

        await self.revoke_operator(room, user)

    async def send_status_update(self, user: User):
        """Sends out a status update for the given user to:
        * The user itself
        * Users who have the user in their ``add_users`` list
        * Users who are in the same room as the user
        """
        peer = self.find_peer_by_name(user.name)

        status_message = GetUserStatus.Response(
            username=user.name,
            status=user.status.value,
            privileged=user.privileged
        )

        # Notify the user who is changing his status. Not applicable for statuses:
        # * OFFLINE: user disconnected and thus will not receive the message
        #            anyway
        # * ONLINE: message is not sent during logon. This causes the message
        #           not to be sent when setting status from Away to Online.
        #           This is intentional
        if user.status not in (UserStatus.OFFLINE, UserStatus.ONLINE):
            await peer.send_message(status_message)

        # Notify users who are tracking the users
        await self.notify_added_users(user, status_message)

        # Notify all users in rooms which the user is part of
        for room in self.get_joined_rooms(user):
            await self.notify_room_joined_users(room, status_message)

    async def send_stats_update(self, user: User):
        stats_message = GetUserStats.Response(
            username=user.name,
            user_stats=UserStats(
                avg_speed=user.avg_speed,
                uploads=user.uploads,
                shared_file_count=user.shared_file_count,
                shared_folder_count=user.shared_folder_count
            )
        )
        for room in self.get_joined_rooms(user):
            await self.notify_room_joined_users(room, stats_message)

    async def send_queued_private_messages(self, peer: Peer):
        """Sends all private messages to the peer"""
        for queued_message in peer.user.queued_private_messages:
            await peer.send_message(
                queued_message.to_protocol_message(is_direct=False))

    async def create_public_room(self, name: str) -> Room:
        """Creates a new private room, should be called when all checks are
        complete
        """
        logger.info(f"creating public room {name}")
        room = Room(name=name)
        self.rooms.append(room)
        return room

    async def create_private_room(self, name: str, user: User) -> Room:
        """Creates a new private room, should be called when all checks are
        complete
        """
        logger.info(f"creating new private room {name} with owner {user.name}")
        room = Room(name=name, owner=user)
        self.rooms.append(room)

        await self.send_room_list_update(user)
        return room

    async def send_room_tickers(self, room: Room, peer: Peer):
        # Send room tickers
        await peer.send_message(
            RoomTickers.Response(
                room=room.name,
                tickers=[
                    RoomTicker(
                        username=username,
                        ticker=message
                    ) for username, message in room.tickers.items()
                ]
            )
        )

    async def join_room(self, room: Room, peer: Peer):
        """Joins a user to a room.

        This method will send the appropriate response to the peer and notify
        all joined users in the room
        """
        room.joined_users.append(peer.user)

        # Report to all other users in the room the user has joined
        # Currently includes the newly joined user (intended?)
        user_joined_message = UserJoinedRoom.Response(
            room.name,
            peer.user.name,
            peer.user.status.value,
            UserStats(
                int(peer.user.avg_speed),
                peer.user.uploads,
                peer.user.shared_file_count,
                peer.user.shared_folder_count
            ),
            slots_free=peer.user.slots_free,
            country_code=peer.user.country
        )
        await self.notify_room_joined_users(room, user_joined_message)

        # Report to the user he has joined successfully (no mistake)
        await peer.send_message(
            JoinRoom.Response(
                room.name,
                users=[
                    user.name
                    for user in room.joined_users
                ],
                users_status=[
                    user.status.value
                    for user in room.joined_users
                ],
                users_stats=[
                    UserStats(user.avg_speed, user.uploads, user.shared_file_count, user.shared_folder_count)
                    for user in room.joined_users
                ],
                users_slots_free=[
                    user.slots_free
                    for user in room.joined_users
                ],
                users_countries=[
                    user.country
                    for user in room.joined_users
                ],
                owner=room.owner.name if room.status == RoomStatus.PRIVATE else None,
                operators=[operator.name for operator in room.operators] if room.status == RoomStatus.PRIVATE else None
            )
        )
        await self.send_room_tickers(room, peer)

    async def leave_room(self, room: Room, peer: Peer):
        """Removes the user from the joined users.

        This method will do nothing in case the user is not joined. Otherwise the
        message will be sent to the peer and the joined users in the room will be
        notified.

        * Send LeaveRoom to leaving user
        * Send UserLeftRoom to other joined users
        """
        if peer.user not in room.joined_users:
            return

        room.joined_users.remove(peer.user)

        await peer.send_message(LeaveRoom.Response(room.name))

        user_left_message = UserLeftRoom.Response(room.name, peer.user.name)
        await self.notify_room_joined_users(room, user_left_message)

    async def notify_room_owner(self, room: Room, message: str):
        """Sends an admin message to the room owner"""
        if not room.owner:
            return

        peer = self.find_peer_by_name(room.owner.name)
        if peer:
            await self.send_admin_message(message, peer)

    async def notify_room_members(self, room: Room, message: MessageDataclass):
        """Sends a protocol message to all members in the given private room"""
        tasks = []
        for user in room.all_members:
            peer = self.find_peer_by_name(user.name)
            if peer:
                tasks.append(peer.send_message(message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def notify_room_joined_users(self, room: Room, message: MessageDataclass):
        """Sends a protocol message to all joined users in the given room"""
        tasks = []
        for user in room.joined_users:
            peer = self.find_peer_by_name(user.name)
            if peer:
                tasks.append(peer.send_message(message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def notify_added_users(self, user: User, message: MessageDataclass):
        """Sends a protocol message to the users who have the given user in
        their ``added_users`` list
        """
        peers = self.get_valid_peers()

        tasks = []
        for peer in peers:
            if user.name not in peer.user.added_users:
                continue

            tasks.append(peer.send_message(message))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def grant_membership(self, room: Room, user: User, granting_user: User):
        """Adds a user to a private room

        :param room: The private room to add the user to
        :param user: The user to add to the private room
        :param granting_user: The user adding the other user
        """
        # Add user to room
        room.members.append(user)

        # Notify the room members (intentional: includes the newly added member)
        await self.notify_room_members(
            room, PrivateRoomGrantMembership.Response(room.name, user.name))

        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomMembershipGranted.Response(room.name))
            await self.send_room_list_update(target_peer.user)

        # Notify owner
        if granting_user in room.operators:
            msg = AdminMessage.PRIVATE_ROOM_USER_ADDED_BY_OPERATOR.format(
                user.name, room.name, granting_user.name
            )
        else:
            msg = AdminMessage.PRIVATE_ROOM_USER_ADDED.format(
                user.name, room.name
            )
        await self.notify_room_owner(room, msg)

    async def revoke_membership(self, room: Room, user: User):
        """Removes a user from a private room

        * Send PrivateRoomMembershipRevoked to the removed user
        * Send PrivateRoomRevokeMembership message to other members in the room
        * Send message to owner notifying user is removed from room
        * Leaves the room if necessary
        * Send updated private room info
        """
        room.members.remove(user)

        # Notify the person being removed
        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomMembershipRevoked.Response(room.name))

        # Notify all other members. This message is not sent to the removed
        # member
        message = PrivateRoomRevokeMembership.Response(room.name, user.name)
        await self.notify_room_members(room, message)

        # Notify the owner
        # No specialized message for operator (unlike during granting)
        await self.notify_room_owner(
            room,
            AdminMessage.PRIVATE_ROOM_USER_REMOVED.format(user.name, room.name)
        )

        # Leave the room if the user is joined and send private room updates
        if target_peer:
            await self.leave_room(room, target_peer)
            await self.send_room_list_update(user)

    async def grant_operator(self, room: Room, user: User):
        """Grants operator privileges to a user in a private room"""
        logger.info(f"granting operator to {user.name} on room {room.name}")
        room.operators.append(user)

        # Notify all other members. This message is not sent to the removed
        # member
        # ALSO NOTIFY JOINED USERS (don't know why)
        message = PrivateRoomGrantOperator.Response(room.name, user.name)
        await self.notify_room_members(room, message)
        await self.notify_room_joined_users(room, message)

        # Send message to the user being granted operator
        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomOperatorGranted.Response(room.name))
            await self.send_room_list_update(target_peer.user)

        # Notify the owner
        await self.notify_room_owner(
            room,
            AdminMessage.PRIVATE_ROOM_OPERATOR_GRANTED.format(user.name, room.name)
        )

    async def revoke_operator(self, room: Room, user: User):
        """Revokes operator privileges from a user in a private room. Does
        nothing if the user is not an operator
        """
        if user not in room.operators:
            return

        logger.info(f"revoking operator from {user.name} on room {room.name}")
        room.operators.remove(user)

        # Notify all other members. This message is not sent to the removed
        # member
        # ALSO NOTIFY JOINED USERS (don't know why)
        message = PrivateRoomRevokeOperator.Response(room.name, user.name)
        await self.notify_room_members(room, message)
        await self.notify_room_joined_users(room, message)

        # Send message to the user being revoked operator
        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomOperatorRevoked.Response(room.name))
            await self.send_room_list_update(target_peer.user)

        # Notify the owner
        await self.notify_room_owner(
            room,
            AdminMessage.PRIVATE_ROOM_OPERATOR_REVOKED.format(user.name, room.name)
        )

    def get_global_recommendations(self) -> typing.Counter[str]:
        """Gets global recommendations

        :return: List of global recommendations for this item. This still needs
            to be split into recommendations and unrecommendations
        """
        recommendations = Counter()
        for peer in self.get_valid_peers():
            recommendations.update(peer.user.interests)
            recommendations.subtract(peer.user.hated_interests)

        # Unverified
        remove_0_values(recommendations)

        return recommendations

    def get_recommendations_for_item(self, item: str) -> typing.Counter[str]:
        """Gets item recommendations

        :return: List of recommendations for this item. This still includes
            the item itself and needs still needs to be split into
            recommendations and unrecommendations
        """
        recommendations = Counter()
        for peer in self.get_valid_peers():
            if item in peer.user.interests:
                recommendations.update(peer.user.interests)
                recommendations.subtract(peer.user.hated_interests)

        remove_0_values(recommendations)

        return recommendations

    def get_recommendations_for_user(self, user: User) -> typing.Counter[str]:
        """Gets all recommendations of a user based on his interests"""
        counter = Counter()
        for other_peer in self.get_valid_peers():
            if other_peer.user == user:
                continue

            for interest in user.interests:
                if interest in other_peer.user.interests:
                    counter.update(other_peer.user.interests)
                    counter.subtract(other_peer.user.hated_interests)

                if interest in other_peer.user.hated_interests:
                    counter.subtract(other_peer.user.interests)


            for hated_interest in user.hated_interests:
                if hated_interest in other_peer.user.interests:
                    counter.subtract(other_peer.user.interests)

        # Remove
        for to_remove in user.interests | user.hated_interests:
            del counter[to_remove]

        # Remove 0 values
        remove_0_values(counter)

        return counter


def _get_distributed_strategy_class(name: str) -> Type[DistributedStrategy]:
    for strategy_cls in DistributedStrategy.__subclasses__():
        if strategy_cls.get_name() == name:
            return strategy_cls

    raise ValueError(f'invalid distributed strategy : {name}')


async def main(args):
    # Parse mock variables
    prefix = 'mock_'
    mock_vars = {
        name[len(prefix):]: value for name, value in vars(args).items()
        if name.startswith(prefix)
    }

    distributed_strategy_cls = _get_distributed_strategy_class(args.distributed_strategy)

    admin_users = [
        User(name='admin0', password='pass0', is_admin=True),
    ]

    privileged_users = [
        User(name='priv0', password='pass0', privileges_time_left=3600 * 24 * 7)
    ]

    mock_server = MockServer(
        ports=set(args.port),
        distributed_strategy_class=distributed_strategy_cls,
        potential_parent_interval=args.potential_parent_interval,
        mock_variables=MockVariables(**mock_vars)
    )
    mock_server.users.extend(admin_users + privileged_users)

    await mock_server.connect()
    serving_tasks = [
        connection.serve_forever()
        for connection in mock_server.connections.values()
    ]
    await asyncio.gather(*serving_tasks)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--port',
        help=(
            "Port(s) to listen on. Multiple ports can be provided which can be "
            "useful when testing different clients"
        ),
        nargs="+",
        type=int,
        default=[2416]
    )
    parser.add_argument(
        '--distributed-strategy',
        help="Distributed strategy to use. Default is to treat everyone as a root",
        default='everyone_root',
        choices=[
            strategy_cls.get_name()
            for strategy_cls in DistributedStrategy.__subclasses__()
        ]
    )
    parser.add_argument(
        '--potential-parent-interval',
        help=(
            "Interval in seconds at which potential parents will be announced to "
            "peers looking for a parent. Use a value of 0 or less to disable"
        ),
        default=0,
        type=int
    )

    # Mock variables argument group
    mock_vars_group = parser.add_argument_group(title="Mock variables")
    mock_vars_group.add_argument(
        '--mock-upload-speed',
        help=(
            "Assign a default average upload speed to users connecting. Useful "
            "when testing distributed connections"
        ),
        default=0,
        type=float
    )
    mock_vars_group.add_argument(
        '--mock-search-interval',
        help=(
            "Periodically send a search request through the distributed network"
        ),
        default=0,
        type=float
    )

    args = parser.parse_args()

    asyncio.run(main(args))
