from pyslsk.events import build_message_map, on_message, EventBus, UserAddEvent
from pyslsk.model import User
from pyslsk.protocol.messages import Login, AddUser

import pytest
from unittest.mock import create_autospec


def listener1(event: UserAddEvent):
    pass


def listener2(event: UserAddEvent):
    pass


async def async_listener(event: UserAddEvent):
    pass


class DummyClass:

    @on_message(Login.Response)
    def login(self):
        pass

    @on_message(AddUser.Response)
    def add_user(self):
        pass


class TestFunctions:

    def test_decoratorOnMessage_shouldRegisterMessageClass(self):
        def my_test_func():
            pass

        on_message(Login.Response)(my_test_func)

        assert my_test_func._registered_message == Login.Response

    def test_buildMessageMap(self):
        dummy_obj = DummyClass()
        msg_map = build_message_map(dummy_obj)
        assert msg_map == {
            Login.Response: dummy_obj.login,
            AddUser.Response: dummy_obj.add_user
        }


class TestEventBus:

    def test_whenRegisterNonExistingEvent_shouldAddListener(self):
        bus = EventBus()

        bus.register(UserAddEvent, listener1)

        assert bus._events[UserAddEvent] == [listener1, ]

    def test_whenRegisterExistingEvent_shouldAddListener(self):
        bus = EventBus()

        bus.register(UserAddEvent, listener1)
        bus.register(UserAddEvent, listener2)

        assert bus._events[UserAddEvent] == [listener1, listener2, ]

    @pytest.mark.asyncio
    async def test_whenEmitNoListenersRegister_shouldNotRaise(self):
        bus = EventBus()

        await bus.emit(UserAddEvent(User("test")))

    @pytest.mark.asyncio
    async def test_whenEmit_shouldEmitToListeners(self):
        bus = EventBus()

        mock_listener1 = create_autospec(listener1)
        mock_listener2 = create_autospec(listener2)
        bus.register(UserAddEvent, mock_listener1)
        bus.register(UserAddEvent, mock_listener2)

        event = UserAddEvent(User("test"))

        await bus.emit(event)

        mock_listener1.assert_called_once_with(event)
        mock_listener2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_whenEmit_withAsyncListener_shouldEmitToListeners(self):
        bus = EventBus()

        mock_listener1 = create_autospec(async_listener)
        bus.register(UserAddEvent, mock_listener1)

        event = UserAddEvent(User("test"))

        await bus.emit(event)

        mock_listener1.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_whenEmitAndListenerRaises_shouldContinue(self):
        bus = EventBus()

        mock_listener1 = create_autospec(listener1, side_effect=ValueError('error'))
        mock_listener2 = create_autospec(listener2)
        bus.register(UserAddEvent, mock_listener1)
        bus.register(UserAddEvent, mock_listener2)

        event = UserAddEvent(User("test"))

        await bus.emit(event)

        mock_listener1.assert_called_once_with(event)
        mock_listener2.assert_called_once_with(event)
