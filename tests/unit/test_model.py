from aioslsk.model import Room, User


class TestModel:

    def test_addUser_userExists_shouldNotAddUser(self):
        user = User(name='myuser')
        room = Room(name='myroom', users=[user])
        room.add_user(user)
        assert room.users == [user]

    def test_addUser_userDoesNotExist_shouldAddUser(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_user(user)
        assert room.users == [user]

    def test_removeUser_userExists_shouldRemoveUser(self):
        user = User(name='myuser')
        room = Room(name='myroom', users=[user])

        room.remove_user(user)
        assert [] == room.users

    def test_removeUser_userDoesNotExist_shouldDoNothing(self):
        user = User(name='myuser')
        room = Room(name='myroom')

        room.remove_user(user)

    def test_addOperator_operatorExists_shouldNotAddOperator(self):
        user = User(name='myuser')
        room = Room(name='myroom', operators=[user])
        room.add_operator(user)
        assert room.operators == [user]

    def test_addOperator_operatorDoesNotExist_shouldAddOperator(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.add_operator(user)
        assert room.operators == [user]

    def test_removeOperator_operatorExists_shouldRemoveOperator(self):
        user = User(name='myuser')
        room = Room(name='myroom')
        room.operators = [user]

        room.remove_operator(user)
        assert [] == room.operators

    def test_removeOperator_operatorDoesNotExist_shouldDoNothing(self):
        user = User(name='myuser')
        room = Room(name='myroom')

        room.remove_operator(user)
