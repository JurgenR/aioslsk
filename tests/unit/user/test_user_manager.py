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
from unittest.mock import AsyncMock, Mock


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'Test1234'
    }
}

@pytest.fixture
def manager() -> UserManager:
    event_bus = EventBus()
    internal_event_bus = Mock()
    network = AsyncMock()
    network.server = AsyncMock()

    manager = UserManager(
        Settings(**DEFAULT_SETTINGS),
        event_bus,
        internal_event_bus,
        network
    )

    return manager


class TestUserManager:

    def test_getOrCreateUser_missingUserByName_shouldCreateAndReturnUser(self, manager: UserManager):
        username = 'myuser'

        user = manager.get_or_create_user(username)
        assert isinstance(user, User)
        assert username == user.name
        assert username in manager.users

    def test_getOrCreateUser_existingUserByName_shouldReturnUser(self, manager: UserManager):
        username = 'myuser'
        user = User(name=username)
        manager.users[username] = user

        assert user == manager.get_or_create_user(username)

    def test_getOrCreateUser_missingUserByObject_shouldCreateAndReturnUser(self, manager: UserManager):
        original = User('user0')

        user = manager.get_or_create_user(original)

        assert user == original
        assert manager.users == {'user0': user}

    def test_getOrCreateUser_existingUserByObject_shouldReturnUser(self, manager: UserManager):
        original = User('user0')
        manager.users = {'user0': original}

        user = manager.get_or_create_user(original)

        assert user == original
        assert manager.users == {'user0': original}

    def test_getOrCreateUser_existingUserByName_shouldReturnUser(self, manager: UserManager):
        username = 'myuser'
        user = User(name=username)
        manager.users[username] = user

        assert user == manager.get_or_create_user(username)

    @pytest.mark.asyncio
    async def test_trackUser_userNotTracked_shouldSendAddUser(self, manager: UserManager):
        user = manager.get_or_create_user('user0')

        await manager.track_user('user0', TrackingFlag.REQUESTED)

        assert user.tracking_flags == TrackingFlag.REQUESTED
        manager._network.send_server_messages.assert_awaited_once_with(
            AddUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_trackUser_userTracked_shouldNotSendAddUser(self, manager: UserManager):
        user = manager.get_or_create_user('user0')
        user.status = UserStatus.ONLINE
        user.tracking_flags = TrackingFlag.FRIEND

        await manager.track_user('user0', TrackingFlag.REQUESTED)

        assert user.tracking_flags == TrackingFlag.REQUESTED | TrackingFlag.FRIEND
        assert 0 == manager._network.send_server_messages.await_count

    @pytest.mark.asyncio
    async def test_untrackUser_lastAddUserFlag_shouldSendRemoveUser(self, manager: UserManager):
        user = manager.get_or_create_user('user0')
        user.status = UserStatus.ONLINE
        user.tracking_flags = TrackingFlag.FRIEND

        await manager.untrack_user('user0', TrackingFlag.FRIEND)

        assert user.status == UserStatus.UNKNOWN
        assert user.tracking_flags == TrackingFlag(0)
        manager._network.send_server_messages.assert_awaited_once_with(
            RemoveUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_untrackUser_lastAddUserFlag_shouldSendRemoveUserAndNotSetStatusUnknown(self, manager: UserManager):
        user = manager.get_or_create_user('user0')
        user.status = UserStatus.ONLINE
        user.tracking_flags = TrackingFlag.FRIEND | TrackingFlag.ROOM_USER

        await manager.untrack_user('user0', TrackingFlag.FRIEND)

        assert user.status == UserStatus.ONLINE
        assert user.tracking_flags == TrackingFlag.ROOM_USER
        manager._network.send_server_messages.assert_awaited_once_with(
            RemoveUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_untrackUser_addUserFlagRemains_shouldNotSendRemoveUser(self, manager: UserManager):
        user = manager.get_or_create_user('user0')
        user.tracking_flags = TrackingFlag.FRIEND | TrackingFlag.REQUESTED

        await manager.untrack_user('user0', TrackingFlag.FRIEND)

        assert user.tracking_flags == TrackingFlag.REQUESTED
        assert 0 == manager._network.send_server_messages.await_count

    @pytest.mark.asyncio
    async def test_onPrivateChatMessage_shouldSendAckAndEmitEvent(self, manager: UserManager):
        callback = AsyncMock()
        manager._event_bus.register(PrivateMessageEvent, callback)

        user = manager.get_or_create_user('user0')

        await manager._on_private_message(
            PrivateChatMessage.Response(
                chat_id=1,
                username='user0',
                message='hello',
                timestamp=100.0,
                is_admin=False
            ),
            manager._network.server
        )

        manager._network.send_server_messages.assert_awaited_once_with(
            PrivateChatMessageAck.Request(1)
        )
        message = ChatMessage(
            id=1,
            timestamp=100.0,
            user=user,
            message='hello',
            is_admin=False
        )
        callback.assert_awaited_once_with(PrivateMessageEvent(message))
