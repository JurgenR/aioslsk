from pyslsk.protocol.primitives import (
    calc_md5,
    DirectoryData,
    FileData,
    Attribute,
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
    ParentInactivityTimeout,
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
    BranchLevel,
    BranchRoot,
    ChildDepth,
    PrivateRoomUsers,
    PrivateRoomAddUser,
    PrivateRoomRemoveUser,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
    PrivateRoomAdded,
    PrivateRoomRemoved,
    TogglePrivateRooms,
    NewPassword,
    PrivateRoomAddOperator,
    PrivateRoomRemoveOperator,
    PrivateRoomOperatorAdded,
    PrivateRoomOperatorRemoved,
    PrivateRoomOperators,
    ChatMessageUsers,
    ChatEnablePublic,
    ChatDisablePublic,
    ChatPublicMessage,
    FileSearchEx,
    CannotConnect,
    PeerPierceFirewall,
    PeerInit,
    PeerSharesRequest,
    PeerSharesReply,
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


class TestParentInactivityTimeout:

    def test_ParentInactivityTimeout_Response_serialize(self):
        message = ParentInactivityTimeout.Response(1000)
        data = bytes.fromhex('0800000056000000e8030000')
        assert message.serialize() == data

    def test_ParentInactivityTimeout_Response_deserialize(self):
        message = ParentInactivityTimeout.Response(1000)
        data = bytes.fromhex('0800000056000000e8030000')
        assert ParentInactivityTimeout.Response.deserialize(data) == message


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


class TestBranchLevel:

    def test_BranchLevel_Request_serialize(self):
        message = BranchLevel.Request(5)
        data = bytes.fromhex('080000007e00000005000000')
        assert message.serialize() == data

    def test_BranchLevel_Request_deserialize(self):
        message = BranchLevel.Request(5)
        data = bytes.fromhex('080000007e00000005000000')
        assert BranchLevel.Request.deserialize(data) == message


class TestBranchRoot:

    def test_BranchRoot_Request_serialize(self):
        message = BranchRoot.Request('user0')
        data = bytes.fromhex('0d0000007f000000050000007573657230')
        assert message.serialize() == data

    def test_BranchRoot_Request_deserialize(self):
        message = BranchRoot.Request('user0')
        data = bytes.fromhex('0d0000007f000000050000007573657230')
        assert BranchRoot.Request.deserialize(data) == message


class TestChildDepth:

    def test_ChildDepth_Request_serialize(self):
        message = ChildDepth.Request(5)
        data = bytes.fromhex('080000008100000005000000')
        assert message.serialize() == data

    def test_ChildDepth_Request_deserialize(self):
        message = ChildDepth.Request(5)
        data = bytes.fromhex('080000008100000005000000')
        assert ChildDepth.Request.deserialize(data) == message


class TestPrivateRoomUsers:

    def test_PrivateRoomUsers_Request_serialize(self):
        message = PrivateRoomUsers.Request(
            room='room0',
            usernames=['user0', 'user1']
        )
        data = bytes.fromhex('230000008500000005000000726f6f6d3002000000050000007573657230050000007573657231')
        assert message.serialize() == data

    def test_PrivateRoomUsers_Request_deserialize(self):
        message = PrivateRoomUsers.Request(
            room='room0',
            usernames=['user0', 'user1']
        )
        data = bytes.fromhex('230000008500000005000000726f6f6d3002000000050000007573657230050000007573657231')
        assert PrivateRoomUsers.Request.deserialize(data) == message


class TestPrivateRoomAddUser:

    def test_PrivateRoomAddUser_Request_serialize(self):
        message = PrivateRoomAddUser.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008600000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomAddUser_Request_deserialize(self):
        message = PrivateRoomAddUser.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008600000005000000726f6f6d30050000007573657230')
        assert PrivateRoomAddUser.Request.deserialize(data) == message

    def test_PrivateRoomAddUser_Response_serialize(self):
        message = PrivateRoomAddUser.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008600000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomAddUser_Response_deserialize(self):
        message = PrivateRoomAddUser.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008600000005000000726f6f6d30050000007573657230')
        assert PrivateRoomAddUser.Response.deserialize(data) == message


class TestPrivateRoomRemoveUser:

    def test_PrivateRoomRemoveUser_Request_serialize(self):
        message = PrivateRoomRemoveUser.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008700000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomRemoveUser_Request_deserialize(self):
        message = PrivateRoomRemoveUser.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008700000005000000726f6f6d30050000007573657230')
        assert PrivateRoomRemoveUser.Request.deserialize(data) == message

    def test_PrivateRoomRemoveUser_Response_serialize(self):
        message = PrivateRoomRemoveUser.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008700000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomRemoveUser_Response_deserialize(self):
        message = PrivateRoomRemoveUser.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008700000005000000726f6f6d30050000007573657230')
        assert PrivateRoomRemoveUser.Response.deserialize(data) == message


class TestPrivateRoomDropMembership:

    def test_PrivateRoomDropMembership_Request_serialize(self):
        message = PrivateRoomDropMembership.Request('room0')
        data = bytes.fromhex('0d0000008800000005000000726f6f6d30')
        assert message.serialize() == data

    def test_PrivateRoomDropMembership_Request_deserialize(self):
        message = PrivateRoomDropMembership.Request('room0')
        data = bytes.fromhex('0d0000008800000005000000726f6f6d30')
        assert PrivateRoomDropMembership.Request.deserialize(data) == message


class TestPrivateRoomDropOwnership:

    def test_PrivateRoomDropOwnership_Request_serialize(self):
        message = PrivateRoomDropOwnership.Request('room0')
        data = bytes.fromhex('0d0000008900000005000000726f6f6d30')
        assert message.serialize() == data

    def test_PrivateRoomDropOwnership_Request_deserialize(self):
        message = PrivateRoomDropOwnership.Request('room0')
        data = bytes.fromhex('0d0000008900000005000000726f6f6d30')
        assert PrivateRoomDropOwnership.Request.deserialize(data) == message


class TestPrivateRoomAdded:

    def test_PrivateRoomAdded_Response_serialize(self):
        message = PrivateRoomAdded.Response('room0')
        data = bytes.fromhex('0d0000008b00000005000000726f6f6d30')
        assert message.serialize() == data

    def test_PrivateRoomAdded_Response_deserialize(self):
        message = PrivateRoomAdded.Response('room0')
        data = bytes.fromhex('0d0000008b00000005000000726f6f6d30')
        assert PrivateRoomAdded.Response.deserialize(data) == message


class TestPrivateRoomRemoved:

    def test_PrivateRoomRemoved_Response_serialize(self):
        message = PrivateRoomRemoved.Response('room0')
        data = bytes.fromhex('0d0000008c00000005000000726f6f6d30')
        assert message.serialize() == data

    def test_PrivateRoomRemoved_Response_deserialize(self):
        message = PrivateRoomRemoved.Response('room0')
        data = bytes.fromhex('0d0000008c00000005000000726f6f6d30')
        assert PrivateRoomRemoved.Response.deserialize(data) == message


class TestTogglePrivateRooms:

    def test_TogglePrivateRooms_Request_serialize(self):
        message = TogglePrivateRooms.Request(True)
        data = bytes.fromhex('050000008d00000001')
        assert message.serialize() == data

    def test_TogglePrivateRooms_Request_deserialize(self):
        message = TogglePrivateRooms.Request(True)
        data = bytes.fromhex('050000008d00000001')
        assert TogglePrivateRooms.Request.deserialize(data) == message


class TestNewPassword:

    def test_NewPassword_Request_serialize(self):
        message = NewPassword.Request('password0')
        data = bytes.fromhex('110000008e0000000900000070617373776f726430')
        assert message.serialize() == data

    def test_NewPassword_Request_deserialize(self):
        message = NewPassword.Request('password0')
        data = bytes.fromhex('110000008e0000000900000070617373776f726430')
        assert NewPassword.Request.deserialize(data) == message


class TestPrivateRoomAddOperator:

    def test_PrivateRoomAddOperator_Request_serialize(self):
        message = PrivateRoomAddOperator.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008f00000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomAddOperator_Request_deserialize(self):
        message = PrivateRoomAddOperator.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008f00000005000000726f6f6d30050000007573657230')
        assert PrivateRoomAddOperator.Request.deserialize(data) == message

    def test_PrivateRoomAddOperator_Response_serialize(self):
        message = PrivateRoomAddOperator.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008f00000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomAddOperator_Response_deserialize(self):
        message = PrivateRoomAddOperator.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000008f00000005000000726f6f6d30050000007573657230')
        assert PrivateRoomAddOperator.Response.deserialize(data) == message


class TestPrivateRoomRemoveOperator:

    def test_PrivateRoomRemoveOperator_Request_serialize(self):
        message = PrivateRoomRemoveOperator.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000009000000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomRemoveOperator_Request_deserialize(self):
        message = PrivateRoomRemoveOperator.Request(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000009000000005000000726f6f6d30050000007573657230')
        assert PrivateRoomRemoveOperator.Request.deserialize(data) == message

    def test_PrivateRoomRemoveOperator_Response_serialize(self):
        message = PrivateRoomRemoveOperator.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000009000000005000000726f6f6d30050000007573657230')
        assert message.serialize() == data

    def test_PrivateRoomRemoveOperator_Response_deserialize(self):
        message = PrivateRoomRemoveOperator.Response(
            room='room0',
            username='user0'
        )
        data = bytes.fromhex('160000009000000005000000726f6f6d30050000007573657230')
        assert PrivateRoomRemoveOperator.Response.deserialize(data) == message


class TestPrivateRoomOperatorAdded:

    def test_PrivateRoomOperatorAdded_Response_serialize(self):
        message = PrivateRoomOperatorAdded.Response('room0')
        data = bytes.fromhex('0d0000009100000005000000726f6f6d30')
        assert message.serialize() == data

    def test_PrivateRoomOperatorAdded_Response_deserialize(self):
        message = PrivateRoomOperatorAdded.Response('room0')
        data = bytes.fromhex('0d0000009100000005000000726f6f6d30')
        assert PrivateRoomOperatorAdded.Response.deserialize(data) == message


class TestPrivateRoomOperatorRemoved:

    def test_PrivateRoomOperatorRemoved_Response_serialize(self):
        message = PrivateRoomOperatorRemoved.Response('room0')
        data = bytes.fromhex('0d0000009200000005000000726f6f6d30')
        assert message.serialize() == data

    def test_PrivateRoomOperatorRemoved_Response_deserialize(self):
        message = PrivateRoomOperatorRemoved.Response('room0')
        data = bytes.fromhex('0d0000009200000005000000726f6f6d30')
        assert PrivateRoomOperatorRemoved.Response.deserialize(data) == message


class TestPrivateRoomOperators:

    def test_PrivateRoomOperators_Response_serialize(self):
        message = PrivateRoomOperators.Response(
            room='room0',
            usernames=['user0', 'user1']
        )
        data = bytes.fromhex('230000009400000005000000726f6f6d3002000000050000007573657230050000007573657231')
        assert message.serialize() == data

    def test_PrivateRoomOperators_Response_deserialize(self):
        message = PrivateRoomOperators.Response(
            room='room0',
            usernames=['user0', 'user1']
        )
        data = bytes.fromhex('230000009400000005000000726f6f6d3002000000050000007573657230050000007573657231')
        assert PrivateRoomOperators.Response.deserialize(data) == message


class TestChatMessageUsers:

    def test_ChatMessageUsers_Request_serialize(self):
        message = ChatMessageUsers.Request(
            usernames=['user0', 'user1'],
            message="Hello"
        )
        data = bytes.fromhex('2300000095000000020000000500000075736572300500000075736572310500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatMessageUsers_Request_deserialize(self):
        message = ChatMessageUsers.Request(
            usernames=['user0', 'user1'],
            message="Hello"
        )
        data = bytes.fromhex('2300000095000000020000000500000075736572300500000075736572310500000048656c6c6f')
        assert ChatMessageUsers.Request.deserialize(data) == message


class TestChatEnablePublic:

    def test_ChatEnablePublic_Request_serialize(self):
        message = ChatEnablePublic.Request()
        data = bytes.fromhex('0400000096000000')
        assert message.serialize() == data

    def test_ChatEnablePublic_Request_deserialize(self):
        message = ChatEnablePublic.Request()
        data = bytes.fromhex('0400000096000000')
        assert ChatEnablePublic.Request.deserialize(data) == message


class TestChatDisablePublic:

    def test_ChatDisablePublic_Request_serialize(self):
        message = ChatDisablePublic.Request()
        data = bytes.fromhex('0400000097000000')
        assert message.serialize() == data

    def test_ChatDisablePublic_Request_deserialize(self):
        message = ChatDisablePublic.Request()
        data = bytes.fromhex('0400000097000000')
        assert ChatDisablePublic.Request.deserialize(data) == message


class TestChatPublicMessage:

    def test_ChatPublicMessage_Response_serialize(self):
        message = ChatPublicMessage.Response(
            room='room0',
            username='user0',
            message="Hello"
        )
        data = bytes.fromhex('1f0000009800000005000000726f6f6d300500000075736572300500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatPublicMessage_Response_deserialize(self):
        message = ChatPublicMessage.Response(
            room='room0',
            username='user0',
            message="Hello"
        )
        data = bytes.fromhex('1f0000009800000005000000726f6f6d300500000075736572300500000048656c6c6f')
        assert ChatPublicMessage.Response.deserialize(data) == message


class TestFileSearchEx:

    def test_FileSearchEx_Request_serialize(self):
        message = FileSearchEx.Request('Query')
        data = bytes.fromhex('0d00000099000000050000005175657279')
        assert message.serialize() == data

    def test_FileSearchEx_Request_deserialize(self):
        message = FileSearchEx.Request('Query')
        data = bytes.fromhex('0d00000099000000050000005175657279')
        assert FileSearchEx.Request.deserialize(data) == message

    def test_FileSearchEx_Response_serialize(self):
        message = FileSearchEx.Response(
            query='Query',
            unknown=1
        )
        data = bytes.fromhex('110000009900000005000000517565727901000000')
        assert message.serialize() == data

    def test_FileSearchEx_Response_deserialize(self):
        message = FileSearchEx.Response(
            query='Query',
            unknown=1
        )
        data = bytes.fromhex('110000009900000005000000517565727901000000')
        assert FileSearchEx.Response.deserialize(data) == message


class TestCannotConnect:

    def test_CannotConnect_Request_serialize_withoutUsername(self):
        message = CannotConnect.Request(
            ticket=1234
        )
        data = bytes.fromhex('08000000e9030000d2040000')
        assert message.serialize() == data

    def test_CannotConnect_Request_deserialize_withoutUsername(self):
        message = CannotConnect.Request(
            ticket=1234
        )
        data = bytes.fromhex('08000000e9030000d2040000')
        assert CannotConnect.Request.deserialize(data) == message

    def test_CannotConnect_Request_serialize_withUsername(self):
        message = CannotConnect.Request(
            ticket=1234,
            username='user0'
        )
        data = bytes.fromhex('11000000e9030000d2040000050000007573657230')
        assert message.serialize() == data

    def test_CannotConnect_Request_deserialize_withUsername(self):
        message = CannotConnect.Request(
            ticket=1234,
            username='user0'
        )
        data = bytes.fromhex('11000000e9030000d2040000050000007573657230')
        assert CannotConnect.Request.deserialize(data) == message

    # Response
    def test_CannotConnect_Response_serialize_withoutUsername(self):
        message = CannotConnect.Response(
            ticket=1234
        )
        data = bytes.fromhex('08000000e9030000d2040000')
        assert message.serialize() == data

    def test_CannotConnect_Response_deserialize_withoutUsername(self):
        message = CannotConnect.Response(
            ticket=1234
        )
        data = bytes.fromhex('08000000e9030000d2040000')
        assert CannotConnect.Response.deserialize(data) == message

    def test_CannotConnect_Response_serialize_withUsername(self):
        message = CannotConnect.Response(
            ticket=1234,
            username='user0'
        )
        data = bytes.fromhex('11000000e9030000d2040000050000007573657230')
        assert message.serialize() == data

    def test_CannotConnect_Response_deserialize_withUsername(self):
        message = CannotConnect.Response(
            ticket=1234,
            username='user0'
        )
        data = bytes.fromhex('11000000e9030000d2040000050000007573657230')
        assert CannotConnect.Response.deserialize(data) == message


# Peer Initialization messages

class TestPeerPierceFirewall:

    def test_PeerPierceFirewall_Request_serialize(self):
        message = PeerPierceFirewall.Request(1000)
        data = bytes.fromhex('0500000000e8030000')
        assert message.serialize() == data

    def test_PeerPierceFirewall_Request_deserialize(self):
        message = PeerPierceFirewall.Request(1000)
        data = bytes.fromhex('0500000000e8030000')
        assert PeerPierceFirewall.Request.deserialize(data) == message


class TestPeerInit:

    def test_PeerInit_Request_serialize(self):
        message = PeerInit.Request(
            username='user0',
            typ='D',
            ticket=1000
        )
        data = bytes.fromhex('13000000010500000075736572300100000044e8030000')
        assert message.serialize() == data

    def test_PeerInit_Request_deserialize_uint32(self):
        message = PeerInit.Request(
            username='user0',
            typ='D',
            ticket=1000
        )
        data = bytes.fromhex('13000000010500000075736572300100000044e8030000')
        assert PeerInit.Request.deserialize(data) == message

    def test_PeerInit_Request_deserialize_uint64(self):
        message = PeerInit.Request(
            username='user0',
            typ='D',
            ticket=1000
        )
        data = bytes.fromhex('13000000010500000075736572300100000044e803000000000000')
        assert PeerInit.Request.deserialize(data) == message


# Peer messages

class TestPeerSharesRequest:

    def test_PeerSharesRequest_Request_serialize(self):
        message = PeerSharesRequest.Request()
        data = bytes.fromhex('0400000004000000')
        assert message.serialize() == data

    def test_PeerSharesRequest_Request_deserialize(self):
        message = PeerSharesRequest.Request()
        data = bytes.fromhex('0400000004000000')
        assert PeerSharesRequest.Request.deserialize(data) == message


class TestPeerSharesReply:
    MESSAGE = PeerSharesReply.Request(
        directories=[
            DirectoryData(
                name="C:\\dir0",
                files=[
                    FileData(
                        unknown='0',
                        filename="song0.mp3",
                        filesize=1000000,
                        extension='mp3',
                        attributes=[
                            Attribute(1, 320),
                            Attribute(2, 3000)
                        ]
                    )
                ]
            )
        ]
    )
    DATA = bytes.fromhex('3f00000005000000789c6364606060076267ab9894cc2203462013840d388144717e5eba815e6e81b183133f03335000c864822a70001220f60e6e0630000051cf085e')

    MESSAGE_LOCKED = PeerSharesReply.Request(
        directories=[
            DirectoryData(
                name="C:\\dir0",
                files=[
                    FileData(
                        unknown='1',
                        filename="song0.mp3",
                        filesize=1000000,
                        extension='mp3',
                        attributes=[
                            Attribute(1, 320),
                            Attribute(2, 3000)
                        ]
                    )
                ]
            )
        ],
        locked_directories=[
            DirectoryData(
                name="C:\\locked_dir0",
                files=[
                    FileData(
                        unknown='1',
                        filename="locked_song0.mp3",
                        filesize=1000000,
                        extension='mp3',
                        attributes=[
                            Attribute(1, 320),
                            Attribute(2, 3000)
                        ]
                    )
                ]
            )
        ]
    )
    DATA_LOCKED = bytes.fromhex('5400000005000000789c6364606060076267ab9894cc2203462013840d398144717e5eba815e6e81b183133f03335000c864822a70001220f60e6e06300089f141ccc9c94fce4e4d8947314e004840c5893515008852166d')

    def test_PeerSharesReply_Request_serialize_withoutLockedResults(self):
        message = self.MESSAGE
        data = self.DATA
        assert message.serialize() == data

    def test_PeerSharesReply_Request_deserialize_withoutLockedResults(self):
        message = self.MESSAGE
        data = self.DATA
        assert PeerSharesReply.Request.deserialize(data) == message

    def test_PeerSharesReply_Request_serialize_withLockedResults(self):
        message = self.MESSAGE_LOCKED
        data = self.DATA_LOCKED
        assert message.serialize() == data

    def test_PeerSharesReply_Request_deserialize_withLockedResults(self):
        message = self.MESSAGE_LOCKED
        data = self.DATA_LOCKED
        assert PeerSharesReply.Request.deserialize(data) == message
