from pyslsk.events import EventBus, PrivateMessageEvent


def listener1():
    pass


def listener2():
    pass


class TestEventBus:

    def test_whenRegisterNonExistingEvent_shouldAddListener(self):
        bus = EventBus()

        bus.register(PrivateMessageEvent, listener1)

        assert bus._events[PrivateMessageEvent] == [listener1, ]


    def test_whenRegisterExistingEvent_shouldAddListener(self):
        bus = EventBus()

        bus.register(PrivateMessageEvent, listener1)
        bus.register(PrivateMessageEvent, listener2)

        assert bus._events[PrivateMessageEvent] == [listener1, listener2, ]
