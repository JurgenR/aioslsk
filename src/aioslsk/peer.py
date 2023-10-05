import logging

from .network.connection import PeerConnection
from .events import (
    on_message,
    build_message_map,
    EventBus,
    InternalEventBus,
    MessageReceivedEvent,
    UserDirectoryEvent,
    UserInfoEvent,
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
from .network.network import Network
from .settings import Settings
from .shares.manager import SharesManager
from .state import State
from .transfer.manager import TransferManager
from .utils import ticket_generator


logger = logging.getLogger(__name__)


class PeerManager:
    """Peer manager is responsible for handling peer messages"""

    def __init__(
            self, state: State, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            shares_manager: SharesManager, transfer_manager: TransferManager,
            network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._network: Network = network
        self._shares_manager: SharesManager = shares_manager
        self._transfer_manager: TransferManager = transfer_manager

        self._ticket_generator = ticket_generator()

        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)

        self.MESSAGE_MAP = build_message_map(self)

    # External methods
    async def get_user_info(self, username: str):
        """Requests user info from the peer itself

        :param username: name of the peer
        """
        await self._network.send_peer_messages(
            username, PeerUserInfoRequest.Request())

    async def get_user_shares(self, username: str):
        """Requests the shares of the peer

        :param username: name of the peer
        """
        await self._network.send_peer_messages(
            username, PeerSharesRequest.Request())

    async def get_user_directory(self, username: str, directory: str) -> int:
        """Requests details for a single directory from a peer

        :param username: name of the peer
        :param directory: directory to request details for
        """
        ticket = next(self._ticket_generator)
        await self._network.send_peer_messages(
            username,
            PeerDirectoryContentsRequest.Request(
                ticket=ticket,
                directory=directory
            )
        )
        return ticket

    # Peer messages

    @on_message(PeerSharesRequest.Request)
    async def _on_peer_shares_request(self, message: PeerSharesRequest.Request, connection: PeerConnection):
        visible, locked = self._shares_manager.create_shares_reply(connection.username)
        await connection.send_message(
            PeerSharesReply.Request(
                directories=visible,
                locked_directories=locked
            )
        )

    @on_message(PeerSharesReply.Request)
    async def _on_peer_shares_reply(self, message: PeerSharesReply.Request, connection: PeerConnection):
        logger.info(f"PeerSharesReply : from username {connection.username}, got {len(message.directories)} directories")

        user = self._state.get_or_create_user(connection.username)
        locked_directories = message.locked_directories or []

        await self._event_bus.emit(
            UserSharesReplyEvent(user, message.directories, locked_directories)
        )

    @on_message(PeerDirectoryContentsRequest.Request)
    async def _on_peer_directory_contents_req(self, message: PeerDirectoryContentsRequest.Request, connection: PeerConnection):
        directories = self._shares_manager.create_directory_reply(message.directory)
        await connection.send_message(
            PeerDirectoryContentsReply.Request(
                ticket=message.ticket,
                directory=message.directory,
                directories=directories
            )
        )

    @on_message(PeerDirectoryContentsReply.Request)
    async def _on_peer_directory_contents_reply(self, message: PeerDirectoryContentsReply.Request, connection: PeerConnection):
        user = self._state.get_or_create_user(connection.username)
        await self._event_bus.emit(
            UserDirectoryEvent(user, message.directory, message.directories)
        )

    @on_message(PeerUserInfoReply.Request)
    async def _on_peer_user_info_reply(self, message: PeerUserInfoReply.Request, connection: PeerConnection):
        user = self._state.get_or_create_user(connection.username)
        user.description = message
        user.picture = message.picture
        user.upload_slots = message.upload_slots
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free

        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(PeerUserInfoRequest.Request)
    async def _on_peer_user_info_request(self, message: PeerUserInfoRequest.Request, connection: PeerConnection):
        try:
            description = self._settings.get('credentials.info.description')
        except KeyError:
            description = ""

        try:
            picture = self._settings.get('credentials.info.picture')
        except KeyError:
            picture = None

        await connection.send_message(
            PeerUserInfoReply.Request(
                description=description,
                has_picture=bool(picture),
                picture=picture,
                upload_slots=self._transfer_manager.get_upload_slots(),
                queue_size=self._transfer_manager.get_queue_size(),
                has_slots_free=self._transfer_manager.has_slots_free()
            )
        )

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)
