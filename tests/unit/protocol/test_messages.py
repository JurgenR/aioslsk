from pyslsk.protocol.primitives import (
    calc_md5,
    PotentialParent,
    ItemRecommendation,
    SimilarUser,
    RoomTicker,
)
from pyslsk.protocol.messages import (
    Login,
    SetListenPort,
    GetPeerAddress,
    AddUser,
    RemoveUser,
    GetUserStatus,
    ChatRoomMessage,
    ChatLeaveRoom,
    ChatJoinRoom,
    ChatUserLeftRoom,
    GetUserStats,
    ConnectToPeer,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
    FileSearch,
    SetStatus,
    Ping,
    SharedFolderFiles,
    UserSearch,
    RoomList,
    PrivilegedUsers,
    ToggleParentSearch,
    ParentIP,
    ParentMinSpeed,
    ParentSpeedRatio,
    SearchInactivityTimeout,
    MinParentsInCache,
    DistributedAliveInterval,
    AddPrivilegedUser,
    CheckPrivileges,
    ServerSearchRequest,
    AcceptChildren,
    PotentialParents,
    WishlistSearch,
    WishlistInterval,
    GetSimilarUsers,
    GetItemRecommendations,
    ChatRoomTickers,
    ChatRoomTickerAdded,
    ChatRoomTickerRemoved,
    ChatRoomTickerSet,
    ChatRoomSearch,
    SendUploadSpeed,
    GetUserPrivileges,
    GiveUserPrivileges,
    PrivilegesNotification,
    PrivilegesNotificationAck,
)


class TestLogin:
    REQ_MESSAGE = Login.Request(
        username='Test',
        password='Test1234',
        client_version=10,
        password_md5=calc_md5('Test1234'),
        minor_version=123
    )
    REQ_MESSAGE_BYTES = bytes.fromhex("440000000100000004000000546573740800000054657374313233340a0000002000000032633933343163613463663364383762396534656239303564366133656334357b000000")

    def test_Login_Request(self):
        assert self.REQ_MESSAGE.serialize() == self.REQ_MESSAGE_BYTES

    def test_Login_Request(self):
        assert Login.Request.deserialize(self.REQ_MESSAGE_BYTES) == self.REQ_MESSAGE

    def test_Login_Response_serialize_successful(self):
        message = Login.Response(
            success=True,
            greeting="Hello",
            ip='1.2.3.4',
            md5hash=calc_md5('Test1234'),
            unknown=0
        )

    def test_Login_Response_serialize_unsuccessful(self):
        message = Login.Response(
            success=False,
            reason="INVALIDPASS"
        )
        assert message.serialize() == bytes.fromhex("1400000001000000000b000000494e56414c494450415353")

    def test_Login_Response_deserialize_successful(self):
        pass

    def test_Login_Response_deserialize_unsuccessful(self):
        obj = Login.Response.deserialize(
            bytes.fromhex("1400000001000000000b000000494e56414c494450415353")
        )
        assert obj == Login.Response(
            success=False,
            reason="INVALIDPASS"
        )


class TestSetListenPort:

    def test_SetListenPort_Request_serialize_withoutObfuscatedPorts(self):
        message = SetListenPort.Request(1234)
        data = bytes.fromhex('0800000002000000d2040000')
        assert message.serialize() == data

    def test_SetListenPort_Request_deserialize_withoutObfuscatedPorts(self):
        message = SetListenPort.Request(1234)
        data = bytes.fromhex('0800000002000000d2040000')
        assert SetListenPort.Request.deserialize(data) == message

    def test_SetListenPort_Request_serialize_withObfuscatedPorts(self):
        message = SetListenPort.Request(1234, obfuscated_ports=[1235])
        data = bytes.fromhex('1000000002000000d204000001000000d3040000')
        assert message.serialize() == data

    def test_SetListenPort_Request_deserialize_withObfuscatedPorts(self):
        message = SetListenPort.Request(1234, obfuscated_ports=[1235])
        data = bytes.fromhex('1000000002000000d204000001000000d3040000')
        assert SetListenPort.Request.deserialize(data) == message


class TestGetPeerAddress:

    def test_GetPeerAddress_Request_serialize(self):
        message = GetPeerAddress.Request('user0')
        data = bytes.fromhex('0d00000003000000050000007573657230')
        assert message.serialize() == data

    def test_GetPeerAddress_Request_deserialize(self):
        message = GetPeerAddress.Request('user0')
        data = bytes.fromhex('0d00000003000000050000007573657230')
        assert GetPeerAddress.Request.deserialize(data) == message

    # Response
    def test_GetPeerAddress_Response_serialize_withoutObfuscatedPorts(self):
        message = GetPeerAddress.Response(
            username='user0',
            ip='1.2.3.4',
            port=1234
        )
        data = bytes.fromhex('150000000300000005000000757365723004030201d2040000')
        assert message.serialize() == data

    def test_GetPeerAddress_Response_deserialize_withoutObfuscatedPorts(self):
        message = GetPeerAddress.Response(
            username='user0',
            ip='1.2.3.4',
            port=1234
        )
        data = bytes.fromhex('150000000300000005000000757365723004030201d2040000')
        assert GetPeerAddress.Response.deserialize(data) == message

    def test_GetPeerAddress_Response_serialize_withObfuscatedPorts(self):
        message = GetPeerAddress.Response(
            username='user0',
            ip='1.2.3.4',
            port=1234,
            obfuscated_ports=[1235]
        )
        data = bytes.fromhex('1b0000000300000005000000757365723004030201d204000001000000d304')
        assert message.serialize() == data

    def test_GetPeerAddress_Response_deserialize_withObfuscatedPorts(self):
        message = GetPeerAddress.Response(
            username='user0',
            ip='1.2.3.4',
            port=1234,
            obfuscated_ports=[1235]
        )
        data = bytes.fromhex('1b0000000300000005000000757365723004030201d204000001000000d304')
        assert GetPeerAddress.Response.deserialize(data) == message


class TestAddUser:

    def test_AddUser_Request_serialize(self):
        message = AddUser.Request('user0')
        data = bytes.fromhex('0d00000005000000050000007573657230')
        assert message.serialize() == data

    def test_AddUser_Request_deserialize(self):
        message = AddUser.Request('user0')
        data = bytes.fromhex('0d00000005000000050000007573657230')
        assert AddUser.Request.deserialize(data) == message

    # Response
    def test_AddUser_Response_serialize_existsWithoutCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            avg_speed=100,
            download_num=1000,
            file_count=10000,
            dir_count=100000
        )
        data = bytes.fromhex('2600000005000000050000007573657230010100000064000000e80300000000000010270000a0860100')
        assert message.serialize() == data

    def test_AddUser_Response_deserialize_existsWithoutCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            avg_speed=100,
            download_num=1000,
            file_count=10000,
            dir_count=100000
        )
        data = bytes.fromhex('2600000005000000050000007573657230010100000064000000e80300000000000010270000a0860100')
        assert AddUser.Response.deserialize(data) == message

    def test_AddUser_Response_serialize_existsWithCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            avg_speed=100,
            download_num=1000,
            file_count=10000,
            dir_count=100000,
            country_code='DE'
        )
        data = bytes.fromhex('2c00000005000000050000007573657230010100000064000000e80300000000000010270000a0860100020000004445')
        assert message.serialize() == data

    def test_AddUser_Response_deserialize_existsWithCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            avg_speed=100,
            download_num=1000,
            file_count=10000,
            dir_count=100000,
            country_code='DE'
        )
        data = bytes.fromhex('2c00000005000000050000007573657230010100000064000000e80300000000000010270000a0860100020000004445')
        assert AddUser.Response.deserialize(data) == message


class TestRemoveUser:

    def test_RemoveUser_Request_serialize(self):
        message = RemoveUser.Request('user0')
        data = bytes.fromhex('0d00000006000000050000007573657230')
        assert message.serialize() == data

    def test_RemoveUser_Request_deserialize(self):
        message = RemoveUser.Request('user0')
        data = bytes.fromhex('0d00000006000000050000007573657230')
        assert RemoveUser.Request.deserialize(data) == message


class TestGetUserStatus:

    def test_GetUserStatus_Request_serialize(self):
        message = GetUserStatus.Request('user0')
        data = bytes.fromhex('0d00000007000000050000007573657230')
        assert message.serialize() == data

    def test_GetUserStatus_Request_deserialize(self):
        message = GetUserStatus.Request('user0')
        data = bytes.fromhex('0d00000007000000050000007573657230')
        assert GetUserStatus.Request.deserialize(data) == message

    def test_GetUserStatus_Response_serialize(self):
        message = GetUserStatus.Response(
            username='user0',
            status=2,
            privileged=1
        )
        data = bytes.fromhex('12000000070000000500000075736572300200000001')
        assert message.serialize() == data

    def test_GetUserStatus_Response_deserialize(self):
        message = GetUserStatus.Response(
            username='user0',
            status=2,
            privileged=1
        )
        data = bytes.fromhex('12000000070000000500000075736572300200000001')
        assert GetUserStatus.Response.deserialize(data) == message


class TestChatRoomMessage:

    def test_ChatRoomMessage_Request_serialize(self):
        message = ChatRoomMessage.Request(
            room='room0',
            username='user0',
            message="Hello"
        )
        data = bytes.fromhex('1f0000000d00000005000000726f6f6d300500000075736572300500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatRoomMessage_Request_deserialize(self):
        message = ChatRoomMessage.Request(
            room='room0',
            username='user0',
            message="Hello"
        )
        data = bytes.fromhex('1f0000000d00000005000000726f6f6d300500000075736572300500000048656c6c6f')
        assert ChatRoomMessage.Request.deserialize(data) == message


class TestChatJoinRoom:
    pass


class TestChatLeaveRoom:

    def test_ChatLeaveRoom_Request_serialize(self):
        message = ChatLeaveRoom.Request('room0')
        data = bytes.fromhex('0d0000000f00000005000000726f6f6d30')
        assert message.serialize() == data

    def test_ChatLeaveRoom_Request_deserialize(self):
        message = ChatLeaveRoom.Request('room0')
        data = bytes.fromhex('0d0000000f00000005000000726f6f6d30')
        assert ChatLeaveRoom.Request.deserialize(data) == message

    def test_ChatLeaveRoom_Response_serialize(self):
        message = ChatLeaveRoom.Response('room0')
        data = bytes.fromhex('0d0000000f00000005000000726f6f6d30')
        assert message.serialize() == data

    def test_ChatLeaveRoom_Response_deserialize(self):
        message = ChatLeaveRoom.Response('room0')
        data = bytes.fromhex('0d0000000f00000005000000726f6f6d30')
        assert ChatLeaveRoom.Response.deserialize(data) == message


class TestUserJoinedRoom:

    pass


class TestChatUserLeftRoom:

    def test_ChatUserLeftRoom_Response_serialize(self):
        message = ChatUserLeftRoom.Response('room0', 'user0')
        data = bytes.fromhex('160000001100000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_ChatUserLeftRoom_Response_deserialize(self):
        message = ChatUserLeftRoom.Response('room0', 'user0')
        data = bytes.fromhex('160000001100000005000000726f6f6d30050000007573657230')
        assert ChatUserLeftRoom.Response.deserialize(data) == message


class TestConnectToPeer:

    def test_ConnectToPeer_Request_serialize(self):
        message = ConnectToPeer.Request(
            ticket=1234,
            username='user0',
            typ='P'
        )
        data = bytes.fromhex('1600000012000000d20400000500000075736572300100000050')
        assert message.serialize() == data

    def test_ConnectToPeer_Request_deserialize(self):
        message = ConnectToPeer.Request(
            ticket=1234,
            username='user0',
            typ='P'
        )
        data = bytes.fromhex('1600000012000000d20400000500000075736572300100000050')
        assert ConnectToPeer.Request.deserialize(data) == message

    def test_ConnectToPeer_Response_serialize_withoutObfuscatedPort(self):
        message = ConnectToPeer.Response(
            username='user0',
            typ='P',
            ip='1.2.3.4',
            port=1234,
            ticket=1000,
            privileged=True
        )
        data = bytes.fromhex('1f00000012000000050000007573657230010000005004030201d2040000e803000001')
        assert message.serialize() == data

    def test_ConnectToPeer_Response_deserialize_withoutObfuscatedPort(self):
        message = ConnectToPeer.Response(
            username='user0',
            typ='P',
            ip='1.2.3.4',
            port=1234,
            ticket=1000,
            privileged=True
        )
        data = bytes.fromhex('1f00000012000000050000007573657230010000005004030201d2040000e803000001')
        assert ConnectToPeer.Response.deserialize(data) == message

    def test_ConnectToPeer_Response_serialize_emptyObfuscatedPort(self):
        message = ConnectToPeer.Response(
            username='user0',
            typ='P',
            ip='1.2.3.4',
            port=1234,
            ticket=1000,
            privileged=True,
            obfuscated_port_amount=0,
            obfuscated_port=0
        )
        data = bytes.fromhex('2700000012000000050000007573657230010000005004030201d2040000e8030000010000000000000000')
        assert message.serialize() == data

    def test_ConnectToPeer_Response_deserialize_emptyObfuscatedPort(self):
        message = ConnectToPeer.Response(
            username='user0',
            typ='P',
            ip='1.2.3.4',
            port=1234,
            ticket=1000,
            privileged=True,
            obfuscated_port_amount=0,
            obfuscated_port=0
        )
        data = bytes.fromhex('2700000012000000050000007573657230010000005004030201d2040000e8030000010000000000000000')
        assert ConnectToPeer.Response.deserialize(data) == message

    def test_ConnectToPeer_Response_serialize_withObfuscatedPort(self):
        message = ConnectToPeer.Response(
            username='user0',
            typ='P',
            ip='1.2.3.4',
            port=1234,
            ticket=1000,
            privileged=True,
            obfuscated_port_amount=1,
            obfuscated_port=1235
        )
        data = bytes.fromhex('2700000012000000050000007573657230010000005004030201d2040000e80300000101000000d3040000')
        assert message.serialize() == data

    def test_ConnectToPeer_Response_deserialize_withObfuscatedPort(self):
        message = ConnectToPeer.Response(
            username='user0',
            typ='P',
            ip='1.2.3.4',
            port=1234,
            ticket=1000,
            privileged=True,
            obfuscated_port_amount=1,
            obfuscated_port=1235
        )
        data = bytes.fromhex('2700000012000000050000007573657230010000005004030201d2040000e80300000101000000d3040000')
        assert ConnectToPeer.Response.deserialize(data) == message


class TestChatPrivateMessage:

    def test_ChatPrivateMessage_Request_serialize(self):
        message = ChatPrivateMessage.Request(
            username='user0',
            message='Hello'
        )
        data = bytes.fromhex('16000000160000000500000075736572300500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatPrivateMessage_Request_deserialize(self):
        message = ChatPrivateMessage.Request(
            username='user0',
            message='Hello'
        )
        data = bytes.fromhex('16000000160000000500000075736572300500000048656c6c6f')
        assert ChatPrivateMessage.Request.deserialize(data) == message

    def test_ChatPrivateMessage_Response_serialize_withoutIsAdmin(self):
        message = ChatPrivateMessage.Response(
            chat_id=123456,
            timestamp=1666606341,
            username='user0',
            message='Hello',
            is_admin=None
        )
        data = bytes.fromhex('1e0000001600000040e20100056556630500000075736572300500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatPrivateMessage_Response_deserialize_withoutIsAdmin(self):
        # is_admin has default of false
        message = ChatPrivateMessage.Response(
            chat_id=123456,
            timestamp=1666606341,
            username='user0',
            message='Hello',
            is_admin=False
        )
        data = bytes.fromhex('1e0000001600000040e20100056556630500000075736572300500000048656c6c6f')
        assert ChatPrivateMessage.Response.deserialize(data) == message

    def test_ChatPrivateMessage_Response_serialize_withIsAdmin(self):
        message = ChatPrivateMessage.Response(
            chat_id=123456,
            timestamp=1666606341,
            username='user0',
            message='Hello',
            is_admin=True
        )
        data = bytes.fromhex('1f0000001600000040e20100056556630500000075736572300500000048656c6c6f01')
        assert message.serialize() == data

    def test_ChatPrivateMessage_Response_deserialize_withIsAdmin(self):
        message = ChatPrivateMessage.Response(
            chat_id=123456,
            timestamp=1666606341,
            username='user0',
            message='Hello',
            is_admin=True
        )
        data = bytes.fromhex('1f0000001600000040e20100056556630500000075736572300500000048656c6c6f01')
        assert ChatPrivateMessage.Response.deserialize(data) == message


class TestChatAckPrivateMessage:

    def test_ChatAckPrivateMessage_Request_serialize(self):
        message = ChatAckPrivateMessage.Request(1234)
        data = bytes.fromhex('0800000017000000d2040000')
        assert message.serialize() == data

    def test_ChatAckPrivateMessage_Request_deserialize(self):
        message = ChatAckPrivateMessage.Request(1234)
        data = bytes.fromhex('0800000017000000d2040000')
        assert ChatAckPrivateMessage.Request.deserialize(data) == message


class TestFileSearch:

    def test_FileSearch_Request_serialize(self):
        message = FileSearch.Request(
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('110000001a000000d2040000050000005175657279')
        assert message.serialize() == data

    def test_FileSearch_Request_deserialize(self):
        message = FileSearch.Request(
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('110000001a000000d2040000050000005175657279')
        assert FileSearch.Request.deserialize(data) == message

    def test_FileSearch_Response_serialize(self):
        message = FileSearch.Response(
            username='user0',
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1a0000001a000000050000007573657230d2040000050000005175657279')
        assert message.serialize() == data

    def test_FileSearch_Response_deserialize(self):
        message = FileSearch.Response(
            username='user0',
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1a0000001a000000050000007573657230d2040000050000005175657279')
        assert FileSearch.Response.deserialize(data) == message


class TestSetStatus:

    def test_SetStatus_Request_serialize(self):
        message = SetStatus.Request(2)
        data = bytes.fromhex('080000001c00000002000000')
        assert message.serialize() == data

    def test_SetStatus_Request_deserialize(self):
        message = SetStatus.Request(2)
        data = bytes.fromhex('080000001c00000002000000')
        assert SetStatus.Request.deserialize(data) == message


class TestPing:

    def test_Ping_Request_serialize(self):
        message = Ping.Request()
        data = bytes.fromhex('0400000020000000')
        assert message.serialize() == data

    def test_Ping_Request_deserialize(self):
        message = Ping.Request()
        data = bytes.fromhex('0400000020000000')
        assert Ping.Request.deserialize(data) == message


class TestSharedFolderFiles:

    def test_SharedFolderFiles_Request_serialize(self):
        message = SharedFolderFiles.Request(
            dir_count=1000,
            file_count=10000
        )
        data = bytes.fromhex('0c00000020000000e803000010270000')
        assert message.serialize() == data

    def test_SharedFolderFiles_Request_deserialize(self):
        message = SharedFolderFiles.Request(
            dir_count=1000,
            file_count=10000
        )
        data = bytes.fromhex('0c00000020000000e803000010270000')
        assert SharedFolderFiles.Request.deserialize(data) == message


class TestGetUserStats:

    def test_GetUserStats_Request_serialize(self):
        message = GetUserStats.Request('user0')
        data = bytes.fromhex('0d00000024000000050000007573657230')
        assert message.serialize() == data

    def test_GetUserStats_Request_deserialize(self):
        message = GetUserStats.Request('user0')
        data = bytes.fromhex('0d00000024000000050000007573657230')
        assert GetUserStats.Request.deserialize(data) == message

    def test_GetUserStats_Response_serialize(self):
        message = GetUserStats.Response(
            username='user0',
            avg_speed=100000,
            download_num=1000000,
            file_count=10000,
            dir_count=1000
        )
        data = bytes.fromhex('2100000024000000050000007573657230a086010040420f000000000010270000e8030000')
        assert message.serialize() == data

    def test_GetUserStats_Response_deserialize(self):
        message = GetUserStats.Response(
            username='user0',
            avg_speed=100000,
            download_num=1000000,
            file_count=10000,
            dir_count=1000
        )
        data = bytes.fromhex('2100000024000000050000007573657230a086010040420f000000000010270000e8030000')
        assert GetUserStats.Response.deserialize(data) == message


class TestUserSearch:

    def test_UserSearch_Request_serialize(self):
        message = UserSearch.Request(
            username='user0',
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1a0000002a000000050000007573657230d2040000050000005175657279')
        assert message.serialize() == data

    def test_UserSearch_Request_deserialize(self):
        message = UserSearch.Request(
            username='user0',
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1a0000002a000000050000007573657230d2040000050000005175657279')
        assert UserSearch.Request.deserialize(data) == message


class TestRoomList:

    def test_RoomList_Request_serialize(self):
        message = RoomList.Request()
        data = bytes.fromhex('0400000040000000')
        assert message.serialize() == data

    def test_RoomList_Request_deserialize(self):
        message = RoomList.Request()
        data = bytes.fromhex('0400000040000000')
        assert RoomList.Request.deserialize(data) == message

    # TODO: Response tests

class TestPrivilegedUsers:

    def test_PrivilegedUsers_Response_serialize(self):
        message = PrivilegedUsers.Response(users=['user0', 'user1'])
        data = bytes.fromhex('1a0000004500000002000000050000007573657230050000007573657231')
        assert message.serialize() == data

    def test_PrivilegedUsers_Response_deserialize(self):
        message = PrivilegedUsers.Response(users=['user0', 'user1'])
        data = bytes.fromhex('1a0000004500000002000000050000007573657230050000007573657231')
        assert PrivilegedUsers.Response.deserialize(data) == message


class TestToggleParentSearch:

    def test_ToggleParentSearch_Request_serialize(self):
        message = ToggleParentSearch.Request(True)
        data = bytes.fromhex('050000004700000001')
        assert message.serialize() == data

    def test_ToggleParentSearch_Request_deserialize(self):
        message = ToggleParentSearch.Request(True)
        data = bytes.fromhex('050000004700000001')
        assert ToggleParentSearch.Request.deserialize(data) == message


class TestParentIP:

    def test_ParentIP_Request_serialize(self):
        message = ParentIP.Request('1.2.3.4')
        data = bytes.fromhex('080000004900000004030201')
        assert message.serialize() == data

    def test_ParentIP_Request_deserialize(self):
        message = ParentIP.Request('1.2.3.4')
        data = bytes.fromhex('080000004900000004030201')
        assert ParentIP.Request.deserialize(data) == message


class TestParentMinSpeed:

    def test_ParentMinSpeed_Response_serialize(self):
        message = ParentMinSpeed.Response(1000)
        data = bytes.fromhex('0800000053000000e8030000')
        assert message.serialize() == data

    def test_ParentMinSpeed_Response_deserialize(self):
        message = ParentMinSpeed.Response(1000)
        data = bytes.fromhex('0800000053000000e8030000')
        assert ParentMinSpeed.Response.deserialize(data) == message


class TestParentSpeedRatio:

    def test_ParentSpeedRatio_Response_serialize(self):
        message = ParentSpeedRatio.Response(1000)
        data = bytes.fromhex('0800000054000000e8030000')
        assert message.serialize() == data

    def test_ParentSpeedRatio_Response_deserialize(self):
        message = ParentSpeedRatio.Response(1000)
        data = bytes.fromhex('0800000054000000e8030000')
        assert ParentSpeedRatio.Response.deserialize(data) == message


class TestSearchInactivityTimeout:

    def test_SearchInactivityTimeout_Response_serialize(self):
        message = SearchInactivityTimeout.Response(1000)
        data = bytes.fromhex('0800000057000000e8030000')
        assert message.serialize() == data

    def test_SearchInactivityTimeout_Response_deserialize(self):
        message = SearchInactivityTimeout.Response(1000)
        data = bytes.fromhex('0800000057000000e8030000')
        assert SearchInactivityTimeout.Response.deserialize(data) == message


class TestMinParentsInCache:

    def test_MinParentsInCache_Response_serialize(self):
        message = MinParentsInCache.Response(1000)
        data = bytes.fromhex('0800000058000000e8030000')
        assert message.serialize() == data

    def test_MinParentsInCache_Response_deserialize(self):
        message = MinParentsInCache.Response(1000)
        data = bytes.fromhex('0800000058000000e8030000')
        assert MinParentsInCache.Response.deserialize(data) == message


class TestDistributedAliveInterval:

    def test_DistributedAliveInterval_Response_serialize(self):
        message = DistributedAliveInterval.Response(1000)
        data = bytes.fromhex('080000005a000000e8030000')
        assert message.serialize() == data

    def test_DistributedAliveInterval_Response_deserialize(self):
        message = DistributedAliveInterval.Response(1000)
        data = bytes.fromhex('080000005a000000e8030000')
        assert DistributedAliveInterval.Response.deserialize(data) == message


class TestAddPrivilegedUser:

    def test_AddPrivilegedUser_Response_serialize(self):
        message = AddPrivilegedUser.Response('user0')
        data = bytes.fromhex('0d0000005b000000050000007573657230')
        assert message.serialize() == data

    def test_AddPrivilegedUser_Response_deserialize(self):
        message = AddPrivilegedUser.Response('user0')
        data = bytes.fromhex('0d0000005b000000050000007573657230')
        assert AddPrivilegedUser.Response.deserialize(data) == message


class TestCheckPrivileges:

    def test_CheckPrivileges_Request_serialize(self):
        message = CheckPrivileges.Request()
        data = bytes.fromhex('040000005c000000')
        assert message.serialize() == data

    def test_CheckPrivileges_Request_deserialize(self):
        message = CheckPrivileges.Request()
        data = bytes.fromhex('040000005c000000')
        assert CheckPrivileges.Request.deserialize(data) == message

    def test_CheckPrivileges_Response_serialize(self):
        message = CheckPrivileges.Response(1000)
        data = bytes.fromhex('080000005c000000e8030000')
        assert message.serialize() == data

    def test_CheckPrivileges_Response_deserialize(self):
        message = CheckPrivileges.Response(1000)
        data = bytes.fromhex('080000005c000000e8030000')
        assert CheckPrivileges.Response.deserialize(data) == message


class TestServerSearchRequest:

    def test_ServerSearchRequest_Response_serialize(self):
        message = ServerSearchRequest.Response(
            distributed_code=3,
            unknown=0,
            username='user0',
            ticket=1234,
            query='Query'
        )
        data = bytes.fromhex('1f0000005d0000000300000000050000007573657230d2040000050000005175657279')
        assert message.serialize() == data

    def test_ServerSearchRequest_Response_deserialize(self):
        message = ServerSearchRequest.Response(
            distributed_code=3,
            unknown=0,
            username='user0',
            ticket=1234,
            query='Query'
        )
        data = bytes.fromhex('1f0000005d0000000300000000050000007573657230d2040000050000005175657279')
        assert ServerSearchRequest.Response.deserialize(data) == message


class TestAcceptChildren:

    def test_AcceptChildren_Request_serialize(self):
        message = AcceptChildren.Request(True)
        data = bytes.fromhex('050000006400000001')
        assert message.serialize() == data

    def test_AcceptChildren_Request_deserialize(self):
        message = AcceptChildren.Request(True)
        data = bytes.fromhex('050000006400000001')
        assert AcceptChildren.Request.deserialize(data) == message


class TestPotentialParents:

    def test_PotentialParents_Response_serialize(self):
        message = PotentialParents.Response(
            entries=[
                PotentialParent(
                    username='user0',
                    ip='1.2.3.4',
                    port=1234
                ),
                PotentialParent(
                    username='user1',
                    ip='1.2.3.5',
                    port=1235
                )
            ]
        )
        data = bytes.fromhex('2a000000660000000200000005000000757365723004030201d204000005000000757365723105030201d3040000')
        assert message.serialize() == data

    def test_PotentialParents_Response_deserialize(self):
        message = PotentialParents.Response(
            entries=[
                PotentialParent(
                    username='user0',
                    ip='1.2.3.4',
                    port=1234
                ),
                PotentialParent(
                    username='user1',
                    ip='1.2.3.5',
                    port=1235
                )
            ]
        )
        data = bytes.fromhex('2a000000660000000200000005000000757365723004030201d204000005000000757365723105030201d3040000')
        assert PotentialParents.Response.deserialize(data) == message


class TestWishlistSearch:

    def test_WishlistSearch_Request_serialize(self):
        message = WishlistSearch.Request(
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1100000067000000d2040000050000005175657279')
        assert message.serialize() == data

    def test_WishlistSearch_Request_deserialize(self):
        message = WishlistSearch.Request(
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1100000067000000d2040000050000005175657279')
        assert WishlistSearch.Request.deserialize(data) == message


class TestWishlistInterval:

    def test_WishlistInterval_Response_serialize(self):
        message = WishlistInterval.Response(1000)
        data = bytes.fromhex('0800000068000000e8030000')
        assert message.serialize() == data

    def test_WishlistInterval_Response_deserialize(self):
        message = WishlistInterval.Response(1000)
        data = bytes.fromhex('0800000068000000e8030000')
        assert WishlistInterval.Response.deserialize(data) == message


class TestGetSimilarUsers:

    def test_GetSimilarUsers_Request_serialize(self):
        message = GetSimilarUsers.Request()
        data = bytes.fromhex('040000006e000000')
        assert message.serialize() == data

    def test_GetSimilarUsers_Request_deserialize(self):
        message = GetSimilarUsers.Request()
        data = bytes.fromhex('040000006e000000')
        assert GetSimilarUsers.Request.deserialize(data) == message

    def test_GetSimilarUsers_Response_serialize(self):
        message = GetSimilarUsers.Response(
            users=[
                SimilarUser('user0', 1),
                SimilarUser('user1', 2)
            ]
        )
        data = bytes.fromhex('220000006e000000020000000500000075736572300100000005000000757365723102000000')
        assert message.serialize() == data

    def test_GetSimilarUsers_Response_deserialize(self):
        message = GetSimilarUsers.Response(
            users=[
                SimilarUser('user0', 1),
                SimilarUser('user1', 2)
            ]
        )
        data = bytes.fromhex('220000006e000000020000000500000075736572300100000005000000757365723102000000')
        assert GetSimilarUsers.Response.deserialize(data) == message


class TestGetItemRecommendations:

    def test_GetItemRecommendations_Request_serialize(self):
        message = GetItemRecommendations.Request('recommendation0')
        data = bytes.fromhex('170000006f0000000f0000007265636f6d6d656e646174696f6e30')
        assert message.serialize() == data

    def test_GetItemRecommendations_Request_deserialize(self):
        message = GetItemRecommendations.Request('recommendation0')
        data = bytes.fromhex('170000006f0000000f0000007265636f6d6d656e646174696f6e30')
        assert GetItemRecommendations.Request.deserialize(data) == message

    def test_GetItemRecommendations_Response_serialize(self):
        message = GetItemRecommendations.Response(
            recommendations=[
                ItemRecommendation('recommendation0', 1),
                ItemRecommendation('recommendation1', 2)
            ]
        )
        data = bytes.fromhex('360000006f000000020000000f0000007265636f6d6d656e646174696f6e30010000000f0000007265636f6d6d656e646174696f6e3102000000')
        assert message.serialize() == data

    def test_GetItemRecommendations_Response_deserialize(self):
        message = GetItemRecommendations.Response(
            recommendations=[
                ItemRecommendation('recommendation0', 1),
                ItemRecommendation('recommendation1', 2)
            ]
        )
        data = bytes.fromhex('360000006f000000020000000f0000007265636f6d6d656e646174696f6e30010000000f0000007265636f6d6d656e646174696f6e3102000000')
        assert GetItemRecommendations.Response.deserialize(data) == message


class TestChatRoomTickers:

    def test_ChatRoomTickers_Response_serialize(self):
        message = ChatRoomTickers.Response(
            room='room0',
            tickers=[
                RoomTicker('user0', 'ticker0'),
                RoomTicker('user1', 'ticker1')
            ]
        )
        data = bytes.fromhex('390000007100000005000000726f6f6d3002000000050000007573657230070000007469636b657230050000007573657231070000007469636b657231')
        assert message.serialize() == data

    def test_ChatRoomTickers_Response_deserialize(self):
        message = ChatRoomTickers.Response(
            room='room0',
            tickers=[
                RoomTicker('user0', 'ticker0'),
                RoomTicker('user1', 'ticker1')
            ]
        )
        data = bytes.fromhex('390000007100000005000000726f6f6d3002000000050000007573657230070000007469636b657230050000007573657231070000007469636b657231')
        assert ChatRoomTickers.Response.deserialize(data) == message


class TestChatRoomTickerAdded:

    def test_ChatRoomTickerAdded_Response_serialize(self):
        message = ChatRoomTickerAdded.Response(
            room='room0',
            username='user0',
            ticker='ticker0'
        )
        data = bytes.fromhex('210000007200000005000000726f6f6d30050000007573657230070000007469636b657230')
        assert message.serialize() == data

    def test_ChatRoomTickerAdded_Response_deserialize(self):
        message = ChatRoomTickerAdded.Response(
            room='room0',
            username='user0',
            ticker='ticker0'
        )
        data = bytes.fromhex('210000007200000005000000726f6f6d30050000007573657230070000007469636b657230')
        assert ChatRoomTickerAdded.Response.deserialize(data) == message


class TestChatRoomTickerRemoved:

    def test_ChatRoomTickerRemoved_Response_serialize(self):
        message = ChatRoomTickerRemoved.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000007300000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_ChatRoomTickerRemoved_Response_deserialize(self):
        message = ChatRoomTickerRemoved.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000007300000005000000726f6f6d30050000007573657230')
        assert ChatRoomTickerRemoved.Response.deserialize(data) == message


class TestChatRoomTickerSet:

    def test_ChatRoomTickerSet_Request_serialize(self):
        message = ChatRoomTickerSet.Request(
            room='room0',
            ticker='ticker0'
        )
        data = bytes.fromhex('180000007400000005000000726f6f6d30070000007469636b657230')
        assert message.serialize() == data

    def test_ChatRoomTickerSet_Request_deserialize(self):
        message = ChatRoomTickerSet.Request(
            room='room0',
            ticker='ticker0'
        )
        data = bytes.fromhex('180000007400000005000000726f6f6d30070000007469636b657230')
        assert ChatRoomTickerSet.Request.deserialize(data) == message


class TestChatRoomSearch:

    def test_ChatRoomSearch_Request_serialize(self):
        message = ChatRoomSearch.Request(
            room='room0',
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1a0000007800000005000000726f6f6d30d2040000050000005175657279')
        assert message.serialize() == data

    def test_ChatRoomSearch_Request_deserialize(self):
        message = ChatRoomSearch.Request(
            room='room0',
            ticket=1234,
            query="Query"
        )
        data = bytes.fromhex('1a0000007800000005000000726f6f6d30d2040000050000005175657279')
        assert ChatRoomSearch.Request.deserialize(data) == message


class TestSendUploadSpeed:

    def test_SendUploadSpeed_Request_serialize(self):
        message = SendUploadSpeed.Request(1000)
        data = bytes.fromhex('0800000079000000e8030000')
        assert message.serialize() == data

    def test_SendUploadSpeed_Request_deserialize(self):
        message = SendUploadSpeed.Request(1000)
        data = bytes.fromhex('0800000079000000e8030000')
        assert SendUploadSpeed.Request.deserialize(data) == message


class TestGetUserPrivileges:

    def test_GetUserPrivileges_Request_serialize(self):
        message = GetUserPrivileges.Request('user0')
        data = bytes.fromhex('0d0000007a000000050000007573657230')
        assert message.serialize() == data

    def test_GetUserPrivileges_Request_deserialize(self):
        message = GetUserPrivileges.Request('user0')
        data = bytes.fromhex('0d0000007a000000050000007573657230')
        assert GetUserPrivileges.Request.deserialize(data) == message

    def test_GetUserPrivileges_Response_serialize(self):
        message = GetUserPrivileges.Response('user0', True)
        data = bytes.fromhex('0e0000007a00000005000000757365723001')
        assert message.serialize() == data

    def test_GetUserPrivileges_Response_deserialize(self):
        message = GetUserPrivileges.Response('user0', True)
        data = bytes.fromhex('0e0000007a00000005000000757365723001')
        assert GetUserPrivileges.Response.deserialize(data) == message


class TestGiveUserPrivileges:

    def test_GiveUserPrivileges_Request_serialize(self):
        message = GiveUserPrivileges.Request(
            username='user0',
            days=1000
        )
        data = bytes.fromhex('110000007b000000050000007573657230e8030000')
        assert message.serialize() == data

    def test_GiveUserPrivileges_Request_deserialize(self):
        message = GiveUserPrivileges.Request(
            username='user0',
            days=1000
        )
        data = bytes.fromhex('110000007b000000050000007573657230e8030000')
        assert GiveUserPrivileges.Request.deserialize(data) == message


class TestPrivilegesNotification:

    def test_PrivilegesNotification_Request_serialize(self):
        message = PrivilegesNotification.Request(
            notification_id=1000,
            username='user0'
        )
        data = bytes.fromhex('110000007c000000e8030000050000007573657230')
        assert message.serialize() == data

    def test_PrivilegesNotification_Request_deserialize(self):
        message = PrivilegesNotification.Request(
            notification_id=1000,
            username='user0'
        )
        data = bytes.fromhex('110000007c000000e8030000050000007573657230')
        assert PrivilegesNotification.Request.deserialize(data) == message


class TestPrivilegesNotificationAck:

    def test_PrivilegesNotificationAck_Request_serialize(self):
        message = PrivilegesNotificationAck.Request(1000)
        data = bytes.fromhex('080000007d000000e8030000')
        assert message.serialize() == data

    def test_PrivilegesNotificationAck_Request_deserialize(self):
        message = PrivilegesNotificationAck.Request(1000)
        data = bytes.fromhex('080000007d000000e8030000')
        assert PrivilegesNotificationAck.Request.deserialize(data) == message
