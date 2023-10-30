from collections import OrderedDict
import logging
import time
from typing import Dict, List

from ..base_manager import BaseManager
from ..events import (
    build_message_map,
    ConnectionStateChangedEvent,
    EventBus,
    InternalEventBus,
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
    UserInfoEvent,
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
from ..user.model import UserStatus, TrackingFlag

logger = logging.getLogger(__name__)


class RoomManager(BaseManager):
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

        self._MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    @property
    def joined_rooms(self) -> List[Room]:
        return [room for room in self.rooms.values() if room.joined]

    @property
    def private_rooms(self) -> List[Room]:
        return [room for room in self.rooms.values() if room.private]

    @property
    def public_rooms(self) -> List[Room]:
        return [room for room in self.rooms.values() if not room.private]

    @property
    def owned_rooms(self) -> List[Room]:
        me = self._user_manager.get_self()
        return [room for room in self.rooms.values() if room.owner == me]

    @property
    def operated_rooms(self) -> List[Room]:
        me = self._user_manager.get_self()
        return [room for room in self.rooms.values() if me in room.operators]

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
        self._internal_event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)

    async def auto_join_rooms(self):
        """Automatically joins rooms stored in the settings"""
        rooms = self._settings.rooms.favorites
        logger.info(f"automatically rejoining {len(rooms)} rooms")
        await self._network.send_server_messages(
            *[JoinRoom.Request(room) for room in rooms]
        )

    @on_message(RoomChatMessage.Response)
    async def _on_chat_room_message(self, message: RoomChatMessage.Response, connection: ServerConnection):
        user = self._user_manager.get_or_create_user(message.username)
        room = self.get_or_create_room(message.room)
        room_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=message.message
        )

        await self._event_bus.emit(RoomMessageEvent(room_message))

    @on_message(PublicChatMessage.Response)
    async def _on_public_chat_message(self, message: PublicChatMessage.Response, connection: ServerConnection):
        user = self._user_manager.get_or_create_user(message.username)
        room = self.get_or_create_room(message.room)
        public_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=message.message
        )

        await self._event_bus.emit(PublicMessageEvent(public_message))

    @on_message(UserJoinedRoom.Response)
    async def _on_user_joined_room(self, message: UserJoinedRoom.Response, connection: ServerConnection):
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

    @on_message(UserLeftRoom.Response)
    async def _on_user_left_room(self, message: UserLeftRoom.Response, connection: ServerConnection):
        user = self._user_manager.get_or_create_user(message.username)
        room = self.get_or_create_room(message.room)

        # Remove tracking flag if there's no room left which the user is in
        for joined_room in self.joined_rooms:
            if joined_room != room and user in joined_room.users:
                break
        else:
            await self._user_manager.untrack_user(user.name, TrackingFlag.ROOM_USER)

        room.remove_user(user)

        await self._event_bus.emit(
            RoomLeftEvent(room=room, user=user))

    @on_message(JoinRoom.Response)
    async def _on_join_room(self, message: JoinRoom.Response, connection: ServerConnection):
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

    @on_message(LeaveRoom.Response)
    async def _on_leave_room(self, message: LeaveRoom.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)

        # Remove tracking flag from users (that are no longer in other rooms)
        for user in room.users:
            for joined_room in self.joined_rooms:
                if joined_room == room:
                    continue
                if user in joined_room.users:
                    break
            else:
                await self._user_manager.untrack_user(user.name, TrackingFlag.ROOM_USER)

        room.joined = False
        room.users = []

        await self._event_bus.emit(RoomLeftEvent(room=room))

    @on_message(RoomTickers.Response)
    async def _on_chat_room_tickers(self, message: RoomTickers.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        tickers = OrderedDict()
        for ticker in message.tickers:
            self._user_manager.get_or_create_user(ticker.username)
            tickers[ticker.username] = ticker.ticker

        # Just replace all tickers instead of modifying the existing dict
        room.tickers = tickers

        await self._event_bus.emit(RoomTickersEvent(room, tickers))

    @on_message(RoomTickerAdded.Response)
    async def _on_chat_room_ticker_added(self, message: RoomTickerAdded.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_or_create_user(message.username)

        room.tickers[user.name] = message.ticker

        await self._event_bus.emit(RoomTickerAddedEvent(room, user, message.ticker))

    @on_message(RoomTickerRemoved.Response)
    async def _on_chat_room_ticker_removed(self, message: RoomTickerRemoved.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room)
        user = self._user_manager.get_or_create_user(message.username)

        try:
            del room.tickers[user.name]
        except KeyError:
            logger.warning(
                f"attempted to remove room ticker for user {user.name} in room {room.name} "
                "but it wasn't present")

        await self._event_bus.emit(RoomTickerRemovedEvent(room, user))

    @on_message(TogglePrivateRoomInvites.Response)
    async def _on_private_room_toggle(self, message: TogglePrivateRoomInvites.Response, connection: ServerConnection):
        logger.debug(f"private rooms enabled : {message.enabled}")

    @on_message(PrivateRoomGrantMembership.Response)
    async def _on_private_room_add_user(self, message: PrivateRoomGrantMembership.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.add_member(user)

        await self._event_bus.emit(
            RoomMembershipGrantedEvent(room=room, member=user))

    @on_message(PrivateRoomMembershipGranted.Response)
    async def _on_private_room_added(self, message: PrivateRoomMembershipGranted.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_self()
        room.add_member(user)

        await self._event_bus.emit(
            RoomMembershipGrantedEvent(room=room))

    @on_message(PrivateRoomRevokeMembership.Response)
    async def _on_private_room_remove_user(self, message: PrivateRoomRevokeMembership.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.remove_member(user)
        room.remove_operator(user)

        await self._event_bus.emit(
            RoomMembershipRevokedEvent(room=room, member=user))

    @on_message(PrivateRoomMembershipRevoked.Response)
    async def _on_private_room_removed(self, message: PrivateRoomMembershipRevoked.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_self()
        room.remove_member(user)
        room.remove_operator(user)

        await self._event_bus.emit(
            RoomMembershipRevokedEvent(room=room))

    @on_message(PrivateRoomMembers.Response)
    async def _on_private_room_users(self, message: PrivateRoomMembers.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.members = list(
            map(self._user_manager.get_or_create_user, message.usernames)
        )

        await self._event_bus.emit(
            RoomMembersEvent(room, room.members))

    @on_message(PrivateRoomOperators.Response)
    async def _on_private_room_operators(self, message: PrivateRoomOperators.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.operators = list(
            map(self._user_manager.get_or_create_user, message.usernames))

        await self._event_bus.emit(
            RoomOperatorsEvent(room, room.operators))

    @on_message(PrivateRoomOperatorGranted.Response)
    async def _on_private_room_operator_added(self, message: PrivateRoomOperatorGranted.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.is_operator = True

        await self._event_bus.emit(
            RoomOperatorGrantedEvent(room=room))

    @on_message(PrivateRoomOperatorRevoked.Response)
    async def _on_private_room_operator_removed(self, message: PrivateRoomOperatorRevoked.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        room.is_operator = False

        await self._event_bus.emit(
            RoomOperatorRevokedEvent(room=room))

    @on_message(PrivateRoomGrantOperator.Response)
    async def _on_private_room_add_operator(self, message: PrivateRoomGrantOperator.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.add_operator(user)
        await self._event_bus.emit(
            RoomOperatorGrantedEvent(room=room, member=user))

    @on_message(PrivateRoomRevokeOperator.Response)
    async def _on_private_room_remove_operators(self, message: PrivateRoomRevokeOperator.Response, connection: ServerConnection):
        room = self.get_or_create_room(message.room, private=True)
        user = self._user_manager.get_or_create_user(message.username)
        room.remove_operator(user)

        await self._event_bus.emit(
            RoomOperatorRevokedEvent(room=room, member=user))

    @on_message(RoomList.Response)
    async def _on_room_list(self, message: RoomList.Response, connection):
        me = self._user_manager.get_self()
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
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            self.reset_rooms()

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        logger.debug(f"rooms : session initialized : {event.session}")
        await self._network.send_server_messages(
            TogglePrivateRoomInvites.Request(self._settings.rooms.private_room_invites)
        )
        if not self._settings.rooms.auto_join:
            await self.auto_join_rooms()
