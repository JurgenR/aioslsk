from pyslsk.model import Room, User


class TestModel:

    def test_whenAddUserToRoomAndUserExists_shouldNotAddUser(self):
        user = User(name='myuser')
        room = Room(name='myroom', users=[user])
        room.add_user(user)
        assert room.users == [user]

    def test_whenAddUserToRoomAndUserDoesNotExist_shouldAddUser(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_user(user)
        assert room.users == [user]

    def test_whenAddOperatorToRoomAndOperatorExists_shouldNotAddOperator(self):
        user = User(name='myuser')
        room = Room(name='myroom', operators=[user])
        room.add_operator(user)
        assert room.operators == [user]

    def test_whenAddOperatorToRoomAndOperatorDoesNotExist_shouldAddOperator(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_operator(user)
        assert room.operators == [user]
