from aioslsk.events import (
    EventBus,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomMessageEvent,
    RoomTickersEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
)
from aioslsk.room.model import Room, RoomMessage
from aioslsk.user.model import UserStatus, TrackingFlag
from aioslsk.protocol.messages import (
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    ChatRoomMessage,
    ChatRoomTickerAdded,
    ChatRoomTickers,
    ChatRoomTickerRemoved,
)
from aioslsk.protocol.primitives import RoomTicker, UserStats
from aioslsk.room.manager import RoomManager
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager

import pytest
from unittest.mock import AsyncMock, Mock, patch


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234'
    }
}


@pytest.fixture
def user_manager() -> UserManager:
    user_manager = UserManager(
        Settings(DEFAULT_SETTINGS),
        Mock(), # Event bus
        Mock(), # Internal event bus
        AsyncMock(), # Network
    )
    return user_manager


@pytest.fixture
def manager(user_manager: UserManager) -> RoomManager:
    event_bus = EventBus()
    internal_event_bus = Mock()
    network = AsyncMock()
    network.server = AsyncMock()

    manager = RoomManager(
        Settings(DEFAULT_SETTINGS),
        event_bus,
        internal_event_bus,
        user_manager,
        network
    )

    return manager


class TestRoomManager:

    def test_whenMissingRoom_shouldCreateAndReturnRoom(self, manager: RoomManager):
        room_name = 'myroom'

        room = manager.get_or_create_room(room_name)
        assert isinstance(room, Room)
        assert room_name == room.name
        assert room_name in manager.rooms

    def test_whenExistingRoom_shouldReturnRoom(self, manager: RoomManager):
        room_name = 'myuser'
        user = Room(name=room_name)
        manager.rooms[room_name] = user

        assert user == manager.get_or_create_room(room_name)

    def test_getJoinedRooms(self, manager: RoomManager):
        room0 = manager.get_or_create_room('room0')
        room0.joined = True
        manager.get_or_create_room('room1')

        rooms = manager.get_joined_rooms()

        assert rooms == [room0]

    # def test_resetUsersAndRooms(self, manager: RoomManager):
    #     user0 = manager.get_or_create_user('user0')
    #     user0.status = UserStatus.ONLINE
    #     user0.tracking_flags = TrackingFlag.FRIEND

    #     user1 = manager.get_or_create_user('user1')
    #     room = manager.get_or_create_room('room0')
    #     room.add_user(user1)

    #     manager.reset_users_and_rooms()

    #     assert user0.status == UserStatus.UNKNOWN
    #     assert user0.tracking_flags == TrackingFlag(0)

    #     assert len(room.users) == 0

    @pytest.mark.asyncio
    async def test_whenRoomTickersReceived_shouldUpdateModelAndEmit(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickersEvent, callback)

        await manager._on_chat_room_tickers(
            ChatRoomTickers.Response(
                room='room0',
                tickers=[
                    RoomTicker('user0', 'hello'),
                    RoomTicker('user1', 'world')
                ]
            ),
            manager._network.server
        )
        # Check model
        expected_tickers = {
            'user0': 'hello',
            'user1': 'world'
        }

        assert manager.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickersEvent(
                manager.rooms['room0'],
                tickers=expected_tickers
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerAdded_shouldUpdateModelAndEmit(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerAddedEvent, callback)

        await manager._on_chat_room_ticker_added(
            ChatRoomTickerAdded.Response(
                room='room0', username='user0', ticker='hello'),
            manager._network.server
        )
        # Check model
        expected_tickers = {'user0': 'hello'}

        assert manager.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickerAddedEvent(
                manager.rooms['room0'],
                manager._user_manager.users['user0'],
                'hello',
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_shouldUpdateModelAndEmit(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        room = manager.get_or_create_room('room0')
        room.tickers['user0'] = 'hello'

        await manager._on_chat_room_ticker_removed(
            ChatRoomTickerRemoved.Response(room='room0', username='user0'),
            manager._network.server
        )
        # Check model
        expected_tickers = {}

        assert manager.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickerRemovedEvent(
                manager.rooms['room0'],
                manager._user_manager.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_noTickerForUser_shouldWarnAndEmit(self, caplog, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        manager.get_or_create_room('room0')

        await manager._on_chat_room_ticker_removed(
            ChatRoomTickerRemoved.Response(room='room0', username='user0'),
            manager._network.server
        )

        assert caplog.records[-1].levelname == 'WARNING'
        callback.assert_awaited_once_with(
            RoomTickerRemovedEvent(
                manager.rooms['room0'],
                manager._user_manager.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_onChatRoomMessage_shouldEmitEvent(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomMessageEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_or_create_user('user0')

        with patch('time.time', return_value=100.0):
            await manager._on_chat_room_message(
                ChatRoomMessage.Response(
                    room='room0',
                    username='user0',
                    message='hello'
                ),
                manager._network.server
            )

        message = RoomMessage(timestamp=100.0, room=room, user=user, message='hello')
        callback.assert_awaited_once_with(RoomMessageEvent(message))

    @pytest.mark.asyncio
    async def test_onJoinRoom_shouldUpdateRoomAndUsers(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomJoinedEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_or_create_user('user0')

        user_stats = (1, 2, 3, 4)
        await manager._on_join_room(
            ChatJoinRoom.Response(
                room='room0',
                users=['user0'],
                users_status=[UserStatus.ONLINE],
                users_stats=[UserStats(*user_stats)],
                users_slots_free=[10],
                users_countries=['US'],
                owner='user0',
                operators=['user0']
            ),
            manager._network.server
        )

        assert user in room.users
        assert room.joined is True
        assert room.owner == user
        assert user in room.operators

        assert user_stats == (user.avg_speed, user.uploads, user.shared_file_count, user.shared_folder_count)
        assert 'US' == user.country
        assert 10 == user.slots_free
        assert UserStatus.ONLINE == user.status
        assert TrackingFlag.ROOM_USER in user.tracking_flags

        callback.assert_awaited_once_with(RoomJoinedEvent(room, None))

    @pytest.mark.asyncio
    async def test_onLeaveRoom_shouldUpdateRoomAndUsers(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomLeftEvent, callback)

        # Create 2 rooms: first room with 2 users, second with 1 user
        # After leaving the tracking for the user we no longer share any rooms
        # with should be disabled and the status reset
        user0 = manager._user_manager.get_or_create_user('user0')
        user0.status = UserStatus.ONLINE
        user0.tracking_flags = TrackingFlag.ROOM_USER
        user1 = manager._user_manager.get_or_create_user('user1')
        user1.status = UserStatus.ONLINE
        user1.tracking_flags = TrackingFlag.ROOM_USER

        room0 = manager.get_or_create_room('room0')
        room0.joined = True
        room0.add_user(user0)
        room0.add_user(user1)

        room1 = manager.get_or_create_room('room1')
        room1.joined = True
        room1.add_user(user0)

        await manager._on_leave_room(
            ChatLeaveRoom.Response(room='room0'),
            manager._network.server
        )

        assert room0.joined is False
        assert room0.users == []

        assert user0.status == UserStatus.ONLINE
        assert TrackingFlag.ROOM_USER in user0.tracking_flags

        assert user1.status == UserStatus.UNKNOWN
        assert TrackingFlag.ROOM_USER not in user1.tracking_flags

        callback.assert_awaited_once_with(RoomLeftEvent(room0, None))

    @pytest.mark.asyncio
    async def test_onUserJoinedRoom_shouldAddUserToRoom(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomJoinedEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_or_create_user('user0')

        user_stats = (1, 2, 3, 4)
        await manager._on_user_joined_room(
            ChatUserJoinedRoom.Response(
                room='room0',
                username='user0',
                status=UserStatus.ONLINE,
                user_stats=UserStats(*user_stats),
                slots_free=10,
                country_code='US'
            ),
            manager._network.server
        )

        assert user in room.users

        assert user_stats == (user.avg_speed, user.uploads, user.shared_file_count, user.shared_folder_count)
        assert 'US' == user.country
        assert 10 == user.slots_free
        assert UserStatus.ONLINE == user.status
        assert TrackingFlag.ROOM_USER in user.tracking_flags
        callback.assert_awaited_once_with(RoomJoinedEvent(room, user))

    @pytest.mark.asyncio
    async def test_onUserLeftRoom_shouldRemoveUserFromRoom(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomLeftEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_or_create_user('user0')
        room.add_user(user)

        await manager._on_user_left_room(
            ChatUserLeftRoom.Response(room='room0', username='user0'),
            manager._network.server
        )

        assert TrackingFlag.ROOM_USER not in user.tracking_flags
        assert 0 == len(room.users)
        callback.assert_awaited_once_with(RoomLeftEvent(room, user))

    @pytest.mark.asyncio
    async def test_whenSetRoomTicker_shouldSetRoomTicker(self, manager: RoomManager):
        await manager.set_room_ticker('room0', 'hello')
        manager._network.send_server_messages.assert_awaited_once()
