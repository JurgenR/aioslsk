from collections.abc import Collection
import logging
from typing import Union
from .exceptions import AioSlskException
from .protocol.primitives import MessageDataclass
from .protocol import messages


def resolve(message_class: str) -> type[MessageDataclass]:
    message_root, req_resp = message_class.split('.')

    if root_message := getattr(messages, message_root, None):
        if req_resp_message := getattr(root_message, req_resp, None):
            return req_resp_message
        else:
            raise AioSlskException(
                f"could not resolve message with name : {req_resp} : {message_class}")
    else:
        raise AioSlskException(
            f"could not resolve message with name : {message_root} : {message_class}")


class MessageFilter(logging.Filter):
    """Logging filter for protocol messages"""

    def __init__(self, message_types: Collection[Union[type[MessageDataclass], str]]):
        super().__init__()
        converted = []
        for message_type in message_types:
            if isinstance(message_type, str):
                mtype = resolve(message_type)
            else:
                mtype = message_type
            converted.append(mtype)

        self.message_types: Collection[type[MessageDataclass]] = converted

    def filter(self, record: logging.LogRecord) -> bool:
        if message_type := getattr(record, 'message_type', None):
            return message_type not in self.message_types

        return True


class DistributedSearchMessageFilter(MessageFilter):
    """Logging filter that filters out any distributed search request messages
    """

    TYPES = (
        messages.ServerSearchRequest.Response,
        messages.DistributedSearchRequest.Request,
        messages.DistributedServerSearchRequest.Request,
    )

    def __init__(self):  # pragma: no cover
        super().__init__(self.TYPES)


class ConnectionLoggerAdapter(logging.LoggerAdapter):

    def process(self, msg, kwargs):
        if 'extra' in kwargs:
            extra = kwargs['extra']
            infos = [
                f"{extra['hostname']}:{extra['port']}"
            ]

            if 'connection_type' in extra:
                infos.append(extra['connection_type'])

            if 'username' in extra:
                infos.append(extra['username'] or 'N/A')

            return f"[{'|'.join(infos)}] {msg}", kwargs

        return super().process(msg, kwargs)
