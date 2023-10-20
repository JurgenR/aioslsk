import logging
import time
from typing import Dict, List

from ..network.connection import ConnectionState, ServerConnection
from ..events import (
    build_message_map,
    ConnectionStateChangedEvent,
    EventBus,
    InternalEventBus,
    MessageReceivedEvent,
    on_message,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomListEvent,
    RoomMessageEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    RoomTickersEvent,
    RoomOperatorGrantedEvent,
    RoomOperatorRevokedEvent,
    RoomMembershipGrantedEvent,
    RoomMembershipRevokedEvent,
    ServerDisconnectedEvent,
    UserInfoEvent,
)
from ..protocol.messages import (
    ChatRoomMessage,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatRoomTickers,
    ChatRoomTickerAdded,
    ChatRoomTickerRemoved,
    ChatRoomTickerSet,
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    GetUserStatus,
    GetUserStats,
    Login,
    PrivateRoomAddUser,
    PrivateRoomRemoveUser,
    PrivateRoomUsers,
    PrivateRoomAdded,
    PrivateRoomOperators,
    PrivateRoomOperatorAdded,
    PrivateRoomOperatorRemoved,
    PrivateRoomAddOperator,
    PrivateRoomRemoveOperator,
    PrivateRoomRemoved,
    TogglePrivateRooms,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
    RoomList,
)
from .model import Room, RoomMessage
from ..network.network import Network
from ..settings import Settings
from ..user.manager import UserManager
from ..user.model import UserStatus, TrackingFlag

logger = logging.getLogger(__name__)


class RoomManager:
    """Class handling rooms"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            user_manager: UserManager, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._user_manager: UserManager = user_manager
        self._network: Network = network

        self.rooms: Dict[str, Room] = {}

        self.MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    def get_joined_rooms(self) -> List[Room]:
        return [room for room in self.rooms.values() if room.joined]

    def get_or_create_room(self, room_name: str, private: bool = False) -> Room:
        try:
            return self.rooms[room_name]
        except KeyError:
            room = Room(name=room_name, private=private)
            self.rooms[room_name] = room
            return room

    def reset_rooms(self):
        """Performs a reset on all users and rooms"""
        self.rooms = {}

    def register_listeners(self):
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    async def auto_join_rooms(self):
        """Automatically joins rooms stored in the settings. This method will
        do nothing if the `chats.auto_join` setting is not enabled
        """
        if not self._settings.get('chats.auto_join'):
            return

        rooms = self._settings.get('chats.rooms')
        logger.info(f"automatically rejoining {len(rooms)} rooms")
        await self._network.send_server_messages(
            *[ChatJoinRoom.Request(room) for room in rooms]
        )

    async def get_user_stats(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(GetUserStats.Request(username))

    async def get_user_status(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(GetUserStatus.Request(username))

    async def get_room_list(self):  # pragma: no cover
        """Request the list of chat rooms from the server"""
        await self._network.send_server_messages(RoomList.Request())

    async def join_room(self, room: str, private: bool = False):  # pragma: no cover
        await self._network.send_server_messages(
            ChatJoinRoom.Request(room, is_private=private)
        )

    async def leave_room(self, room: str):  # pragma: no cover
        await self._network.send_server_messages(ChatLeaveRoom.Request(room))

    async def add_user_to_room(self, room: str, username: str):  # pragma: no cover
        """Adds a user to a private room"""
        await self._network.send_server_messages(
            PrivateRoomAddUser.Request(room=room, username=username)
        )

    async def remove_user_from_room(self, room: str, username: str):  # pragma: no cover
        """Removes a user from a private room"""
        await self._network.send_server_messages(
            PrivateRoomRemoveUser.Request(room=room, username=username)
        )

    async def grant_operator(self, room: str, username: str):  # pragma: no cover
        """Grant operator privileges to the given `username` in `room`. This is
        only applicable to private rooms
        """
        await self._network.send_server_messages(
            PrivateRoomAddOperator.Request(room=room, username=username)
        )

    async def revoke_operator(self, room: str, username: str):  # pragma: no cover
        await self._network.send_server_messages(
            PrivateRoomRemoveOperator.Request(room=room, username=username)
        )

    async def set_room_ticker(self, room: str, ticker: str):  # pragma: no cover
        # No need to update the ticker in the model, a ChatRoomTickerAdded will
        # be sent back to us
        await self._network.send_server_messages(
            ChatRoomTickerSet.Request(room=room, ticker=ticker)
        )

    async def send_room_message(self, room: str, message: str):  # pragma: no cover
        await self._network.send_server_messages(
            ChatRoomMessage.Request(room, message)
        )

    async def drop_room_ownership(self, room: str):  # pragma: no cover
        """Drop ownership of the private room"""
        await self._network.send_server_messages(
            PrivateRoomDropOwnership.Request(room)
        )

    async def drop_room_membership(self, room: str):  # pragma: no cover
        """Drop membership of the private room"""
        await self._network.send_server_messages(
            PrivateRoomDropMembership.Request(room)
        )

    @on_message(Login.Response)
    async def _on_login(self, message: Login.Response, connection: ServerConnection):
        if message.success:
            await self._network.send_server_messages(
                TogglePrivateRooms.Request(self._settings.get('chats.private_room_invites'))
            )

    @on_message(ChatRoomMessage.Response)
    async def _on_chat_room_message(self, message: ChatRoomMessage.Response, connection: ServerConnection):
        user = self._user_manager.get_or_create_user(message.username)
        room = self.get_or_create_room(message.room)
        room_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=message.message
        )

        await self._event_bus.emit(RoomMessageEvent(room_message))

    @on_message(ChatUserJoinedRoom.Response)
    async def _on_user_joined_room(self, message: ChatUserJoinedRoom.Response, connection: ServerConnection):
        user = self._user_manager.get_or_create_user(message.username)
        user.status = UserStatus(message.status)
        user.update_from_user_stats(message.user_stats)
        user.slots_free = message.slots_free
        user.country = message.country_code
        await self._user_manager.track_user(user.name, TrackingFlag.ROOM_USER)

        room = self.get_or_create_room(message.room)
        room.add_user(user)

        await self._event_bus.emit(
            RoomJoinedEvent(room=room, user=user))
        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(ChatUserLeftRoom.Response)
    async def _on_user_left_room(self, message: ChatUserLeftRoom.Response, connection: ServerConnection):
        user = self._user_manager.get_or_create_user(message.username)
        room = self.get_or_create_room(message.room)

        # Remove tracking flag if there's no room left which the user is in
        for joined_room in self.get_joined_rooms():
            if joined_room != room and user in joined_room.users:
                break
        else:
            await self._user_manager.untrack_user(user.name, TrackingFlag.ROOM_USER)

        room.remove_user(user)

        await self._event_bus.emit(
            RoomLeftEvent(room=room, user=user))

    @on_message(ChatJoinRoom.Response)
    async def _on_join_room(self, message: ChatJoinRoom.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        room.joined = True
        # There isn't a boolean to indicate that a room is private, but a private
        # room should always have an owner
        room.private = bool(message.owner)

        for idx, name in enumerate(message.users):
            user = self._user_manager.get_or_create_user(name)
            user.status = UserStatus(message.users_status[idx])
            user.update_from_user_stats(message.users_stats[idx])
            user.country = message.users_countries[idx]
            user.slots_free = message.users_slots_free[idx]
            await self._user_manager.track_user(user.name, TrackingFlag.ROOM_USER)

            room.add_user(user)
            await self._event_bus.emit(UserInfoEvent(user))

        if message.owner:
            room.owner = self._user_manager.get_or_create_user(message.owner)
        for operator in message.operators or []:
            room.add_operator(self._user_manager.get_or_create_user(operator))

        await self._event_bus.emit(RoomJoinedEvent(room=room))

    @on_message(ChatLeaveRoom.Response)
    async def _on_leave_room(self, message: ChatLeaveRoom.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)

        # Remove tracking flag from users (that are no longer in other rooms)
        for user in room.users:
            for joined_room in self.get_joined_rooms():
                if joined_room == room:
                    continue
                if user in joined_room.users:
                    break
            else:
                await self._user_manager.untrack_user(user.name, TrackingFlag.ROOM_USER)

        room.joined = False
        room.users = []

        await self._event_bus.emit(RoomLeftEvent(room=room))

    @on_message(ChatRoomTickers.Response)
    async def _on_chat_room_tickers(self, message: ChatRoomTickers.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        tickers = {}
        for ticker in message.tickers:
            self._user_manager.get_or_create_user(ticker.username)
            tickers[ticker.username] = ticker.ticker

        # Just replace all tickers instead of modifying the existing dict
        room.tickers = tickers

        await self._event_bus.emit(RoomTickersEvent(room, tickers))

    @on_message(ChatRoomTickerAdded.Response)
    async def _on_chat_room_ticker_added(self, message: ChatRoomTickerAdded.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_or_create_user(message.username)

        room.tickers[user.name] = message.ticker

        await self._event_bus.emit(RoomTickerAddedEvent(room, user, message.ticker))

    @on_message(ChatRoomTickerRemoved.Response)
    async def _on_chat_room_ticker_removed(self, message: ChatRoomTickerRemoved.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_or_create_user(message.username)

        try:
            del room.tickers[user.name]
        except KeyError:
            logger.warning(
                f"attempted to remove room ticker for user {user.name} in room {room.name} "
                "but it wasn't present")

        await self._event_bus.emit(RoomTickerRemovedEvent(room, user))

    @on_message(TogglePrivateRooms.Response)
    async def _on_private_room_toggle(self, message: TogglePrivateRooms.Response, connection: ServerConnection):
        logger.debug(f"private rooms enabled : {message.enabled}")

    @on_message(PrivateRoomAddUser.Response)
    async def _on_private_room_add_user(self, message: PrivateRoomAddUser.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)

        room.add_member(user)

        await self._event_bus.emit(
            RoomMembershipGrantedEvent(room=room, member=user))

    @on_message(PrivateRoomAdded.Response)
    async def _on_private_room_added(self, message: PrivateRoomAdded.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(self._settings.get('credentials.username'))
        room.add_member(user)

        await self._event_bus.emit(
            RoomMembershipGrantedEvent(room=room))

    @on_message(PrivateRoomRemoveUser.Response)
    async def _on_private_room_remove_user(self, message: PrivateRoomRemoveUser.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.remove_member(user)

        await self._event_bus.emit(
            RoomMembershipRevokedEvent(room=room, member=user))

    @on_message(PrivateRoomRemoved.Response)
    async def _on_private_room_removed(self, message: PrivateRoomRemoved.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(self._settings.get('credentials.username'))
        room.remove_member(user)

        await self._event_bus.emit(
            RoomMembershipRevokedEvent(room=room))

    @on_message(PrivateRoomUsers.Response)
    async def _on_private_room_users(self, message: PrivateRoomUsers.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.members = list(
            map(self._user_manager.get_or_create_user, message.usernames)
        )

    @on_message(PrivateRoomOperators.Response)
    async def _on_private_room_operators(self, message: PrivateRoomOperators.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.operators = list(
            map(self._user_manager.get_or_create_user, message.usernames))

    @on_message(PrivateRoomOperatorAdded.Response)
    async def _on_private_room_operator_added(self, message: PrivateRoomOperatorAdded.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.is_operator = True

        await self._event_bus.emit(
            RoomOperatorGrantedEvent(room=room))

    @on_message(PrivateRoomOperatorRemoved.Response)
    async def _on_private_room_operator_removed(self, message: PrivateRoomOperatorRemoved.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.is_operator = False

        await self._event_bus.emit(
            RoomOperatorRevokedEvent(room=room))

    @on_message(PrivateRoomAddOperator.Response)
    async def _on_private_room_add_operator(self, message: PrivateRoomAddOperator.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.add_operator(user)
        await self._event_bus.emit(
            RoomOperatorGrantedEvent(room=room, member=user))

    @on_message(PrivateRoomRemoveOperator.Response)
    async def _on_private_room_remove_operators(self, message: PrivateRoomRemoveOperator.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.remove_operator(user)

        await self._event_bus.emit(
            RoomOperatorRevokedEvent(room=room, member=user))

    @on_message(RoomList.Response)
    async def _on_room_list(self, message: RoomList.Response, connection):
        me = self._user_manager.get_or_create_user(self._settings.get('credentials.username'))
        for idx, room_name in enumerate(message.rooms):
            room = self.get_or_create_room(room_name, private=False)
            room.user_count = message.rooms_user_count[idx]

        for idx, room_name in enumerate(message.rooms_private_owned):
            room = self.get_or_create_room(room_name, private=True)
            room.add_member(me)
            room.user_count = message.rooms_private_owned_user_count[idx]
            room.owner = me

        for idx, room_name in enumerate(message.rooms_private):
            room = self.get_or_create_room(room_name, private=True)
            room.add_member(me)
            room.user_count = message.rooms_private_user_count[idx]

        for room_name in message.rooms_private_operated:
            room = self.get_or_create_room(room_name, private=True)
            room.add_operator(me)
            room.is_operator = True

        await self._event_bus.emit(
            RoomListEvent(rooms=list(self.rooms.values()))
        )

    # Listeners

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            self.reset_rooms()

            await self._event_bus.emit(ServerDisconnectedEvent())
