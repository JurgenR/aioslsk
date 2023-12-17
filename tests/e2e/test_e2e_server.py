from aioslsk.client import SoulSeekClient
from aioslsk.commands import (
    AddInterestCommand,
    AddHatedInterestCommand,
    GrantRoomMembershipCommand,
    GetGlobalRecommendationsCommand,
    GetItemSimilarUsersCommand,
    GetItemRecommendationsCommand,
    GetRecommendationsCommand,
    GetSimilarUsersCommand,
    GetUserStatusCommand,
    GetUserInterestsCommand,
    JoinRoomCommand,
    RemoveHatedInterestCommand,
    RemoveInterestCommand,
    SetStatusCommand,
    SetRoomTickerCommand,
)
from aioslsk.events import (
    GlobalRecommendationsEvent,
    ItemRecommendationsEvent,
    ItemSimilarUsersEvent,
    RecommendationsEvent,
    RoomJoinedEvent,
    RoomMembershipGrantedEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    SimilarUsersEvent,
    UserInterestsEvent,
)
from aioslsk.user.model import UserStatus
from aioslsk.room.model import Room
from aioslsk.protocol.primitives import Recommendation
from .mock.server import MockServer
from .fixtures import mock_server, client_1, client_2
from .utils import (
    wait_until_clients_initialized,
    wait_for_listener_awaited,
    wait_for_listener_awaited_events,
)
import asyncio
import pytest
from typing import Tuple
from unittest.mock import AsyncMock


class TestE2EServer:

    @pytest.mark.asyncio
    async def test_add_remove_interest(self, mock_server: MockServer, client_1: SoulSeekClient):
        await wait_until_clients_initialized(mock_server, amount=1)

        username = client_1.settings.credentials.username

        await client_1.execute(AddInterestCommand('interest0'), response=True)
        await asyncio.sleep(0.5)

        assert mock_server.find_user_by_name(username).interests == {'interest0'}

        await client_1.execute(RemoveInterestCommand('interest0'), response=True)
        await asyncio.sleep(0.5)

        assert len(mock_server.find_user_by_name(username).interests) == 0

    @pytest.mark.asyncio
    async def test_add_remove_hated_interest(self, mock_server: MockServer, client_1: SoulSeekClient):
        await wait_until_clients_initialized(mock_server, amount=1)

        username = client_1.settings.credentials.username

        await client_1.execute(AddHatedInterestCommand('hinterest0'), response=True)
        await asyncio.sleep(0.5)

        assert mock_server.find_user_by_name(username).hated_interests == {'hinterest0'}

        await client_1.execute(RemoveHatedInterestCommand('hinterest0'), response=True)
        await asyncio.sleep(0.5)

        assert len(mock_server.find_user_by_name(username).hated_interests) == 0

    @pytest.mark.asyncio
    async def test_get_user_interests(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(UserInterestsEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=2)

        username2 = client_2.settings.credentials.username

        user_2 = mock_server.find_user_by_name(username2)
        user_2.interests = {'interest0'}
        user_2.hated_interests = {'hinterest0'}

        actual_interests, actual_hinterests = await client_1(
            GetUserInterestsCommand(username2), response=True)

        assert actual_interests == ['interest0']
        assert actual_hinterests == ['hinterest0']

        event: UserInterestsEvent = await wait_for_listener_awaited(listener)

        assert event.user.name == username2
        assert event.interests == ['interest0']
        assert event.hated_interests == ['hinterest0']

    @pytest.mark.asyncio
    async def test_get_item_similar_users(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(ItemSimilarUsersEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=2)

        username2 = client_2.settings.credentials.username

        user_2 = mock_server.find_user_by_name(username2)
        user_2.interests = {'interest0'}

        actual_users = await client_1(
            GetItemSimilarUsersCommand('interest0'), response=True)

        assert len(actual_users) == 1
        assert actual_users[0].name == username2

        event: ItemSimilarUsersEvent = await wait_for_listener_awaited(listener)

        assert event.item == 'interest0'
        assert len(event.users) == 1
        assert event.users[0].name == username2

    @pytest.mark.asyncio
    async def test_get_similar_users(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(SimilarUsersEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=2)

        username1 = client_1.settings.credentials.username
        username2 = client_2.settings.credentials.username

        user_1 = mock_server.find_user_by_name(username1)
        user_1.interests = {'interest0'}
        user_2 = mock_server.find_user_by_name(username2)
        user_2.interests = {'interest0'}

        actual_users = await client_1(GetSimilarUsersCommand(), response=True)

        assert len(actual_users) == 1
        assert actual_users[0][0].name == username2
        assert actual_users[0][1] == 1

        event: SimilarUsersEvent = await wait_for_listener_awaited(listener)

        assert len(event.users) == 1
        assert event.users[0][0].name == username2
        assert event.users[0][1] == 1

    @pytest.mark.asyncio
    async def test_get_item_recommendations(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(ItemRecommendationsEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=2)

        username2 = client_2.settings.credentials.username

        user_2 = mock_server.find_user_by_name(username2)
        user_2.interests = {'interest0', 'interest1'}
        user_2.hated_interests = {'hinterest0'}

        expected_recommendations = [
            Recommendation('interest1', 1),
            Recommendation('hinterest0', -1)
        ]

        actual_recommendations = await client_1(
            GetItemRecommendationsCommand('interest0'), response=True)

        assert actual_recommendations == expected_recommendations

        event: ItemRecommendationsEvent = await wait_for_listener_awaited(listener)

        assert event.item == 'interest0'
        assert event.recommendations == expected_recommendations

    @pytest.mark.asyncio
    async def test_get_global_recommendations(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(GlobalRecommendationsEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=2)

        username2 = client_2.settings.credentials.username

        user_2 = mock_server.find_user_by_name(username2)
        user_2.interests = {'interest0', 'interest1'}
        user_2.hated_interests = {'hinterest0'}

        expected_recommendations = [
            Recommendation('interest0', 1),
            Recommendation('interest1', 1),
            Recommendation('hinterest0', -1)
        ]
        expected_unrecommendations = list(reversed(expected_recommendations))

        actual_recommendations, actual_unrecommendations = await client_1(
            GetGlobalRecommendationsCommand(), response=True)

        assert actual_recommendations == expected_recommendations
        assert actual_unrecommendations == expected_unrecommendations

        event: GlobalRecommendationsEvent = await wait_for_listener_awaited(listener)

        assert event.recommendations == expected_recommendations
        assert event.unrecommendations == expected_unrecommendations

    @pytest.mark.asyncio
    async def test_get_recommendations(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(RecommendationsEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=2)

        username1 = client_1.settings.credentials.username
        username2 = client_2.settings.credentials.username

        user_1 = mock_server.find_user_by_name(username1)
        user_1.interests = {'interest0'}

        user_2 = mock_server.find_user_by_name(username2)
        user_2.interests = {'interest0', 'interest1'}
        user_2.hated_interests = {'hinterest0'}

        expected_recommendations = [
            Recommendation('interest1', 1),
            Recommendation('hinterest0', -1)
        ]
        expected_unrecommendations = list(reversed(expected_recommendations))

        actual_recommendations, actual_unrecommendations = await client_1(
            GetRecommendationsCommand(), response=True)

        assert actual_recommendations == expected_recommendations
        assert actual_unrecommendations == expected_unrecommendations

        event: RecommendationsEvent = await wait_for_listener_awaited(listener)

        assert event.recommendations == expected_recommendations
        assert event.unrecommendations == expected_unrecommendations

    @pytest.mark.asyncio
    async def test_set_get_user_status(self, mock_server: MockServer, client_1: SoulSeekClient):
        await wait_until_clients_initialized(mock_server, amount=1)

        username = client_1.settings.credentials.username
        expected_status = UserStatus.AWAY

        await client_1.execute(SetStatusCommand(expected_status))

        actual_status, actual_privs = await client_1.execute(
            GetUserStatusCommand(username), response=True)

        assert actual_status == expected_status
        assert actual_privs is False

    @pytest.mark.asyncio
    async def test_join_public_room(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(RoomJoinedEvent, listener)
        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'pubroom'

        username1 = client_1.settings.credentials.username
        username2 = client_2.settings.credentials.username

        # First user joins / creates room

        room: Room = await client_1.execute(
            JoinRoomCommand(room_name, private=False), response=True)

        assert room.name == room_name
        assert room.private is False
        assert len(room.users) == 1
        assert room.users[0].name == username1

        # Second user joins room

        room2: Room = await client_2.execute(
            JoinRoomCommand(room_name, private=False), response=True)

        assert room2.name == room_name
        assert room2.private is False
        assert len(room2.users) == 2
        room2_usernames = sorted(user.name for user in room2.users)
        assert room2_usernames == sorted([username1, username2])

        ## Assert event on the first client

        assert len(room.users) == 2
        room_usernames = sorted(user.name for user in room.users)
        assert username2 in room_usernames

        event: RoomJoinedEvent = await wait_for_listener_awaited(listener)

        assert event.user.name == username2
        assert event.room.name == room_name

    @pytest.mark.asyncio
    async def test_join_private_room(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        user_added_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipGrantedEvent, user_added_listener1)

        user_added_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipGrantedEvent, user_added_listener2)

        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'privroom'

        username1 = client_1.settings.credentials.username
        username2 = client_2.settings.credentials.username

        # First user joins / creates room

        room: Room = await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)

        # Check if room is created
        assert room.name == room_name
        assert room.private is True
        # Check if user joined the room
        assert len(room.users) == 1
        assert room.users[0].name == username1
        # Check room owner and members (should not be in the list of members but
        # should be the owner)
        assert room.owner == username1
        assert len(room.members) == 0

        # Add second user as a member
        add_room, add_user = await client_1.execute(
            GrantRoomMembershipCommand(room_name, username2), response=True)

        assert add_room.name == room_name
        assert add_user.name == username2
        assert len(add_room.members) == 1
        assert username2 in add_room.members

        event1: RoomMembershipGrantedEvent = await wait_for_listener_awaited(user_added_listener1)
        events2: Tuple[RoomMembershipGrantedEvent] = await wait_for_listener_awaited_events(
            user_added_listener2, amount=2
        )

        assert event1.room.name == room_name
        assert event1.member.name == username2

        assert events2[1].room.name == room_name
        assert events2[1].member is None

        # Second user joins room
        join_listener = AsyncMock()
        client_1.events.register(RoomJoinedEvent, join_listener)

        room2: Room = await client_2.execute(JoinRoomCommand(room_name, private=True), response=True)

        assert room2.name == room_name
        assert room2.private is True
        assert room2.owner == username1
        assert len(room2.members) == 1
        assert username2 in room2.members
        room2_joined_usernames = sorted(user.name for user in room2.users)
        assert sorted([username1, username2]) == room2_joined_usernames

        ## Assert event on the first client

        # Take index 1, index 0 should be the initial joining
        event: RoomJoinedEvent = await wait_for_listener_awaited(join_listener)

        assert event.user.name == username2
        assert event.room.name == room_name

    @pytest.mark.asyncio
    async def test_set_room_ticker(self, mock_server: MockServer, client_1: SoulSeekClient):
        await wait_until_clients_initialized(mock_server, amount=1)

        ticker_added_listener = AsyncMock()
        client_1.events.register(RoomTickerAddedEvent, ticker_added_listener)
        ticker_removed_listener = AsyncMock()
        client_1.events.register(RoomTickerRemovedEvent, ticker_removed_listener)

        room_name = 'pubroom'
        username1 = client_1.settings.credentials.username
        ticker = 'hello'

        room: Room = await client_1.execute(
            JoinRoomCommand(room_name, private=False), response=True)

        # 1. Send initial ticker
        await client_1.execute(
            SetRoomTickerCommand(room_name, ticker), response=True)

        # Validate added event
        ticker_add_event: RoomTickerAddedEvent = await wait_for_listener_awaited(ticker_added_listener)
        assert ticker_add_event.room.name == room_name
        assert ticker_add_event.user.name == username1
        assert ticker_add_event.ticker == ticker
        # Validate room
        assert room.tickers[username1] == ticker

        # 2. Update ticker
        new_ticker = 'world'

        await client_1.execute(
            SetRoomTickerCommand(room_name, new_ticker), response=True)

        ticker_removed_event: RoomTickerRemovedEvent = await wait_for_listener_awaited(ticker_removed_listener)
        ticker_add_event: RoomTickerAddedEvent = await wait_for_listener_awaited(ticker_added_listener)

        # Validate removed event
        assert ticker_removed_event.room.name == room_name
        assert ticker_removed_event.user.name == username1
        # Validate added event
        assert ticker_add_event.room.name == room_name
        assert ticker_add_event.user.name == username1
        assert ticker_add_event.ticker == new_ticker
        # Validate room
        assert room.tickers[username1] == new_ticker
