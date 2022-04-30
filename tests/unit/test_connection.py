from pyslsk.connection import (
    Connection,
    CloseReason,
    ConnectionState,
    DataConnection,
    PeerConnection,
    PeerConnectionState,
)
from unittest.mock import MagicMock, Mock, patch


class TestConnection:

    def test_whenDisconnect_shouldCallCloseAndSetState(self):
        conn = Connection(hostname='test', port=1234)
        conn.fileobj = Mock()

        conn.disconnect()

        conn.fileobj.close.assert_called_once()
        assert conn.state == ConnectionState.CLOSED

    def test_whenDisconnectAndCloseRaisesException_shouldSetState(self):
        conn = Connection(hostname='test', port=1234)
        conn.fileobj = Mock(side_effect=OSError('error closing'))

        conn.disconnect()

        conn.fileobj.close.assert_called_once()
        assert conn.state == ConnectionState.CLOSED


class TestDataConnection:
    # read

    @patch('pyslsk.connection.DataConnection.process_buffer')
    def test_whenReadSuccessful_shouldBufferAndReturnTrue(self, process_buffer):
        data = b"050000000095000000"

        conn = DataConnection(hostname='test', port=1234)
        conn.fileobj = Mock()
        conn.fileobj.recv.return_value = data

        result = conn.read()

        assert result is True
        assert conn._buffer == data
        assert conn.bytes_received == len(data)
        assert conn.last_interaction != 0
        conn.process_buffer.assert_called_once()

    @patch('pyslsk.connection.DataConnection.disconnect')
    def test_whenReadReturnsEmptyData_shouldDisconnectAndReturnFalse(self, disconnect):
        data = b""

        conn = DataConnection(hostname='test', port=1234)
        conn.fileobj = Mock()
        conn.fileobj.recv.return_value = data

        result = conn.read()

        assert result is False
        assert conn._buffer == b""
        assert conn.bytes_received == 0
        assert conn.last_interaction != 0
        conn.disconnect.assert_called_once_with(reason=CloseReason.EOF)

    @patch('pyslsk.connection.DataConnection.disconnect')
    def test_whenReadUnsuccessful_shouldCallDisconnectAndReturnFalse(self, disconnect):

        conn = DataConnection(hostname='test', port=1234)
        conn.fileobj = Mock()
        conn.fileobj.recv.side_effect = OSError("read error")

        result = conn.read()

        assert result is False
        assert conn._buffer == b""
        assert conn.bytes_received == 0
        assert conn.last_interaction == 0
        conn.disconnect.assert_called_once_with(reason=CloseReason.READ_ERROR)

    # buffer

    def test_whenBuffer_shouldStoreData(self):
        conn = DataConnection(hostname='test', port=1234)

        data_to_send = b"abc"
        conn.buffer(data_to_send)

        assert conn.bytes_received == len(data_to_send)
        assert conn._buffer == data_to_send

    # send_message

    def test_whenSendMessageNoMessageQueued_shouldReturnTrue(self):
        conn = DataConnection(hostname='test', port=1234)
        conn.fileobj = Mock()

        res = conn.send_message()

        assert res is True
        assert conn.bytes_sent == 0
        assert conn.last_interaction == 0.0

    def test_whenSendMessageSuccessful_shouldReturnTrue(self):
        conn = DataConnection(hostname='test', port=1234)
        conn.fileobj = Mock()

        data_to_send = b"abc"
        conn.queue_message(data_to_send)

        res = conn.send_message()

        conn.fileobj.sendall.assert_called_once_with(data_to_send)
        assert res is True
        assert conn.bytes_sent == len(data_to_send)
        assert conn.last_interaction != 0

    @patch('pyslsk.connection.DataConnection.disconnect')
    def test_whenSendMessageFails_shouldDisconnectAndReturnFalse(self, disconnect):
        conn = DataConnection(hostname='test', port=1234)
        conn.fileobj = Mock()
        conn.fileobj.sendall.side_effect = OSError("write error")

        data_to_send = b"abc"
        conn.queue_message(data_to_send)

        res = conn.send_message()

        conn.fileobj.sendall.assert_called_once_with(data_to_send)
        assert res is False
        assert conn.bytes_sent == 0
        assert conn.last_interaction != 0
        conn.disconnect.assert_called_once_with(reason=CloseReason.WRITE_ERROR)


class TestPeerConnection:

    def test_whenCreatePeerConnection_verifyInitialState(self):
        conn = PeerConnection()
        assert conn.state == ConnectionState.UNINITIALIZED
        assert conn.connection_state == PeerConnectionState.AWAITING_INIT

    @patch('pyslsk.connection.socket.socket', autospec=True)
    def test_whenConnect_shouldSetConnectingState(self, sock_mock):
        ip, port = '1.2.3.4', 1234
        conn = PeerConnection(hostname=ip, port=port)

        fileobj = MagicMock()
        fileobj.connect_ex.return_value = 10035
        sock_mock.return_value = fileobj

        conn.connect()

        fileobj.connect_ex.assert_called_once()
        assert conn.state == ConnectionState.CONNECTING
        assert conn.last_interaction != 0

    def test_whenStateChanged_shouldSetStateAndCallListeners(self):
        conn = PeerConnection()
        listeners = Mock(), Mock()

        conn.listeners = listeners
        conn.set_state(ConnectionState.CLOSED, close_reason=CloseReason.READ_ERROR)

        for listener in listeners:
            listener.on_state_changed.assert_called_once_with(ConnectionState.CLOSED, conn, close_reason=CloseReason.READ_ERROR)
        assert conn.state == ConnectionState.CLOSED
