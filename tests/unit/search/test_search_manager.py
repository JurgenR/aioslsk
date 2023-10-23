from aioslsk.events import SearchResultEvent, UserInfoEvent
from aioslsk.protocol.primitives import FileData
from aioslsk.protocol.messages import (
    UserSearch,
    FileSearch,
    RoomSearch,
    PeerSearchReply,
)
from aioslsk.search.manager import SearchManager
from aioslsk.search.model import SearchType, SearchRequest
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager

import pytest
from unittest.mock import AsyncMock, Mock, call


DEFAULT_USER = 'testuser0'
DEFAULT_SETTINGS = {
    'credentials': {
        'username': DEFAULT_USER,
        'password': 'password0'
    }
}


@pytest.fixture
def user_manager() -> UserManager:
    user_manager = UserManager(
        Settings(**DEFAULT_SETTINGS),
        Mock(), # Event bus
        Mock(), # Internal event bus
        AsyncMock(), # Network
    )
    return user_manager


@pytest.fixture
def manager(user_manager: UserManager) -> SearchManager:
    network = Mock()
    network.send_server_messages = AsyncMock()
    event_bus = Mock()
    event_bus.emit = AsyncMock()
    event_bus.register = Mock()
    internal_event_bus = Mock()
    internal_event_bus.emit = AsyncMock()
    internal_event_bus.register = Mock()
    shares_manager = Mock()
    transfer_manager = Mock()

    return SearchManager(
        Settings(**DEFAULT_SETTINGS),
        event_bus,
        internal_event_bus,
        user_manager,
        shares_manager,
        transfer_manager,
        network
    )



class TestSearchManager:

    @pytest.mark.asyncio
    async def test_search(self, manager: SearchManager):
        request = await manager.search('query')

        assert request.search_type == SearchType.NETWORK
        assert request.ticket is not None
        assert request.query == 'query'
        assert request.username is None
        assert request.room is None

        assert request.ticket in manager.requests

        manager._network.send_server_messages.assert_awaited_once_with(
            FileSearch.Request(request.ticket, 'query')
        )

    @pytest.mark.asyncio
    async def test_searchUser(self, manager: SearchManager):
        request = await manager.search_user('user0', 'query')

        assert request.search_type == SearchType.USER
        assert request.ticket is not None
        assert request.query == 'query'
        assert request.username == 'user0'
        assert request.room is None

        assert request.ticket in manager.requests

        manager._network.send_server_messages.assert_awaited_once_with(
            UserSearch.Request('user0', request.ticket, 'query')
        )

    @pytest.mark.asyncio
    async def test_searchRoom(self, manager: SearchManager):
        request = await manager.search_room('room0', 'query')

        assert request.search_type == SearchType.ROOM
        assert request.ticket is not None
        assert request.query == 'query'
        assert request.username is None
        assert request.room == 'room0'

        assert request.ticket in manager.requests

        manager._network.send_server_messages.assert_awaited_once_with(
            RoomSearch.Request('room0', request.ticket, 'query')
        )

    @pytest.mark.asyncio
    async def test_onPeerSearchReply_shouldStoreResultsAndEmit(self, manager: SearchManager):
        TICKET = 1234
        connection = AsyncMock()

        manager.requests[TICKET] = SearchRequest(
            TICKET, 'search', SearchType.NETWORK)

        reply_message = PeerSearchReply.Request(
            'user0',
            TICKET,
            results=[FileData(1, 'myfile.mp3', 10000, 'mp3', attributes=[])],
            has_slots_free=True,
            avg_speed=100,
            queue_size=2,
            locked_results=[FileData(1, 'locked.mp3', 10000, 'mp3', attributes=[])]
        )
        await manager._on_peer_search_reply(reply_message, connection)

        assert 1 == len(manager.requests[TICKET].results)

        manager._event_bus.emit.assert_has_awaits(
            [
                call(
                    SearchResultEvent(
                        manager.requests[TICKET],
                        manager.requests[TICKET].results[0]
                    )
                ),
                call(UserInfoEvent(manager._user_manager.get_or_create_user('user0')))
            ]
        )
