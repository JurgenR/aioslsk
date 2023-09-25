from aioslsk.events import (
    EventBus,
    PrivateMessageEvent,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomMessageEvent,
    RoomTickersEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    UserJoinedRoomEvent,
    UserLeftRoomEvent,
)
from aioslsk.model import ChatMessage, RoomMessage, UserStatus, TrackingFlag
from aioslsk.protocol.messages import (
    AddUser,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    ChatRoomMessage,
    ChatRoomTickerAdded,
    ChatRoomTickers,
    ChatRoomTickerRemoved,
    RemoveUser,
)
from aioslsk.protocol.primitives import RoomTicker, UserStats
from aioslsk.search import SearchType
from aioslsk.settings import Settings
from aioslsk.server import ServerManager
from aioslsk.state import State

import pytest
from unittest.mock import AsyncMock, Mock, patch


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234'
    }
}

@pytest.fixture
def manager() -> ServerManager:
    state = State()
    event_bus = EventBus()
    internal_event_bus = Mock()
    shares_manager = Mock()
    network = AsyncMock()
    network.server = AsyncMock()

    manager = ServerManager(
        state,
        Settings(DEFAULT_SETTINGS),
        event_bus,
        internal_event_bus,
        shares_manager,
        network
    )

    return manager


class TestServerManager:

    @pytest.mark.asyncio
    async def test_trackUser_userNotTracked_shouldSendAddUser(self, manager: ServerManager):
        user = manager._state.get_or_create_user('user0')

        await manager.track_user('user0', TrackingFlag.REQUESTED)

        assert user.tracking_flags == TrackingFlag.REQUESTED
        manager._network.send_server_messages.assert_awaited_once_with(
            AddUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_trackUser_userTracked_shouldNotSendAddUser(self, manager: ServerManager):
        user = manager._state.get_or_create_user('user0')
        user.status = UserStatus.ONLINE
        user.tracking_flags = TrackingFlag.FRIEND

        await manager.track_user('user0', TrackingFlag.REQUESTED)

        assert user.tracking_flags == TrackingFlag.REQUESTED | TrackingFlag.FRIEND
        assert 0 == manager._network.send_server_messages.await_count

    @pytest.mark.asyncio
    async def test_untrackUser_lastAddUserFlag_shouldSendRemoveUser(self, manager: ServerManager):
        user = manager._state.get_or_create_user('user0')
        user.status = UserStatus.ONLINE
        user.tracking_flags = TrackingFlag.FRIEND

        await manager.untrack_user('user0', TrackingFlag.FRIEND)

        assert user.status == UserStatus.UNKNOWN
        assert user.tracking_flags == TrackingFlag(0)
        manager._network.send_server_messages.assert_awaited_once_with(
            RemoveUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_untrackUser_lastAddUserFlag_shouldSendRemoveUserAndNotSetStatusUnknown(self, manager: ServerManager):
        user = manager._state.get_or_create_user('user0')
        user.status = UserStatus.ONLINE
        user.tracking_flags = TrackingFlag.FRIEND | TrackingFlag.ROOM_USER

        await manager.untrack_user('user0', TrackingFlag.FRIEND)

        assert user.status == UserStatus.ONLINE
        assert user.tracking_flags == TrackingFlag.ROOM_USER
        manager._network.send_server_messages.assert_awaited_once_with(
            RemoveUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_untrackUser_addUserFlagRemains_shouldNotSendRemoveUser(self, manager: ServerManager):
        user = manager._state.get_or_create_user('user0')
        user.tracking_flags = TrackingFlag.FRIEND | TrackingFlag.REQUESTED

        await manager.untrack_user('user0', TrackingFlag.FRIEND)

        assert user.tracking_flags == TrackingFlag.REQUESTED
        assert 0 == manager._network.send_server_messages.await_count

    @pytest.mark.asyncio
    async def test_whenRoomTickersReceived_shouldUpdateModelAndEmit(self, manager: ServerManager):
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

        assert manager._state.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickersEvent(
                manager._state.rooms['room0'],
                tickers=expected_tickers
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerAdded_shouldUpdateModelAndEmit(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerAddedEvent, callback)

        await manager._on_chat_room_ticker_added(
            ChatRoomTickerAdded.Response(
                room='room0', username='user0', ticker='hello'),
            manager._network.server
        )
        # Check model
        expected_tickers = {'user0': 'hello'}

        assert manager._state.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickerAddedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0'],
                'hello',
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_shouldUpdateModelAndEmit(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        room = manager._state.get_or_create_room('room0')
        room.tickers['user0'] = 'hello'

        await manager._on_chat_room_ticker_removed(
            ChatRoomTickerRemoved.Response(room='room0', username='user0'),
            manager._network.server
        )
        # Check model
        expected_tickers = {}

        assert manager._state.rooms['room0'].tickers == expected_tickers
        callback.assert_awaited_once_with(
            RoomTickerRemovedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_noTickerForUser_shouldWarnAndEmit(self, caplog, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        manager._state.get_or_create_room('room0')

        await manager._on_chat_room_ticker_removed(
            ChatRoomTickerRemoved.Response(room='room0', username='user0'),
            manager._network.server
        )

        assert caplog.records[-1].levelname == 'WARNING'
        callback.assert_awaited_once_with(
            RoomTickerRemovedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_onChatRoomMessage_shouldEmitEvent(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomMessageEvent, callback)

        room = manager._state.get_or_create_room('room0')
        user = manager._state.get_or_create_user('user0')

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
    async def test_onChatPrivateMessage_shouldSendAckAndEmitEvent(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(PrivateMessageEvent, callback)

        user = manager._state.get_or_create_user('user0')

        await manager._on_private_message(
            ChatPrivateMessage.Response(
                chat_id=1,
                username='user0',
                message='hello',
                timestamp=100.0,
                is_admin=False
            ),
            manager._network.server
        )

        manager._network.send_server_messages.assert_awaited_once_with(
            ChatAckPrivateMessage.Request(1)
        )
        message = ChatMessage(
            id=1,
            timestamp=100.0,
            user=user,
            message='hello',
            is_admin=False
        )
        callback.assert_awaited_once_with(PrivateMessageEvent(message))

    @pytest.mark.asyncio
    async def test_onJoinRoom_shouldUpdateRoomAndUsers(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomJoinedEvent, callback)

        room = manager._state.get_or_create_room('room0')
        user = manager._state.get_or_create_user('user0')

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

        callback.assert_awaited_once_with(RoomJoinedEvent(room))

    @pytest.mark.asyncio
    async def test_onLeaveRoom_shouldUpdateRoomAndUsers(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(RoomLeftEvent, callback)

        # Create 2 rooms: first room with 2 users, second with 1 user
        # After leaving the tracking for the user we no longer share any rooms
        # with should be disabled and the status reset
        user0 = manager._state.get_or_create_user('user0')
        user0.status = UserStatus.ONLINE
        user0.tracking_flags = TrackingFlag.ROOM_USER
        user1 = manager._state.get_or_create_user('user1')
        user1.status = UserStatus.ONLINE
        user1.tracking_flags = TrackingFlag.ROOM_USER

        room0 = manager._state.get_or_create_room('room0')
        room0.joined = True
        room0.add_user(user0)
        room0.add_user(user1)

        room1 = manager._state.get_or_create_room('room1')
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

        callback.assert_awaited_once_with(RoomLeftEvent(room0))

    @pytest.mark.asyncio
    async def test_onUserJoinedRoom_shouldAddUserToRoom(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(UserJoinedRoomEvent, callback)

        room = manager._state.get_or_create_room('room0')
        user = manager._state.get_or_create_user('user0')

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
        callback.assert_awaited_once_with(UserJoinedRoomEvent(room, user))

    @pytest.mark.asyncio
    async def test_onUserLeftRoom_shouldRemoveUserFromRoom(self, manager: ServerManager):
        callback = AsyncMock()
        manager._event_bus.register(UserLeftRoomEvent, callback)

        room = manager._state.get_or_create_room('room0')
        user = manager._state.get_or_create_user('user0')
        room.add_user(user)

        await manager._on_user_left_room(
            ChatUserLeftRoom.Response(room='room0', username='user0'),
            manager._network.server
        )

        assert TrackingFlag.ROOM_USER not in user.tracking_flags
        assert 0 == len(room.users)
        callback.assert_awaited_once_with(UserLeftRoomEvent(room, user))

    @pytest.mark.asyncio
    async def test_whenSetRoomTicker_shouldSetRoomTicker(self, manager: ServerManager):
        await manager.set_room_ticker('room0', 'hello')
        manager._network.send_server_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_searchNetwork_shouldSearchAndCreateEntry(self, manager: ServerManager):
        search_query = await manager.search('my query')
        assert 'my query' == search_query.query
        assert isinstance(search_query.ticket, int)
        assert SearchType.NETWORK == search_query.search_type

        manager._network.send_server_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_searchRoom_shouldSearchAndCreateEntry(self, manager: ServerManager):
        query = 'my query'
        room_name = 'room0'

        search_query = await manager.search_room(room_name, query)
        assert query == search_query.query
        assert isinstance(search_query.ticket, int)
        assert SearchType.ROOM == search_query.search_type
        assert room_name == search_query.room

        manager._network.send_server_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_searchUser_shouldSearchAndCreateEntry(self, manager: ServerManager):
        query = 'my query'
        username = 'room0'

        search_query = await manager.search_user(username, query)
        assert query == search_query.query
        assert isinstance(search_query.ticket, int)
        assert SearchType.USER == search_query.search_type
        assert username == search_query.username

        manager._network.send_server_messages.assert_awaited_once()
