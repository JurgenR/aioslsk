import pytest
from unittest.mock import AsyncMock, Mock

from aioslsk.log_utils import MessageFilter
from aioslsk.network.connection import ConnectionState, ServerConnection
from aioslsk.protocol.messages import JoinRoom, Ping


@pytest.fixture
def connection() -> ServerConnection:
    connection = ServerConnection('1.1.1.1', 1234, network=Mock())
    connection._reader = Mock()
    connection._writer = Mock()
    connection._writer.write = Mock()
    connection._writer.drain = AsyncMock()

    return connection


class TestMessageFilter:

    @pytest.mark.asyncio
    async def test_whenSendMatches_shouldFilterMessage(
            self, connection: ServerConnection, caplog: pytest.LogCaptureFixture):

        with caplog.filtering(MessageFilter([JoinRoom.Request])):
            await connection.send_message(JoinRoom.Request('test'))

        assert len(caplog.records) == 0
        connection._writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_whenSendMismatches_shouldNotFilterMessage(
            self, connection: ServerConnection, caplog: pytest.LogCaptureFixture):

        message = Ping.Request()
        with caplog.filtering(MessageFilter([JoinRoom.Request])):
            await connection.send_message(message)

        assert len(caplog.records) == 1
        assert message.__class__.__name__ in caplog.records[-1].getMessage()
        connection._writer.write.assert_called_once()


    @pytest.mark.asyncio
    async def test_whenReceiveMatches_shouldFilterMessage(
            self, connection: ServerConnection, caplog: pytest.LogCaptureFixture):

        message = Ping.Response()
        connection.receive_message = AsyncMock(return_value=message.serialize())

        with caplog.filtering(MessageFilter([Ping.Response])):
            received_message = await connection.receive_message_object()

        assert len(caplog.records) == 0
        assert received_message == message

    @pytest.mark.asyncio
    async def test_whenReceiveMismatches_shouldNotFilterMessage(
            self, connection: ServerConnection, caplog: pytest.LogCaptureFixture):

        message = Ping.Response()
        connection.receive_message = AsyncMock(return_value=message.serialize())

        with caplog.filtering(MessageFilter([JoinRoom.Request])):
            received_message = await connection.receive_message_object()

        assert len(caplog.records) == 1
        assert message.__class__.__name__ in caplog.records[-1].getMessage()
        assert received_message == message

    @pytest.mark.asyncio
    async def test_whenLogNonFilteredMessage_shouldNotFilterMessage(
            self, connection: ServerConnection, caplog: pytest.LogCaptureFixture):

        # `send_message` logs a warning when attempting to send a message while
        # the connection is closed. This test verifies if non-message logs are
        # still logged
        connection.network = AsyncMock()
        await connection.set_state(ConnectionState.CLOSED)

        with caplog.filtering(MessageFilter([Ping.Request()])):
            await connection.send_message(Ping.Request())

        assert len(caplog.records) == 1
