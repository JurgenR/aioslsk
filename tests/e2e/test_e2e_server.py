from aioslsk.client import SoulSeekClient
from aioslsk.commands import (
    AddInterestCommand,
    AddHatedInterestCommand,
    DropRoomMembershipCommand,
    DropRoomOwnershipCommand,
    GrantRoomMembershipCommand,
    GrantRoomOperatorCommand,
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
    RevokeRoomMembershipCommand,
    RevokeRoomOperatorCommand,
    SetStatusCommand,
    SetRoomTickerCommand,
)
from aioslsk.events import (
    GlobalRecommendationsEvent,
    ItemRecommendationsEvent,
    ItemSimilarUsersEvent,
    RecommendationsEvent,
    RoomJoinedEvent,
    RoomOperatorGrantedEvent,
    RoomOperatorRevokedEvent,
    RoomMembershipGrantedEvent,
    RoomMembershipRevokedEvent,
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
    wait_for_room_owner,
)
import asyncio
import pytest
from pytest_unordered import unordered
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

        assert actual_recommendations == unordered(expected_recommendations)

        event: ItemRecommendationsEvent = await wait_for_listener_awaited(listener)

        assert event.item == 'interest0'
        assert event.recommendations == unordered(expected_recommendations)

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

        actual_recommendations, actual_unrecommendations = await client_1(
            GetGlobalRecommendationsCommand(), response=True)

        assert actual_recommendations == unordered(expected_recommendations)
        assert actual_unrecommendations == unordered(expected_recommendations)

        event: GlobalRecommendationsEvent = await wait_for_listener_awaited(listener)

        assert event.recommendations == unordered(expected_recommendations)
        assert event.unrecommendations == unordered(expected_recommendations)

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

        actual_recommendations, actual_unrecommendations = await client_1(
            GetRecommendationsCommand(), response=True)

        assert actual_recommendations == unordered(expected_recommendations)
        assert actual_unrecommendations == unordered(expected_recommendations)

        event: RecommendationsEvent = await wait_for_listener_awaited(listener)

        assert event.recommendations == unordered(expected_recommendations)
        assert event.unrecommendations == unordered(expected_recommendations)

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
    async def test_join_private_room(self, mock_server: MockServer, client_1: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(RoomJoinedEvent, listener)

        await wait_until_clients_initialized(mock_server, amount=1)

        room_name = 'privroom'

        username1 = client_1.settings.credentials.username

        # Create private room

        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)

        await wait_for_listener_awaited_events(listener, 2)

        assert client_1.rooms.rooms[room_name].owner == username1
        assert client_1.rooms.rooms[room_name].private is True
        assert username1 in [user.name for user in client_1.rooms.rooms[room_name].users]

    @pytest.mark.asyncio
    async def test_join_public_room(self, mock_server: MockServer, client_1: SoulSeekClient):
        listener = AsyncMock()
        client_1.events.register(RoomJoinedEvent, listener)
        await wait_until_clients_initialized(mock_server, amount=1)

        room_name = 'pubroom'

        username1 = client_1.settings.credentials.username

        # First user joins / creates room

        room: Room = await client_1.execute(
            JoinRoomCommand(room_name, private=False), response=True)

        await wait_for_listener_awaited_events(listener, 2)

        assert room.name == room_name
        assert room.private is False
        assert len(room.users) == 1
        assert room.users[0].name == username1

    @pytest.mark.asyncio
    async def test_private_room_grant_membership(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        member_granted_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipGrantedEvent, member_granted_listener1)

        member_granted_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipGrantedEvent, member_granted_listener2)

        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'privroom'

        username1 = client_1.settings.credentials.username
        username2 = client_2.settings.credentials.username

        # First user joins / creates room

        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)

        # Grant membership to second user
        await client_1.execute(
            GrantRoomMembershipCommand(room_name, username2), response=True)

        event1: RoomMembershipGrantedEvent = await wait_for_listener_awaited(member_granted_listener1)
        events2: tuple[RoomMembershipGrantedEvent] = await wait_for_listener_awaited_events(
            member_granted_listener2, amount=2
        )

        assert event1.room.name == room_name
        assert event1.member.name == username2

        assert events2[1].room.name == room_name
        assert events2[1].member is None

        # Second user joins room
        join_listener = AsyncMock()
        client_1.events.register(RoomJoinedEvent, join_listener)

        await client_2.execute(JoinRoomCommand(room_name, private=True), response=True)

        await wait_for_listener_awaited(join_listener)

        # Check rooms for user 1 and 2
        assert username2 in client_1.rooms.rooms[room_name].members
        assert username2 in [user.name for user in client_1.rooms.rooms[room_name].users]

        assert username2 in client_2.rooms.rooms[room_name].members
        assert client_2.rooms.rooms[room_name].owner == username1
        assert client_2.rooms.rooms[room_name].private is True
        assert username1 in [user.name for user in client_2.rooms.rooms[room_name].users]
        assert username2 in [user.name for user in client_2.rooms.rooms[room_name].users]

    @pytest.mark.asyncio
    async def test_private_room_revoke_membership(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        member_granted_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipGrantedEvent, member_granted_listener1)

        member_granted_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipGrantedEvent, member_granted_listener2)

        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'privroom'

        username2 = client_2.settings.credentials.username

        # First user joins / creates room and grants membership to second user
        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)
        await client_1.execute(GrantRoomMembershipCommand(room_name, username2), response=True)

        await wait_for_listener_awaited(member_granted_listener1)
        await wait_for_listener_awaited_events(member_granted_listener2, amount=2)
        await client_2.execute(JoinRoomCommand(room_name, private=True), response=True)

        # Register listeners
        member_revoked_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipRevokedEvent, member_revoked_listener1)

        member_revoked_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipRevokedEvent, member_revoked_listener2)

        # Revoke membership
        await client_1(RevokeRoomMembershipCommand(room_name, username2), response=True)

        revoked_event1 = await wait_for_listener_awaited(member_revoked_listener1)
        revoked_event2 = await wait_for_listener_awaited(member_revoked_listener2)

        revoked_event1.room.name == room_name
        revoked_event2.room.name == room_name

        revoked_event1.member.name == username2
        revoked_event2.member is None

        assert username2 not in client_1.rooms.rooms[room_name].members
        assert username2 not in client_2.rooms.rooms[room_name].members

    @pytest.mark.asyncio
    async def test_private_room_grant_operator(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        member_granted_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipGrantedEvent, member_granted_listener1)

        member_granted_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipGrantedEvent, member_granted_listener2)

        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'privroom'

        username1 = client_1.settings.credentials.username
        username2 = client_2.settings.credentials.username

        # First user joins / creates room and grants membership to second user
        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)
        await client_1.execute(GrantRoomMembershipCommand(room_name, username2), response=True)

        await wait_for_listener_awaited(member_granted_listener1)
        await wait_for_listener_awaited_events(member_granted_listener2, amount=2)
        await client_2.execute(JoinRoomCommand(room_name, private=True), response=True)

        # Register listeners
        op_granted_listener1 = AsyncMock()
        client_1.events.register(RoomOperatorGrantedEvent, op_granted_listener1)

        op_granted_listener2 = AsyncMock()
        client_2.events.register(RoomOperatorGrantedEvent, op_granted_listener2)

        # Grant operator
        await client_1(GrantRoomOperatorCommand(room_name, username2), response=True)

        granted_event1 = await wait_for_listener_awaited(op_granted_listener1)
        granted_event2 = await wait_for_listener_awaited(op_granted_listener2)

        granted_event1.room.name == room_name
        granted_event2.room.name == room_name

        granted_event1.member.name == username2
        granted_event2.member.name == username2

        assert username2 in client_1.rooms.rooms[room_name].members
        assert username2 in client_2.rooms.rooms[room_name].members
        assert username2 in client_1.rooms.rooms[room_name].operators
        assert username2 in client_2.rooms.rooms[room_name].operators

    @pytest.mark.asyncio
    async def test_private_room_revoke_operator(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        member_granted_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipGrantedEvent, member_granted_listener1)

        member_granted_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipGrantedEvent, member_granted_listener2)

        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'privroom'

        username2 = client_2.settings.credentials.username

        # First user joins / creates room and grants membership to second user
        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)
        await client_1.execute(GrantRoomMembershipCommand(room_name, username2), response=True)

        await wait_for_listener_awaited(member_granted_listener1)
        await wait_for_listener_awaited_events(member_granted_listener2, amount=2)
        await client_2.execute(JoinRoomCommand(room_name, private=True), response=True)

        # Register granting listeners and grant operator
        op_granted_listener1 = AsyncMock()
        client_1.events.register(RoomOperatorGrantedEvent, op_granted_listener1)
        op_granted_listener2 = AsyncMock()
        client_2.events.register(RoomOperatorGrantedEvent, op_granted_listener2)

        await client_1(GrantRoomOperatorCommand(room_name, username2), response=True)

        await wait_for_listener_awaited(op_granted_listener1)
        await wait_for_listener_awaited(op_granted_listener2)

        # Revoke operator
        op_revoked_listener1 = AsyncMock()
        client_1.events.register(RoomOperatorRevokedEvent, op_revoked_listener1)
        op_revoked_listener2 = AsyncMock()
        client_2.events.register(RoomOperatorRevokedEvent, op_revoked_listener2)

        await client_1(RevokeRoomOperatorCommand(room_name, username2), response=True)

        revoked_event1 = await wait_for_listener_awaited(op_revoked_listener1)
        revoked_event2 = await wait_for_listener_awaited(op_revoked_listener2)

        revoked_event1.room.name == room_name
        revoked_event2.room.name == room_name

        revoked_event1.member.name == username2
        revoked_event2.member.name == username2

        assert username2 in client_1.rooms.rooms[room_name].members
        assert username2 in client_2.rooms.rooms[room_name].members
        assert username2 not in client_1.rooms.rooms[room_name].operators
        assert username2 not in client_2.rooms.rooms[room_name].operators

    @pytest.mark.asyncio
    async def test_private_room_drop_membership(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        member_granted_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipGrantedEvent, member_granted_listener1)

        member_granted_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipGrantedEvent, member_granted_listener2)

        await wait_until_clients_initialized(mock_server, amount=2)

        room_name = 'privroom'

        username2 = client_2.settings.credentials.username

        # First user joins / creates room and grants membership to second user
        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)
        await client_1.execute(GrantRoomMembershipCommand(room_name, username2), response=True)

        await wait_for_listener_awaited(member_granted_listener1)
        await wait_for_listener_awaited_events(member_granted_listener2, amount=2)
        await client_2.execute(JoinRoomCommand(room_name, private=True), response=True)

        # Revoke operator
        member_revoked_listener1 = AsyncMock()
        client_1.events.register(RoomMembershipRevokedEvent, member_revoked_listener1)

        member_revoked_listener2 = AsyncMock()
        client_2.events.register(RoomMembershipRevokedEvent, member_revoked_listener2)

        # Drop membership
        await client_2(DropRoomMembershipCommand(room_name), response=True)

        revoked_event1 = await wait_for_listener_awaited(member_revoked_listener1)
        revoked_event2 = await wait_for_listener_awaited(member_revoked_listener2)

        revoked_event1.room.name == room_name
        revoked_event2.room.name == room_name

        revoked_event1.member.name == username2
        revoked_event2.member is None

        assert username2 not in client_1.rooms.rooms[room_name].members
        # assert username2 not in client_2.rooms.rooms[room_name].members
        assert room_name not in client_2.rooms.rooms

    @pytest.mark.asyncio
    async def test_private_room_drop_ownership(self, mock_server: MockServer, client_1: SoulSeekClient):
        await wait_until_clients_initialized(mock_server, amount=1)

        room_name = 'privroom'

        # First user joins
        await client_1.execute(JoinRoomCommand(room_name, private=True), response=True)

        await client_1.execute(DropRoomOwnershipCommand(room_name), response=True)

        await wait_for_room_owner(mock_server, room_name, None)

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
