from aioslsk.model import Room, User
from aioslsk.state import State


class TestState:

    def test_whenMissingUser_shouldCreateAndReturnUser(self):
        state = State()
        username = 'myuser'

        user = state.get_or_create_user(username)
        assert isinstance(user, User)
        assert username == user.name
        assert username in state.users

    def test_whenExistingUser_shouldReturnUser(self):
        state = State()
        username = 'myuser'
        user = User(name=username)
        state.users[username] = user

        assert user == state.get_or_create_user(username)

    def test_whenMissingRoom_shouldCreateAndReturnRoom(self):
        state = State()
        room_name = 'myroom'

        room = state.get_or_create_room(room_name)
        assert isinstance(room, Room)
        assert room_name == room.name
        assert room_name in state.rooms

    def test_whenExistingRoom_shouldReturnRoom(self):
        state = State()
        room_name = 'myuser'
        user = Room(name=room_name)
        state.rooms[room_name] = user

        assert user == state.get_or_create_room(room_name)
