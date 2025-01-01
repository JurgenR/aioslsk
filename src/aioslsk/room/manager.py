from collections import OrderedDict
import logging
import time

from ..base_manager import BaseManager
from ..events import (
    build_message_map,
    ConnectionStateChangedEvent,
    EventBus,
    MessageReceivedEvent,
    on_message,
    PublicMessageEvent,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomListEvent,
    RoomMembersEvent,
    RoomMembershipGrantedEvent,
    RoomMembershipRevokedEvent,
    RoomMessageEvent,
    RoomOperatorGrantedEvent,
    RoomOperatorRevokedEvent,
    RoomOperatorsEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    RoomTickersEvent,
    SessionInitializedEvent,
)
from ..protocol.messages import (
    RoomChatMessage,
    JoinRoom,
    LeaveRoom,
    RoomTickers,
    RoomTickerAdded,
    RoomTickerRemoved,
    UserJoinedRoom,
    UserLeftRoom,
    PrivateRoomGrantMembership,
    PrivateRoomRevokeMembership,
    PrivateRoomMembers,
    PrivateRoomMembershipGranted,
    PrivateRoomOperators,
    PrivateRoomOperatorGranted,
    PrivateRoomOperatorRevoked,
    PrivateRoomGrantOperator,
    PrivateRoomRevokeOperator,
    PrivateRoomMembershipRevoked,
    PublicChatMessage,
    TogglePrivateRoomInvites,
    RoomList,
)
from .model import Room, RoomMessage
from ..network.connection import ConnectionState, ServerConnection
from ..network.network import Network
from ..settings import Settings
from ..user.manager import UserManager
from ..user.model import BlockingFlag, UserStatus


logger = logging.getLogger(__name__)


class RoomManager(BaseManager):
    """Class handling rooms"""

    def __init__(
            self, settings: Settings, event_bus: EventBus,
            user_manager: UserManager, network: Network):

        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._user_manager: UserManager = user_manager
        self._network: Network = network

        self._rooms: dict[str, Room] = dict()

        self._MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    @property
    def rooms(self) -> dict[str, Room]:
        return self._rooms

    def get_joined_rooms(self) -> list[Room]:
        """Returns a list of all rooms currently joined"""
        return [room for room in self._rooms.values() if room.joined]

    def get_private_rooms(self) -> list[Room]:
        """Returns a list of all private rooms of which we are a member or
        owner. This includes rooms that are not joined
        """
        return [room for room in self._rooms.values() if room.private]

    def get_public_rooms(self) -> list[Room]:
        """Returns the list of public rooms"""
        return [room for room in self._rooms.values() if not room.private]

    def get_owned_rooms(self) -> list[Room]:
        """Returns a list of which we are the owner"""
        me = self._user_manager.get_self()
        return [
            room for room in self._rooms.values()
            if room.owner == me.name
        ]

    def get_operated_rooms(self) -> list[Room]:
        """Returns a list of rooms in which we have operator privileges"""
        me = self._user_manager.get_self()
        return [
            room for room in self._rooms.values()
            if me.name in room.operators
        ]

    def get_or_create_room(self, room_name: str, private: bool = False) -> Room:
        try:
            return self._rooms[room_name]
        except KeyError:
            room = Room(name=room_name, private=private)
            self._rooms[room_name] = room
            return room

    def reset_rooms(self):
        """Performs a reset on all users and rooms"""
        self._rooms = {}

    def register_listeners(self):
        self._event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)

    async def auto_join_rooms(self):
        """Automatically joins rooms stored in the settings"""
        rooms = self._settings.rooms.favorites
        logger.info("automatically rejoining %d rooms", len(rooms))
        await self._network.send_server_messages(
            *[JoinRoom.Request(room) for room in rooms]
        )

    @on_message(RoomChatMessage.Response)
    async def _on_chat_room_message(self, message: RoomChatMessage.Response, connection: ServerConnection):

        if self._settings.users.is_blocked(message.username, BlockingFlag.ROOM_MESSAGES):
            return

        user = self._user_manager.get_user_object(message.username)
        room = self.get_or_create_room(message.room)
        room_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=message.message
        )

        await self._event_bus.emit(
            RoomMessageEvent(
                room_message,
                raw_message=message
            )
        )

    @on_message(PublicChatMessage.Response)
    async def _on_public_chat_message(self, message: PublicChatMessage.Response, connection: ServerConnection):

        if self._settings.users.is_blocked(message.username, BlockingFlag.ROOM_MESSAGES):
            return

        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_user_object(message.username)

        await self._event_bus.emit(
            PublicMessageEvent(
                timestamp=int(time.time()),
                room=room,
                user=user,
                message=message.message,
                raw_message=message
            )
        )

    @on_message(UserJoinedRoom.Response)
    async def _on_user_joined_room(self, message: UserJoinedRoom.Response, connection: ServerConnection):
        user = self._user_manager.get_user_object(message.username)
        user.status = UserStatus(message.status)
        user.update_from_user_stats(message.user_stats)
        user.slots_free = message.slots_free
        user.country = message.country_code

        room = self.get_or_create_room(message.room)
        room.add_user(user)

        await self._event_bus.emit(
            RoomJoinedEvent(
                room=room,
                user=user,
                raw_message=message
            )
        )

    @on_message(UserLeftRoom.Response)
    async def _on_user_left_room(self, message: UserLeftRoom.Response, connection: ServerConnection):
        user = self._user_manager.get_user_object(message.username)
        room = self.get_or_create_room(message.room)
        room.remove_user(user)

        await self._event_bus.emit(
            RoomLeftEvent(
                room=room,
                user=user,
                raw_message=message
            )
        )

    @on_message(JoinRoom.Response)
    async def _on_join_room(self, message: JoinRoom.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        room.joined = True
        # There isn't a boolean to indicate that a room is private, but a private
        # room should always have an owner
        room.private = bool(message.owner)

        for idx, name in enumerate(message.users):
            user = self._user_manager.get_user_object(name)
            user.status = UserStatus(message.users_status[idx])
            user.update_from_user_stats(message.users_stats[idx])
            user.country = message.users_countries[idx]
            user.slots_free = message.users_slots_free[idx]

            room.add_user(user)

        # For private rooms
        room.owner = message.owner
        room.operators = set(message.operators or [])

        await self._event_bus.emit(
            RoomJoinedEvent(
                room=room,
                raw_message=message
            )
        )

    @on_message(LeaveRoom.Response)
    async def _on_leave_room(self, message: LeaveRoom.Response, connection: ServerConnection):
        """Received when we leave a room"""
        room = self.get_or_create_room(message.room)
        room.joined = False
        room.users = []
        await self._event_bus.emit(
            RoomLeftEvent(
                room=room,
                raw_message=message
            )
        )

    @on_message(RoomTickers.Response)
    async def _on_chat_room_tickers(self, message: RoomTickers.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        tickers = OrderedDict()
        for ticker in message.tickers:
            self._user_manager.get_user_object(ticker.username)
            tickers[ticker.username] = ticker.ticker

        room.tickers = tickers

        await self._event_bus.emit(
            RoomTickersEvent(
                room=room,
                tickers=tickers,
                raw_message=message
            )
        )

    @on_message(RoomTickerAdded.Response)
    async def _on_chat_room_ticker_added(self, message: RoomTickerAdded.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_user_object(message.username)

        room.tickers[user.name] = message.ticker

        await self._event_bus.emit(
            RoomTickerAddedEvent(
                room,
                user,
                message.ticker,
                raw_message=message
            )
        )

    @on_message(RoomTickerRemoved.Response)
    async def _on_chat_room_ticker_removed(self, message: RoomTickerRemoved.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_user_object(message.username)

        try:
            del room.tickers[user.name]
        except KeyError:
            logger.warning(
                "attempted to remove room ticker for user %s in room %s but it wasn't present",
                user.name, room.name
            )

        await self._event_bus.emit(
            RoomTickerRemovedEvent(
                room,
                user,
                raw_message=message
            )
        )

    @on_message(TogglePrivateRoomInvites.Response)
    async def _on_private_room_toggle(
            self, message: TogglePrivateRoomInvites.Response, connection: ServerConnection):

        logger.debug("private rooms enabled : %s", message.enabled)

    @on_message(PrivateRoomGrantMembership.Response)
    async def _on_private_room_add_user(
            self, message: PrivateRoomGrantMembership.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_user_object(message.username)
        room.members.add(message.username)

        await self._event_bus.emit(
            RoomMembershipGrantedEvent(
                room=room,
                member=user,
                raw_message=message
            )
        )

    @on_message(PrivateRoomMembershipGranted.Response)
    async def _on_private_room_added(
            self, message: PrivateRoomMembershipGranted.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_self()
        room.members.add(user.name)

        await self._event_bus.emit(
            RoomMembershipGrantedEvent(
                room=room,
                raw_message=message
            )
        )

    @on_message(PrivateRoomRevokeMembership.Response)
    async def _on_private_room_remove_user(
            self, message: PrivateRoomRevokeMembership.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_user_object(message.username)

        room.members.discard(message.username)
        room.operators.discard(message.username)

        await self._event_bus.emit(
            RoomMembershipRevokedEvent(
                room=room,
                member=user,
                raw_message=message
            )
        )

    @on_message(PrivateRoomMembershipRevoked.Response)
    async def _on_private_room_removed(
            self, message: PrivateRoomMembershipRevoked.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_self()
        room.members.discard(user.name)
        room.operators.discard(user.name)

        await self._event_bus.emit(
            RoomMembershipRevokedEvent(
                room=room,
                raw_message=message
            )
        )

    @on_message(PrivateRoomMembers.Response)
    async def _on_private_room_users(self, message: PrivateRoomMembers.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.members = set(message.usernames)

        await self._event_bus.emit(
            RoomMembersEvent(
                room=room,
                members=list(map(self._user_manager.get_user_object, message.usernames)),
                raw_message=message
            )
        )

    @on_message(PrivateRoomOperators.Response)
    async def _on_private_room_operators(
            self, message: PrivateRoomOperators.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        room.operators = set(message.usernames)

        await self._event_bus.emit(
            RoomOperatorsEvent(
                room=room,
                operators=list(map(self._user_manager.get_user_object, room.operators)),
                raw_message=message
            )
        )

    @on_message(PrivateRoomOperatorGranted.Response)
    async def _on_operator_granted(
            self, message: PrivateRoomOperatorGranted.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        room.operators.discard(self._user_manager.get_self().name)

        await self._event_bus.emit(
            RoomOperatorGrantedEvent(
                room=room,
                raw_message=message
            )
        )

    @on_message(PrivateRoomOperatorRevoked.Response)
    async def _on_operator_revoked(
            self, message: PrivateRoomOperatorRevoked.Response, connection: ServerConnection):

        room = self.get_or_create_room(message.room, private=True)
        room.operators.discard(self._user_manager.get_self().name)

        await self._event_bus.emit(
            RoomOperatorRevokedEvent(
                room=room,
                raw_message=message
            )
        )

    @on_message(PrivateRoomGrantOperator.Response)
    async def _on_user_operator_granted(
            self, message: PrivateRoomGrantOperator.Response, connection: ServerConnection):

        user = self._user_manager.get_user_object(message.username)
        room = self.get_or_create_room(message.room, private=True)
        room.operators.add(message.username)

        await self._event_bus.emit(
            RoomOperatorGrantedEvent(
                room=room,
                member=user,
                raw_message=message
            )
        )

    @on_message(PrivateRoomRevokeOperator.Response)
    async def _on_user_operator_revoked(
            self, message: PrivateRoomRevokeOperator.Response, connection: ServerConnection):

        user = self._user_manager.get_user_object(message.username)
        room = self.get_or_create_room(message.room, private=True)
        room.operators.discard(message.username)

        await self._event_bus.emit(
            RoomOperatorRevokedEvent(
                room=room,
                member=user,
                raw_message=message
            )
        )

    @on_message(RoomList.Response)
    async def _on_room_list(self, message: RoomList.Response, connection: ServerConnection):
        me = self._user_manager.get_self()
        for idx, room_name in enumerate(message.rooms):
            room = self.get_or_create_room(room_name, private=False)
            room.user_count = message.rooms_user_count[idx]

        for idx, room_name in enumerate(message.rooms_private_owned):
            room = self.get_or_create_room(room_name, private=True)
            room.owner = me.name
            room.user_count = message.rooms_private_owned_user_count[idx]

        for idx, room_name in enumerate(message.rooms_private):
            room = self.get_or_create_room(room_name, private=True)
            room.members.add(me.name)
            room.user_count = message.rooms_private_user_count[idx]

        for room_name in message.rooms_private_operated:
            room = self.get_or_create_room(room_name, private=True)
            room.operators.add(me.name)

        # Remove all rooms no longer tracked
        all_rooms = set(message.rooms) | set(message.rooms_private) | set(message.rooms_private_owned)
        unknown_rooms = set(self._rooms.keys()) - all_rooms
        for unknown_room in unknown_rooms:
            del self._rooms[unknown_room]

        # For the remaining rooms update owner, operators, members, private
        for room_name, room in self._rooms.items():
            if room_name not in message.rooms_private_owned:
                if room.owner == me.name:
                    room.owner = None

            if room_name not in message.rooms_private_operated:
                room.operators.discard(me.name)

            if room_name not in message.rooms_private:
                room.members.discard(me.name)

            room.private = room_name not in message.rooms

        await self._event_bus.emit(
            RoomListEvent(
                rooms=list(self._rooms.values()),
                raw_message=message
            )
        )

    # Listeners

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            self.reset_rooms()

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        await self._network.send_server_messages(
            TogglePrivateRoomInvites.Request(self._settings.rooms.private_room_invites)
        )
        if not self._settings.rooms.auto_join:
            await self.auto_join_rooms()
