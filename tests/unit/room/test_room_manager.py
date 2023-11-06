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
    RoomChatMessage,
    JoinRoom,
    LeaveRoom,
    RoomTickerAdded,
    RoomTickerRemoved,
    RoomTickers,
    UserJoinedRoom,
    UserLeftRoom,
)
from aioslsk.protocol.primitives import RoomTicker, UserStats
from aioslsk.room.manager import RoomManager
from aioslsk.session import Session
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager
from aioslsk.user.model import User

import pytest
from unittest.mock import AsyncMock, Mock, patch

DEFAULT_USER = 'user0'
DEFAULT_SETTINGS = {
    'credentials': {
        'username': DEFAULT_USER,
        'password': 'password0'
    }
}


@pytest.fixture
def session() -> Session:
    return Session(
        User(DEFAULT_USER),
        ip_address='1.2.3.4',
        greeting='',
        client_version=157,
        minor_version=100
    )


@pytest.fixture
def user_manager(session: Session) -> UserManager:
    user_manager = UserManager(
        Settings(**DEFAULT_SETTINGS),
        Mock(), # Event bus
        AsyncMock(), # Network
    )
    user_manager._session = session
    user_manager.get_user_object(session.user.name)

    return user_manager


@pytest.fixture
def manager(user_manager: UserManager) -> RoomManager:
    event_bus = EventBus()
    network = AsyncMock()
    network.server = AsyncMock()

    manager = RoomManager(
        Settings(**DEFAULT_SETTINGS),
        event_bus,
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

    def test_getPublicRooms(self, manager: RoomManager):
        room0 = manager.get_or_create_room('room0')
        room0.private = False
        room1 = manager.get_or_create_room('room1')
        room1.private = True

        rooms = manager.get_public_rooms()

        assert rooms == [room0]

    def test_getPrivateRooms(self, manager: RoomManager):
        room0 = manager.get_or_create_room('room0')
        room0.private = False
        room1 = manager.get_or_create_room('room1')
        room1.private = True

        rooms = manager.get_private_rooms()

        assert rooms == [room1]

    def test_getOperatedRooms(self, manager: RoomManager):
        user0 = manager._user_manager.get_user_object(DEFAULT_USER)
        user1 = manager._user_manager.get_user_object('user1')

        room0 = manager.get_or_create_room('room0')
        room0.private = True
        room0.owner = user1
        room0.operators = {user0.name}
        room1 = manager.get_or_create_room('room1')
        room1.private = True
        room0.owner = user1

        rooms = manager.get_operated_rooms()

        assert rooms == [room0]

    def test_getOwnedRooms(self, manager: RoomManager):
        user0 = manager._user_manager.get_user_object(DEFAULT_USER)
        user1 = manager._user_manager.get_user_object('user1')

        room0 = manager.get_or_create_room('room0')
        room0.private = True
        room0.owner = user0.name
        room1 = manager.get_or_create_room('room1')
        room1.private = True
        room1.owner = user1.name

        rooms = manager.get_owned_rooms()

        assert rooms == [room0]

    def test_getJoinedRooms(self, manager: RoomManager):
        room0 = manager.get_or_create_room('room0')
        room0.joined = True
        manager.get_or_create_room('room1')

        rooms = manager.get_joined_rooms()

        assert rooms == [room0]

    # def test_resetUsersAndRooms(self, manager: RoomManager):
    #     user0 = manager.get_user_object('user0')
    #     user0.status = UserStatus.ONLINE
    #     user0.tracking_flags = TrackingFlag.FRIEND

    #     user1 = manager.get_user_object('user1')
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

        raw_message = RoomTickers.Response(
            room='room0',
            tickers=[
                RoomTicker('user0', 'hello'),
                RoomTicker('user1', 'world')
            ]
        )
        await manager._on_chat_room_tickers(raw_message, manager._network.server)
        # Check model
        expected_tickers = {
            'user0': 'hello',
            'user1': 'world'
        }

        assert manager.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickersEvent(
                manager.rooms['room0'],
                tickers=expected_tickers,
                raw_message=raw_message
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerAdded_shouldUpdateModelAndEmit(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerAddedEvent, callback)

        raw_message = RoomTickerAdded.Response(room='room0', username='user0', ticker='hello')
        await manager._on_chat_room_ticker_added(raw_message, manager._network.server)
        # Check model
        expected_tickers = {'user0': 'hello'}

        assert manager.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickerAddedEvent(
                manager.rooms['room0'],
                manager._user_manager.users['user0'],
                'hello',
                raw_message=raw_message
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_shouldUpdateModelAndEmit(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        room = manager.get_or_create_room('room0')
        room.tickers['user0'] = 'hello'

        raw_message = RoomTickerRemoved.Response(room='room0', username='user0')
        await manager._on_chat_room_ticker_removed(raw_message, manager._network.server)
        # Check model
        expected_tickers = {}

        assert manager.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickerRemovedEvent(
                manager.rooms['room0'],
                manager._user_manager.users['user0'],
                raw_message=raw_message
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_noTickerForUser_shouldWarnAndEmit(self, caplog, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        manager.get_or_create_room('room0')

        raw_message = RoomTickerRemoved.Response(room='room0', username='user0')
        await manager._on_chat_room_ticker_removed(raw_message, manager._network.server)

        assert caplog.records[-1].levelname == 'WARNING'
        callback.assert_awaited_once_with(
            RoomTickerRemovedEvent(
                manager.rooms['room0'],
                manager._user_manager.users['user0'],
                raw_message=raw_message
            )
        )

    @pytest.mark.asyncio
    async def test_onRoomChatMessage_shouldEmitEvent(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomMessageEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_user_object('user0')

        raw_message = RoomChatMessage.Response(
            room='room0',
            username='user0',
            message='hello'
        )
        with patch('time.time', return_value=100.0):
            await manager._on_chat_room_message(raw_message, manager._network.server)

        message = RoomMessage(timestamp=100.0, room=room, user=user, message='hello')
        callback.assert_awaited_once_with(
            RoomMessageEvent(message, raw_message=raw_message))

    @pytest.mark.asyncio
    async def test_onJoinRoom_shouldUpdateRoomAndUsers(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomJoinedEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_user_object('user0')

        user_stats = (1, 2, 3, 4)

        raw_message = JoinRoom.Response(
            room='room0',
            users=['user0'],
            users_status=[UserStatus.ONLINE],
            users_stats=[UserStats(*user_stats)],
            users_slots_free=[10],
            users_countries=['US'],
            owner='user0',
            operators=['user0']
        )
        await manager._on_join_room(raw_message, manager._network.server)

        assert user in room.users
        assert room.joined is True
        assert room.owner == user.name
        assert user.name in room.operators

        assert user_stats == (user.avg_speed, user.uploads, user.shared_file_count, user.shared_folder_count)
        assert 'US' == user.country
        assert 10 == user.slots_free
        assert UserStatus.ONLINE == user.status

        callback.assert_awaited_once_with(
            RoomJoinedEvent(
                room=room,
                user=None,
                raw_message=raw_message
            )
        )

    @pytest.mark.asyncio
    async def test_onLeaveRoom_shouldUpdateRoomAndUsers(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomLeftEvent, callback)

        user0 = manager._user_manager.get_user_object('user0')

        room0 = manager.get_or_create_room('room0')
        room0.joined = True
        room0.add_user(user0)

        raw_message = LeaveRoom.Response(room='room0')
        await manager._on_leave_room(raw_message, manager._network.server)

        assert len(room0.users) == 0
        assert room0.joined is False

        callback.assert_awaited_once_with(
            RoomLeftEvent(room=room0, raw_message=raw_message, user=None))

    @pytest.mark.asyncio
    async def test_onUserJoinedRoom_shouldAddUserToRoom(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomJoinedEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_user_object('user0')

        user_stats = (1, 2, 3, 4)
        raw_message = UserJoinedRoom.Response(
            room='room0',
            username='user0',
            status=UserStatus.ONLINE,
            user_stats=UserStats(*user_stats),
            slots_free=10,
            country_code='US'
        )
        await manager._on_user_joined_room(raw_message, manager._network.server)

        assert user in room.users

        assert user_stats == (user.avg_speed, user.uploads, user.shared_file_count, user.shared_folder_count)
        assert 'US' == user.country
        assert 10 == user.slots_free
        assert UserStatus.ONLINE == user.status
        callback.assert_awaited_once_with(
            RoomJoinedEvent(
                room=room,
                user=user,
                raw_message=raw_message
            )
        )

    @pytest.mark.asyncio
    async def test_onUserLeftRoom_shouldRemoveUserFromRoom(self, manager: RoomManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomLeftEvent, callback)

        room = manager.get_or_create_room('room0')
        user = manager._user_manager.get_user_object('user0')
        room.add_user(user)

        raw_message = UserLeftRoom.Response(room='room0', username='user0')
        await manager._on_user_left_room(raw_message, manager._network.server)

        assert 0 == len(room.users)
        callback.assert_awaited_once_with(
            RoomLeftEvent(
                room=room,
                user=user,
                raw_message=raw_message
            )
        )
