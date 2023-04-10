from aioslsk.events import (
    EventBus,
    RoomMessageEvent,
    RoomTickersEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    UserJoinedRoomEvent,
    UserLeftRoomEvent,
)
from aioslsk.model import RoomMessage, UserStatus
from aioslsk.protocol.messages import (
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    ChatRoomMessage,
    ChatRoomTickerAdded,
    ChatRoomTickers,
    ChatRoomTickerRemoved,
)
from aioslsk.protocol.primitives import RoomTicker, UserData
from aioslsk.search import SearchType
from aioslsk.settings import Settings
from aioslsk.server_manager import ServerManager
from aioslsk.state import State

import pytest
from unittest.mock import AsyncMock, Mock, patch


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234'
    }
}


class TestServerManager:

    def _create_server_manager(self) -> ServerManager:
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

    @pytest.mark.asyncio
    async def test_whenRoomTickersReceived_shouldUpdateModelAndEmit(self):
        manager = self._create_server_manager()

        callback = Mock()
        manager._event_bus.register(RoomTickersEvent, callback)

        await manager._on_chat_room_tickers(
            ChatRoomTickers.Response(
                room='room0',
                tickers=[
                    RoomTicker('user0', 'hello'),
                    RoomTicker('user1', 'world')
                ]
            ),
            manager.network.server
        )
        # Check model
        expected_tickers = {
            'user0': 'hello',
            'user1': 'world'
        }

        assert manager._state.rooms['room0'].tickers == expected_tickers
        callback.assert_called_once_with(
            RoomTickersEvent(
                manager._state.rooms['room0'],
                tickers=expected_tickers
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerAdded_shouldUpdateModelAndEmit(self):
        manager = self._create_server_manager()

        callback = Mock()
        manager._event_bus.register(RoomTickerAddedEvent, callback)

        await manager._on_chat_room_ticker_added(
            ChatRoomTickerAdded.Response(
                room='room0', username='user0', ticker='hello'),
            manager.network.server
        )
        # Check model
        expected_tickers = {'user0': 'hello'}

        assert manager._state.rooms['room0'].tickers == expected_tickers
        callback.assert_called_once_with(
            RoomTickerAddedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0'],
                'hello',
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_shouldUpdateModelAndEmit(self):
        manager = self._create_server_manager()

        callback = Mock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        room = manager._state.get_or_create_room('room0')
        room.tickers['user0'] = 'hello'

        await manager._on_chat_room_ticker_removed(
            ChatRoomTickerRemoved.Response(room='room0', username='user0'),
            manager.network.server
        )
        # Check model
        expected_tickers = {}

        assert manager._state.rooms['room0'].tickers == expected_tickers
        callback.assert_called_once_with(
            RoomTickerRemovedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_whenRoomTickerRemoved_noTickerForUser_shouldWarnAndEmit(self, caplog):
        manager = self._create_server_manager()

        callback = Mock()
        manager._event_bus.register(RoomTickerRemovedEvent, callback)

        manager._state.get_or_create_room('room0')

        await manager._on_chat_room_ticker_removed(
            ChatRoomTickerRemoved.Response(room='room0', username='user0'),
            manager.network.server
        )

        assert caplog.records[-1].levelname == 'WARNING'
        callback.assert_called_once_with(
            RoomTickerRemovedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_onChatRoomMessage_shouldEmitEvent(self):
        manager = self._create_server_manager()

        callback = Mock()
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
                manager.network.server
            )

        message = RoomMessage(timestamp=100.0, room=room, user=user, message='hello')
        assert message == room.messages[-1]
        callback.assert_called_once_with(RoomMessageEvent(message))

    @pytest.mark.asyncio
    async def test_onUserJoinedRoom_shouldAddUser(self):
        manager = self._create_server_manager()

        callback = Mock()
        manager._event_bus.register(UserJoinedRoomEvent, callback)

        room = manager._state.get_or_create_room('room0')
        user = manager._state.get_or_create_user('user0')

        user_data = (1, 2, 3, 4)
        await manager._on_user_joined_room(
            ChatUserJoinedRoom.Response(
                room='room0',
                username='user0',
                status=UserStatus.ONLINE,
                user_data=UserData(*user_data),
                slots_free=10,
                country_code='US'
            ),
            manager.network.server
        )

        assert user in room.users

        assert user_data == (user.avg_speed, user.downloads, user.files, user.directories)
        assert 'US' == user.country
        assert 10 == user.has_slots_free
        assert UserStatus.ONLINE == user.status
        callback.assert_called_once_with(UserJoinedRoomEvent(room, user))

    @pytest.mark.asyncio
    async def test_onUserLeftRoom_shouldRemoveUser(self):
        manager = self._create_server_manager()

        callback = Mock()
        manager._event_bus.register(UserLeftRoomEvent, callback)

        room = manager._state.get_or_create_room('room0')
        user = manager._state.get_or_create_user('user0')
        room.add_user(user)

        await manager._on_user_left_room(
            ChatUserLeftRoom.Response(room='room0', username='user0'),
            manager.network.server
        )

        assert 0 == len(room.users)
        callback.assert_called_once_with(UserLeftRoomEvent(room, user))

    @pytest.mark.asyncio
    async def test_whenSetRoomTicker_shouldSetRoomTicker(self):
        manager = self._create_server_manager()

        await manager.set_room_ticker('room0', 'hello')
        manager.network.send_server_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_searchNetwork_shouldSearchAndCreateEntry(self):
        manager = self._create_server_manager()

        search_query = await manager.search('my query')
        assert 'my query' == search_query.query
        assert isinstance(search_query.ticket, int)
        assert SearchType.NETWORK == search_query.search_type

        manager.network.queue_server_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_searchRoom_shouldSearchAndCreateEntry(self):
        manager = self._create_server_manager()

        query = 'my query'
        room_name = 'room0'

        search_query = await manager.search_room(room_name, query)
        assert query == search_query.query
        assert isinstance(search_query.ticket, int)
        assert SearchType.ROOM == search_query.search_type
        assert room_name == search_query.room

        manager.network.queue_server_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_searchUser_shouldSearchAndCreateEntry(self):
        manager = self._create_server_manager()

        query = 'my query'
        username = 'room0'

        search_query = await manager.search_user(username, query)
        assert query == search_query.query
        assert isinstance(search_query.ticket, int)
        assert SearchType.USER == search_query.search_type
        assert username == search_query.username

        manager.network.queue_server_messages.assert_called_once()
