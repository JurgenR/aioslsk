from aioslsk.events import UserDirectoryEvent
from aioslsk.protocol.primitives import DirectoryData
from aioslsk.protocol.messages import (
    PeerDirectoryContentsRequest,
    PeerDirectoryContentsReply,
    PeerUserInfoReply,
    PeerUserInfoRequest,
)
from aioslsk.peer import PeerManager
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager
from aioslsk.user.model import BlockingFlag

import copy
import pytest
from unittest.mock import AsyncMock, Mock


DEFAULT_USERNAME = 'user0'
USER_DESCRIPTION = 'describes the user'
USER_PICTURE = bytes.fromhex('AABBCCDDEE')
UPLOAD_SLOTS = 2
QUEUE_SIZE = 100
HAS_SLOTS_FREE = True
DEFAULT_SETTINGS = {
    'credentials': {
        'username': DEFAULT_USERNAME,
        'password': 'Test1234',
    }
}
SETTINGS_WITH_INFO = {
    'credentials': {
        'username': DEFAULT_USERNAME,
        'password': 'Test1234',
        'info': {
            'description': USER_DESCRIPTION,
            'picture': USER_PICTURE
        }
    },
    'transfers': {
        'limits': {
            'upload_slots': UPLOAD_SLOTS
        }
    }
}


class TestPeer:

    def _create_user_manager(self, settings: Settings) -> UserManager:
        return UserManager(
            settings,
            Mock(), # Event bus
            AsyncMock() # Network
        )

    def _create_peer_manager(self, settings: dict = DEFAULT_SETTINGS) -> PeerManager:
        settings_obj = Settings(**settings)
        user_manager = self._create_user_manager(settings_obj)

        event_bus = Mock()
        event_bus.emit = AsyncMock()
        shares_manager = Mock()
        transfer_manager = Mock()
        network = AsyncMock()
        network.server = AsyncMock()

        manager = PeerManager(
            settings_obj,
            event_bus,
            user_manager,
            shares_manager,
            transfer_manager,
            network
        )

        return manager

    @pytest.mark.asyncio
    async def test_onPeerInfoRequest_withInfo_shouldSendPeerInfoReply(self):
        manager = self._create_peer_manager(SETTINGS_WITH_INFO)
        connection = AsyncMock()
        connection.username = DEFAULT_USERNAME
        manager._upload_info_provider.get_upload_slots = Mock(return_value=UPLOAD_SLOTS)
        manager._upload_info_provider.get_queue_size = Mock(return_value=QUEUE_SIZE)
        manager._upload_info_provider.has_slots_free = Mock(return_value=HAS_SLOTS_FREE)

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
        connection.username = DEFAULT_USERNAME
        manager._upload_info_provider.get_upload_slots = Mock(return_value=UPLOAD_SLOTS)
        manager._upload_info_provider.get_queue_size = Mock(return_value=QUEUE_SIZE)
        manager._upload_info_provider.has_slots_free = Mock(return_value=HAS_SLOTS_FREE)

        await manager._on_peer_user_info_request(PeerUserInfoRequest.Request(), connection)

        connection.send_message.assert_awaited_once_with(
            PeerUserInfoReply.Request(
                description='',
                has_picture=False,
                picture=None,
                upload_slots=UPLOAD_SLOTS,
                queue_size=QUEUE_SIZE,
                has_slots_free=HAS_SLOTS_FREE
            )
        )

    @pytest.mark.asyncio
    async def test_blocked_withInfo_shouldNotSendPeerInfoReply(self):
        settings = copy.deepcopy(SETTINGS_WITH_INFO)
        settings['users'] = {'blocked': {DEFAULT_USERNAME: BlockingFlag.INFO}}

        manager = self._create_peer_manager(settings)
        connection = AsyncMock()
        connection.username = DEFAULT_USERNAME

        await manager._on_peer_user_info_request(PeerUserInfoRequest.Request(), connection)

        connection.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whenDirectoryRequestReceived_shouldRespond(self):
        DIRECTORY = 'C:\\dir0'
        USER = 'user0'
        DIRECTORY_DATA = [DirectoryData(DIRECTORY, files=[])]
        TICKET = 1324

        manager = self._create_peer_manager()
        manager._shares_manager.create_directory_reply.return_value = DIRECTORY_DATA

        connection = AsyncMock()
        connection.username = USER

        await manager._on_peer_directory_contents_req(
            PeerDirectoryContentsRequest.Request(TICKET, DIRECTORY), connection
        )

        manager._shares_manager.create_directory_reply.assert_called_once_with(DIRECTORY)
        connection.send_message.assert_called_once_with(
            PeerDirectoryContentsReply.Request(TICKET, DIRECTORY, DIRECTORY_DATA)
        )

    @pytest.mark.asyncio
    async def test_whenDirectoryRequestReceived_blocked_shouldNotRespond(self):
        DIRECTORY = 'C:\\dir0'
        TICKET = 1324

        settings = copy.deepcopy(SETTINGS_WITH_INFO)
        settings['users'] = {'blocked': {DEFAULT_USERNAME: BlockingFlag.SHARES}}

        manager = self._create_peer_manager(settings)

        connection = AsyncMock()
        connection.username = DEFAULT_USERNAME

        await manager._on_peer_directory_contents_req(
            PeerDirectoryContentsRequest.Request(TICKET, DIRECTORY), connection
        )

        manager._shares_manager.create_directory_reply.assert_not_called()
        connection.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whenDirectoryReplyReceived_shouldEmitEvent(self):
        DIRECTORY = 'C:\\dir0'
        USER = 'user0'
        DIRECTORIES = [DirectoryData(DIRECTORY, files=[])]

        manager = self._create_peer_manager()
        user = manager._user_manager.get_user_object(USER)

        connection = AsyncMock()
        connection.username = USER

        raw_message = PeerDirectoryContentsReply.Request(1234, DIRECTORY, DIRECTORIES)
        await manager._on_peer_directory_contents_reply(raw_message, connection)

        manager._event_bus.emit.assert_awaited_once_with(
            UserDirectoryEvent(user, DIRECTORY, DIRECTORIES, raw_message)
        )
