from email import message
from re import L
from urllib.parse import uses_relative
from pyslsk.messages import (
    AcceptChildren,
    AddUser,
    BranchLevel,
    BranchRoot,
    CannotConnect,
    ChatAckPrivateMessage,
    ChatJoinRoom,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatPrivateMessage,
    ChatRoomMessage,
    ChatRoomSearch,
    ChatRoomTickerSet,
    ChildDepth,
    ConnectToPeer,
    FileSearch,
    FileSearchEx,
    GetPeerAddress,
    GetUserStats,
    GetUserStatus,
    GivePrivileges,
    HaveNoParent,
    ItemRecommendations,
    Login,
    NewPassword,
    ParentIP,
    Ping,
    PrivateRoomAddOperator,
    PrivateRoomAddUser,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
    PrivateRoomRemoveOperator,
    PrivateRoomRemoveUser,
    PrivateRoomToggle,
    PrivilegesNotification,
    RemoveUser,
    RoomList,
    SendUploadSpeed,
    SetListenPort,
    SetStatus,
    SharedFoldersFiles,
    UserSearch,
    WishlistSearch,
)
class TestServerMessages:

    def test_create_Login(self):
        message = Login.create(username='user', password='password', client_version=200, minor_version=123)
        assert message.hex() == '440000000100000004000000757365720800000070617373776f7264c80000002000000064343430616564313839613133666639373064616337653765386639383762327b000000'

    def test_create_NewPassword(self):
        message = NewPassword.create('password')
        assert message.hex() == '100000008e0000000800000070617373776f7264'

    def test_create_SetListenPort_withoutObfuscated(self):
        message = SetListenPort.create(port=1234)
        assert message.hex() == '1000000002000000d20400000000000000000000'

    def test_create_SetListenPort_withObfuscated(self):
        message = SetListenPort.create(port=1234, obfuscated_port=12345)
        assert message.hex() == '1000000002000000d20400000100000039300000'

    def test_create_SetStatus(self):
        message = SetStatus.create(1)
        assert message.hex() == '080000001c00000001000000'

    def test_create_SendUploadSpeed(self):
        message = SendUploadSpeed.create(12345678)
        assert message.hex() == '08000000790000004e61bc00'

    def test_create_SharedFoldersFiles(self):
        message = SharedFoldersFiles.create(10, 20)
        assert message.hex() == '0c000000230000000a00000014000000'

    def test_create_UserSearch(self):
        message = UserSearch.create('user', 1234, 'query')
        assert message.hex() == '190000002a0000000400000075736572d2040000050000007175657279'

    def test_create_BranchLevel(self):
        message = BranchLevel.create(4)
        assert message.hex() == '080000007e00000004000000'

    def test_create_BranchRoot(self):
        message = BranchRoot.create('user')
        assert message.hex() == '0c0000007f0000000400000075736572'

    def test_create_ChildDepth(self):
        message = ChildDepth.create(5)
        assert message.hex() == '080000008100000005000000'

    def test_create_HaveNoParent(self):
        message = HaveNoParent.create(True)
        assert message.hex() == '050000004700000001'

    def test_create_ParentIP(self):
        message = ParentIP.create('123.123.123.123')
        assert message.hex() == '08000000490000007b7b7b7b'

    def test_create_AcceptChildren(self):
        message = AcceptChildren.create(True)
        assert message.hex() == '050000006400000001'

    def test_create_ItemRecommendations(self):
        message = ItemRecommendations.create('recommendation')
        assert message.hex() == '160000006f0000000e0000007265636f6d6d656e646174696f6e'

    def test_create_Ping(self):
        message = Ping.create()
        assert message.hex() == '0400000020000000'

    def test_create_AddUser(self):
        message = AddUser.create('user')
        assert message.hex() == '0c000000050000000400000075736572'

    def test_create_RemoveUser(self):
        message = RemoveUser.create('user')
        assert message.hex() == '0c000000060000000400000075736572'

    def test_create_CannotConnect(self):
        message = CannotConnect.create(123, 'user')
        assert message.hex() == '10000000e90300007b0000000400000075736572'

    def test_create_RoomList(self):
        message = RoomList.create()
        assert message.hex() == '0400000040000000'

    def test_create_GetPeerAddress(self):
        message = GetPeerAddress.create('user')
        assert message.hex() == '0c000000030000000400000075736572'

    def test_create_ConnectToPeer(self):
        message = ConnectToPeer.create(ticket=1234, username='user', typ='F')
        assert message.hex() == '1500000012000000d204000004000000757365720100000046'

    def test_create_GetUserStats(self):
        message = GetUserStats.create('user')
        assert message.hex() == '0c000000240000000400000075736572'

    def test_create_GetUserStatus(self):
        message = GetUserStatus.create('user')
        assert message.hex() == '0c000000070000000400000075736572'

    def test_create_ChatRoomMessage(self):
        message = ChatRoomMessage.create('room', 'my message')
        assert message.hex() == '1a0000000d00000004000000726f6f6d0a0000006d79206d657373616765'

    def test_create_ChatPrivateMessage(self):
        message = ChatPrivateMessage.create(username='user', message='hello there')
        assert message.hex() == '1b0000001600000004000000757365720b00000068656c6c6f207468657265'

    def test_create_ChatAckPrivateMessage(self):
        message = ChatAckPrivateMessage.create(chat_id=1234)
        assert message.hex() == '0800000017000000d2040000'

    def test_create_ChatJoinRoom(self):
        message = ChatJoinRoom.create('room')
        assert message.hex() == '0c0000000e00000004000000726f6f6d'

    def test_create_ChatLeaveRoom(self):
        message = ChatLeaveRoom.create('room')
        assert message.hex() == '0c0000000f00000004000000726f6f6d'

    def test_create_ChatRoomTickerAdd(self):
        message = ChatRoomTickerSet.create('room', 'hello there')
        assert message.hex() == '1b0000007400000004000000726f6f6d0b00000068656c6c6f207468657265'

    def test_create_PrivateRoomAddUser(self):
        message = PrivateRoomAddUser.create('room', 'user')
        assert message.hex() == '140000008600000004000000726f6f6d0400000075736572'

    def test_create_PrivateRoomRemoveUser(self):
        message = PrivateRoomRemoveUser.create('room', 'user')
        assert message.hex() == '140000008700000004000000726f6f6d0400000075736572'

    def test_create_PrivateRoomDropMembership(self):
        message = PrivateRoomDropMembership.create('room')
        assert message.hex() == '0c0000008700000004000000726f6f6d'

    def test_create_PrivateRoomDropOwnership(self):
        message = PrivateRoomDropOwnership.create('room')
        assert message.hex() == '0c0000008800000004000000726f6f6d'

    def test_create_PrivateRoomAddOperator(self):
        message = PrivateRoomAddOperator.create('room', 'user')
        assert message.hex() == '140000008f00000004000000726f6f6d0400000075736572'

    def test_create_PrivateRoomRemoveOperator(self):
        message = PrivateRoomRemoveOperator.create('room', 'user')
        assert message.hex() == '140000009000000004000000726f6f6d0400000075736572'

    def test_create_PrivateRoomToggle(self):
        message = PrivateRoomToggle.create(True)
        assert message.hex() == '050000008d00000001'

    def test_create_GivePrivileges(self):
        message = GivePrivileges.create('user', 7)
        assert message.hex() == '100000007b000000040000007573657207000000'

    def test_create_PrivilegesNotification(self):
        message = PrivilegesNotification.create(1234, 'user')
        assert message.hex() == '100000007c000000d20400000400000075736572'

    def test_create_ChatRoomSearch(self):
        message = ChatRoomSearch.create('room', 1234, 'query')
        assert message.hex() == '190000007800000004000000726f6f6dd2040000050000007175657279'

    def test_create_FileSearchEx(self):
        message = FileSearchEx.create('query')
        assert message.hex() == '0d00000099000000050000007175657279'

    def test_create_FileSearch(self):
        message = FileSearch.create(1234, 'query')
        assert message.hex() == '110000001a000000d2040000050000007175657279'

    def test_create_WishlistSearch(self):
        message = WishlistSearch.create(1234, 'query')
        assert message.hex() == '1100000067000000d2040000050000007175657279'
