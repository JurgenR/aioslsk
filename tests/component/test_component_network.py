from asyncio import Event
import copy
from unittest.mock import Mock, patch

from aioslsk.events import InternalEventBus
from aioslsk.protocol.messages import (
    PeerInit,
)
from aioslsk.network.connection import (
    ConnectionState,
    PeerConnection,
    PeerConnectionState,
    ServerConnection
)
from aioslsk.network.network import Network
from aioslsk.network.rate_limiter import LimitedRateLimiter, UnlimitedRateLimiter
from aioslsk.state import State
from aioslsk.settings import Settings


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
        network = Network(state, Settings(settings), InternalEventBus(), Event())

        # Mock UPNP
        network._upnp = Mock()

        # Mock server object
        network.server = ServerConnection('server.slsk.org', 2234, network)

        return network

    def _validate_server_message(self, network, message_type):
        assert isinstance(network.server._messages[0].message, message_type)

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
        assert isinstance(connection._messages[0].message, init_message_type.Request)

        # Mock succesful sending of message
        network.on_message_sent(connection._messages[0], connection)

        # Assert request was completed
        assert len(network._connection_requests) == 0
        assert connection.connection_state == PeerConnectionState.ESTABLISHED
        assert len(network.peer_connections) == 1


class TestComponentNetwork(_BaseTestComponentNetwork):
    """Validation of peer connection flows"""

    # Connect to peer (ip/port known), connection succeeds immediately
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_withIpPort_success(self, peer_connect):
        pass

    # Connect to peer (only username), connection successful
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_withUsername_success(self, peer_connect):
        pass

    # Connect to peer, connection does not succeed. ConnectToPeer sent -> successful
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_ConnectToPeerSuccessful(self, peer_connect):
        pass

    # Connect to peer, connection does not succeed. ConnectToPeer sent -> successful
    @patch.object(PeerConnection, 'connect')
    def test_initPeerConnection_ConnectToPeerFailed(self, peer_connect):
        pass


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
