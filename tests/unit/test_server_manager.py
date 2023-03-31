from pyslsk.events import (
    EventBus,
    RoomTickersEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
)
from pyslsk.protocol.messages import (
    ChatRoomTickerAdded,
    ChatRoomTickers,
    ChatRoomTickerRemoved,
)
from pyslsk.protocol.primitives import RoomTicker
from pyslsk.settings import Settings
from pyslsk.server_manager import ServerManager
from pyslsk.state import State

import pytest
from unittest.mock import AsyncMock, Mock


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
        # Check model
        callback.assert_called_once_with(
            RoomTickerRemovedEvent(
                manager._state.rooms['room0'],
                manager._state.users['user0']
            )
        )

    @pytest.mark.asyncio
    async def test_whenSetRoomTicker_shouldSetRoomTicker(self):
        manager = self._create_server_manager()

        await manager.set_room_ticker('room0', 'hello')
        manager.network.send_server_messages.assert_called_once()
