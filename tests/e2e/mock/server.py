import asyncio
from collections import Counter
import logging
import re
import socket
import time
from typing import Dict, List, Tuple
import typing

from aioslsk.events import on_message, build_message_map
from aioslsk.user.model import UserStatus
from aioslsk.protocol.primitives import (
    calc_md5,
    PotentialParent,
    Recommendation,
    RoomTicker,
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
    FileSearch,
    GetRelatedSearches,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetPeerAddress,
    GetRecommendations,
    GetSimilarUsers,
    GetUserStats,
    GetUserStatus,
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
from tests.e2e.mock.constants import MAX_RECOMMENDATIONS
from tests.e2e.mock.messages import AdminMessage
from tests.e2e.mock.model import User, Room, Settings
from tests.e2e.mock.peer import Peer


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def chat_id_generator(initial: int = 1) -> int:
    idx = initial
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = initial
        yield idx


class DistributedStrategy:

    def __init__(self, peers: List[Peer]):
        self.peers: List[Peer] = peers

    def get_peers_accepting_children(self) -> List[Peer]:
        """Returns a list of all peers that are:

        * Not looking for a parent
        * Accepting children
        """
        eligable_peers = []
        for peer in self.peers:
            if not peer.user.accept_children:
                continue

            if peer.user.enable_parent_search:
                continue

            if peer.branch_level is None:
                continue

            eligable_peers.append(peer)

        return eligable_peers

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        return []


class ChainParentsStrategy(DistributedStrategy):
    """This strategy simply picks the peers with the highest branch level to be
    potential parents
    """

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        try:
            max_level = max([
                peer.branch_level for peer in self.get_peers_accepting_children()
                if peer != target_peer
            ])
        except ValueError:
            return []

        return [
            peer for peer in self.get_peers_accepting_children()
            if peer.branch_level == max_level and peer != target_peer
        ]


class RealisticParentsStrategy(DistributedStrategy):

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        """Implement a more realistic parent strategy.

        There is a max on how many children a parent can have based on upload
        speed. Perhaps there is a way to sort parents by upload speed.

        Eg.: if peer0 has upload speed of 2000 and a max of 10 children is
        configured, he can have 10 children that have a upload speed of 200.
        Those children can then have 10 children whose upload speed is 20, etc.

        So if a peer has an upload speed of roughly 200, suggest peer0 as parent
        if it has not reached its max limit yet (become level 1). If he has
        roughly upload speed of 20 suggest one of the level 1 peers (become level 2).

        Perhaps it could be testable if it is more realistic. When receiving a
        parent, check its speed and check the speed of the root and try a couple
        of times to see if any conclusions could be drawn.

        Not sure how to determine if someone should be branch root though. Possibly:
        * If the upload speed is greater than all others? -> that could cause issues
        * If the upload speed is greater than the lowest upload speed of one of
          the branch roots
        """


class MockServer:

    def __init__(
            self, hostname: str = '0.0.0.0', port: int = 2416,
            distributed_strategy: DistributedStrategy = None):
        self.hostname: str = hostname
        self.port: int = port
        self.connection: asyncio.Server = None
        self.settings: Settings = Settings()

        self.users: List[User] = []
        self.rooms: List[Room] = []
        self.peers: List[Peer] = []
        self.track_map: Dict[str, List[str]] = {}
        self.distributed_strategy: DistributedStrategy = distributed_strategy or DistributedStrategy(self.peers)

        self.chat_id_gen = chat_id_generator()

        self.MESSAGE_MAP = build_message_map(self)
        self.message_log: List[MessageDataclass] = []

    async def connect(self, start_serving=False) -> asyncio.AbstractServer:
        logger.info(
            f"open {self.hostname}:{self.port} : listening connection")

        self.connection = await asyncio.start_server(
            self.accept_peer,
            self.hostname,
            self.port,
            family=socket.AF_INET,
            start_serving=start_serving
        )
        return self.connection

    async def disconnect_peers(self):
        await asyncio.gather(
            *[peer.disconnect() for peer in self.peers], return_exceptions=True)

    async def disconnect(self):
        logger.debug(f"{self.hostname}:{self.port} : disconnecting")
        try:
            if self.connection is not None:
                if self.connection.is_serving():
                    self.connection.close()
                await self.connection.wait_closed()
            await self.disconnect_peers()

        except Exception as exc:
            logger.warning(
                f"{self.hostname}:{self.port} : exception while disconnecting", exc_info=exc)

        finally:
            logger.debug(f"{self.hostname}:{self.port} : disconnected")

    async def accept_peer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        hostname, port = writer.get_extra_info('peername')
        logger.debug(f"{self.hostname}:{self.port} : accepted connection {hostname}:{port}")
        peer = Peer(hostname, port, self, reader, writer)
        self.peers.append(peer)
        peer.start_reader_loop()

    async def on_peer_disconnected(self, peer: Peer):
        """Called when a peer is disconnected

        This will remove the peer from the tracked peers and send:

        *
        """
        logger.info(f"disconnected peer : {peer!r}")
        if peer in self.peers:
            self.peers.remove(peer)

        if peer.user:
            peer.user.reset()
            # Leave all rooms
            for room in self.get_joined_rooms(peer.user):
                await self.leave_room(room, peer)

            # Send a status update
            await self.send_status_update(peer.user)

    async def on_peer_message(self, message, peer: Peer):
        """Called when a peer receives a message"""
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, peer)

    def get_valid_peers(self) -> List[Peer]:
        """Returns all peers which are logged in (user set)"""
        return [
            peer for peer in self.peers if peer.user
        ]

    def find_peer_by_name(self, username: str) -> Peer:
        for peer in self.peers:
            if peer.user and peer.user.name == username:
                return peer

    def find_user_by_name(self, username: str) -> User:
        for user in self.users:
            if user.name == username:
                return user

    def find_room_by_name(self, name: str) -> Room:
        for room in self.rooms:
            if room.name == name:
                return room

    def get_joined_rooms(self, user: User) -> List[Room]:
        return [room for room in self.rooms if user in room.joined_users]

    def get_user(self, name: str) -> User:
        for user in self.users:
            if user.name == name:
                return user
        else:
            raise ValueError('user does not exist')

    def get_distributed_roots(self) -> List[Peer]:
        roots = [
            peer for peer in self.peers
            if peer.branch_level == 0 and not peer.user.enable_parent_search
        ]
        if not roots:
            return [
                peer for peer in self.peers
                if peer.branch_level == 0
            ]
        else:
            return roots

    async def send_search_request(self, username: str, sender: str, query: str, ticket: int):
        """This a utility method for testing. To make a peer a root the server
        has to send an initial search message to that user

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

    async def send_potential_parents(self, username: str):
        """This is a utility method used for testing to send the potential
        parents to the peer with given username

        :param username: Username of the peer to send the potential parents to
        """
        peer = self.find_peer_by_name(username)

        message = PotentialParents.Response(
            entries=[
                PotentialParent(
                    username=pparent.user.name,
                    ip=pparent.hostname,
                    port=pparent.user.port
                )
                for pparent in self.distributed_strategy.get_potential_parents(peer)
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
                is_admin=True
            )
        )

    async def send_room_list(self, peer: Peer):
        """Send the room list for the user"""
        public_rooms: List[Room] = []
        private_rooms: List[Room] = []
        private_rooms_owned: List[Room] = []
        private_rooms_operated: List[Room] = []
        for room in self.rooms:
            if room.is_private:
                if room.owner == peer.user:
                    private_rooms_owned.append(room)
                else:
                    if peer.user in room.operators:
                        private_rooms_operated.append(room)
                    private_rooms.append(room)
            else:
                public_rooms.append(room)

        await peer.send_message(
            RoomList.Response(
                rooms=[room.name for room in public_rooms],
                rooms_user_count=[len(room.joined_users) for room in public_rooms],
                rooms_private=[room.name for room in private_rooms],
                rooms_private_user_count=[len(room.joined_users) for room in private_rooms],
                rooms_private_owned=[room.name for room in private_rooms_owned],
                rooms_private_owned_user_count=[len(room.joined_users) for room in private_rooms_owned],
                rooms_private_operated=[room.name for room in private_rooms_operated]
            )
        )

    async def send_all_private_room_info(self, user: User):
        """Sends a user the info on the private rooms he is in

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

        await self.send_room_list(peer)

        # Following is done in 2 loops deliberatly
        # PrivateRoomMembers (excludes owner, includes operators)
        for room in self.rooms:
            if peer.user not in room.members:
                continue

            await peer.send_message(
                PrivateRoomMembers.Response(
                    room=room.name,
                    usernames=[member.name for member in room.members if member != room.owner]
                )
            )

        # RoomOperators (only operators)
        for room in self.rooms:
            if peer.user not in room.members:
                continue

            await peer.send_message(
                PrivateRoomOperators.Response(
                    room=room.name,
                    usernames=[member.name for member in room.operators]
                )
            )

    async def notify_trackers_status(self, user: User):
        """Notify the peers tracking the given user of status changes"""
        if user.name not in self.track_map:
            return

        message = GetUserStatus.Response(
            username=user.name,
            status=user.status.value,
            privileged=user.privileged
        )

        tasks = []
        for tracker_name in self.track_map[user.name]:
            tracker_peer = self.find_peer_by_name(tracker_name)
            if tracker_peer:
                tasks.append(tracker_peer.send_message(message))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def notify_trackers(self, user: User):
        """Notify the peers tracking the given user of changes"""
        if user.name not in self.track_map:
            return

        tasks = []
        message = AddUser.Response(
            user.name,
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

        for username in self.track_map[user.name]:
            for peer in self.get_valid_peers():
                if peer.user.name == username:
                    tasks.append(peer.send_message(message))

        await asyncio.gather(*tasks, return_exceptions=True)

    @on_message(ExactFileSearch.Request)
    async def on_ExactFileSearch(self, message: ExactFileSearch.Request, peer: Peer):
        pass

    @on_message(Login.Request)
    async def on_login(self, message: Login.Request, peer: Peer):
        # Check if username entered is valid
        if not message.username:
            await peer.send_message(Login.Response(
                success=False,
                reason='INVALIDUSERNAME'
            ))
            return

        # Check if we have a user, if so check the password
        user = self.find_user_by_name(message.username)
        if user and message.password != user.password:
            await peer.send_message(Login.Response(
                success=False,
                reason='INVALIDPASS'
            ))
            return

        # Login is successful, just need to check if we need to create a new user
        # or this user is already logged in elsewhere
        if user:
            # Check if there is another peer
            other_peer = self.find_peer_by_name(message.username)
            if other_peer:
                other_peer.user = None
                await other_peer.send_message(Kicked.Response())
                await other_peer.disconnect()
        else:
            # Create a new user if we did not have it yet
            user = User(
                message.username,
                password=message.password
            )
            self.users.append(user)

        # Send success response and set user/peer

        peer.user = user
        user.status = UserStatus.ONLINE
        # TODO: Check if tracking users are notified (and if the initial status
        # is actually online or the last status the user had)

        await peer.send_message(Login.Response(
            success=True,
            greeting='',
            ip=peer.hostname,
            md5hash=calc_md5(message.password),
            privileged=False
        ))

        # Send all post login messages
        await self.send_room_list(peer)
        await peer.send_message(
            ParentMinSpeed.Response(self.settings.parent_min_speed))
        await peer.send_message(
            ParentSpeedRatio.Response(self.settings.parent_speed_ratio))
        await peer.send_message(
            WishlistInterval.Response(self.settings.wishlist_interval))
        await peer.send_message(
            PrivilegedUsers.Response([user.name for user in self.users if user.privileged]))

    @on_message(SetListenPort.Request)
    async def on_listen_port(self, message: SetListenPort.Request, peer: Peer):
        peer.user.port = message.port
        peer.user.obfuscated_port = message.obfuscated_port

    @on_message(CheckPrivileges.Request)
    async def on_check_privileges(self, message: CheckPrivileges.Request, peer: Peer):
        if peer.user is None:
            return

        await peer.send_message(CheckPrivileges.Response(
            peer.user.privileges_time_left
        ))

    @on_message(RoomList.Request)
    async def on_room_list(self, message: RoomList.Request, peer: Peer):
        await self.send_room_list(peer)

    @on_message(AddUser.Request)
    async def on_add_user(self, message: AddUser.Request, peer: Peer):
        """
        TODO: Investigate
        * Empty username
        * Track user already tracked
        """
        if (user := self.find_user_by_name(message.username)) is not None:
            if message.username in self.track_map:
                self.track_map[message.username].append(peer.user.name)
            else:
                self.track_map[message.username] = [peer.user.name]

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
        """User sends a private message to multiple users

        TODO: Investigate:
        * Empty list
        * Empty message
        * One/multiple of the users does not exist
        * One/multiple of the users is not connected
        """
        timestamp = int(time.time())
        messages = []
        for username in message.usernames:
            if (user := self.find_user_by_name(username)) is None:
                continue

            if (receiving_peer := self.find_peer_by_name(username)) is None:
                continue

            messages.append(receiving_peer.send_message(
                PrivateChatMessage.Response(
                    next(self.chat_id_gen),
                    timestamp,
                    message=message.message,
                    username=peer.user.name,
                    is_admin=peer.user.is_admin
                )
            ))

        asyncio.gather(*messages, return_exceptions=True)

    @on_message(PrivateChatMessage.Request)
    async def on_chat_private_message(self, message: PrivateChatMessage.Request, peer: Peer):
        """User sends a private message to a another user

        TODO: Investigate:
        * Empty username
        * Empty message
        * User does not exist
        * Does message get queued and sent if user is valid but not online
        * Trimming of messages?
        """
        if not peer.user:
            return

        # Do nothing when sending u user that does not exist
        if self.find_user_by_name(message.username) is None:
            return

        # User exists but is currently not connected
        if (peer_receiver := self.find_peer_by_name(message.username)) is None:
            return

        await peer_receiver.send_message(
            PrivateChatMessage.Response(
                next(self.chat_id_gen),
                timestamp=int(time.time()),
                message=message.message,
                username=peer.user.name,
                is_admin=peer.user.is_admin
            )
        )

    @on_message(RoomChatMessage.Request)
    async def on_chat_room_message(self, message: RoomChatMessage.Request, peer: Peer):
        """

        TODO:
        * Check if users who joined a public room and have the public chat
            enabled receive it twice (also the order)
        """
        if not peer.user:
            return

        if not message.message:
            return

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
        futures = []
        for peer in self.get_valid_peers():
            if peer.user in room.joined_users:
                futures.append(peer.send_message(room_message))

        # Send to public chat
        if not room.is_private:
            public_message = PublicChatMessage.Response(
                room=room.name,
                username=peer.user.name,
                message=message.message
            )
            for peer in self.get_valid_peers():
                if peer.user.enable_public_chat:
                    futures.append(public_message)

        await asyncio.gather(*futures, return_exceptions=True)

    @on_message(RemoveUser.Request)
    async def on_remove_user(self, message: RemoveUser.Request, peer: Peer):
        if not peer.user:
            return

        if message.username in self.track_map:
            if peer.user.name in self.track_map[message.username]:
                self.track_map[message.username].remove(peer.user.name)

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

    @on_message(SharedFoldersFiles.Request)
    async def on_shared_folders_files(self, message: SharedFoldersFiles.Request, peer: Peer):
        peer.user.shared_folder_count = message.shared_folder_count
        peer.user.shared_file_count = message.shared_file_count

    @on_message(SetStatus.Request)
    async def on_set_status(self, message: SetStatus.Request, peer: Peer):
        """
        TODO: Investigates
        * Invalid status (also try offline)
        TODO:
        * Send GetUserStatus message to users in rooms
        """
        if not peer.user:
            return

        peer.user.status = UserStatus(message.status)
        await self.send_status_update(peer.user)

    @on_message(GetPeerAddress.Request)
    async def on_get_peer_address(self, message: GetPeerAddress.Request, peer: Peer):
        for other_peer in self.peers:
            if other_peer.user.name == message.username:
                await peer.send_message(
                    GetPeerAddress.Response(
                        message.username,
                        other_peer.hostname,
                        port=other_peer.user.port,
                        obfuscated_port_amount=1 if other_peer.user.obfuscated_port else 0,
                        obfuscated_port=other_peer.user.obfuscated_port
                    )
                )
                break

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
        peer.branch_level = message.level

    @on_message(BranchRoot.Request)
    async def on_branch_root(self, message: BranchRoot.Request, peer: Peer):
        peer.branch_root = message.username

    @on_message(ChildDepth.Request)
    async def on_child_depth(self, message: ChildDepth.Request, peer: Peer):
        peer.child_depth = message.depth

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
        if peer.user is None:
            return

        if (room := self.find_room_by_name(message.room)) is None:
            return

        if peer.user not in room.members:
            return

        message = FileSearch(
            username=peer.user.name,
            ticket=message.ticket,
            query=message.query
        )

        await self.notify_room_users(room, message)

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
        if peer.user is None:
            return

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
            *[peer.send_message(message) for peer in self.get_distributed_roots()],
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
        logger.debug("in ticker set")
        if (room := self.find_room_by_name(message.room)) is None:
            logger.debug("did not find room")
            return

        if peer.user is None:
            logger.debug("user was not set for peer")
            return

        if peer.user not in room.joined_users:
            logger.debug(f"user has not joined the room : {room.joined_users}")
            return

        # TODO: Other validations (empty message...)

        # Remove the ticker if it was set
        if peer.user.name in room.tickers:
            del room.tickers[peer.user.name]
            remove_message = RoomTickerRemoved.Response(
                room=room.name,
                username=peer.user.name
            )
            await self.notify_room_users(room, remove_message)

        logger.debug(f"setting ticker : {peer.user.name} : {message.ticker}")
        room.tickers[peer.user.name] = message.ticker

        add_message = RoomTickerAdded.Response(
            room=room.name,
            username=peer.user.name,
            ticker=message.ticker
        )

        await self.notify_room_users(room, add_message)

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
            for rec, score in rec_counter.most_common(MAX_RECOMMENDATIONS)
        ]
        unrecommendations = [
            Recommendation(rec, score)
            for rec, score in rec_counter.most_common()[:-MAX_RECOMMENDATIONS-1:-1]
        ]

        await peer.send_message(
            GetGlobalRecommendations.Response(
                recommendations=recommendations,
                unrecommendations=unrecommendations
            )
        )

    @on_message(GetRecommendations.Request)
    async def on_get_recommendations(self, message: GetRecommendations.Request, peer: Peer):
        """
        TODO: Implementation
        """
        await peer.send_message(
            GetRecommendations.Response(
                recommendations=[],
                unrecommendations=[]
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

        recommendations = []
        for rec, score in rec_counter.most_common(MAX_RECOMMENDATIONS):
            recommendations.append(Recommendation(rec, score))

        await peer.send_message(
            GetItemRecommendations.Response(
                item=message.item,
                recommendations=recommendations
            )
        )

    @on_message(GetSimilarUsers.Request)
    async def on_get_similar_users(self, message: GetSimilarUsers.Request, peer: Peer):
        """
        * Only online / away users

        TODO:
        * Implementation
        * What's the max?
        """
        await peer.send_message(
            GetSimilarUsers.Response(
                users=[]
            )
        )

    @on_message(AddInterest.Request)
    async def on_add_interest(self, message: AddInterest.Request, peer: Peer):
        """
        To investigate:
        - does this return something?
        - input errors
        - duplicate
        """
        peer.user.interests.add(message.interest)

    @on_message(RemoveInterest.Request)
    async def on_remove_interest(self, message: RemoveInterest.Request, peer: Peer):
        """
        To investigate:
        - does this return something?
        - input errors
        - not an interest
        """
        try:
            peer.user.interests.remove(message.interest)
        except KeyError:
            pass

    @on_message(AddHatedInterest.Request)
    async def on_add_hated_interest(self, message: AddHatedInterest.Request, peer: Peer):
        peer.user.hated_interests.add(message.hated_interest)

    @on_message(RemoveHatedInterest.Request)
    async def on_remove_hated_interest(self, message: RemoveHatedInterest.Request, peer: Peer):
        try:
            peer.user.hated_interests.remove(message.hated_interest)
        except KeyError:
            pass

    @on_message(SendUploadSpeed.Request)
    async def on_send_upload_speed(self, message: SendUploadSpeed.Request, peer: Peer):
        """
        TODO: Investigate
        * Formula used for calculation
        """
        if peer.user.uploads == 0:
            peer.user.avg_speed = message.speed
        else:
            new_speed = (peer.user.avg_speed * peer.user.uploads) + message.speed
            new_speed /= (peer.user.uploads + 1)
            peer.user.avg_speed = int(new_speed)

        peer.user.uploads += 1

        await self.notify_trackers(peer.user)

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
        is_private = bool(message.is_private)

        if existing_room:
            if peer.user in existing_room.joined_users:
                # Already in room, do nothing
                return

            # Attempt to join the room
            # We do not need to check if the is_private parameter matches the
            # room's is_private
            if existing_room.is_private:
                if peer.user in existing_room.members:
                    await self.join_room(existing_room, peer)
                else:
                    await peer.send_message(
                        CannotCreateRoom.Response(message.room)
                    )
                    await self.send_admin_message(
                        AdminMessage.ROOM_CANNOT_ENTER_PRIVATE_ROOM.format(message.room),
                        peer
                    )
            else:
                # We get a message when the room is public and we attempt to
                # create it as private (and nobody is inside). It's odd that
                # this is under the joining block but the logic server side
                # might be a little different
                if message.is_private and len(existing_room.joined_users) == 0:
                    await self.send_admin_message(
                        AdminMessage.ROOM_CANNOT_CREATE_PUBLIC.format(message.room)
                    )
                await self.join_room(existing_room, peer)

        else:
            # Create a new room
            if is_private:
                new_room = await self.create_private_room(message.room, peer)
            else:
                new_room = await self.create_public_room(message.room, peer)
            await self.join_room(new_room, peer)

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
        # This covers 2 cases. Not a user of private room and drop membership
        # of public room (since members should be empty for public rooms)
        if peer.user not in room.members:
            return
        # Owner cannot drop membership, he needs to drop ownership
        if peer.user == room.owner:
            return

        await self.remove_from_private_room(room, peer)
        await self.revoke_operator(room, peer.user)

    @on_message(PrivateRoomDropOwnership.Request)
    async def on_private_room_drop_ownership(self, message: PrivateRoomDropOwnership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)

        if not room:
            return
        if room.owner != peer.user:
            return



        self.rooms.remove(room)

    @on_message(PrivateRoomGrantMembership.Request)
    async def on_private_room_add_user(self, message: PrivateRoomGrantMembership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)
        peer_to_add = self.find_peer_by_name(message.username)

        if not room:
            return
        # Permissions
        if not room.can_add(peer.user):
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

        if user in room.members:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_ALREADY_MEMBER.format(message.username, message.room),
                peer
            )
            return

        await self.add_to_private_room(room, user, peer.user)

    @on_message(PrivateRoomRevokeMembership.Request)
    async def on_private_room_remove_user(self, message: PrivateRoomRevokeMembership.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)

        if not user:
            return
        if not room:
            return
        if not room.can_remove(peer.user, user):
            return
        if user not in room.members:
            return

        await self.remove_from_private_room(room, user)

    @on_message(PrivateRoomGrantOperator.Request)
    async def on_private_room_add_operator(self, message: PrivateRoomGrantOperator.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)

        if not user:
            return
        if not room:
            return
        if peer.user != room.owner:
            return
        if user not in room.members:
            return

        await self.grant_operator(room, user)

    @on_message(PrivateRoomRevokeOperator.Request)
    async def on_private_room_remove_operator(self, message: PrivateRoomRevokeOperator.Request, peer: Peer):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)

        if not user:
            return
        if not room:
            return
        if peer.user != room.owner:
            return
        if user not in room.members:
            return

        await self.revoke_operator(room, user)

    async def send_status_update(self, user: User):
        await self.notify_trackers_status(user)

        status_message = GetUserStatus.Response(
            username=user.name,
            status=user.status.value,
            privileged=user.privileged
        )
        for room in self.get_joined_rooms(user):
            await self.notify_room_users(room, status_message)

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
            await self.notify_room_users(room, stats_message)

    async def create_public_room(self, name: str, peer: Peer) -> Room:
        """Creates a new private room, should be called when all checks are
        complete
        """
        logger.info(f"creating public room {name}")
        room = Room(
            name=name,
            is_private=False
        )
        self.rooms.append(room)
        return room

    async def create_private_room(self, name: str, peer: Peer) -> Room:
        """Creates a new private room, should be called when all checks are
        complete
        """
        logger.info(f"creating new private room {name} with owner {peer.user.name}")
        room = Room(
            name=name,
            members=[peer.user, ],
            owner=peer.user,
            is_private=True
        )
        self.rooms.append(room)

        await self.send_all_private_room_info(peer.user)
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
        await self.notify_room_users(room, user_joined_message)

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
                owner=room.owner.name if room.is_private else None,
                operators=[operator.name for operator in room.operators] if room.is_private else None
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
        await self.notify_room_users(room, user_left_message)

    async def notify_room_owner(self, room: Room, message: str):
        """Sends an admin message to the room owner"""
        peer = self.find_peer_by_name(room.owner.name)
        if peer:
            await self.send_admin_message(message, peer)

    async def notify_room_members(self, room: Room, message: MessageDataclass):
        """Sends a protocol message to all members in the given private room"""
        tasks = []
        for user in room.members:
            peer = self.find_peer_by_name(user.name)
            if peer:
                tasks.append(peer.send_message(message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def notify_room_users(self, room: Room, message: MessageDataclass):
        """Sends a protocol message to all joined users in the given room"""
        tasks = []
        for user in room.joined_users:
            peer = self.find_peer_by_name(user.name)
            if peer:
                tasks.append(peer.send_message(message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def add_to_private_room(self, room: Room, user: User, user_adding: User):
        """Adds a user to a private room

        :param room: The private room to add the user to
        :param user: The user to add to the private room
        :param user_adding: The user adding the other user
        """
        # Add user to room
        room.members.append(user)

        # Notify the room members (intentional: includes the newly added member)
        await self.notify_room_members(
            room, PrivateRoomGrantMembership.Response(room.name, user.name))

        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomMembershipGranted.Response(room.name))
            await self.send_all_private_room_info(target_peer.user)

        # Notify owner
        if user_adding in room.operators:
            msg = AdminMessage.PRIVATE_ROOM_USER_ADDED_BY_OPERATOR.format(
                user.name, room.name, user_adding.name
            )
        else:
            msg = AdminMessage.PRIVATE_ROOM_USER_ADDED.format(
                user.name, room.name
            )
        await self.notify_room_owner(room, msg)

    async def remove_from_private_room(self, room: Room, user: User):
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
        # TODO: Check if same message if operator removes
        await self.notify_room_owner(
            room,
            AdminMessage.PRIVATE_ROOM_USER_REMOVED.format(user.name, room.name)
        )

        # Leave the room if the user is joined and send private room updates
        if target_peer:
            await self.leave_room(room, target_peer)
            await self.send_all_private_room_info(user)

    async def grant_operator(self, room: Room, user: User):
        """Grants operator privileges to a user in a private room"""
        logger.info(f"granting operator to {user.name} on room {room.name}")
        room.operators.append(user)

        # Notify all other members. This message is not sent to the removed
        # member
        # ALSO NOTIFY JOINED USERS (don't know why)
        message = PrivateRoomGrantOperator.Response(room.name, user.name)
        await self.notify_room_members(room, message)
        await self.notify_room_users(room, message)

        # Send message to the user being granted operator
        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomOperatorGranted.Response(room.name))
            await self.send_all_private_room_info(target_peer.user)

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
        await self.notify_room_users(room, message)

        # Send message to the user being revoked operator
        target_peer = self.find_peer_by_name(user.name)
        if target_peer:
            await target_peer.send_message(PrivateRoomOperatorRevoked.Response(room.name))
            await self.send_all_private_room_info(target_peer.user)

        # Notify the owner
        await self.notify_room_owner(
            room,
            AdminMessage.PRIVATE_ROOM_OPERATOR_REVOKED.format(user.name, room.name)
        )

    def get_global_recommendations(self) -> typing.Counter[str]:
        recommendations = Counter()
        for peer in self.get_valid_peers():
            recommendations += Counter(peer.user.interests)
            recommendations.subtract(peer.user.hated_interests)

        return recommendations

    def get_recommendations_for_item(self, item: str) -> typing.Counter[str]:
        """Gets global recommendations for a given item

        :return: List of recommendations for this item. This still includes
            the item itself and needs still needs to be split into
            recommendations and unrecommendations
        """
        recommendations = Counter()
        for peer in self.get_valid_peers():
            if item in peer.user.interests:
                recommendations += Counter(peer.user.interests)
                recommendations.subtract(peer.user.hated_interests)

        return recommendations

    def get_recommendations_for_user(self, user: User) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Gets all recommendations of a user based on his interests"""
        recommendations = Counter()
        interests = user.interests


async def main():
    admin_users = [
        User(name='admin0', password='pass0', is_admin=True),
    ]

    privileged_users = [
        User(name='priv0', password='pass0', privileges_time_left=3600 * 24 * 7),
        User(name='Khyle91', password='Test1234', privileges_time_left=3600 * 24 * 7)
    ]

    mock_server = MockServer(port=2240)
    mock_server.users.extend(admin_users + privileged_users)
    async with await mock_server.connect():
        await mock_server.connection.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
