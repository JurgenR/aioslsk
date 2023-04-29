from aioslsk.events import UserDirectoryEvent, UserInfoEvent, SearchResultEvent
from aioslsk.protocol.primitives import DirectoryData, FileData
from aioslsk.protocol.messages import (
    PeerDirectoryContentsRequest,
    PeerDirectoryContentsReply,
    PeerUserInfoReply,
    PeerUserInfoRequest,
    PeerSearchReply,
)
from aioslsk.peer import PeerManager
from aioslsk.search import SearchRequest, SearchType
from aioslsk.settings import Settings
from aioslsk.state import State

import pytest
from unittest.mock import ANY, AsyncMock, call, Mock, PropertyMock


USER_DESCRIPTION = 'describes the user'
USER_PICTURE = 'https://example.com/picture.png'
UPLOAD_SLOTS = 2
QUEUE_SIZE = 100
HAS_SLOTS_FREE = True
DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234',
    }
}
SETTINGS_WITH_INFO = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234',
        'info': {
            'description': USER_DESCRIPTION,
            'picture': USER_PICTURE
        }
    },
    'sharing': {
        'limits': {
            'upload_slots': UPLOAD_SLOTS
        }
    }
}


class TestPeer:

    def _create_peer_manager(self, settings: dict = DEFAULT_SETTINGS) -> PeerManager:
        state = State()
        event_bus = AsyncMock()
        internal_event_bus = Mock()
        shares_manager = Mock()
        transfer_manager = Mock()
        network = AsyncMock()
        network.server = AsyncMock()

        manager = PeerManager(
            state,
            Settings(settings),
            event_bus,
            internal_event_bus,
            shares_manager,
            transfer_manager,
            network
        )

        return manager

    @pytest.mark.asyncio
    async def test_onPeerInfoRequest_withInfo_shouldSendPeerInfoReply(self):
        manager = self._create_peer_manager(SETTINGS_WITH_INFO)
        connection = AsyncMock()
        type(manager._transfer_manager).upload_slots = PropertyMock(return_value=UPLOAD_SLOTS)
        manager._transfer_manager.get_queue_size = Mock(return_value=QUEUE_SIZE)
        manager._transfer_manager.has_slots_free = Mock(return_value=HAS_SLOTS_FREE)

        await manager._on_peer_user_info_request(PeerUserInfoRequest.Request(), connection)

        connection.send_message.assert_awaited_once_with(
            PeerUserInfoReply.Request(
                description=USER_DESCRIPTION,
                has_picture=True,
                picture=USER_PICTURE,
                upload_slots=UPLOAD_SLOTS,
                queue_size=QUEUE_SIZE,
                has_slots_free=HAS_SLOTS_FREE
            ))

    @pytest.mark.asyncio
    async def test_onPeerInfoRequest_withoutInfo_shouldSendPeerInfoReply(self):
        manager = self._create_peer_manager(DEFAULT_SETTINGS)
        connection = AsyncMock()
        type(manager._transfer_manager).upload_slots = PropertyMock(return_value=UPLOAD_SLOTS)
        manager._transfer_manager.get_queue_size = Mock(return_value=QUEUE_SIZE)
        manager._transfer_manager.has_slots_free = Mock(return_value=HAS_SLOTS_FREE)

        await manager._on_peer_user_info_request(PeerUserInfoRequest.Request(), connection)

        connection.send_message.assert_awaited_once_with(
            PeerUserInfoReply.Request(
                description='',
                has_picture=False,
                picture=None,
                upload_slots=UPLOAD_SLOTS,
                queue_size=QUEUE_SIZE,
                has_slots_free=HAS_SLOTS_FREE
            ))

    @pytest.mark.asyncio
    async def test_whenGetUserDirectory_shouldSendRequest(self):
        manager = self._create_peer_manager()

        ticket = await manager.get_user_directory('user0', 'C:\\dir0')
        manager._network.send_peer_messages.assert_awaited_once_with('user0', ANY)

        assert isinstance(ticket, int)

    @pytest.mark.asyncio
    async def test_whenDirectoryRequestReceived_shouldRespond(self):
        DIRECTORY = 'C:\\dir0'
        USER = 'user0'
        DIRECTORY_DATA = [DirectoryData(DIRECTORY, files=[])]
        TICKET = 1324

        manager = self._create_peer_manager()
        manager._shares_manager.create_directory_reply.return_value = DIRECTORY_DATA

        connection = Mock()
        connection.username = USER

        await manager._on_peer_directory_contents_req(
            PeerDirectoryContentsRequest.Request(TICKET, DIRECTORY), connection
        )

        manager._shares_manager.create_directory_reply.assert_called_once_with(DIRECTORY)
        connection.queue_message.assert_called_once_with(
            PeerDirectoryContentsReply.Request(TICKET, DIRECTORY, DIRECTORY_DATA)
        )

    @pytest.mark.asyncio
    async def test_whenDirectoryReplyReceived_shouldEmitEvent(self):
        DIRECTORY = 'C:\\dir0'
        USER = 'user0'
        DIRECTORIES = [DirectoryData(DIRECTORY, files=[])]

        manager = self._create_peer_manager()
        user = manager._state.get_or_create_user(USER)

        connection = AsyncMock()
        connection.username = USER

        await manager._on_peer_directory_contents_reply(
            PeerDirectoryContentsReply.Request(1234, DIRECTORY, DIRECTORIES),
            connection
        )

        manager._event_bus.emit.assert_awaited_once_with(
            UserDirectoryEvent(user, DIRECTORY, DIRECTORIES)
        )

    @pytest.mark.asyncio
    async def test_onPeerSearchReply_shouldStoreResultsAndEmit(self):
        manager = self._create_peer_manager()
        TICKET = 1234
        connection = AsyncMock()

        manager._state.search_queries[TICKET] = SearchRequest(
            TICKET, 'search', SearchType.NETWORK)

        reply_message = PeerSearchReply.Request(
            'user0',
            TICKET,
            results=[FileData(1, 'myfile.mp3', 10000, 'mp3', attributes=[])],
            has_slots_free=True,
            avg_speed=100,
            queue_size=2,
            locked_results=[FileData(1, 'locked.mp3', 10000, 'mp3', attributes=[])]
        )
        await manager._on_peer_search_reply(reply_message, connection)

        assert 1 == len(manager._state.search_queries[TICKET].results)

        manager._event_bus.emit.assert_has_awaits(
            [
                call(
                    SearchResultEvent(
                        manager._state.search_queries[TICKET],
                        manager._state.search_queries[TICKET].results[0]
                    )
                ),
                call(UserInfoEvent(manager._state.get_or_create_user('user0')))
            ]

        )
