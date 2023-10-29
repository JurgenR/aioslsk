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

    def test_addOperator_operatorExists_shouldNotAdd(self):
        user = User(name='myuser')
        room = Room(name='myroom', operators=[user])
        room.add_operator(user)
        assert room.operators == [user]

    def test_addOperator_operatorDoesNotExist_shouldAdd(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_operator(user)
        assert room.operators == [user]

    def test_removeOperator_operatorExists_shouldRemove(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.operators = [user]

        room.remove_operator(user)
        assert [] == room.operators

    def test_removeOperator_operatorDoesNotExist_shouldDoNothing(self):
        user = User(name='myuser')
        room = Room(name='myroom')

        room.remove_operator(user)

    def test_addMember_memberExists_shouldNotAdd(self):
        user = User(name='myuser')
        room = Room(name='myroom', members=[user])
        room.add_member(user)
        assert room.members == [user]

    def test_addMember_memberDoesNotExist_shouldAdd(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_member(user)
        assert room.members == [user]

    def test_removeMember_memberExists_shouldRemove(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.members = [user]

        room.remove_member(user)
        assert [] == room.members

    def test_removeMember_memberDoesNotExist_shouldDoNothing(self):
        user = User(name='myuser')
        room = Room(name='myroom')

        room.remove_member(user)
