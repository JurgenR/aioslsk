from aioslsk.exceptions import (
    ConnectionFailedError,
    ConnectionReadError,
    ConnectionWriteError,
    MessageDeserializationError,
    MessageSerializationError,
)
from aioslsk.protocol.messages import (
    ChatLeaveRoom,
    DistributedBranchLevel,
    MessageDataclass,
    PeerInit,
    PeerPlaceInQueueRequest,
)
from aioslsk.protocol.obfuscation import decode, encode
from aioslsk.network.connection import (
    Connection,
    CloseReason,
    ConnectionState,
    DataConnection,
    ListeningConnection,
    PeerConnection,
    PeerConnectionState,
    PeerConnectionType,
)
from aioslsk.network.network import Network

from asyncio import IncompleteReadError, TimeoutError
import pytest
from unittest.mock import AsyncMock, call, Mock, patch


@pytest.fixture
def network():
    nw = Mock()
    nw.set_state = AsyncMock()
    nw.connect = AsyncMock()
    nw.disconnect = AsyncMock()
    nw.on_state_changed = AsyncMock()
    nw.on_peer_accepted = AsyncMock()
    return nw


class TestConnection:

    @pytest.mark.asyncio
    async def test_setState_setStateAndCallback(self, network: Network):
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
    async def test_connectSuccessful_shouldSetState(self, network: Network):
        connection = DataConnection('1.2.3.4', 1234, network)
        connection._start_reader_task = Mock()
        reader, writer = Mock(), Mock()
        with patch('asyncio.open_connection', return_value=(reader, writer)) as open_mock:
            await connection.connect()

        assert ConnectionState.CONNECTED == connection.state
        assert connection._reader is not None
        assert connection._writer is not None
        open_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connectUnsuccessful_shouldDisconnectAndRaise(self, network: Network):
        connection = DataConnection('1.2.3.4', 1234, network)
        connection.disconnect = AsyncMock()

        with patch('asyncio.open_connection', side_effect=OSError) as open_mock:
            with pytest.raises(ConnectionFailedError):
                await connection.connect()

        assert connection._reader is None
        assert connection._writer is None
        connection.disconnect.assert_awaited_once_with(CloseReason.CONNECT_FAILED)
        open_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connectTimeout_shouldDisconnectAndRaise(self, network: Network):
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
        connection = self._create_connection(network, state)
        connection.set_state = AsyncMock()

        await connection.disconnect(CloseReason.EOF)

        connection.set_state.assert_not_awaited()
        assert connection.state == state

    @pytest.mark.asyncio
    async def test_disconnect_shouldSetState(self, network: Network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()
        connection._stop_reader_task = Mock()

        writer_mock = Mock()
        connection._writer = writer_mock
        connection._writer.close = Mock()
        connection._writer.wait_closed = AsyncMock()
        connection._writer.is_closing = Mock(return_value=False)

        await connection.disconnect(CloseReason.EOF)

        self._validate_disconnected(connection, writer_mock)

    @pytest.mark.asyncio
    async def test_disconnect_exception_shouldSetState(self, network: Network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()
        connection._stop_reader_task = Mock()

        writer_mock = Mock()
        connection._writer = writer_mock
        connection._writer.close = Mock()
        connection._writer.wait_closed = AsyncMock(side_effect=OSError)
        connection._writer.is_closing = Mock(return_value=False)

        await connection.disconnect(CloseReason.EOF)

        self._validate_disconnected(connection, writer_mock)

    # receive_message
    @pytest.mark.asyncio
    async def test_receiveMessage_unobfuscatedConnection(self, network: Network):
        expected_message = ChatLeaveRoom.Response('room').serialize()
        header, content = expected_message[:4], expected_message[4:]

        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(side_effect=(header, content))

        actual_message = await connection.receive_message()
        assert expected_message == actual_message

    @pytest.mark.asyncio
    async def test_receiveMessage_obfuscatedConnection(self, network: Network):
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
    async def test_receiveMessage_exception_shouldDisconnectAndRaise(self, network: Network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(side_effect=OSError)
        connection.disconnect = AsyncMock()

        with pytest.raises(ConnectionReadError):
            await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.READ_ERROR)

    @pytest.mark.asyncio
    async def test_receiveMessage_timeoutException_shouldDisconnectAndRaise(self, network: Network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection.disconnect = AsyncMock()

        with patch('asyncio.wait_for', side_effect=TimeoutError):
            with pytest.raises(ConnectionReadError):
                await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.TIMEOUT)

    @pytest.mark.asyncio
    async def test_receiveMessage_incompleteReadException_eof_shouldDisconnect(self, network: Network):
        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.readexactly = AsyncMock(
            side_effect=IncompleteReadError('', None))
        connection.disconnect = AsyncMock()

        await connection.receive_message()

        connection.disconnect.assert_awaited_once_with(CloseReason.EOF)

    @pytest.mark.asyncio
    async def test_receiveMessage_incompleteReadException_notEof_shouldDisconnectAndRaise(self, network: Network):
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
    async def test_sendMessage_unobfuscatedConnection(self, network: Network):
        expected_message = ChatLeaveRoom.Response('room').serialize()

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock()

        await connection.send_message(expected_message)
        connection._writer.write.assert_called_once_with(expected_message)
        connection._writer.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sendMessage_obfuscatedConnection(self, network: Network):
        expected_message = ChatLeaveRoom.Response('room').serialize()
        enc_message = encode(expected_message, key=bytes.fromhex('11223344'))

        connection = self._create_connection(network)
        connection.obfuscated = True
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock()

        with patch('aioslsk.protocol.obfuscation.encode', return_value=enc_message) as encode_func:
            await connection.send_message(expected_message)

        encode_func.assert_called_once_with(expected_message)
        connection._writer.write.assert_called_once_with(enc_message)
        connection._writer.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sendMessage_exception_shouldDisconnectAndRaise(self, network: Network):
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
    async def test_sendMessage_timeoutException_shouldDisconnectAndRaise(self, network: Network):
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

    def _validate_disconnected(self, connection: DataConnection, writer_mock: Mock):
        writer_mock.close.assert_called_once()
        writer_mock.wait_closed.assert_awaited_once()
        assert connection._writer is None
        assert connection._reader is None
        assert 2 == connection.set_state.call_count
        connection.set_state.assert_has_awaits(
            [
                call(ConnectionState.CLOSING, close_reason=CloseReason.EOF),
                call(ConnectionState.CLOSED, close_reason=CloseReason.EOF)
            ]
        )
        assert connection._reader_task == None


class TestPeerConnection:

    def test_createPeerConnection_verifyInitialState(self, network: Network):
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
    def test_deserializeMessage_shouldReturnMessage(self, network, peer_state: PeerConnectionState, peer_type: PeerConnectionType, message: MessageDataclass):
        conn = self._create_connection(network)
        conn.connection_state = peer_state
        conn.connection_type = peer_type

        actual_message = conn.deserialize_message(message.serialize())
        assert message == actual_message

    def test_decodeMessageData_nonObfuscated_shouldReturnMessage(self, network: Network):
        conn = self._create_connection(network)
        conn.connection_state = PeerConnectionState.AWAITING_INIT
        conn.obfuscated = False

        message_obj = PeerInit.Request('user', 'P', 1)
        data = message_obj.serialize()

        assert message_obj == conn.decode_message_data(data)

    def test_decodeMessageData_obfuscated_shouldReturnMessage(self, network: Network):
        conn = self._create_connection(network)
        conn.connection_state = PeerConnectionState.AWAITING_INIT
        conn.obfuscated = True

        message_obj = PeerInit.Request('user', 'P', 1)
        data = encode(message_obj.serialize())

        assert message_obj == conn.decode_message_data(data)

    def test_decodeMessageData_error_shouldRaise(self, network: Network):
        conn = self._create_connection(network)
        conn.connection_state = PeerConnectionState.AWAITING_INIT
        conn.obfuscated = False

        message_obj = PeerInit.Request('user', 'P', 1)
        data = message_obj.serialize()

        with pytest.raises(MessageDeserializationError):
            conn.decode_message_data(data[1:])

    def test_encodeMessageData_nonObfuscated_shouldReturnBytes(self, network: Network):
        conn = self._create_connection(network)
        conn.connection_state = PeerConnectionState.AWAITING_INIT
        conn.obfuscated = False

        message_obj = PeerInit.Request('user', 'P', 1)
        data = message_obj.serialize()

        assert data == conn.encode_message_data(message_obj)

    def test_encodeMessageData_obfuscated_shouldReturnBytes(self, network: Network):
        conn = self._create_connection(network)
        conn.connection_state = PeerConnectionState.AWAITING_INIT
        conn.obfuscated = True

        message_obj = PeerInit.Request('user', 'P', 1)
        data = encode(message_obj.serialize())

        assert data == decode(conn.encode_message_data(data))

    def test_encodeMessageData_error_shouldRaise(self, network: Network):
        conn = self._create_connection(network)
        conn.connection_state = PeerConnectionState.AWAITING_INIT
        conn.obfuscated = False

        message_obj = PeerInit.Request('user', 'P', 2 ** 32 + 1)

        with pytest.raises(MessageSerializationError):
            conn.encode_message_data(message_obj)

    # receive_data
    @pytest.mark.asyncio
    async def test_receiveData(self, network: Network):
        expected_data = bytes.fromhex('aabbccdd')
        to_read = 8

        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.read = AsyncMock(return_value=expected_data)

        actual_data = await connection.receive_data(to_read)
        assert expected_data == actual_data
        connection._reader.read.assert_awaited_once_with(to_read)

    @pytest.mark.asyncio
    async def test_receiveData_eof_shouldDisconnect(self, network: Network):
        to_read = 8

        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.read = AsyncMock(return_value=bytes())
        connection.disconnect = AsyncMock()

        actual_data = await connection.receive_data(to_read)
        assert actual_data is None
        connection._reader.read.assert_awaited_once_with(to_read)
        connection.disconnect.assert_awaited_once_with(CloseReason.EOF)

    @pytest.mark.asyncio
    async def test_receiveData_exception_shouldDisconnectAndRaise(self, network: Network):
        to_read = 8

        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.read = AsyncMock(side_effect=OSError)
        connection.disconnect = AsyncMock()

        with pytest.raises(ConnectionReadError):
            await connection.receive_data(to_read)

        connection._reader.read.assert_awaited_once_with(to_read)
        connection.disconnect.assert_awaited_once_with(CloseReason.READ_ERROR)

    @pytest.mark.asyncio
    async def test_receiveData_timeoutException_shouldDisconnectAndRaise(self, network: Network):
        to_read = 8

        connection = self._create_connection(network)
        connection._reader = Mock()
        connection._reader.read = AsyncMock(side_effect=OSError)
        connection.disconnect = AsyncMock()

        with patch('asyncio.wait_for', side_effect=TimeoutError):
            with pytest.raises(ConnectionReadError):
                await connection.receive_data(to_read)

        connection.disconnect.assert_awaited_once_with(CloseReason.TIMEOUT)

    # receive_file
    @pytest.mark.asyncio
    @pytest.mark.parametrize('callback', [None, Mock()])
    async def test_receiveFile(self, network: Network, callback):
        data = bytes.fromhex('AABBCCDDEEFF1122')
        split_data = (data[0:2], data[2:4], data[4:6], data[6:8])
        # Mock rate limiter
        network._download_rate_limiter = Mock()
        network._download_rate_limiter.take_tokens = AsyncMock(return_value=2)

        # Mock receiving connection
        connection = self._create_connection(network)
        connection.receive_data = AsyncMock(side_effect=split_data)

        # Mock target file handle
        file_handle = Mock()
        file_handle.write = AsyncMock()

        await connection.receive_file(file_handle, len(data), callback=callback)

        expected_calls = [call(data_part) for data_part in split_data]
        file_handle.write.assert_has_awaits(expected_calls)
        if callback:
            callback.assert_has_calls(expected_calls)

    # send_data
    @pytest.mark.asyncio
    async def test_sendData(self, network: Network):
        expected_data = bytes.fromhex('aabbccdd')

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection._writer.write = Mock()
        connection._writer.drain = AsyncMock()

        await connection.send_data(expected_data)
        connection._writer.write.assert_called_once_with(expected_data)
        connection._writer.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sendData_exception_shouldDisconnectAndRaise(self, network: Network):
        expected_data = bytes.fromhex('aabbccdd')

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection._writer.write = Mock(side_effect=OSError)
        connection.disconnect = AsyncMock()

        with pytest.raises(ConnectionWriteError):
            await connection.send_data(expected_data)

        connection.disconnect.assert_awaited_once_with(CloseReason.WRITE_ERROR)

    @pytest.mark.asyncio
    async def test_sendData_timeoutException_shouldDisconnectAndRaise(self, network: Network):
        expected_data = bytes.fromhex('aabbccdd')

        connection = self._create_connection(network)
        connection._writer = Mock()
        connection.disconnect = AsyncMock()

        with patch('asyncio.wait_for', side_effect=TimeoutError):
            with pytest.raises(ConnectionWriteError):
                await connection.send_data(expected_data)

        connection.disconnect.assert_awaited_once_with(CloseReason.TIMEOUT)

    # helpers
    def _create_connection(self, network: Network, state: ConnectionState = ConnectionState.CONNECTED) -> PeerConnection:
        ip, port = '1.2.3.4', 1234
        connection = PeerConnection(hostname=ip, port=port, network=network)
        connection.state = state
        connection.download_rate_limiter = network._download_rate_limiter
        return connection


class TestListeningConnection:

    @pytest.mark.asyncio
    async def test_connect(self, network: Network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()
        server = Mock()

        with patch('asyncio.start_server', return_value=server) as start_server:
            await connection.connect()

        start_server.assert_awaited_once()
        assert 2 == connection.set_state.call_count
        connection.set_state.assert_has_awaits(
            [call(ConnectionState.CONNECTING), call(ConnectionState.CONNECTED)]
        )

    @pytest.mark.asyncio
    async def test_disconnect_shouldSetState(self, network: Network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()

        server_mock = Mock()
        connection._server = server_mock
        connection._server.close = Mock()
        connection._server.wait_closed = AsyncMock()
        connection._server.is_serving = Mock(return_value=True)

        await connection.disconnect(CloseReason.REQUESTED)

        self._validate_disconnected(connection, server_mock)

    @pytest.mark.asyncio
    async def test_disconnect_exception_shouldSetState(self, network: Network):
        connection = self._create_connection(network)
        connection.set_state = AsyncMock()

        server_mock = Mock()
        connection._server = server_mock
        connection._server.close = Mock()
        connection._server.wait_closed = AsyncMock(side_effect=OSError)
        connection._server.is_serving = Mock(return_value=True)

        await connection.disconnect(CloseReason.REQUESTED)

        self._validate_disconnected(connection, server_mock)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'obfuscated', [(True, ), (False, )]
    )
    async def test_accept(self, network, obfuscated):
        connection = self._create_connection(network)
        peer_ip, peer_port = ('1.2.3.4', 1234)
        connection.obfuscated = obfuscated

        reader, writer = Mock(), Mock()
        writer.get_extra_info = Mock(return_value=(peer_ip, peer_port))

        await connection.accept(reader, writer)

        connection.network.on_peer_accepted.assert_awaited_once()
        peer_connection = connection.network.on_peer_accepted.call_args.args[0]
        assert peer_ip == peer_connection.hostname
        assert peer_port == peer_connection.port
        assert peer_connection.incoming is True
        assert PeerConnectionType.PEER == peer_connection.connection_type
        assert peer_connection.obfuscated is obfuscated

    def _validate_disconnected(self, connection: ListeningConnection, server_mock: Mock):
        server_mock.close.assert_called_once()
        server_mock.wait_closed.assert_awaited_once()
        assert connection._server is None
        assert 2 == connection.set_state.call_count
        connection.set_state.assert_has_awaits(
            [
                call(ConnectionState.CLOSING, close_reason=CloseReason.REQUESTED),
                call(ConnectionState.CLOSED, close_reason=CloseReason.REQUESTED)
            ]
        )

    def _create_connection(self, network, state: ConnectionState = ConnectionState.CONNECTED) -> ListeningConnection:
        ip, port = '0.0.0.0', 10000
        connection = ListeningConnection(hostname=ip, port=port, network=network)
        connection.state = state
        return connection
