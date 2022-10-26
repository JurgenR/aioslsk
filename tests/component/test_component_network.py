import copy
from unittest.mock import Mock, patch

from pyslsk.connection import (
    ConnectionState,
    CloseReason,
    PeerConnection,
    PeerConnectionType,
    PeerConnectionState,
    ServerConnection
)
from pyslsk.events import InternalEventBus
from pyslsk.protocol.messages import (
    CannotConnect,
    ConnectToPeer,
    GetPeerAddress,
    PeerInit,
    PeerPierceFirewall
)
from pyslsk.network import Network, LimitedRateLimiter, UnlimitedRateLimiter
from pyslsk.scheduler import Scheduler
from pyslsk.state import State
from pyslsk.settings import Settings


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0'
    },
    'sharing': {
        'limits': {
            'upload_speed_kbps': 0,
            'download_speed_kbps': 0
        }
    },
    'network': {
        'server_hostname': 'server.slsk.org',
        'server_port': 2234,
        'listening_port': 10000,
        'use_upnp': False,
        'peer': {
            'obfuscate': False
        }
    },
    'debug': {
        'user_ip_overrides': {}
    }
}


class _BaseTestComponentNetwork:

    def _create_network(self, settings=None) -> Network:
        settings = settings or DEFAULT_SETTINGS
        state = State()
        state.scheduler = Scheduler()
        network = Network(state, Settings(settings), InternalEventBus())

        # Mock UPNP
        network._upnp = Mock()

        # Mock server object
        network.server = ServerConnection('server.slsk.org', 2234, network)
        network.server.fileobj = Mock()
        network.server.fileobj.fileno.return_value = 0
        network.server.set_state(ConnectionState.CONNECTING)
        network.server.set_state(ConnectionState.CONNECTED)

        return network

    def _validate_server_message(self, network, message_type):
        assert network.server._messages[0].message[4] == message_type.MESSAGE_ID

    def _validate_successful_connection(
            self, network, connection, init_message_type=PeerInit):
        """Mocks successful connection to a peer and performs validation on the
        network and the peer connection
        """
        # Mock succesfully connecting
        connection.fileobj = Mock()
        connection.fileobj.fileno.return_value = 1
        connection.set_state(ConnectionState.CONNECTING)

        # Mock successful connection
        connection.set_state(ConnectionState.CONNECTED)

        # Assert correct message is sent
        assert len(connection._messages) == 1
        assert connection._messages[0].message[4] == init_message_type.Request.MESSAGE_ID

        # Mock succesful sending of message
        connection.notify_message_sent(connection._messages[0])

        # Assert request was completed
        assert len(network._connection_requests) == 0
        assert connection.connection_state == PeerConnectionState.ESTABLISHED
        assert len(network.peer_connections) == 1


class TestComponentNetwork(_BaseTestComponentNetwork):
    """Validation of peer connection flows"""

    # Connect to peer (ip/port known), connection succeeds immediately
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_withIpPort_success(self, peer_connect):
        network = self._create_network()
        network.init_peer_connection(
            username='user1',
            typ=PeerConnectionType.PEER,
            ip='1.2.3.4',
            port=1234
        )

        # Assert connection object was made and connect was attempted
        peer_connect.assert_called_once()
        assert len(network._connection_requests) == 1
        req = list(network._connection_requests.values())[0]
        assert req.username == 'user1'
        assert req.typ == PeerConnectionType.PEER
        assert req.ip == '1.2.3.4'
        assert req.port == 1234
        assert req.is_requested_by_us is True

        assert req.connection.hostname == '1.2.3.4'
        assert req.connection.port == 1234
        assert req.connection.connection_type == PeerConnectionType.PEER
        assert req.connection.obfuscated is False

        self._validate_successful_connection(network, req.connection)

    # Connect to peer (only username), connection successful
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_withUsername_success(self, peer_connect):
        network = self._create_network()
        network.init_peer_connection(
            username='user1',
            typ=PeerConnectionType.PEER
        )

        # Assert request object was made
        assert len(network._connection_requests) == 1
        req = list(network._connection_requests.values())[0]
        assert req.username == 'user1'
        assert req.typ == PeerConnectionType.PEER
        assert req.ip is None
        assert req.port is None
        assert req.is_requested_by_us is True
        assert req.connection is None

        # Assert GetPeerAddress was requested
        assert network.server._messages[-1].message[4] == GetPeerAddress.Request.MESSAGE_ID

        # Mock GetPeerAddress response
        get_peer_address = GetPeerAddress.Response(
            username='user1',
            ip='1.2.3.4',
            port=1234,
            obfuscated_port_amount=1,
            obfuscated_port=1235
        )
        network._on_get_peer_address(get_peer_address, network.server)

        # Assert connection object was made and connect was attempted
        peer_connect.assert_called_once()
        assert len(network._connection_requests) == 1
        req = list(network._connection_requests.values())[0]
        assert req.ip == '1.2.3.4'
        assert req.port == 1234

        assert req.connection.hostname == '1.2.3.4'
        assert req.connection.port == 1234
        assert req.connection.connection_type == PeerConnectionType.PEER
        assert req.connection.obfuscated is False

        self._validate_successful_connection(network, req.connection)

    # Connect to peer, connection does not succeed. ConnectToPeer sent -> successful
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_ConnectToPeerSuccessful(self, peer_connect):
        network = self._create_network()
        network.init_peer_connection(
            username='user1',
            typ=PeerConnectionType.PEER,
            ip='1.2.3.4',
            port=1234
        )

        # Assert connection object was made and connect was attempted
        peer_connect.assert_called_once()
        assert len(network._connection_requests) == 1
        req = list(network._connection_requests.values())[0]
        assert req.connection is not None

        connection = req.connection

        # Mock succesfully connecting
        connection.fileobj = Mock()
        connection.fileobj.fileno.return_value = 1
        connection.set_state(ConnectionState.CONNECTING)

        # Mock connection failure
        connection.set_state(
            ConnectionState.CLOSED, close_reason=CloseReason.CONNECT_FAILED)

        # Assert ConnectToPeer is sent and task is scheduled
        self._validate_server_message(network, ConnectToPeer.Request)

        # Mock incoming connection
        inc_connection = PeerConnection(
            '1.2.3.4', 1234, network, incoming=True)
        inc_connection.fileobj = Mock()
        inc_connection.fileobj.fileno.return_value = 2

        network.on_peer_accepted(inc_connection)
        inc_connection.set_state(ConnectionState.CONNECTED)

        # Simulate piercefirewall
        pierce_firewall = PeerPierceFirewall.Request(req.ticket)
        network._on_peer_pierce_firewall(pierce_firewall, inc_connection)

        # Assert connection is properly configured
        assert inc_connection.username == 'user1'
        assert inc_connection.connection_state == PeerConnectionState.ESTABLISHED
        assert inc_connection.connection_type == PeerConnectionType.PEER

        # Assert request is finalized
        assert len(network._connection_requests) == 0
        assert len(network.peer_connections) == 1

    # Connect to peer, connection does not succeed. ConnectToPeer sent -> successful
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_ConnectToPeerFailed(self, peer_connect):
        network = self._create_network()
        network.init_peer_connection(
            username='user1',
            typ=PeerConnectionType.PEER,
            ip='1.2.3.4',
            port=1234
        )

        # Assert connection object was made and connect was attempted
        peer_connect.assert_called_once()
        assert len(network._connection_requests) == 1
        req = list(network._connection_requests.values())[0]
        assert req.connection is not None

        connection = req.connection

        # Mock succesfully connecting
        connection.fileobj = Mock()
        connection.fileobj.fileno.return_value = 1
        connection.set_state(ConnectionState.CONNECTING)

        # Mock connection failure
        connection.set_state(
            ConnectionState.CLOSED, close_reason=CloseReason.CONNECT_FAILED)

        # Assert ConnectToPeer is sent and task is scheduled
        self._validate_server_message(network, ConnectToPeer.Request)

        # Mock CannotConnect

        cannot_connect = CannotConnect.Request(
            ticket=req.ticket,
            username=req.username
        )
        network._on_cannot_connect(cannot_connect, network.server)

        # Assert request is finalized
        assert len(network._connection_requests) == 0
        assert len(network.peer_connections) == 0


class TestComponentNetworkLimiter(_BaseTestComponentNetwork):

    def test_whenChangeUploadSpeed_limitedToUnlimited_shouldChangeLimiter(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['sharing']['limits']['upload_speed_kbps'] = 10
        network = self._create_network(settings=settings)

        assert isinstance(network.upload_rate_limiter, LimitedRateLimiter)

        limit = 0
        network._settings.set('sharing.limits.upload_speed_kbps', limit)

        assert isinstance(network.upload_rate_limiter, UnlimitedRateLimiter)

    def test_whenChangeUploadSpeed_unlimitedToLimited_shouldChangeLimiter(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['sharing']['limits']['upload_speed_kbps'] = 0
        network = self._create_network(settings=settings)

        assert isinstance(network.upload_rate_limiter, UnlimitedRateLimiter)

        limit = 10
        network._settings.set('sharing.limits.upload_speed_kbps', limit)

        assert isinstance(network.upload_rate_limiter, LimitedRateLimiter)
        assert network.upload_rate_limiter.limit_bps == (limit * 1024)

    def test_whenChangeUploadSpeed_limitedToLimited_shouldKeepBucket(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['sharing']['limits']['upload_speed_kbps'] = 10
        network = self._create_network(settings=settings)

        # Verify the initially created limiter is actually limited, modify the
        # params
        bucket = 9 * 1024
        last_refill = 1.0
        assert isinstance(network.upload_rate_limiter, LimitedRateLimiter)
        network.upload_rate_limiter.bucket = bucket
        network.upload_rate_limiter.last_refill = last_refill

        limit = 5
        network._settings.set('sharing.limits.upload_speed_kbps', limit)

        assert isinstance(network.upload_rate_limiter, LimitedRateLimiter)
        assert network.upload_rate_limiter.limit_bps == (limit * 1024)
        assert network.upload_rate_limiter.bucket == (limit * 1024)
        assert network.upload_rate_limiter.last_refill == last_refill

    # Download
    def test_whenChangeDownloadSpeed_limitedToUnlimited_shouldChangeLimiter(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['sharing']['limits']['download_speed_kbps'] = 10
        network = self._create_network(settings=settings)

        assert isinstance(network.download_rate_limiter, LimitedRateLimiter)

        limit = 0
        network._settings.set('sharing.limits.download_speed_kbps', limit)

        assert isinstance(network.download_rate_limiter, UnlimitedRateLimiter)

    def test_whenChangeDownloadSpeed_unlimitedToLimited_shouldChangeLimiter(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['sharing']['limits']['download_speed_kbps'] = 0
        network = self._create_network(settings=settings)

        assert isinstance(network.download_rate_limiter, UnlimitedRateLimiter)

        limit = 10
        network._settings.set('sharing.limits.download_speed_kbps', limit)

        assert isinstance(network.download_rate_limiter, LimitedRateLimiter)
        assert network.download_rate_limiter.limit_bps == (limit * 1024)

    def test_whenChangeDownloadSpeed_limitedToLimited_shouldKeepBucket(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['sharing']['limits']['download_speed_kbps'] = 10
        network = self._create_network(settings=settings)

        # Verify the initially created limiter is actually limited, modify the
        # params
        bucket = 9 * 1024
        last_refill = 1.0
        assert isinstance(network.download_rate_limiter, LimitedRateLimiter)
        network.download_rate_limiter.bucket = bucket
        network.download_rate_limiter.last_refill = last_refill

        limit = 5
        network._settings.set('sharing.limits.download_speed_kbps', limit)

        assert isinstance(network.download_rate_limiter, LimitedRateLimiter)
        assert network.download_rate_limiter.limit_bps == (limit * 1024)
        assert network.download_rate_limiter.bucket == (limit * 1024)
        assert network.download_rate_limiter.last_refill == last_refill
