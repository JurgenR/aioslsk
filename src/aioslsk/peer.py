import logging

from .base_manager import BaseManager
from .events import (
    on_message,
    build_message_map,
    EventBus,
    MessageReceivedEvent,
    UserDirectoryEvent,
    UserSharesReplyEvent,
)
from .protocol.messages import (
    PeerDirectoryContentsRequest,
    PeerDirectoryContentsReply,
    PeerSharesRequest,
    PeerSharesReply,
    PeerUserInfoReply,
    PeerUserInfoRequest,
)
from .network.connection import PeerConnection
from .network.network import Network
from .settings import Settings
from .shares.manager import SharesManager
from .transfer.interface import UploadInfoProvider
from .user.manager import UserManager
from .user.model import BlockingFlag
from .utils import ticket_generator


logger = logging.getLogger(__name__)


class PeerManager(BaseManager):
    """Peer manager is responsible for handling peer messages"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus,
            user_manager: UserManager,
            shares_manager: SharesManager, upload_info_provider: UploadInfoProvider,
            network: Network):

        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network
        self._user_manager: UserManager = user_manager
        self._shares_manager: SharesManager = shares_manager
        self._upload_info_provider: UploadInfoProvider = upload_info_provider

        self._ticket_generator = ticket_generator()

        self._MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    def register_listeners(self):
        self._event_bus.register(
            MessageReceivedEvent, self._on_message_received)

    # Peer messages

    @on_message(PeerSharesRequest.Request)
    async def _on_peer_shares_request(self, message: PeerSharesRequest.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerSharesRequest for a connection that wasn't properly initialized")
            return

        if self._settings.users.is_blocked(connection.username, BlockingFlag.SHARES):
            return

        visible, locked = self._shares_manager.create_shares_reply(connection.username)
        await connection.send_message(
            PeerSharesReply.Request(
                directories=visible,
                locked_directories=locked
            )
        )

    @on_message(PeerSharesReply.Request)
    async def _on_peer_shares_reply(self, message: PeerSharesReply.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerSharesRequest for a connection that wasn't properly initialized")
            return

        logger.info(
            "PeerSharesReply : from username %s, got %d directories",
            connection.username, len(message.directories)
        )

        user = self._user_manager.get_user_object(connection.username)

        await self._event_bus.emit(
            UserSharesReplyEvent(
                user=user,
                directories=message.directories,
                locked_directories=message.locked_directories or [],
                raw_message=message
            )
        )

    @on_message(PeerDirectoryContentsRequest.Request)
    async def _on_peer_directory_contents_req(
            self, message: PeerDirectoryContentsRequest.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerDirectoryContentsRequest for a connection that wasn't properly initialized")
            return

        if self._settings.users.is_blocked(connection.username, BlockingFlag.SHARES):
            return

        directories = self._shares_manager.create_directory_reply(message.directory)
        await connection.send_message(
            PeerDirectoryContentsReply.Request(
                ticket=message.ticket,
                directory=message.directory,
                directories=directories
            )
        )

    @on_message(PeerDirectoryContentsReply.Request)
    async def _on_peer_directory_contents_reply(
            self, message: PeerDirectoryContentsReply.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerDirectoryContentsReply for a connection that wasn't properly initialized")
            return

        user = self._user_manager.get_user_object(connection.username)
        await self._event_bus.emit(
            UserDirectoryEvent(
                user=user,
                directory=message.directory,
                directories=message.directories,
                raw_message=message
            )
        )

    @on_message(PeerUserInfoRequest.Request)
    async def _on_peer_user_info_request(self, message: PeerUserInfoRequest.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerSharesRequest for a connection that wasn't properly initialized")
            return

        if self._settings.users.is_blocked(connection.username, BlockingFlag.INFO):
            return

        description = self._settings.credentials.info.description or ""
        picture = self._settings.credentials.info.picture

        await connection.send_message(
            PeerUserInfoReply.Request(
                description=description,
                has_picture=bool(picture),
                picture=picture,
                upload_slots=self._upload_info_provider.get_upload_slots(),
                queue_size=self._upload_info_provider.get_queue_size(),
                has_slots_free=self._upload_info_provider.has_slots_free()
            )
        )

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)
