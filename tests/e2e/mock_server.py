import asyncio
from dataclasses import dataclass, field
import logging
import re
import socket
import struct
import time
from typing import Dict, List

from aioslsk.events import on_message, build_message_map
from aioslsk.model import UserStatus
from aioslsk.protocol.primitives import uint32, calc_md5, UserStats
from aioslsk.protocol.messages import (
    MessageDataclass,
    ServerMessage,
    Login,
    SetListenPort,
    AddUser,
    RemoveUser,
    RoomList,
    SharedFoldersFiles,
    GetPeerAddress,
    CannotConnect,
    SetStatus,
    GetUserStats,
    GetUserStatus,
    ConnectToPeer,
    BranchLevel,
    BranchRoot,
    ChildDepth,
    FileSearch,
    ServerSearchRequest,
    SendUploadSpeed,
    ToggleParentSearch,
    TogglePrivateRooms,
    ChatDisablePublic,
    ChatEnablePublic,
    Ping,
    Kicked,
    PrivilegedUsers,
    WishlistInterval,
    ParentMinSpeed,
    ParentSpeedRatio,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatPrivateMessage,
    PrivateRoomUsers,
    PrivateRoomOperators,
    ChatUserJoinedRoom,
    ChatRoomTickers,
    ChatUserLeftRoom,
    CannotCreateRoom,
    PrivateRoomAddUser,
    PrivateRoomRemoveUser,
    PrivateRoomAdded,
    PrivateRoomRemoved,
    PrivateRoomAddOperator,
    PrivateRoomRemoveOperator,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

HEADER_SIZE: int = struct.calcsize('I')


def chat_id_generator(initial: int = 1) -> int:
    idx = initial
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = initial
        yield idx


class AdminMessage:
    PRIVATE_ROOM_USER_ADDED = "User {} is now a member of room {}"
    PRIVATE_ROOM_USER_ADDED_BY_OPERATOR = "User [{}] was added as a member of room [{}] by operator [{}]"
    PRIVATE_ROOM_USER_REMOVED = "User {} is no longer a member of room {}"
    PRIVATE_ROOM_ADD_USER_NOT_ACCEPTING_INVITES = "user {} hasn't enabled private room add. please message them and ask them to do so before trying to add them again."
    PRIVATE_ROOM_ADD_USER_OFFLINE = "user {} is not logged in."
    PRIVATE_ROOM_ADD_USER_ALREADY_MEMBER = "user {} is already a member of room {}"
    ROOM_CANNOT_ENTER = "The room you are trying to enter ({}) is registered as private."
    ROOM_CANNOT_CREATE_EMPTY = "Could not create room. Reason: Room name empty."
    ROOM_CANNOT_CREATE_SPACES = "Could not create room. Reason: Room name {} contains leading or trailing spaces."
    ROOM_CANNOT_CREATE_SPACES_MULTIPLE = "Could not create room. Reason: Room name {} contains multiple following spaces."
    ROOM_CANNOT_CREATE_INVALID_CHARACTERS = "Could not create room. Reason: Room name {} contains invalid characters."
    ROOM_CANNOT_CREATE_PUBLIC = "Room ({}) is registered as public."


@dataclass
class Settings:
    parent_min_speed: int = 1
    parent_speed_ratio: int = 50
    min_parents_in_cache: int = 10
    parent_inactivity_timeout: int = 300
    search_inactivity_timeout: int = 0
    distributed_alive_interval: int = 0
    wishlist_interval: int = 720


@dataclass
class User:
    name: str
    password: str = None
    privileged: bool = False

    status: UserStatus = UserStatus.OFFLINE
    avg_speed: int = 0
    uploads: int = 0
    shared_folder_count: int = 0
    shared_file_count: int = 0
    slots_free: int = 0
    country: str = None

    port: int = None
    obfuscated_port: int = None

    # TODO: Investigate what the default values are
    enable_private_rooms: bool = False
    enable_parent_search: bool = False
    enable_public_chat: bool = False

    def reset(self):
        self.status = UserStatus.OFFLINE

        self.port = None
        self.obfuscated_port = None

        self.enable_parent_search = False
        self.enable_private_rooms = False


@dataclass
class Room:
    name: str
    joined_users: List[User] = field(default_factory=list)
    is_private: bool = False
    tickers: Dict[str, str] = field(default_factory=dict)

    # Only for private rooms
    owner: User = None
    users: List[User] = field(default_factory=list)
    operators: List[User] = field(default_factory=list)

    def can_add(self, user: User):
        """Checks if given `user` can add another user to this room"""
        return user == self.owner or user in self.operators

    def can_remove(self, user: User, target: User) -> bool:
        """Checks if given `user` can remove `target` from this room

        owner can remove: operators, members
        operators can remove: members
        """
        if user == self.owner:
            return True

        if user in self.operators:
            if target != self.owner and target not in self.operators:
                return True

        return False


class MockServer:

    def __init__(self, hostname: str = '0.0.0.0', port: int = 2416):
        self.hostname = hostname
        self.port = port
        self.connection = None
        self.settings = Settings()

        self.users: List[User] = []
        self.rooms: List[Room] = []
        self.peers: List['Peer'] = []
        self.track_map: Dict[str, List[str]] = {}

        self.chat_id_gen = chat_id_generator()

        self.MESSAGE_MAP = build_message_map(self)

    async def connect(self) -> asyncio.AbstractServer:
        logger.info(
            f"open {self.hostname}:{self.port} : listening connection")

        self.connection = await asyncio.start_server(
            self.accept_peer,
            self.hostname,
            self.port,
            family=socket.AF_INET
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

        except Exception as exc:
            logger.warning(
                f"{self.hostname}:{self.port} : exception while disconnecting", exc_info=exc)

        finally:
            logger.debug(f"{self.hostname}:{self.port} : disconnected")

    async def accept_peer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        hostname, port = writer.get_extra_info('peername')
        logger.debug(f"{self.hostname}:{self.port} : accepted connection {hostname}:{port}")
        peer = Peer(hostname, port, self, reader, writer)
        await peer.disconnect()
        peer.start_reader_loop()
        self.peers.append(peer)

    async def on_peer_disconnected(self, peer: 'Peer'):
        """Called when a peer is disconnected"""
        if peer in self.peers:
            self.peers.remove(peer)

        if peer.user:
            peer.user.reset()
            # Leave all rooms
            for room in self.rooms:
                if peer.user in room.joined_users:
                    await self.leave_room(room, peer)

    async def on_peer_message(self, message, peer: 'Peer'):
        """Called when a peer receives a message"""
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, peer)

    def find_peer_by_name(self, username: str) -> 'Peer':
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
            raise LookupError('user does not exist')

    async def send_admin_message(self, message: str, peer: 'Peer'):
        await peer.send_message(
            ChatPrivateMessage.Response(
                chat_id=self.chat_id_gen(),
                timestamp=int(time.time()),
                username='server',
                is_admin=True
            )
        )

    async def send_room_list(self, peer: 'Peer'):
        public_rooms = []
        private_rooms = []
        private_rooms_owned = []
        private_rooms_operated = []
        for room in self.rooms:
            if room.is_private:
                if room.owner == peer.user.name:
                    private_rooms_owned.append(room)
                elif peer.user in room.operators:
                    private_rooms_operated.append(room)
                else:
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

    def notify_trackers(self, user: User):
        """Notify the peers tracking the given user of changes"""
        if user.name not in self.track_map:
            return

        tasks = []
        message = AddUser.Response(
            user.name,
            exists=True,
            status=user.status.value(),
            avg_speed=user.avg_speed,
            uploads=user.uploads,
            shared_file_count=user.shared_file_count,
            shared_folder_count=user.shared_folder_count,
            country_code=user.country
        )
        for username in self.track_map[user.name]:
            for peer in self.peers:
                if peer.user.name == username:
                    tasks.append(peer.send_message(message))

        asyncio.gather(*tasks, return_exceptions=True)

    @on_message(Login.Request)
    async def on_login(self, message: Login.Request, peer: 'Peer'):
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
    async def on_listen_port(self, message: SetListenPort.Request, peer: 'Peer'):
        peer.user.port = message.port
        peer.user.obfuscated_port = message.obfuscated_port

    @on_message(RoomList.Request)
    async def on_room_list(self, message: RoomList.Request, peer: 'Peer'):
        await self.send_room_list(peer)

    @on_message(AddUser.Request)
    async def on_add_user(self, message: AddUser.Request, peer: 'Peer'):
        for user in self.users:
            if user.name == message.username:
                if message.username in self.track_map:
                    self.track_map[message.username].append(peer.user.name)
                else:
                    self.track_map[message.username] = [peer.user.name]

                await peer.send_message(
                    AddUser.Response(
                        message.username,
                        exists=True,
                        status=user.status.value(),
                        avg_speed=user.avg_speed,
                        uploads=user.uploads,
                        shared_file_count=user.shared_file_count,
                        shared_folder_count=user.shared_folder_count,
                        country_code=user.country
                    )
                )
                break

        else:
            await peer.send_message(
                AddUser.Response(
                    message.username,
                    exists=False
                )
            )

    @on_message(RemoveUser)
    async def on_remove_user(self, message: RemoveUser.Request, peer: 'Peer'):
        if not peer.user:
            return

        if message.username in self.track_map:
            if peer.user.name in self.track_map[message.username]:
                self.track_map[message.username].remove(peer.user.name)

    @on_message(GetUserStatus.Request)
    async def on_get_user_status(self, message: GetUserStatus.Request, peer: 'Peer'):
        if (user := self.find_user_by_name(message.username)) is not None:
            await peer.send_message(
                GetUserStatus.Response(
                    username=message.username,
                    status=user.status.value()
                )
            )

    @on_message(GetUserStats.Request)
    async def on_get_user_stats(self, message: GetUserStats.Request, peer: 'Peer'):
        if (user := self.find_user_by_name(message.username)) is not None:
            await peer.send_message(
                GetUserStats.Response(
                    username=message.username,
                    avg_speed=user.avg_speed,
                    uploads=user.uploads,
                    shared_file_count=user.shared_file_count,
                    shared_folder_count=user.shared_folder_count
                )
            )

    @on_message(RemoveUser.Request)
    async def on_remove_user(self, message: RemoveUser.Request, peer: 'Peer'):
        if message.username in self.track_map:
            if peer.user.name in self.track_map[message.username]:
                self.track_map[message.username].remove(peer.user.name)

    @on_message(SharedFoldersFiles.Request)
    async def on_shared_folders_files(self, message: SharedFoldersFiles.Request, peer: 'Peer'):
        peer.user.shared_folder_count = message.shared_folder_count
        peer.user.shared_file_count = message.shared_file_count

    @on_message(SetStatus.Request)
    async def on_set_status(self, message: SetStatus.Request, peer: 'Peer'):
        peer.user.status = UserStatus(message.status)

    @on_message(GetPeerAddress.Request)
    async def on_get_peer_address(self, message: GetPeerAddress.Request, peer: 'Peer'):
        for peer in self.peers:
            if peer.user.name == message.username:
                await peer.send_message(
                    GetPeerAddress.Response(
                        message.username,
                        peer.hostname,
                        port=peer.user.port,
                        obfuscated_port_amount=1 if peer.user.obfuscated_port else 0,
                        obfuscated_port=peer.user.obfuscated_port
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
    async def on_connect_to_peer(self, message: ConnectToPeer.Request, peer: 'Peer'):
        if (peer := self.find_peer_by_name(message.username)) is not None:
            await peer.send_message(
                ConnectToPeer.Response(
                    username=peer.user.name,
                    typ=message.typ,
                    ticket=message.ticket,
                    ip=peer.hostname,
                    port=peer.user.port,
                    obfuscated_port_amount=1 if peer.user.obfuscated_port else 0,
                    obfuscated_port=peer.user.obfuscated_port
                )
            )

    @on_message(BranchLevel.Request)
    async def on_branch_level(self, message: BranchLevel.Request, peer: 'Peer'):
        peer.branch_level = message.level

    @on_message(BranchRoot.Request)
    async def on_branch_root(self, message: BranchRoot.Request, peer: 'Peer'):
        peer.branch_root = message.username

    @on_message(ChildDepth.Request)
    async def on_child_depth(self, message: ChildDepth.Request, peer: 'Peer'):
        peer.child_depth = message.depth

    @on_message(CannotConnect.Request)
    async def on_cannot_connect(self, message: CannotConnect.Request, peer: 'Peer'):
        if (peer := self.find_peer_by_name(message.username)) is not None:
            await peer.send_message(
                CannotConnect.Response(
                    username=peer.user.name,
                    ticket=message.ticket
                )
            )

    @on_message(FileSearch)
    async def on_file_search(self, message: FileSearch.Request, peer: 'Peer'):
        message = ServerSearchRequest.Response(
            0x03,
            0x31,
            peer.user.name,
            message.ticket,
            message.query
        )
        for peer in self.peers:
            if peer.branch_level == 0:
                pass

    @on_message(SendUploadSpeed.Request)
    async def on_send_upload_speed(self, message: SendUploadSpeed.Request, peer: 'Peer'):
        peer.user.avg_speed = message.speed
        peer.user.uploads += 1

    @on_message(TogglePrivateRooms.Request)
    async def on_toggle_private_rooms(self, message: TogglePrivateRooms.Request, peer: 'Peer'):
        peer.user.enable_private_rooms = message.enable

    @on_message(ToggleParentSearch.Request)
    async def on_toggle_private_rooms(self, message: TogglePrivateRooms.Request, peer: 'Peer'):
        peer.user.enable_parent_search = message.enable

    @on_message(ChatEnablePublic.Request)
    async def on_chat_enable_public(self, message: ChatEnablePublic.Request, peer: 'Peer'):
        peer.user.enable_public_chat = True

    @on_message(ChatDisablePublic.Request)
    async def on_chat_disable_public(self, message: ChatDisablePublic.Request, peer: 'Peer'):
        peer.user.enable_public_chat = False

    @on_message(Ping.Request)
    async def on_ping(self, message: Ping.Request, peer: 'Peer'):
        peer.last_ping = time.time()

    @on_message(ChatJoinRoom.Request)
    async def on_join_room(self, message: ChatJoinRoom.Request, peer: 'Peer'):
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
        elif re.match(r'[\s]{2,}') is not None:
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
                if peer.user in existing_room.users:
                    await self.join_room(existing_room, peer)
                else:
                    await peer.send_message(
                        CannotCreateRoom.Response(message.room)
                    )
                    await self.send_admin_message(
                        AdminMessage.ROOM_CANNOT_ENTER.format(message.room),
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

    @on_message(ChatLeaveRoom.Request)
    async def on_chat_leave_room(self, message: ChatLeaveRoom.Request, peer: 'Peer'):
        room = self.find_room_by_name(message.room)
        if room:
            if peer.user in room.joined_users:
                await self.leave_room(room, peer)

    @on_message(PrivateRoomDropMembership)
    async def on_private_room_drop_membership(self, message: PrivateRoomDropMembership.Request, peer: 'Peer'):
        room = self.find_room_by_name(message.room)

        if not room:
            return

        # This covers 2 cases. Not a user of private room and drop membership
        # of public room (since users should be empty for public rooms)
        if peer.user not in room.users:
            return

        if peer.user == room.owner:
            return

        #

    @on_message(PrivateRoomDropOwnership)
    async def on_private_room_drop_ownership(self, message: PrivateRoomDropOwnership.Request, peer: 'Peer'):
        room = self.find_room_by_name(message.room)

        if not room:
            return



        self.rooms.remove(room)

    @on_message(PrivateRoomAddUser.Request)
    async def on_private_room_add_user(self, message: PrivateRoomAddUser.Request, peer: 'Peer'):
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

        if user in room.users:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_ADD_USER_ALREADY_MEMBER.format(message.username, message.room),
                peer
            )
            return

        # Add user to room
        room.users.append(user)

        # Send messages to the peer requesting to add
        await peer.send_message(
            PrivateRoomAddUser.Response(room.name, user.name))
        await self.send_admin_message(
            AdminMessage.PRIVATE_ROOM_USER_ADDED.format(user.name,room.name),
            peer
        )

        # Send messages to the peer being added
        await peer_to_add.send_message(
            PrivateRoomAddUser.Response(room.name, user.name)
        )
        await peer_to_add.send_message(
            PrivateRoomAdded.Response(room.name)
        )
        await self.send_room_list(peer_to_add)

        # Notify owner
        if peer.user in room.operators:
            msg = AdminMessage.PRIVATE_ROOM_USER_ADDED_BY_OPERATOR.format(
                message.username, message.room, peer.user.name
            )
        else:
            msg = AdminMessage.PRIVATE_ROOM_USER_ADDED.format(
                message.username, message.room
            )
        await self.notify_room_owner(room, msg)

    @on_message(PrivateRoomRemoveUser.Request)
    async def on_private_room_remove_user(self, message: PrivateRoomRemoveUser.Request, peer: 'Peer'):
        room = self.find_room_by_name(message.room)
        user = self.find_user_by_name(message.username)

        if not user or not room:
            return

        if not room.can_remove(peer.user, user):
            return

        if user in room.users:
            await self.remove_from_private_room(room, user)

    async def create_public_room(self, name: str, peer: 'Peer') -> Room:
        """Creates a new private room, should be called when all checks are
        complete
        """
        room = Room(
            name=name,
            is_private=False
        )
        self.rooms.append(room)

    async def create_private_room(self, name: str, peer: 'Peer') -> Room:
        """Creates a new private room, should be called when all checks are
        complete
        """
        room = Room(
            name=name,
            users=[peer.user, ],
            owner=peer.user,
            is_private=True
        )
        self.rooms.append(room)

        await self.send_room_list(peer)
        await peer.send_message(
            PrivateRoomUsers.Response(
                name, usernames=[user.name for user in room.users]
            )
        )
        await peer.send_message(
            PrivateRoomOperators.Response(
                name, usernames=[user.name for user in room.operators]
            )
        )
        # TODO: room tickers

    async def join_room(self, room: Room, peer: 'Peer'):
        """Joins a user to a room.

        This method will send the appropriate response to the peer and notify
        all joined users in the room
        """
        # Report to the user he has joined successfully
        room.joined_users.append(peer.user)
        await peer.send_message(
            ChatJoinRoom.Response(
                room.name,
                users=[
                    user.name
                    for user in room.joined_users
                ],
                users_status=[
                    user.status.value()
                    for user in room.joined_users
                ],
                users_data=[
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
                owner=room.owner,
                operators=[operator.name for operator in room.operators] if room.is_private else None
            )
        )

        # Report to all other users in the room the user has joined
        user_joined_message = ChatUserJoinedRoom.Response(
            room.name,
            peer.user.name,
            peer.user.status.value(),
            UserStats(
                peer.user.avg_speed,
                peer.user.uploads,
                peer.user.shared_file_count,
                peer.user.shared_folder_count
            ),
            slots_free=peer.user.slots_free,
            country_code=peer.user.country
        )
        await self.notify_room_users(room, user_joined_message)

    async def leave_room(self, room: Room, peer: 'Peer'):
        """Removes the user from the joined users.

        This method will do nothing in case the user is no joined. Otherwise the
        message will be sent to the peer and the joined users in the room will be
        notified.
        """
        if peer.user not in room.joined_users:
            return

        room.joined_users.remove(peer.user)

        await peer.send_message(ChatLeaveRoom.Response(room.name))

        user_left_message = ChatUserLeftRoom.Response(room.name, peer.user.name)
        await self.notify_room_users(room, user_left_message)

    async def notify_room_owner(self, room: Room, message: str):
        peer = self.find_peer_by_name(room.owner.name)
        if peer:
            await self.send_admin_message(message, peer)

    async def notify_room_users(self, room: Room, message):
        """Sends a protocol message to all joined users in the given room"""
        tasks = []
        for user in room.joined_users:
            peer = self.find_peer_by_name(user.name)
            if peer:
                tasks.append(peer.send_message(message))
        asyncio.gather(*tasks, return_exceptions=True)

    async def remove_from_private_room(self, room: Room, user: User):
        room.users.remove(user)

        # Notify the user being removed
        removed_peer = self.find_peer_by_name(user.name)
        if removed_peer:
            await removed_peer.send_message(PrivateRoomRemoved.Response(room.name))
            await self.leave_room(room, removed_peer)
            await self.send_room_list(removed_peer)

        # Notify the owner
        owner_peer = self.find_peer_by_name(room.owner.name)
        if owner_peer:
            await self.send_admin_message(
                AdminMessage.PRIVATE_ROOM_USER_REMOVED.format(user.name, room.name)
            )

    async def grant_operator(self, room: Room, user: User, peer: 'Peer'):
        pass

    async def revoke_operator(self, room: Room, user: User, peer: 'Peer'):
        pass


class Peer:

    def __init__(self, hostname: str, port: int, server: MockServer, reader: asyncio.StreamReader = None, writer: asyncio.StreamWriter = None):
        self.hostname: str = hostname
        self.port: int = port
        self.server = server

        self.user: User = None

        self.reader = reader
        self.writer = writer
        self.reader_loop = None

        self.should_close = False
        self.last_ping: float = 0.0

        self.branch_level = None
        self.branch_root = None
        self.child_depth = None

    async def disconnect(self):
        logger.debug(f"{self.hostname}:{self.port} : disconnecting")
        try:
            if self.writer is not None:
                if not self.writer.is_closing():
                    self.writer.close()
                await self.writer.wait_closed()
        except Exception:
            logger.exception(f"{self.hostname}:{self.port} : exception while disconnecting")

        finally:
            self.stop_reader_loop()
            self.writer = None
            self.reader = None
            await self.server.on_peer_disconnected(self)


    def start_reader_loop(self):
        self.reader_loop = asyncio.create_task(self._message_reader_loop())

    def stop_reader_loop(self):
        if self.reader_loop:
            self.reader_loop.cancel()
            self.reader_loop = None

    async def receive_message(self):
        header = await self.reader.readexactly(HEADER_SIZE)
        _, message_len = uint32.deserialize(0, header)
        message = await self.reader.readexactly(message_len)
        return header + message

    async def _message_reader_loop(self):
        """Message reader loop. This will loop until the connection is closed or
        the network is closed
        """
        while True:
            try:
                message_data = await self.receive_message()
            except Exception as exc:
                logger.warning(f"{self.hostname}:{self.port} : read error : {exc!r}")
                await self.disconnect()
                break
            else:
                if not message_data:
                    logger.info(f"{self.hostname}:{self.port} : no data received")
                    continue

                try:
                    message = ServerMessage.deserialize_request(message_data)
                except Exception:
                    logger.exception(f"{self.hostname}:{self.port} : failed to parse message data : {message_data.hex()}")
                else:
                    logger.debug(f"{self.hostname}:{self.port}: receive : {message!r}")
                    await self.server.on_peer_message(message, self)

    async def send_message(self, message: MessageDataclass):
        if self.writer is None:
            logger.warning(f"{self.hostname}:{self.port} : disconnected, not sending message : {message!r}")
            return

        logger.debug(f"{self.hostname}:{self.port} : send message : {message!r}")
        data = message.serialize()

        try:
            self.writer.write(data)
            await self.writer.drain()

        except Exception as exc:
            logger.exception(f"failed to send message {message}")
            await self.disconnect()


async def main():
    mock_server = MockServer()
    async with await mock_server.connect():
        await mock_server.connection.serve_forever()


asyncio.run(main())
