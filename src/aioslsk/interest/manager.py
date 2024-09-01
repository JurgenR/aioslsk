import asyncio

from ..base_manager import BaseManager
from ..events import (
    build_message_map,
    on_message,
    EventBus,
    GlobalRecommendationsEvent,
    ItemRecommendationsEvent,
    ItemSimilarUsersEvent,
    MessageReceivedEvent,
    RecommendationsEvent,
    SessionInitializedEvent,
    SimilarUsersEvent,
    UserInterestsEvent,
)
from ..protocol.messages import (
    AddHatedInterest,
    AddInterest,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetRecommendations,
    GetSimilarUsers,
    GetUserInterests,
)
from ..network.connection import ServerConnection
from ..network.network import Network
from ..settings import Settings
from ..user.manager import UserManager


class InterestManager(BaseManager):
    """Class handling interests and recommendations"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus,
            user_manager: UserManager, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._user_manager: UserManager = user_manager
        self._network: Network = network

        self._MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    def register_listeners(self):
        self._event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)

    async def advertise_interests(self):
        """Advertises all interests and hated interests defined in the settings
        to the server
        """
        messages = []
        for interest in self._settings.interests.liked:
            messages.append(
                self._network.send_server_messages(
                    AddInterest.Request(interest)
                )
            )

        for hated_interest in self._settings.interests.hated:
            messages.append(
                self._network.send_server_messages(
                    AddHatedInterest.Request(hated_interest)
                )
            )

        await asyncio.gather(*messages, return_exceptions=True)

    # Recommendations / interests
    @on_message(GetRecommendations.Response)
    async def _on_get_recommendations(
            self, message: GetRecommendations.Response, connection: ServerConnection):

        await self._event_bus.emit(
            RecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations,
                raw_message=message
            )
        )

    @on_message(GetGlobalRecommendations.Response)
    async def _on_get_global_recommendations(
            self, message: GetGlobalRecommendations.Response, connection: ServerConnection):

        await self._event_bus.emit(
            GlobalRecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations,
                raw_message=message
            )
        )

    @on_message(GetItemRecommendations.Response)
    async def _on_get_item_recommendations(
            self, message: GetItemRecommendations.Response, connection: ServerConnection):

        await self._event_bus.emit(
            ItemRecommendationsEvent(
                item=message.item,
                recommendations=message.recommendations,
                raw_message=message
            )
        )

    @on_message(GetUserInterests.Response)
    async def _on_get_user_interests(self, message: GetUserInterests.Response, connection: ServerConnection):
        await self._event_bus.emit(
            UserInterestsEvent(
                user=self._user_manager.get_user_object(message.username),
                interests=message.interests,
                hated_interests=message.hated_interests,
                raw_message=message
            )
        )

    @on_message(GetSimilarUsers.Response)
    async def _on_get_similar_users(self, message: GetSimilarUsers.Response, connection: ServerConnection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                users=[
                    (self._user_manager.get_user_object(user.username), user.score, )
                    for user in message.users
                ],
                raw_message=message
            )
        )

    @on_message(GetItemSimilarUsers.Response)
    async def _on_get_item_similar_users(
            self, message: GetItemSimilarUsers.Response, connection: ServerConnection):
        await self._event_bus.emit(
            ItemSimilarUsersEvent(
                item=message.item,
                users=[
                    self._user_manager.get_user_object(username)
                    for username in message.usernames
                ],
                raw_message=message
            )
        )

    # Listeners

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        await self.advertise_interests()
