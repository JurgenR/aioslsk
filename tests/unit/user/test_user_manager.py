from aioslsk.events import (
    ConnectionStateChangedEvent,
    EventBus,
    PrivateMessageEvent,
    UserTrackingEvent,
    UserUntrackingEvent,
    UserTrackingStateChangedEvent,
)
from aioslsk.protocol.messages import (
    AddUser,
    PrivateChatMessage,
    PrivateChatMessageAck,
    RemoveUser,
)
from aioslsk.network.connection import ConnectionState, ServerConnection
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager, UserTrackingManager, TrackingState
from aioslsk.user.model import ChatMessage, User, TrackingFlag


import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, call, patch
import time
from typing import AsyncGenerator


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


@pytest_asyncio.fixture
async def tracking_manager() -> AsyncGenerator[UserTrackingManager, None]:
    event_bus = EventBus()
    network = AsyncMock()
    network.server = AsyncMock()

    tracking_manager = UserTrackingManager(
        Settings(**DEFAULT_SETTINGS),
        event_bus,
        network
    )

    try:
        yield tracking_manager
    finally:
        cancelled_tasks = tracking_manager.stop()
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)


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

    @pytest.mark.asyncio
    async def test_onPrivateChatMessage_shouldSendAckAndEmitEvent(self, manager: UserManager):
        callback = AsyncMock()
        manager._event_bus.register(PrivateMessageEvent, callback)

        user = manager.get_user_object(DEFAULT_USERNAME)

        raw_message = PrivateChatMessage.Response(
            chat_id=1,
            username=DEFAULT_USERNAME,
            message='hello',
            timestamp=100,
            is_direct=False
        )
        await manager._on_private_message(raw_message, manager._network.server)

        manager._network.send_server_messages.assert_awaited_once_with(
            PrivateChatMessageAck.Request(1)
        )
        message = ChatMessage(
            id=1,
            timestamp=100,
            user=user,
            message='hello',
            is_direct=False
        )
        callback.assert_awaited_once_with(
            PrivateMessageEvent(message=message, raw_message=raw_message))


class TestUserTrackingManager:

    async def wait_for_state(
            self, tracking_manager: UserTrackingManager, username: str, expected: TrackingState,
            timeout: float = 2.0, poll_interval: float = 0.01):

        start = time.monotonic()
        while True:
            state = tracking_manager.get_tracking_state(username)
            if state == expected:
                return state

            if time.monotonic() - start > timeout:
                raise AssertionError(
                    f"Timed out waiting for {username!r} to reach {expected}, current={state}"
                )

            await asyncio.sleep(poll_interval)

    def test_getTrackingState_doesNotExist(self, tracking_manager: UserTrackingManager):
        assert tracking_manager.get_tracking_state('user0') == TrackingState.UNTRACKED

    def test_getTrackingFlags_doesNotExist(self, tracking_manager: UserTrackingManager):
        assert tracking_manager.get_tracking_flags('user0') == TrackingFlag(0)

    @pytest.mark.asyncio
    async def test_trackUser(self, tracking_manager: UserTrackingManager):
        tracked_callback = AsyncMock()
        changed_callback = AsyncMock()
        tracking_manager._event_bus.register(UserTrackingEvent, tracked_callback)
        tracking_manager._event_bus.register(UserTrackingStateChangedEvent, changed_callback)

        tracking_manager._network.send_server_messages = AsyncMock()
        tracking_manager._network.wait_for_server_message = AsyncMock(
            side_effect=[
                AddUser.Response('user0', exists=True)
            ]
        )

        user = User('user0')

        tracking_manager.track_user(user, TrackingFlag.TRANSFER)

        await self.wait_for_state(tracking_manager, 'user0', TrackingState.TRACKED)

        changed_callback.assert_has_awaits([
            call(
                UserTrackingStateChangedEvent(
                    user,
                    TrackingState.TRACKED,
                    AddUser.Response('user0', exists=True)
                )
            )
        ])
        tracked_callback.assert_has_awaits([
            call(
                UserTrackingEvent(
                    user,
                    AddUser.Response('user0', exists=True)
                )
            )
        ])
        assert tracking_manager._network.send_server_messages.await_count == 1
        tracking_manager._network.send_server_messages.assert_awaited_once_with(
            AddUser.Request('user0')
        )

    @pytest.mark.asyncio
    async def test_trackUser_multipleFlags(self, tracking_manager: UserTrackingManager):
        tracked_callback = AsyncMock()
        changed_callback = AsyncMock()
        tracking_manager._event_bus.register(UserTrackingEvent, tracked_callback)
        tracking_manager._event_bus.register(UserTrackingStateChangedEvent, changed_callback)

        tracking_manager._network.send_server_messages = AsyncMock()
        tracking_manager._network.wait_for_server_message = AsyncMock(
            side_effect=[
                AddUser.Response('user0', exists=True)
            ]
        )

        user = User('user0')

        request_1 = tracking_manager.track_user(user, TrackingFlag.FRIEND)
        request_2 = tracking_manager.track_user(user, TrackingFlag.TRANSFER)

        await self.wait_for_state(tracking_manager, 'user0', TrackingState.TRACKED)

        await request_1.handled.wait()
        await request_2.handled.wait()

        changed_callback.assert_has_awaits([
            call(
                UserTrackingStateChangedEvent(
                    user,
                    TrackingState.TRACKED,
                    AddUser.Response('user0', exists=True)
                )
            )
        ])
        tracked_callback.assert_has_awaits([
            call(
                UserTrackingEvent(
                    user,
                    AddUser.Response('user0', exists=True)
                )
            )
        ])
        assert tracking_manager._network.send_server_messages.await_count == 1
        tracking_manager._network.send_server_messages.assert_awaited_once_with(
            AddUser.Request('user0')
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'request_effects,response_effects,retry_message',
        [
            (
                None,
                [
                    AddUser.Response('user0', exists=False),
                    AddUser.Response('user0', exists=True)
                ],
                AddUser.Response('user0', exists=False)
            ),
            (
                None,
                [
                    Exception,
                    AddUser.Response('user0', exists=True)
                ],
                None
            ),
            (
                None,
                [
                    TimeoutError,
                    AddUser.Response('user0', exists=True)
                ],
                None
            ),
            (
                [
                    Exception,
                    None
                ],
                [
                    AddUser.Response('user0', exists=True)
                ],
                None
            ),
        ]
    )
    async def test_trackUser_retryOnFailure(
            self, tracking_manager: UserTrackingManager,
            request_effects, response_effects, retry_message: AddUser.Response):

        actual_sleep = asyncio.sleep
        async def fast_sleep(duration: float):
            await actual_sleep(0)

        tracked_callback = AsyncMock()
        changed_callback = AsyncMock()
        tracking_manager._event_bus.register(UserTrackingEvent, tracked_callback)
        tracking_manager._event_bus.register(UserTrackingStateChangedEvent, changed_callback)

        tracking_manager._network.send_server_messages = AsyncMock(side_effect=request_effects)
        tracking_manager._network.wait_for_server_message = AsyncMock(
            side_effect=response_effects
        )

        user = User('user0')

        # Specifically patch the sleep from the module, otherwise the
        # `wait_for_state` function won't work
        with patch('aioslsk.user.manager.asyncio.sleep', side_effect=fast_sleep):
            tracking_manager.track_user(user, TrackingFlag.TRANSFER)

            await self.wait_for_state(tracking_manager, 'user0', TrackingState.TRACKED, timeout=2)

            changed_callback.assert_has_awaits([
                call(
                    UserTrackingStateChangedEvent(
                        user,
                        TrackingState.RETRY_PENDING,
                        retry_message
                    )
                ),
                call(
                    UserTrackingStateChangedEvent(
                        user,
                        TrackingState.TRACKED,
                        AddUser.Response('user0', exists=True)
                    )
                )
            ])
            tracked_callback.assert_has_awaits([
                call(
                    UserTrackingEvent(
                        user,
                        AddUser.Response('user0', exists=True)
                    )
                )
            ])
            assert tracking_manager._network.send_server_messages.await_count == 2

    @pytest.mark.asyncio
    async def test_untrackUser(self, tracking_manager: UserTrackingManager):
        untracked_callback = AsyncMock()
        changed_callback = AsyncMock()
        tracking_manager._event_bus.register(UserUntrackingEvent, untracked_callback)
        tracking_manager._event_bus.register(UserTrackingStateChangedEvent, changed_callback)

        tracking_manager._network.send_server_messages = AsyncMock()
        tracking_manager._network.wait_for_server_message = AsyncMock(
            side_effect=[
                AddUser.Response('user0', exists=True)
            ]
        )

        user = User('user0')

        tracking_manager.track_user(user, TrackingFlag.TRANSFER)
        await self.wait_for_state(tracking_manager, 'user0', TrackingState.TRACKED)

        tracking_manager.untrack_user(user, TrackingFlag.TRANSFER)
        await self.wait_for_state(tracking_manager, 'user0', TrackingState.UNTRACKED)

        changed_callback.assert_has_awaits([
            call(
                UserTrackingStateChangedEvent(
                    user,
                    TrackingState.TRACKED,
                    AddUser.Response('user0', exists=True)
                )
            ),
            call(
                UserTrackingStateChangedEvent(
                    user,
                    TrackingState.UNTRACKED
                )
            )
        ])
        untracked_callback.assert_has_awaits([
            call(UserUntrackingEvent(user))
        ])
        assert tracking_manager._network.send_server_messages.await_count == 2
        tracking_manager._network.send_server_messages.assert_has_awaits([
            call(AddUser.Request('user0')),
            call(RemoveUser.Request('user0'))
        ])

        assert 'user0' not in tracking_manager._tracked_users

    @pytest.mark.asyncio
    async def test_untrackUser_doesNotExist(self, tracking_manager: UserTrackingManager):

        user = User('user0')

        request = tracking_manager.untrack_user(user, TrackingFlag.TRANSFER)
        assert request is None

    @pytest.mark.asyncio
    async def test_untrackUser_retryPending_cancelRetry(self, tracking_manager: UserTrackingManager):

        untracked_callback = AsyncMock()
        changed_callback = AsyncMock()
        tracking_manager._event_bus.register(UserUntrackingEvent, untracked_callback)
        tracking_manager._event_bus.register(UserTrackingStateChangedEvent, changed_callback)

        tracking_manager._network.send_server_messages = AsyncMock()
        tracking_manager._network.wait_for_server_message = AsyncMock(
            side_effect=[
                AddUser.Response('user0', exists=False)
            ]
        )

        user = User('user0')

        tracking_manager.track_user(user, TrackingFlag.TRANSFER)

        await self.wait_for_state(tracking_manager, 'user0', TrackingState.RETRY_PENDING, timeout=2)

        tracking_manager.untrack_user(user, TrackingFlag.TRANSFER)

        await self.wait_for_state(tracking_manager, 'user0', TrackingState.UNTRACKED, timeout=2)

        changed_callback.assert_has_awaits([
            call(
                UserTrackingStateChangedEvent(
                    user,
                    TrackingState.RETRY_PENDING,
                    AddUser.Response('user0', exists=False)
                )
            ),
            call(
                UserTrackingStateChangedEvent(
                    user,
                    TrackingState.UNTRACKED
                )
            )
        ])
        untracked_callback.assert_has_awaits([
            call(
                UserUntrackingEvent(
                    user
                )
            )
        ])
        assert tracking_manager._network.send_server_messages.await_count == 2

    @pytest.mark.asyncio
    async def test_serverDisconnect(self, tracking_manager: UserTrackingManager):

        tracking_manager._network.send_server_messages = AsyncMock()
        tracking_manager._network.wait_for_server_message = AsyncMock(
            side_effect=[
                AddUser.Response('user0', exists=True)
            ]
        )

        user = User('user0')

        tracking_manager.track_user(user, TrackingFlag.TRANSFER)

        await self.wait_for_state(tracking_manager, 'user0', TrackingState.TRACKED, timeout=2)

        await tracking_manager._event_bus.emit(
            ConnectionStateChangedEvent(
                ServerConnection('1.1.1.1', 1234, AsyncMock()),
                ConnectionState.CLOSED
            )
        )

        assert tracking_manager._tracked_users == {}
