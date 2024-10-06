from aioslsk.client import SoulSeekClient
from aioslsk.events import (
    SearchRequestSentEvent,
    SearchRequestRemovedEvent,
)
from aioslsk.search.model import SearchRequest, SearchType
from aioslsk.settings import WishlistSettingEntry
from .mock.server import MockServer
from .mock.model import Settings
from .fixtures import mock_server, client_1
from .utils import (
    wait_until_clients_initialized,
    wait_for_listener_awaited,
    wait_for_listener_awaited_events,
)
import pytest
from typing import Tuple
from unittest.mock import AsyncMock


WISHLIST_INTERVAL = 2
SERVER_SETTINGS = Settings(wishlist_interval=WISHLIST_INTERVAL)


class TestE2ESearch:

    @pytest.mark.asyncio
    async def test_search_without_timeout(
            self, mock_server: MockServer, client_1: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=1)

        listener = AsyncMock()
        client_1.events.register(SearchRequestSentEvent, listener)

        client_1.settings.searches.send.request_timeout = 0

        query = 'test'
        request = await client_1.searches.search(query)
        assert request.query == query
        assert request.search_type == SearchType.NETWORK
        assert request.timer is None
        assert request in client_1.searches.requests.values()

        event: SearchRequestSentEvent = await wait_for_listener_awaited(listener)

        assert event.query == request

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'search_func_name,search_params,search_type',
        [
            ('search', ('test', ), SearchType.NETWORK),
            ('search_room', ('test', 'room0', ), SearchType.ROOM),
            ('search_user', ('test', 'user0', ), SearchType.USER)
        ]
    )
    async def test_search_with_timeout(
            self, mock_server: MockServer, client_1: SoulSeekClient,
            search_func_name: str, search_params: Tuple, search_type: SearchType):

        await wait_until_clients_initialized(mock_server, amount=1)

        sent_listener = AsyncMock()
        removed_listener = AsyncMock()
        client_1.events.register(SearchRequestSentEvent, sent_listener)
        client_1.events.register(SearchRequestRemovedEvent, removed_listener)

        client_1.settings.searches.send.request_timeout = 2

        search_func = getattr(client_1.searches, search_func_name)
        request: SearchRequest = await search_func(*search_params)
        assert request in client_1.searches.requests.values()
        assert request.search_type == search_type
        assert request.timer is not None
        assert request.timer.timeout == 2

        sent_event: SearchRequestSentEvent = await wait_for_listener_awaited(sent_listener)

        assert sent_event.query == request

        removed_event: SearchRequestRemovedEvent = await wait_for_listener_awaited(removed_listener, timeout=3)

        assert removed_event.query == request
        assert request not in client_1.searches.requests.values()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('mock_server', [SERVER_SETTINGS], indirect=True)
    async def test_search_wishlist_without_timeout(
            self, mock_server: MockServer, client_1: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=1)

        client_1.settings.searches.send.wishlist_request_timeout = 0
        client_1.settings.searches.wishlist.append(
            WishlistSettingEntry(query='test', enabled=True)
        )

        sent_listener = AsyncMock()
        client_1.events.register(SearchRequestSentEvent, sent_listener)

        event: SearchRequestSentEvent = await wait_for_listener_awaited(sent_listener)
        request = event.query

        assert request.query == 'test'
        assert request.search_type == SearchType.WISHLIST
        assert request.timer is None
        assert request in client_1.searches.requests.values()


    @pytest.mark.asyncio
    @pytest.mark.parametrize('mock_server', [SERVER_SETTINGS], indirect=True)
    async def test_search_wishlist_with_server_timeout(
            self, mock_server: MockServer, client_1: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=1)

        client_1.settings.searches.send.wishlist_request_timeout = -1
        client_1.settings.searches.wishlist.append(
            WishlistSettingEntry(query='test', enabled=True)
        )

        sent_listener = AsyncMock()
        removed_listener = AsyncMock()
        client_1.events.register(SearchRequestSentEvent, sent_listener)
        client_1.events.register(SearchRequestRemovedEvent, removed_listener)

        sent_event: SearchRequestSentEvent = await wait_for_listener_awaited(sent_listener)
        request = sent_event.query

        assert request.query == 'test'
        assert request.search_type == SearchType.WISHLIST
        assert request.timer is not None
        assert request.timer.timeout == WISHLIST_INTERVAL
        assert request in client_1.searches.requests.values()

        removed_event: SearchRequestRemovedEvent = await wait_for_listener_awaited(sent_listener)
        assert removed_event.query == request

    @pytest.mark.asyncio
    @pytest.mark.parametrize('mock_server', [SERVER_SETTINGS], indirect=True)
    async def test_search_wishlist_with_custom_timeout(
            self, mock_server: MockServer, client_1: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=1)

        client_1.settings.searches.send.wishlist_request_timeout = 3
        client_1.settings.searches.wishlist.append(
            WishlistSettingEntry(query='test', enabled=True)
        )

        sent_listener = AsyncMock()
        removed_listener = AsyncMock()
        client_1.events.register(SearchRequestSentEvent, sent_listener)
        client_1.events.register(SearchRequestRemovedEvent, removed_listener)

        sent_event: SearchRequestSentEvent = await wait_for_listener_awaited(sent_listener)
        request = sent_event.query

        assert request.query == 'test'
        assert request.search_type == SearchType.WISHLIST
        assert request.timer is not None
        assert request.timer.timeout == 3
        assert request in client_1.searches.requests.values()

        removed_event: SearchRequestRemovedEvent = await wait_for_listener_awaited(sent_listener)
        assert removed_event.query == request
