import pytest
from aioslsk.user.model import ChatMessage, User


class TestModelChatMessage:

    @pytest.mark.parametrize('username,is_admin,expected', [
        ('user', False, False),
        ('user', True, False),
        ('server', False, False),
        ('server', True, True),
    ])
    def test_isServerMessage(self, username: str, is_admin: bool, expected: bool):
        user = User(username)
        message = ChatMessage(
            id=1,
            timestamp=1.0,
            message='a',
            is_admin=is_admin,
            user=user
        )
        assert message.is_server_message() is expected
