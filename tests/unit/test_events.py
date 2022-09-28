from pyslsk.events import on_message, EventBus, UserAddEvent
from pyslsk.messages import Login, Ping
from pyslsk.model import User

from unittest.mock import create_autospec


def listener1(event: UserAddEvent):
    pass


def listener2(event: UserAddEvent):
    pass


class DummyMessageListener:

    @on_message(Ping)
    def on_ping(self):
        pass


class TestFunctions:

    pass


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

    def test_whenEmitNoListenersRegister_shouldNotRaise(self):
        bus = EventBus()

        bus.emit(UserAddEvent(User("test")))

    def test_whenEmit_shouldEmitToListeners(self):
        bus = EventBus()

        mock_listener1 = create_autospec(listener1)
        mock_listener2 = create_autospec(listener2)
        bus.register(UserAddEvent, mock_listener1)
        bus.register(UserAddEvent, mock_listener2)

        event = UserAddEvent(User("test"))

        bus.emit(event)

        mock_listener1.assert_called_once_with(event)
        mock_listener2.assert_called_once_with(event)

    def test_whenEmitAndListenerRaises_shouldContinue(self):
        bus = EventBus()

        mock_listener1 = create_autospec(listener1, side_effect=ValueError('error'))
        mock_listener2 = create_autospec(listener2)
        bus.register(UserAddEvent, mock_listener1)
        bus.register(UserAddEvent, mock_listener2)

        event = UserAddEvent(User("test"))

        bus.emit(event)

        mock_listener1.assert_called_once_with(event)
        mock_listener2.assert_called_once_with(event)
