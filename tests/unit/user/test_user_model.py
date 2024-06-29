import pytest
from aioslsk.user.model import ChatMessage, User


class TestModelChatMessage:

    def test_isServerMessage(self):
        user = User('server')
        message = ChatMessage(
            id=1,
            timestamp=1.0,
            message='a',
            is_direct=True,
            user=user
        )
        assert message.is_server_message() is True
