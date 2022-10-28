from pyslsk.events import EventBus, UserDirectoryEvent
from pyslsk.protocol.primitives import DirectoryData
from pyslsk.protocol.messages import (
    PeerDirectoryContentsRequest,
    PeerDirectoryContentsReply,
)
from pyslsk.peer import PeerManager
from pyslsk.settings import Settings
from pyslsk.state import State

from unittest.mock import ANY, Mock


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234'
    }
}


class TestPeer:

    def _create_peer_manager(self) -> PeerManager:
        state = State()
        event_bus = Mock()
        internal_event_bus = Mock()
        shares_manager = Mock()
        transfer_manager = Mock()
        network = Mock()
        network.server = Mock()

        manager = PeerManager(
            state,
            Settings(DEFAULT_SETTINGS),
            event_bus,
            internal_event_bus,
            shares_manager,
            transfer_manager,
            network
        )

        return manager

    def test_whenGetUserDirectory_shouldSendRequest(self):
        manager = self._create_peer_manager()

        ticket = manager.get_user_directory('user0', 'C:\\dir0')
        manager.network.send_peer_messages.assert_called_once_with('user0', ANY)

        assert isinstance(ticket, int)

    def test_whenDirectoryRequestReceived_shouldRespond(self):
        DIRECTORY = 'C:\\dir0'
        USER = 'user0'
        manager = self._create_peer_manager()

        manager.shares_manager.create_directory_reply.return_value = [
            DirectoryData(DIRECTORY, files=[])
        ]

        connection = Mock()
        connection.username = USER

        manager._on_peer_directory_contents_req(
            PeerDirectoryContentsRequest.Request(1234, DIRECTORY), connection
        )

        manager.shares_manager.create_directory_reply.assert_called_once_with(DIRECTORY)
        manager.network.send_peer_messages.assert_called_once_with(
            'user0', ANY, connection=connection)

    def test_whenDirectoryReplyReceived_shouldEmitEvent(self):
        DIRECTORY = 'C:\\dir0'
        USER = 'user0'
        DIRECTORIES = [DirectoryData(DIRECTORY, files=[])]

        manager = self._create_peer_manager()
        user = manager._state.get_or_create_user(USER)

        connection = Mock()
        connection.username = USER

        manager._on_peer_directory_contents_reply(
            PeerDirectoryContentsReply.Request(1234, DIRECTORY, DIRECTORIES),
            connection
        )

        manager._event_bus.emit.assert_called_once_with(
            UserDirectoryEvent(user, DIRECTORY, DIRECTORIES)
        )
