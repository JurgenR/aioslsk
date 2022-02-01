import inspect


def on_message(message_class):
    def register(event_func):
        try:
            event_func._registered_messages.add(message_class)
        except AttributeError:
            event_func._registered_messages = set([message_class, ])
        return event_func

    return register


def get_listener_methods(obj, message_class):
    methods = inspect.getmembers(obj, predicate=inspect.ismethod)
    listening_methods = []
    for _, method in methods:
        if message_class in getattr(method, '_registered_messages', []):
            listening_methods.append(method)
    return listening_methods


def on_connection_state(state, close_reason=None):
    pass
