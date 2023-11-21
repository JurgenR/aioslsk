from aioslsk.distributed import DistributedNetwork, DistributedPeer
from aioslsk.events import (
    EventBus,
    MessageReceivedEvent,
    PeerInitializedEvent,
    ConnectionStateChangedEvent,
)
from aioslsk.network.connection import (
    ConnectionState,
    PeerConnection,
    ServerConnection,
)
from aioslsk.protocol.messages import (
    AcceptChildren,
    BranchLevel,
    BranchRoot,
    DistributedBranchLevel,
    DistributedBranchRoot,
    GetUserStats,
    ParentMinSpeed,
    ParentSpeedRatio,
    ResetDistributed,
    ToggleParentSearch,
)
from aioslsk.protocol.primitives import UserStats
from aioslsk.settings import Settings
from aioslsk.session import Session
from aioslsk.user.model import User

import pytest
from unittest.mock import AsyncMock, call


DEFAULT_USERNAME = 'user1'
DEFAULT_SETTINGS = {
    'credentials': {
        'username': DEFAULT_USERNAME,
        'password': 'Test1234'
    }
}

@pytest.fixture
def distributed_network() -> DistributedNetwork:
    event_bus = EventBus()
    network = AsyncMock()
    network.server = AsyncMock()

    manager = DistributedNetwork(
        Settings(**DEFAULT_SETTINGS),
        event_bus,
        network
    )
    manager._session = Session(
        user=User(name=DEFAULT_USERNAME),
        ip_address='1.1.1.1',
        greeting='',
        client_version=100,
        minor_version=10
    )

    return manager


def create_get_user_stats_response(speed: int) -> GetUserStats.Response:
    return GetUserStats.Response(
        username=DEFAULT_USERNAME,
        user_stats=UserStats(
            avg_speed=speed,
            uploads=10,
            shared_file_count=1000,
            shared_folder_count=100
        )
    )


class TestDistributedNetwork:

    @pytest.mark.asyncio
    async def test_receiveParentSpeedValues_shouldSendGetUserStats(self, distributed_network: DistributedNetwork):
        min_speed, speed_ratio = 10, 50
        server = AsyncMock()
        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=ParentMinSpeed.Response(min_speed),
                connection=server
            )
        )

        assert distributed_network.parent_min_speed == min_speed
        assert distributed_network.parent_speed_ratio is None
        distributed_network._network.send_server_messages.assert_not_awaited()

        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=ParentSpeedRatio.Response(speed_ratio),
                connection=server
            )
        )

        assert distributed_network.parent_min_speed == min_speed
        assert distributed_network.parent_speed_ratio == speed_ratio
        distributed_network._network.send_server_messages.assert_awaited_once_with(
            GetUserStats.Request(DEFAULT_USERNAME)
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize('accept_children,max_children', [(True, 10), (False, 15)])
    async def test_receiveGetUserStats_noServerSpeedValues_shouldUseDefaults(
            self, distributed_network: DistributedNetwork,
            accept_children: bool, max_children: int):
        distributed_network._accept_children = accept_children
        distributed_network._max_children = max_children

        server = AsyncMock()
        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=create_get_user_stats_response(1000),
                connection=server
            )
        )

        assert distributed_network._accept_children is accept_children
        assert distributed_network._max_children == max_children
        distributed_network._network.send_server_messages.assert_awaited_once_with(
            AcceptChildren.Request(accept_children)
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize('accept_children,max_children', [(True, 10), (False, 15)])
    async def test_receiveGetUserStats_noServerSpeedValues_shouldUseDefaults(
            self, distributed_network: DistributedNetwork,
            accept_children: bool, max_children: int):
        distributed_network._accept_children = accept_children
        distributed_network._max_children = max_children

        server = AsyncMock()
        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=create_get_user_stats_response(1000),
                connection=server
            )
        )

        assert distributed_network._accept_children is accept_children
        assert distributed_network._max_children == max_children
        distributed_network._network.send_server_messages.assert_awaited_once_with(
            AcceptChildren.Request(accept_children)
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'min_speed,ratio,speed,expected_accept,expected_max',
        [
            (1, 50, 1023, False, 0),
            (1, 50, 1024, True, 0),
            (1, 50, 20480, True, 4),
            (1, 30, 20480, True, 6),
        ]
    )
    async def test_receiveGetUserStats_withServerSpeedValues_shouldCalculateChildren(
            self, distributed_network: DistributedNetwork,
            min_speed: int, ratio: int,
            speed: int, expected_accept: bool, expected_max: int):
        distributed_network.parent_min_speed = min_speed
        distributed_network.parent_speed_ratio = ratio

        server = AsyncMock()
        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=create_get_user_stats_response(speed),
                connection=server
            )
        )

        assert distributed_network._accept_children is expected_accept
        assert distributed_network._max_children == expected_max
        distributed_network._network.send_server_messages.assert_awaited_once_with(
            AcceptChildren.Request(expected_accept)
        )

    @pytest.mark.asyncio
    async def test_newChild_maxChildrenReached_shouldDisconnect(self, distributed_network: DistributedNetwork):
        distributed_network.parent_min_speed = 1
        distributed_network.parent_speed_ratio = 50
        distributed_network._max_children = 1
        distributed_network._accept_children = True

        parent = DistributedPeer(
            username='user0',
            connection=AsyncMock(),
            branch_level=0,
            branch_root='user0'
        )

        child = DistributedPeer(
            username='user2',
            connection=AsyncMock(),
            branch_level=2,
            branch_root='user0'
        )
        distributed_network.parent = parent
        distributed_network.children = [child]
        distributed_network.distributed_peers = [parent, child]

        new_child_connection = AsyncMock()
        new_child_connection.username = 'user02'
        new_child_connection.connection_type = 'D'

        await distributed_network._event_bus.emit(
            PeerInitializedEvent(
                connection=new_child_connection,
                requested=False
            )
        )
        new_child_connection.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_newChild_notAcceptingChildren_shouldDisconnect(self, distributed_network: DistributedNetwork):
        distributed_network.parent_min_speed = 1
        distributed_network.parent_speed_ratio = 50
        distributed_network._max_children = 1
        distributed_network._accept_children = False

        parent = DistributedPeer(
            username='user0',
            connection=AsyncMock(),
            branch_level=0,
            branch_root='user0'
        )
        distributed_network.parent = parent
        distributed_network.distributed_peers = [parent]

        new_child_connection = AsyncMock()
        new_child_connection.username = 'user02'
        new_child_connection.connection_type = 'D'

        await distributed_network._event_bus.emit(
            PeerInitializedEvent(
                connection=new_child_connection,
                requested=False
            )
        )
        new_child_connection.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_newChild_shouldAdvertiseDistributedValues(
            self, distributed_network: DistributedNetwork):
        distributed_network.parent_min_speed = 1
        distributed_network.parent_speed_ratio = 50
        distributed_network._max_children = 1
        distributed_network._accept_children = True

        parent = DistributedPeer(
            username='user0',
            connection=AsyncMock(),
            branch_level=0,
            branch_root='user0'
        )
        distributed_network.parent = parent
        distributed_network.distributed_peers = [parent]

        new_child_connection = AsyncMock()
        new_child_connection.username = 'user2'
        new_child_connection.connection_type = 'D'

        await distributed_network._event_bus.emit(
            PeerInitializedEvent(
                connection=new_child_connection,
                requested=False
            )
        )

        new_child_connection.send_message.assert_has_awaits(
            [
                call(DistributedBranchLevel.Request(parent.branch_level + 1)),
                call(DistributedBranchRoot.Request(parent.branch_root))
            ]
        )
        assert len(distributed_network.children) == 1
        child = distributed_network.children[0]
        assert child.username == 'user2'
        assert child.connection == new_child_connection

    @pytest.mark.asyncio
    async def test_reset_isRoot_shouldUnsetParent(self, distributed_network: DistributedNetwork):
        parent = DistributedPeer(
            username=DEFAULT_USERNAME,
            connection=None,
            branch_level=0,
            branch_root=DEFAULT_USERNAME
        )

        distributed_network.parent = parent

        server = AsyncMock()
        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=ResetDistributed.Response(),
                connection=server
            )
        )
        assert distributed_network.parent is None
        distributed_network._network.send_server_messages.assert_has_awaits(
            [call(BranchLevel.Request(0), BranchRoot.Request(DEFAULT_USERNAME), ToggleParentSearch.Request(True))]
        )

    @pytest.mark.asyncio
    async def test_reset_shouldDisconnectParentAndChildren(self, distributed_network: DistributedNetwork):
        parent = DistributedPeer(
            username='user0',
            connection=AsyncMock(),
            branch_level=0,
            branch_root='user0'
        )

        child = DistributedPeer(
            username='user2',
            connection=AsyncMock(),
            branch_level=2,
            branch_root='user0'
        )
        distributed_network.parent = parent
        distributed_network.children = [child]
        distributed_network.distributed_peers = [parent, child]

        server = AsyncMock()
        await distributed_network._event_bus.emit(
            MessageReceivedEvent(
                message=ResetDistributed.Response(),
                connection=server
            )
        )

        parent.connection.disconnect.assert_awaited_once()
        child.connection.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_serverDisconnected_shouldResetSpeedValues(self, distributed_network: DistributedNetwork):
        network = AsyncMock()
        server = ServerConnection(hostname='1.2.3.4', port=1234, network=network)
        await distributed_network._event_bus.emit(
            ConnectionStateChangedEvent(
                connection=server,
                state=ConnectionState.CLOSED
            )
        )
        assert distributed_network.distributed_alive_interval is None
        assert distributed_network.parent_min_speed is None
        assert distributed_network.parent_speed_ratio is None
        assert distributed_network.parent_inactivity_timeout is None
        assert distributed_network.min_parents_in_cache is None

    @pytest.mark.asyncio
    async def test_serverDisconnected_isRoot_shouldUnsetParent(self, distributed_network: DistributedNetwork):
        network = AsyncMock()
        parent = DistributedPeer(
            username=DEFAULT_USERNAME,
            connection=None,
            branch_level=0,
            branch_root=DEFAULT_USERNAME
        )
        distributed_network.parent = parent

        server = ServerConnection(hostname='1.2.3.4', port=1234, network=network)
        await distributed_network._event_bus.emit(
            ConnectionStateChangedEvent(
                connection=server,
                state=ConnectionState.CLOSED
            )
        )
        assert distributed_network.parent is None
        distributed_network._network.send_server_messages.assert_has_awaits(
            [call(BranchLevel.Request(0), BranchRoot.Request(DEFAULT_USERNAME), ToggleParentSearch.Request(True))]
        )

    @pytest.mark.asyncio
    async def test_parentDisconnected_shouldUnsetParent(self, distributed_network: DistributedNetwork):
        parent_username = 'user0'
        connection = PeerConnection(
            hostname='1.2.3.4', port=1234, network=AsyncMock(),
            username=parent_username, connection_type='D'
        )
        parent = DistributedPeer(
            username=parent_username,
            connection=connection,
            branch_level=0,
            branch_root=parent_username
        )

        distributed_network.parent = parent
        distributed_network.distributed_peers = [parent]

        await distributed_network._event_bus.emit(
            ConnectionStateChangedEvent(
                connection=connection,
                state=ConnectionState.CLOSED
            )
        )

        assert distributed_network.parent is None
        distributed_network._network.send_server_messages.assert_has_awaits(
            [call(BranchLevel.Request(0), BranchRoot.Request(DEFAULT_USERNAME), ToggleParentSearch.Request(True))]
        )

    @pytest.mark.asyncio
    async def test_childDisconnected_shouldUnsetChild(self, distributed_network: DistributedNetwork):
        child_username = 'user2'
        connection = PeerConnection(
            hostname='1.2.3.4', port=1234, network=AsyncMock(),
            username=child_username, connection_type='D'
        )

        child = DistributedPeer(
            username=child_username,
            connection=connection,
            branch_level=2,
            branch_root='user0'
        )

        distributed_network.children = [child]
        distributed_network.distributed_peers = [child]

        await distributed_network._event_bus.emit(
            ConnectionStateChangedEvent(
                connection=connection,
                state=ConnectionState.CLOSED
            )
        )

        assert child not in  distributed_network.children
