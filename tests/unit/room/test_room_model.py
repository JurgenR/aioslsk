import pytest
from aioslsk.room.model import Room
from aioslsk.user.model import User


class TestModelRoom:

    def test_addUser_userExists_shouldNotAdd(self):
        user = User(name='myuser')
        room = Room(name='myroom', users=[user])
        room.add_user(user)
        assert room.users == [user]

    def test_addUser_userDoesNotExist_shouldAdd(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_user(user)
        assert room.users == [user]

    def test_removeUser_userExists_shouldRemove(self):
        user = User(name='myuser')
        room = Room(name='myroom', users=[user])

        room.remove_user(user)
        assert [] == room.users

    def test_removeUser_userDoesNotExist_shouldDoNothing(self):
        user = User(name='myuser')
        room = Room(name='myroom')

        room.remove_user(user)
