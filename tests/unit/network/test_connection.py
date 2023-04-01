from pyslsk.exceptions import (
    ConnectionFailedError,
    ConnectionReadError,
    ConnectionWriteError,
)
from pyslsk.protocol.messages import (
    ChatLeaveRoom,
    DistributedBranchLevel,
    MessageDataclass,
    PeerInit,
    PeerPlaceInQueueRequest,
)
from pyslsk.protocol.obfuscation import encode
from pyslsk.network.connection import (
    Connection,
    CloseReason,
    ConnectionState,
    DataConnection,
    PeerConnection,
    PeerConnectionState,
    PeerConnectionType,
)

from asyncio import IncompleteReadError, TimeoutError
import pytest
from unittest.mock import AsyncMock, call, MagicMock, Mock, patch


@pytest.fixture
def network():
    return AsyncMock()


class TestConnection:

    @pytest.mark.asyncio
    async def test_setState_setStateAndCallback(self, network):
        connection = Connection('1.2.3.4', 1234, network)
        connection.state = ConnectionState.CONNECTED

        await connection.set_state(ConnectionState.CLOSED, close_reason=CloseReason.EOF)

        assert ConnectionState.CLOSED == connection.state
        network.on_state_changed.assert_awaited_once_with(
            ConnectionState.CLOSED,
            connection,
            close_reason=CloseReason.EOF
        )


class TestDataConnection:

    # connect
    @pytest.mark.asyncio
    async def test_connectSuccessful_shouldSetState(self, network):
        connection = DataConnection('1.2.3.4', 1234, network)
        connection._start_reader_task = MagicMock()
        reader, writer = Mock(), Mock()
        with patch('asyncio.open_connection', return_value=(reader, writer)):
            await connection.connect()

        assert ConnectionState.CONNECTED == connection.state
        assert connection._reader is not None
        assert connection._writer is not None
        connection._start_reader_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_connectUnsuccessful_shouldDisconnectAndRaise(self, network):
        connection = DataConnection('1.2.3.4', 1234, network)
        connection.disconnect = AsyncMock()

        with patch('asyncio.open_connection', side_effect=OSError):
            with pytest.raises(ConnectionFailedError):
                await connection.connect()

        assert connection._reader is None
        assert connection._writer is None
        connection.disconnect.assert_awaited_once_with(CloseReason.CONNECT_FAILED)

    @pytest.mark.asyncio
    async def test_connectTimeout_shouldDisconnectAndRaise(self, network):
        connection = DataConnection('1.2.3.4', 1234, network)
        connection.disconnect = AsyncMock()

        with patch('asyncio.wait_for', side_effect=TimeoutError):
            with pytest.raises(ConnectionFailedError):
                await connection.connect()

        assert connection._reader is None
        assert connection._writer is None
        connection.disconnect.assert_awaited_once_with(CloseReason.CONNECT_FAILED)

    # disconnect
    @pytest.mark.asyncio
    @pytest.mark.parametrize('state', [ConnectionState.CLOSED, ConnectionState.CLOSING])
    async def test_disconnect_alreadyDisconnected_shouldDoNothing(self, network, state: ConnectionState):
        connection = connection = self._create_connection(network, state)
        connection.set_state = AsyncMock()

        await connection.disconnect(CloseReason.EOF)

        connection.set_state.assert_not_awaited()
        assert connection.state == state

    @pytest.mark.asyncio
    async def test_disconnect_shouldSetState(self, network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()
        connection._stop_reader_task = Mock()
        connection._writer = Mock()
        connection._writer.close = Mock()
        connection._writer.wait_closed = AsyncMock()
        connection._writer.is_closing = Mock(return_value=False)

        await connection.disconnect(CloseReason.EOF)

        self._validate_disconnected(connection)

    @pytest.mark.asyncio
    async def test_disconnectWithException_shouldSetState(self, network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()
        connection._stop_reader_task = Mock()
        connection._writer = Mock()
        connection._writer.close = Mock()
        connection._writer.wait_closed = AsyncMock(side_effect=OSError)
        connection._writer.is_closing = Mock(return_value=False)

        await connection.disconnect(CloseReason.EOF)

        self._validate_disconnected(connection)

    # receive_message
    @pytest.mark.asyncio
    async def test_receiveMessage_unobfuscatedConnection(self, network):
        expected_message = ChatLeaveRoom.Response('room').serialize()
        header, content = expected_message[:4], expected_message[4:]

        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(side_effect=(header, content))

        actual_message = await connection.receive_message()
        assert expected_message == actual_message

    @pytest.mark.asyncio
    async def test_receiveMessage_obfuscatedConnection(self, network):
        expected_message = encode(
            ChatLeaveRoom.Response('room').serialize(), key=bytes.fromhex('12345678'))
        header, content = expected_message[:8], expected_message[8:]

        connection = self._create_connection(network)
        connection.obfuscated = True
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(side_effect=(header, content))

        actual_message = await connection.receive_message()
        assert expected_message == actual_message

    @pytest.mark.asyncio
    async def test_receiveMessage_exception_shouldDisconnectAndRaise(self, network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(side_effect=OSError)
        connection.disconnect = AsyncMock()

        with pytest.raises(ConnectionReadError):
            await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.READ_ERROR)

    @pytest.mark.asyncio
    async def test_receiveMessage_timeoutException_shouldDisconnectAndRaise(self, network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection.disconnect = AsyncMock()

        with patch('asyncio.wait_for', side_effect=TimeoutError):
            with pytest.raises(ConnectionReadError):
                await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.TIMEOUT)

    @pytest.mark.asyncio
    async def test_receiveMessage_incompleteReadException_eof_shouldDisconnect(self, network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(
            side_effect=IncompleteReadError('', None))
        connection.disconnect = AsyncMock()

        await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.EOF)

    @pytest.mark.asyncio
    async def test_receiveMessage_incompleteReadException_notEof_shouldDisconnectAndRaise(self, network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(
            side_effect=IncompleteReadError(bytes.fromhex('11'), None))
        connection.disconnect = AsyncMock()

        with pytest.raises(ConnectionReadError):
            await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.READ_ERROR)

    # send_message
    @pytest.mark.asyncio
    async def test_sendMessage_unobfuscatedConnection(self, network):
        expected_message = ChatLeaveRoom.Response('room').serialize()

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock()

        await connection.send_message(expected_message)
        connection._writer.write.assert_called_once_with(expected_message)
        connection._writer.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sendMessage_obfuscatedConnection(self, network):
        expected_message = ChatLeaveRoom.Response('room').serialize()
        enc_message = encode(expected_message, key=bytes.fromhex('11223344'))

        connection = self._create_connection(network)
        connection.obfuscated = True
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock()

        with patch('pyslsk.protocol.obfuscation.encode', return_value=enc_message) as encode_func:
            await connection.send_message(expected_message)

        encode_func.assert_called_once_with(expected_message)
        connection._writer.write.assert_called_once_with(enc_message)
        connection._writer.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sendMessage_exception_shouldDisconnectAndRaise(self, network):
        expected_message = ChatLeaveRoom.Response('room').serialize()

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock(side_effect=OSError)
        connection.disconnect = AsyncMock()

        with pytest.raises(ConnectionWriteError):
            await connection.send_message(expected_message)

        connection._writer.drain.assert_awaited_once()
        connection.disconnect.assert_awaited_once_with(CloseReason.WRITE_ERROR)

    @pytest.mark.asyncio
    async def test_sendMessage_timeoutException_shouldDisconnectAndRaise(self, network):
        expected_message = ChatLeaveRoom.Response('room').serialize()

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock()
        connection.disconnect = AsyncMock()

        with patch('asyncio.wait_for', side_effect=TimeoutError):
            with pytest.raises(ConnectionWriteError):
                await connection.send_message(expected_message)

        connection.disconnect.assert_awaited_once_with(CloseReason.TIMEOUT)

    # helpers
    def _create_connection(self, network, state: ConnectionState = ConnectionState.CONNECTED) -> DataConnection:
        connection = DataConnection('1.2.3.4', 1234, network)
        connection.state = state
        return connection

    def _validate_disconnected(self, connection: DataConnection):
        connection._writer.close.assert_called_once()
        connection._writer.wait_closed.assert_awaited_once()
        assert 2 == connection.set_state.call_count
        connection.set_state.assert_has_awaits(
            [
                call(ConnectionState.CLOSING, close_reason=CloseReason.EOF),
                call(ConnectionState.CLOSED, close_reason=CloseReason.EOF)
            ]
        )
        connection._stop_reader_task.assert_called_once()


class TestPeerConnection:

    def test_createPeerConnection_verifyInitialState(self, network):
        ip, port = '1.2.3.4', 1234
        conn = PeerConnection(hostname=ip, port=port, network=network)
        assert conn.state == ConnectionState.UNINITIALIZED
        assert conn.connection_state == PeerConnectionState.AWAITING_INIT

    @pytest.mark.parametrize(
        "peer_state,peer_type,message",
        [
            (PeerConnectionState.AWAITING_INIT, PeerConnectionType.PEER, PeerInit.Request('user', 'P', 1)),
            (PeerConnectionState.ESTABLISHED, PeerConnectionType.PEER, PeerPlaceInQueueRequest.Request('myfile.mp3')),
            (PeerConnectionState.ESTABLISHED, PeerConnectionType.DISTRIBUTED, DistributedBranchLevel.Request(1)),
        ]
    )
    def test_parseMessage_shouldReturnMessage(self, peer_state: PeerConnectionState, peer_type: PeerConnectionType, message: MessageDataclass):
        ip, port = '1.2.3.4', 1234
        conn = PeerConnection(
            hostname=ip, port=port, network=network,
            connection_type=peer_type)
        conn.connection_state = peer_state

        actual_message = conn.parse_message(message.serialize())
        assert message == actual_message
