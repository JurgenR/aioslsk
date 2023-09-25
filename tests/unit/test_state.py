from aioslsk.model import Room, User, UserStatus, TrackingFlag
from aioslsk.state import State


class TestState:

    def test_getOrCreateUser_missingUserByName_shouldCreateAndReturnUser(self):
        state = State()
        username = 'myuser'

        user = state.get_or_create_user(username)
        assert isinstance(user, User)
        assert username == user.name
        assert username in state.users

    def test_getOrCreateUser_existingUserByName_shouldReturnUser(self):
        state = State()
        username = 'myuser'
        user = User(name=username)
        state.users[username] = user

        assert user == state.get_or_create_user(username)

    def test_getOrCreateUser_missingUserByObject_shouldCreateAndReturnUser(self):
        state = State()
        original = User('user0')

        user = state.get_or_create_user(original)

        assert user == original
        assert state.users == {'user0': user}

    def test_getOrCreateUser_existingUserByObject_shouldReturnUser(self):
        state = State()
        original = User('user0')
        state.users = {'user0': original}

        user = state.get_or_create_user(original)

        assert user == original
        assert state.users == {'user0': original}

    def test_getOrCreateUser_existingUserByName_shouldReturnUser(self):
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

    def test_getJoinedRooms(self):
        state = State()
        room0 = state.get_or_create_room('room0')
        room0.joined = True
        state.get_or_create_room('room1')

        rooms = state.get_joined_rooms()

        assert rooms == [room0]

    def test_resetUsersAndRooms(self):
        state = State()
        user0 = state.get_or_create_user('user0')
        user0.status = UserStatus.ONLINE
        user0.tracking_flags = TrackingFlag.FRIEND

        user1 = state.get_or_create_user('user1')
        room = state.get_or_create_room('room0')
        room.add_user(user1)

        state.reset_users_and_rooms()

        assert user0.status == UserStatus.UNKNOWN
        assert user0.tracking_flags == TrackingFlag(0)

        assert len(room.users) == 0
