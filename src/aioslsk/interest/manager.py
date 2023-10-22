import logging

from ..network.connection import ConnectionState, ServerConnection
from ..events import (
    build_message_map,
    on_message,
    ConnectionStateChangedEvent,
    EventBus,
    GlobalRecommendationsEvent,
    InternalEventBus,
    ItemRecommendationsEvent,
    MessageReceivedEvent,
    RecommendationsEvent,
    SimilarUsersEvent,
    UserInterestsEvent,
)
from ..protocol.messages import (
    Login,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetRecommendations,
    GetSimilarUsers,
    GetUserInterests,
)
from ..network.network import Network
from ..settings import Settings
from ..user.manager import UserManager


logger = logging.getLogger(__name__)


class InterestManager:
    """Class handling interests and recommendations"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            user_manager: UserManager, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._user_manager: UserManager = user_manager
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._network: Network = network

        self.MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    def register_listeners(self):
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    async def advertise_interests(self):
        pass

    @on_message(Login.Response)
    async def _on_login(self, message: Login.Response, connection: ServerConnection):
        if message.success:
            await self.advertise_interests()

    # Recommendations / interests
    @on_message(GetRecommendations.Response)
    async def _on_get_recommendations(self, message: GetRecommendations.Response, connection: ServerConnection):
        await self._event_bus.emit(
            RecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations
            )
        )

    @on_message(GetGlobalRecommendations.Response)
    async def _on_get_global_recommendations(self, message: GetGlobalRecommendations.Response, connection: ServerConnection):
        await self._event_bus.emit(
            GlobalRecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations
            )
        )

    @on_message(GetItemRecommendations.Response)
    async def _on_get_item_recommendations(self, message: GetItemRecommendations.Response, connection: ServerConnection):
        await self._event_bus.emit(
            ItemRecommendationsEvent(
                item=message.item,
                recommendations=message.recommendations
            )
        )

    @on_message(GetUserInterests.Response)
    async def _on_get_user_interests(self, message: GetUserInterests.Response, connection: ServerConnection):
        await self._event_bus.emit(
            UserInterestsEvent(
                user=self.get_or_create_user(message.username),
                interests=message.interests,
                hated_interests=message.hated_interests
            )
        )

    @on_message(GetSimilarUsers.Response)
    async def _on_get_similar_users(self, message: GetSimilarUsers.Response, connection: ServerConnection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                users=[
                    self.get_or_create_user(user.username)
                    for user in message.users
                ]
            )
        )

    @on_message(GetItemSimilarUsers.Response)
    async def _on_get_item_similar_users(self, message: GetItemSimilarUsers.Response, connection: ServerConnection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                item=message.item,
                users=[
                    self.get_or_create_user(user.username)
                    for user in message.users
                ]
            )
        )

    # Listeners

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            self.reset_users()
