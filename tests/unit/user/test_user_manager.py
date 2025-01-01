from aioslsk.events import EventBus, PrivateMessageEvent
from aioslsk.protocol.messages import (
    AddUser,
    PrivateChatMessage,
    PrivateChatMessageAck,
    RemoveUser,
)
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager
from aioslsk.user.model import ChatMessage, User, UserStatus, TrackingFlag

import pytest
from unittest.mock import AsyncMock


DEFAULT_USERNAME = 'user0'
DEFAULT_SETTINGS = {
    'credentials': {
        'username': DEFAULT_USERNAME,
        'password': 'Test1234'
    }
}

@pytest.fixture
def manager() -> UserManager:
    event_bus = EventBus()
    network = AsyncMock()
    network.server = AsyncMock()

    manager = UserManager(
        Settings(**DEFAULT_SETTINGS),
        event_bus,
        network
    )

    return manager


class TestUserManager:

    def test_getUserObject_missingUserByName_shouldCreateAndReturnUser(self, manager: UserManager):
        username = 'myuser'

        user = manager.get_user_object(username)
        assert isinstance(user, User)
        assert username == user.name
        assert username in manager.users

    def test_getUserObject_existingUserByName_shouldReturnUser(self, manager: UserManager):
        username = 'myuser'
        user = User(name=username)
        manager.users[username] = user

        assert user == manager.get_user_object(username)

    def test_getUserObject_existingUserByName_shouldReturnUser(self, manager: UserManager):
        username = 'myuser'
        user = User(name=username)
        manager.users[username] = user

        assert user == manager.get_user_object(username)

    @pytest.mark.asyncio
    async def test_trackUser_userNotTracked_shouldSendAddUser(self, manager: UserManager):
        user = manager.get_user_object(DEFAULT_USERNAME)

        await manager.track_user(DEFAULT_USERNAME, TrackingFlag.FRIEND)

        assert manager._tracked_users[DEFAULT_USERNAME].flags == TrackingFlag.FRIEND
        manager._network.send_server_messages.assert_awaited_once_with(
            AddUser.Request(DEFAULT_USERNAME)
        )

    @pytest.mark.asyncio
    async def test_trackUser_userTracked_shouldNotSendAddUser(self, manager: UserManager):
        user = manager.get_user_object(DEFAULT_USERNAME)
        manager._set_tracking_flag(user, TrackingFlag.FRIEND)

        await manager.track_user(DEFAULT_USERNAME, TrackingFlag.TRANSFER)

        assert manager._tracked_users[DEFAULT_USERNAME].flags == TrackingFlag.TRANSFER | TrackingFlag.FRIEND
        assert 0 == manager._network.send_server_messages.await_count

    @pytest.mark.asyncio
    async def test_untrackUser_lastAddUserFlag_shouldSendRemoveUser(self, manager: UserManager):
        user = manager.get_user_object(DEFAULT_USERNAME)
        manager._set_tracking_flag(user, TrackingFlag.FRIEND)

        user.status = UserStatus.ONLINE
        manager._tracked_users[user.name].flags = TrackingFlag.FRIEND

        await manager.untrack_user(DEFAULT_USERNAME, TrackingFlag.FRIEND)

        assert user.status == UserStatus.UNKNOWN
        assert DEFAULT_USERNAME not in manager._tracked_users
        manager._network.send_server_messages.assert_awaited_once_with(
            RemoveUser.Request(DEFAULT_USERNAME)
        )

    @pytest.mark.asyncio
    async def test_untrackUser_addUserFlagRemains_shouldNotSendRemoveUser(self, manager: UserManager):
        user = manager.get_user_object(DEFAULT_USERNAME)
        manager._set_tracking_flag(user, TrackingFlag.FRIEND)
        manager._set_tracking_flag(user, TrackingFlag.REQUESTED)

        await manager.untrack_user(DEFAULT_USERNAME, TrackingFlag.FRIEND)

        assert manager._tracked_users[DEFAULT_USERNAME].flags == TrackingFlag.REQUESTED
        assert 0 == manager._network.send_server_messages.await_count

    @pytest.mark.asyncio
    async def test_onPrivateChatMessage_shouldSendAckAndEmitEvent(self, manager: UserManager):
        callback = AsyncMock()
        manager._event_bus.register(PrivateMessageEvent, callback)

        user = manager.get_user_object(DEFAULT_USERNAME)

        raw_message = PrivateChatMessage.Response(
            chat_id=1,
            username=DEFAULT_USERNAME,
            message='hello',
            timestamp=100.0,
            is_direct=False
        )
        await manager._on_private_message(raw_message, manager._network.server)

        manager._network.send_server_messages.assert_awaited_once_with(
            PrivateChatMessageAck.Request(1)
        )
        message = ChatMessage(
            id=1,
            timestamp=100.0,
            user=user,
            message='hello',
            is_direct=False
        )
        callback.assert_awaited_once_with(
            PrivateMessageEvent(message=message, raw_message=raw_message))
