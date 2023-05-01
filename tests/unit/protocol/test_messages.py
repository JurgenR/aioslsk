from aioslsk.protocol.primitives import (
    calc_md5,
    DirectoryData,
    FileData,
    Attribute,
    PotentialParent,
    ItemRecommendation,
    SimilarUser,
    RoomTicker,
    UserStats,
)
from aioslsk.protocol.messages import (
    Login,
    SetListenPort,
    GetPeerAddress,
    AddUser,
    RemoveUser,
    GetUserStatus,
    ChatRoomMessage,
    ChatLeaveRoom,
    ChatUserLeftRoom,
    ChatUserJoinedRoom,
    GetUserStats,
    Kicked,
    ConnectToPeer,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
    FileSearch,
    SetStatus,
    Ping,
    SharedFoldersFiles,
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
    CannotCreateRoom,
    PeerPierceFirewall,
    PeerInit,
    PeerSharesRequest,
    PeerSharesReply,
    PeerSearchReply,
    PeerUserInfoRequest,
    PeerUserInfoReply,
    PeerDirectoryContentsRequest,
    PeerDirectoryContentsReply,
    PeerTransferRequest,
    PeerTransferReply,
    PeerTransferQueue,
    PeerPlaceInQueueReply,
    PeerUploadFailed,
    PeerTransferQueueFailed,
    PeerPlaceInQueueRequest,
    PeerUploadQueueNotification,
    DistributedPing,
    DistributedSearchRequest,
    DistributedBranchLevel,
    DistributedBranchRoot,
    DistributedChildDepth,
    ServerMessage,
    PeerInitializationMessage,
    PeerMessage,
    DistributedMessage,
)

import pytest
from aioslsk.exceptions import UnknownMessageError


class TestMessageDeserializers:

    def test_whenDeserializeServerRequest_shouldDeserialize(self):
        data = bytes.fromhex('0400000020000000')
        message = ServerMessage.deserialize_request(data)
        assert isinstance(message, Ping.Request)

    def test_whenDeserializeServerResponse_shouldDeserialize(self):
        data = bytes.fromhex('080000005c000000e8030000')
        message = ServerMessage.deserialize_response(data)
        assert isinstance(message, CheckPrivileges.Response)

    def test_whenDeserializePeerInitializationRequest_shouldDeserialize(self):
        data = bytes.fromhex('0500000000e8030000')
        message = PeerInitializationMessage.deserialize_request(data)
        assert isinstance(message, PeerPierceFirewall.Request)

    def test_whenDeserializePeerRequest_shouldDeserialize(self):
        data = bytes.fromhex('040000000f000000')
        message = PeerMessage.deserialize_request(data)
        assert isinstance(message, PeerUserInfoRequest.Request)

    def test_whenDeserializeDistributedRequest_shouldDeserialize(self):
        data = bytes.fromhex('050000000405000000')
        message = DistributedMessage.deserialize_request(data)
        assert isinstance(message, DistributedBranchLevel.Request)

    def test_whenDeserializeServerRequest_unknownMessageId_shouldRaise(self):
        data = bytes.fromhex('04000000ff000000')
        with pytest.raises(UnknownMessageError):
            ServerMessage.deserialize_request(data)

    def test_whenDeserializeServerResponse_unknownMessageId_shouldRaise(self):
        data = bytes.fromhex('08000000ff000000e8030000')
        with pytest.raises(UnknownMessageError):
            ServerMessage.deserialize_response(data)

    def test_whenDeserializePeerInitializationRequest_unknownMessageId_shouldRaise(self):
        data = bytes.fromhex('05000000ffe8030000')
        with pytest.raises(UnknownMessageError):
            PeerInitializationMessage.deserialize_request(data)

    def test_whenDeserializePeerRequest_unknownMessageId_shouldRaise(self):
        data = bytes.fromhex('04000000ff000000')
        with pytest.raises(UnknownMessageError):
            PeerMessage.deserialize_request(data)

    def test_whenDeserializeDistributedRequest_unknownMessageId_shouldRaise(self):
        data = bytes.fromhex('05000000ff05000000')
        with pytest.raises(UnknownMessageError):
            DistributedMessage.deserialize_request(data)


class TestLogin:

    def test_Login_Request_serialize(self):
        message = Login.Request(
            username='Test',
            password='Test1234',
            client_version=10,
            md5hash=calc_md5('Test' + 'Test1234'),
            minor_version=123
        )
        data = bytes.fromhex('440000000100000004000000546573740800000054657374313233340a0000002000000032366330666134666430386237653233316237316532643434343034373236367b000000')
        assert message.serialize() == data

    def test_Login_Request_deserialize(self):
        message = Login.Request(
            username='Test',
            password='Test1234',
            client_version=10,
            md5hash=calc_md5('Test' + 'Test1234'),
            minor_version=123
        )
        data = bytes.fromhex('440000000100000004000000546573740800000054657374313233340a0000002000000032366330666134666430386237653233316237316532643434343034373236367b000000')
        assert Login.Request.deserialize(data) == message

    def test_Login_Response_serialize_successful(self):
        message = Login.Response(
            success=True,
            greeting="Hello",
            ip='1.2.3.4',
            md5hash=calc_md5('Test1234'),
            privileged=True
        )
        data = bytes.fromhex('3700000001000000010500000048656c6c6f0403020120000000326339333431636134636633643837623965346562393035643661336563343501')
        assert message.serialize() == data

    def test_Login_Response_serialize_unsuccessful(self):
        message = Login.Response(
            success=False,
            reason="INVALIDPASS"
        )
        assert message.serialize() == bytes.fromhex("1400000001000000000b000000494e56414c494450415353")

    def test_Login_Response_deserialize_successful(self):
        message = Login.Response(
            success=True,
            greeting="Hello",
            ip='1.2.3.4',
            md5hash=calc_md5('Test1234'),
            privileged=True
        )
        data = bytes.fromhex('3700000001000000010500000048656c6c6f0403020120000000326339333431636134636633643837623965346562393035643661336563343501')
        assert Login.Response.deserialize(data) == message

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

    def test_SetListenPort_Request_serialize_withObfuscatedPort(self):
        message = SetListenPort.Request(
            1234,
            obfuscated_port_amount=1,
            obfuscated_port=1235
        )
        data = bytes.fromhex('1000000002000000d204000001000000d3040000')
        assert message.serialize() == data

    def test_SetListenPort_Request_deserialize_withObfuscatedPorts(self):
        message = SetListenPort.Request(
            1234,
            obfuscated_port_amount=1,
            obfuscated_port=1235
        )
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
            obfuscated_port_amount=1,
            obfuscated_port=1235
        )
        data = bytes.fromhex('1b0000000300000005000000757365723004030201d204000001000000d304')
        assert message.serialize() == data

    def test_GetPeerAddress_Response_deserialize_withObfuscatedPorts(self):
        message = GetPeerAddress.Response(
            username='user0',
            ip='1.2.3.4',
            port=1234,
            obfuscated_port_amount=1,
            obfuscated_port=1235
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
            user_stats=UserStats(
                avg_speed=100,
                uploads=1000,
                shared_file_count=10000,
                shared_folder_count=100000
            )
        )
        data = bytes.fromhex('2600000005000000050000007573657230010100000064000000e80300000000000010270000a0860100')
        assert message.serialize() == data

    def test_AddUser_Response_deserialize_existsWithoutCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            user_stats=UserStats(
                avg_speed=100,
                uploads=1000,
                shared_file_count=10000,
                shared_folder_count=100000
            )
        )
        data = bytes.fromhex('2600000005000000050000007573657230010100000064000000e80300000000000010270000a0860100')
        assert AddUser.Response.deserialize(data) == message

    def test_AddUser_Response_serialize_existsWithCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            user_stats=UserStats(
                avg_speed=100,
                uploads=1000,
                shared_file_count=10000,
                shared_folder_count=100000
            ),
            country_code='DE'
        )
        data = bytes.fromhex('2c00000005000000050000007573657230010100000064000000e80300000000000010270000a0860100020000004445')
        assert message.serialize() == data

    def test_AddUser_Response_deserialize_existsWithCountryCode(self):
        message = AddUser.Response(
            username='user0',
            exists=True,
            status=1,
            user_stats=UserStats(
                avg_speed=100,
                uploads=1000,
                shared_file_count=10000,
                shared_folder_count=100000
            ),
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
            message="Hello"
        )
        data = bytes.fromhex('160000000d00000005000000726f6f6d300500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatRoomMessage_Request_deserialize(self):
        message = ChatRoomMessage.Request(
            room='room0',
            message="Hello"
        )
        data = bytes.fromhex('160000000d00000005000000726f6f6d300500000048656c6c6f')
        assert ChatRoomMessage.Request.deserialize(data) == message

    def test_ChatRoomMessage_Response_serialize(self):
        message = ChatRoomMessage.Response(
            room='room0',
            username='user0',
            message="Hello"
        )
        data = bytes.fromhex('1f0000000d00000005000000726f6f6d300500000075736572300500000048656c6c6f')
        assert message.serialize() == data

    def test_ChatRoomMessage_Response_deserialize(self):
        message = ChatRoomMessage.Response(
            room='room0',
            username='user0',
            message="Hello"
        )
        data = bytes.fromhex('1f0000000d00000005000000726f6f6d300500000075736572300500000048656c6c6f')
        assert ChatRoomMessage.Response.deserialize(data) == message


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

    def test_ChatUserJoinedRoom_Response_serialize(self):
        message = ChatUserJoinedRoom.Response(
            room='room0',
            username='user0',
            status=1,
            user_stats=UserStats(
                avg_speed=1000,
                uploads=10000,
                shared_file_count=1000,
                shared_folder_count=1000
            ),
            slots_free=5,
            country_code='DE'
        )
        data = bytes.fromhex('380000001000000005000000726f6f6d3005000000757365723001000000e80300001027000000000000e8030000e803000005000000020000004445')
        assert message.serialize() == data

    def test_ChatUserJoinedRoom_Response_deserialize(self):
        message = ChatUserJoinedRoom.Response(
            room='room0',
            username='user0',
            status=1,
            user_stats=UserStats(
                avg_speed=1000,
                uploads=10000,
                shared_file_count=1000,
                shared_folder_count=1000
            ),
            slots_free=5,
            country_code='DE'
        )
        data = bytes.fromhex('380000001000000005000000726f6f6d3005000000757365723001000000e80300001027000000000000e8030000e803000005000000020000004445')
        assert ChatUserJoinedRoom.Response.deserialize(data) == message


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


class TestSharedFoldersFiles:

    def test_SharedFoldersFiles_Request_serialize(self):
        message = SharedFoldersFiles.Request(
            shared_folder_count=1000,
            shared_file_count=10000
        )
        data = bytes.fromhex('0c00000023000000e803000010270000')
        assert message.serialize() == data

    def test_SharedFoldersFiles_Request_deserialize(self):
        message = SharedFoldersFiles.Request(
            shared_folder_count=1000,
            shared_file_count=10000
        )
        data = bytes.fromhex('0c00000023000000e803000010270000')
        assert SharedFoldersFiles.Request.deserialize(data) == message


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
            user_stats=UserStats(
                avg_speed=100000,
                uploads=1000000,
                shared_file_count=10000,
                shared_folder_count=1000
            )
        )
        data = bytes.fromhex('2100000024000000050000007573657230a086010040420f000000000010270000e8030000')
        assert message.serialize() == data

    def test_GetUserStats_Response_deserialize(self):
        message = GetUserStats.Response(
            username='user0',
            user_stats=UserStats(
                avg_speed=100000,
                uploads=1000000,
                shared_file_count=10000,
                shared_folder_count=1000
            )
        )
        data = bytes.fromhex('2100000024000000050000007573657230a086010040420f000000000010270000e8030000')
        assert GetUserStats.Response.deserialize(data) == message


class TestKicked:

    def test_Kicked_Response_serialize(self):
        message = Kicked.Response()
        data = bytes.fromhex('0400000029000000')
        assert message.serialize() == data

    def test_Kicked_Response_deserialize(self):
        message = Kicked.Response()
        data = bytes.fromhex('0400000029000000')
        assert Kicked.Response.deserialize(data) == message


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

    def test_PrivateRoomUsers_Response_serialize(self):
        message = PrivateRoomUsers.Response(
            room='room0',
            usernames=['user0', 'user1']
        )
        data = bytes.fromhex('230000008500000005000000726f6f6d3002000000050000007573657230050000007573657231')
        assert message.serialize() == data

    def test_PrivateRoomUsers_Response_deserialize(self):
        message = PrivateRoomUsers.Response(
            room='room0',
            usernames=['user0', 'user1']
        )
        data = bytes.fromhex('230000008500000005000000726f6f6d3002000000050000007573657230050000007573657231')
        assert PrivateRoomUsers.Response.deserialize(data) == message


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


class TestCannotCreateRoom:

    def test_CannotCreateRoom_Response_serialize(self):
        message = CannotCreateRoom.Response(
            room='room0'
        )
        data = bytes.fromhex('0d000000eb03000005000000726f6f6d30')
        assert message.serialize() == data

    def test_CannotCreateRoom_Response_deserialize_withUsername(self):
        message = CannotCreateRoom.Response(
            room='room0'
        )
        data = bytes.fromhex('0d000000eb03000005000000726f6f6d30')
        assert CannotCreateRoom.Response.deserialize(data) == message


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
                        unknown=0,
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
    DATA = bytes.fromhex('4100000005000000789c6364606060076267ab9894cc22034620938113888bf3f3d20df4720b8c1d9cf841620ccc400ce4320129902207200162efe006cb3200005766082d')

    MESSAGE_LOCKED = PeerSharesReply.Request(
        directories=[
            DirectoryData(
                name="C:\\dir0",
                files=[
                    FileData(
                        unknown=1,
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
                        unknown=1,
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
    DATA_LOCKED = bytes.fromhex('5400000005000000789c6364606060076267ab9894cc220346209391134814e7e7a51be8e516183b38f1338000331003b94c200540ec002440ec1ddc6059b0181fc49c9cfce4ecd49478b8710240022a468aa9008ea3160b')

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


class TestPeerSearchReply:

    MESSAGE = PeerSearchReply.Request(
        username='user0',
        ticket=1234,
        results=[
            FileData(
                unknown=1,
                filename="C:\\dir0\\song0.mp3",
                filesize=10000000,
                extension='mp3',
                attributes=[
                    Attribute(1, 320),
                    Attribute(2, 100)
                ]
            )
        ],
        has_slots_free=True,
        avg_speed=1000,
        queue_size=5,
    )
    DATA = bytes.fromhex('4c00000009000000789c63656060282d4e2d32b8c4c2c0c008e4300a020967ab9894cc228398e2fcbc7403bddc02e38669331840801988815c2606886207200162a780f82f8092ac0c100000bd030d03')

    MESSAGE_LOCKED = PeerSearchReply.Request(
        username='user0',
        ticket=1234,
        results=[
            FileData(
                unknown=1,
                filename="C:\\dir0\\song0.mp3",
                filesize=10000000,
                extension='mp3',
                attributes=[
                    Attribute(1, 320),
                    Attribute(2, 100)
                ]
            )
        ],
        has_slots_free=True,
        avg_speed=1000,
        queue_size=5,
        locked_results=[
            FileData(
                unknown=1,
                filename="C:\\dir0\\locked_song0.mp3",
                filesize=10000000,
                extension='mp3',
                attributes=[
                    Attribute(1, 320),
                    Attribute(2, 100)
                ]
            )
        ]
    )
    DATA_LOCKED = bytes.fromhex('5b00000009000000789c63656060282d4e2d32b8c4c2c0c008e4300a020967ab9894cc228398e2fcbc7403bddc02e38669331840801988815c2606886207200162a780f82f8092ac0c1000364902c9a49cfce4ecd49478520c040026fe1922')

    def test_PeerSearchReply_Request_serialize_withoutLockedResults(self):
        message = self.MESSAGE
        data = self.DATA
        assert message.serialize() == data

    def test_PeerSearchReply_Request_deserialize_withoutLockedResults(self):
        message = self.MESSAGE
        data = self.DATA
        assert PeerSearchReply.Request.deserialize(data) == message

    def test_PeerSearchReply_Request_serialize_withLockedResults(self):
        message = self.MESSAGE_LOCKED
        data = self.DATA_LOCKED
        assert message.serialize() == data

    def test_PeerSearchReply_Request_deserialize_withLockedResults(self):
        message = self.MESSAGE_LOCKED
        data = self.DATA_LOCKED
        assert PeerSearchReply.Request.deserialize(data) == message


class TestPeerUserInfoRequest:

    def test_PeerUserInfoRequest_Request_serialize(self):
        message = PeerUserInfoRequest.Request()
        data = bytes.fromhex('040000000f000000')
        assert message.serialize() == data

    def test_PeerUserInfoRequest_Request_deserialize(self):
        message = PeerUserInfoRequest.Request()
        data = bytes.fromhex('040000000f000000')
        assert PeerUserInfoRequest.Request.deserialize(data) == message


class TestPeerUserInfoReply:

    def test_PeerUserInfoReply_Request_serialize_withoutPicture(self):
        message = PeerUserInfoReply.Request(
            description="description",
            has_picture=False,
            upload_slots=5,
            queue_size=10,
            has_slots_free=True
        )
        data = bytes.fromhex('1d000000100000000b0000006465736372697074696f6e00050000000a00000001')
        assert message.serialize() == data

    def test_PeerUserInfoReply_Request_deserialize_withoutPicture(self):
        message = PeerUserInfoReply.Request(
            description="description",
            has_picture=False,
            upload_slots=5,
            queue_size=10,
            has_slots_free=True
        )
        data = bytes.fromhex('1d000000100000000b0000006465736372697074696f6e00050000000a00000001')
        assert PeerUserInfoReply.Request.deserialize(data) == message

    def test_PeerUserInfoReply_Request_serialize_withPicture(self):
        message = PeerUserInfoReply.Request(
            description="description",
            has_picture=True,
            picture='picture.png',
            upload_slots=5,
            queue_size=10,
            has_slots_free=True
        )
        data = bytes.fromhex('2c000000100000000b0000006465736372697074696f6e010b000000706963747572652e706e67050000000a00000001')
        assert message.serialize() == data

    def test_PeerUserInfoReply_Request_deserialize_withPicture(self):
        message = PeerUserInfoReply.Request(
            description="description",
            has_picture=True,
            picture='picture.png',
            upload_slots=5,
            queue_size=10,
            has_slots_free=True
        )
        data = bytes.fromhex('2c000000100000000b0000006465736372697074696f6e010b000000706963747572652e706e67050000000a00000001')
        assert PeerUserInfoReply.Request.deserialize(data) == message


class TestPeerDirectoryContentsRequest:

    def test_PeerDirectoryContentsRequest_Request_serialize(self):
        message = PeerDirectoryContentsRequest.Request(
            ticket=1234,
            directory='C:\\dir0'
        )
        data = bytes.fromhex('1300000024000000d204000007000000433a5c64697230')
        assert message.serialize() == data

    def test_PeerDirectoryContentsRequest_Request_deserialize(self):
        message = PeerDirectoryContentsRequest.Request(
            ticket=1234,
            directory='C:\\dir0'
        )
        data = bytes.fromhex('1300000024000000d204000007000000433a5c64697230')
        assert PeerDirectoryContentsRequest.Request.deserialize(data) == message


class TestPeerDirectoryContentsReply:
    MESSAGE = PeerDirectoryContentsReply.Request(
        ticket=1234,
        directory='C:\\dir0',
        directories=[
            DirectoryData(
                name='C:\\dir0',
                files=[
                    FileData(
                        unknown=1,
                        filename='song0.mp3',
                        filesize=1000000,
                        extension='mp3',
                        attributes=[
                            Attribute(1, 320),
                            Attribute(0, 1000)
                        ]
                    )
                ]
            )
        ]
    )
    DATA = bytes.fromhex('4100000025000000789cbbc4c2c0c0cec0c0e06c1593925964c0c880c165e40412c5f979e9067ab905c60e4efc0c20c00cc4402e134801103b308245195e00c501231c0b79')

    def test_PeerDirectoryContentsReply_Request_serialize(self):
        message = self.MESSAGE
        data = self.DATA
        assert message.serialize() == data

    def test_PeerDirectoryContentsReply_Request_deserialize(self):
        message = self.MESSAGE
        data = self.DATA
        assert PeerDirectoryContentsReply.Request.deserialize(data) == message


class TestPeerTransferRequest:

    def test_PeerTransferRequest_Request_serialize_withoutFilesize(self):
        message = PeerTransferRequest.Request(
            direction=1,
            ticket=1234,
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('210000002800000001000000d204000011000000433a5c646972305c736f6e67302e6d7033')
        assert message.serialize() == data

    def test_PeerTransferRequest_Request_deserialize_withoutFilesize(self):
        message = PeerTransferRequest.Request(
            direction=1,
            ticket=1234,
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('210000002800000001000000d204000011000000433a5c646972305c736f6e67302e6d7033')
        assert PeerTransferRequest.Request.deserialize(data) == message

    def test_PeerTransferRequest_Request_serialize_withFilesize(self):
        message = PeerTransferRequest.Request(
            direction=1,
            ticket=1234,
            filename="C:\\dir0\\song0.mp3",
            filesize=100000
        )
        data = bytes.fromhex('290000002800000001000000d204000011000000433a5c646972305c736f6e67302e6d7033a086010000000000')
        assert message.serialize() == data

    def test_PeerTransferRequest_Request_deserialize_withFilesize(self):
        message = PeerTransferRequest.Request(
            direction=1,
            ticket=1234,
            filename="C:\\dir0\\song0.mp3",
            filesize=100000
        )
        data = bytes.fromhex('290000002800000001000000d204000011000000433a5c646972305c736f6e67302e6d7033a086010000000000')
        assert PeerTransferRequest.Request.deserialize(data) == message


class TestPeerTransferReply:

    def test_PeerTransferReply_Request_serialize_withoutExtra(self):
        message = PeerTransferReply.Request(
            ticket=1234,
            allowed=False
        )
        data = bytes.fromhex('0900000029000000d204000000')
        assert message.serialize() == data

    def test_PeerTransferReply_Request_deserialize_withoutExtra(self):
        message = PeerTransferReply.Request(
            ticket=1234,
            allowed=False
        )
        data = bytes.fromhex('0900000029000000d204000000')
        assert PeerTransferReply.Request.deserialize(data) == message

    def test_PeerTransferReply_Request_serialize_withFilesize(self):
        message = PeerTransferReply.Request(
            ticket=1234,
            allowed=True,
            filesize=1000000
        )
        data = bytes.fromhex('1100000029000000d20400000140420f0000000000')
        assert message.serialize() == data

    def test_PeerTransferReply_Request_deserialize_withFilesize(self):
        message = PeerTransferReply.Request(
            ticket=1234,
            allowed=True,
            filesize=1000000
        )
        data = bytes.fromhex('1100000029000000d20400000140420f0000000000')
        assert PeerTransferReply.Request.deserialize(data) == message

    def test_PeerTransferReply_Request_serialize_withReason(self):
        message = PeerTransferReply.Request(
            ticket=1234,
            allowed=False,
            reason='Cancelled'
        )
        data = bytes.fromhex('1600000029000000d2040000000900000043616e63656c6c6564')
        assert message.serialize() == data

    def test_PeerTransferReply_Request_deserialize_withReason(self):
        message = PeerTransferReply.Request(
            ticket=1234,
            allowed=False,
            reason='Cancelled'
        )
        data = bytes.fromhex('1600000029000000d2040000000900000043616e63656c6c6564')
        assert PeerTransferReply.Request.deserialize(data) == message


class TestPeerTransferQueue:

    def test_PeerTransferQueue_Request_serialize(self):
        message = PeerTransferQueue.Request(
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('190000002b00000011000000433a5c646972305c736f6e67302e6d7033')
        assert message.serialize() == data

    def test_PeerTransferQueue_Request_deserialize(self):
        message = PeerTransferQueue.Request(
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('190000002b00000011000000433a5c646972305c736f6e67302e6d7033')
        assert PeerTransferQueue.Request.deserialize(data) == message


class TestPeerPlaceInQueueReply:

    def test_PeerPlaceInQueueReply_Request_serialize(self):
        message = PeerPlaceInQueueReply.Request(
            filename="C:\\dir0\\song0.mp3",
            place=10
        )
        data = bytes.fromhex('1d0000002c00000011000000433a5c646972305c736f6e67302e6d70330a000000')
        assert message.serialize() == data

    def test_PeerPlaceInQueueReply_Request_deserialize(self):
        message = PeerPlaceInQueueReply.Request(
            filename="C:\\dir0\\song0.mp3",
            place=10
        )
        data = bytes.fromhex('1d0000002c00000011000000433a5c646972305c736f6e67302e6d70330a000000')
        assert PeerPlaceInQueueReply.Request.deserialize(data) == message


class TestPeerUploadFailed:

    def test_PeerUploadFailed_Request_serialize(self):
        message = PeerUploadFailed.Request(
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('190000002e00000011000000433a5c646972305c736f6e67302e6d7033')
        assert message.serialize() == data

    def test_PeerUploadFailed_Request_deserialize(self):
        message = PeerUploadFailed.Request(
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('190000002e00000011000000433a5c646972305c736f6e67302e6d7033')
        assert PeerUploadFailed.Request.deserialize(data) == message


class TestPeerTransferQueueFailed:

    def test_PeerTransferQueueFailed_Request_serialize(self):
        message = PeerTransferQueueFailed.Request(
            filename="C:\\dir0\\song0.mp3",
            reason='Cancelled'
        )
        data = bytes.fromhex('260000003200000011000000433a5c646972305c736f6e67302e6d70330900000043616e63656c6c6564')
        assert message.serialize() == data

    def test_PeerTransferQueueFailed_Request_deserialize(self):
        message = PeerTransferQueueFailed.Request(
            filename="C:\\dir0\\song0.mp3",
            reason='Cancelled'
        )
        data = bytes.fromhex('260000003200000011000000433a5c646972305c736f6e67302e6d70330900000043616e63656c6c6564')
        assert PeerTransferQueueFailed.Request.deserialize(data) == message


class TestPeerPlaceInQueueRequest:

    def test_PeerPlaceInQueueRequest_Request_serialize(self):
        message = PeerPlaceInQueueRequest.Request(
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('190000003300000011000000433a5c646972305c736f6e67302e6d7033')
        assert message.serialize() == data

    def test_PeerPlaceInQueueRequest_Request_deserialize(self):
        message = PeerPlaceInQueueRequest.Request(
            filename="C:\\dir0\\song0.mp3"
        )
        data = bytes.fromhex('190000003300000011000000433a5c646972305c736f6e67302e6d7033')
        assert PeerPlaceInQueueRequest.Request.deserialize(data) == message


class TestPeerUploadQueueNotification:

    def test_PeerUploadQueueNotification_Request_serialize(self):
        message = PeerUploadQueueNotification.Request()
        data = bytes.fromhex('0400000034000000')
        assert message.serialize() == data

    def test_PeerUploadQueueNotification_Request_deserialize(self):
        message = PeerUploadQueueNotification.Request()
        data = bytes.fromhex('0400000034000000')
        assert PeerUploadQueueNotification.Request.deserialize(data) == message


# Distributed messages

class TestDistributedPing:

    def test_DistributedPing_Request_serialize(self):
        message = DistributedPing.Request()
        data = bytes.fromhex('0100000000')
        assert message.serialize() == data

    def test_DistributedPing_Request_deserialize(self):
        message = DistributedPing.Request()
        data = bytes.fromhex('0100000000')
        assert DistributedPing.Request.deserialize(data) == message


class TestDistributedSearchRequest:

    def test_DistributedSearchRequest_Request_serialize(self):
        message = DistributedSearchRequest.Request(
            unknown=0x31,
            username='user0',
            ticket=1234,
            query='Query'
        )
        data = bytes.fromhex('1b0000000331000000050000007573657230d2040000050000005175657279')
        assert message.serialize() == data

    def test_DistributedSearchRequest_Request_deserialize(self):
        message = DistributedSearchRequest.Request(
            unknown=0x31,
            username='user0',
            ticket=1234,
            query='Query'
        )
        data = bytes.fromhex('1b0000000331000000050000007573657230d2040000050000005175657279')
        assert DistributedSearchRequest.Request.deserialize(data) == message


class TestDistributedBranchLevel:

    def test_DistributedBranchLevel_Request_serialize(self):
        message = DistributedBranchLevel.Request(5)
        data = bytes.fromhex('050000000405000000')
        assert message.serialize() == data

    def test_DistributedBranchLevel_Request_deserialize(self):
        message = DistributedBranchLevel.Request(5)
        data = bytes.fromhex('050000000405000000')
        assert DistributedBranchLevel.Request.deserialize(data) == message


class TestDistributedBranchRoot:

    def test_DistributedBranchRoot_Request_serialize(self):
        message = DistributedBranchRoot.Request('user0')
        data = bytes.fromhex('0a00000005050000007573657230')
        assert message.serialize() == data

    def test_DistributedBranchRoot_Request_deserialize(self):
        message = DistributedBranchRoot.Request('user0')
        data = bytes.fromhex('0a00000005050000007573657230')
        assert DistributedBranchRoot.Request.deserialize(data) == message


class TestDistributedChildDepth:

    def test_DistributedChildDepth_Request_serialize(self):
        message = DistributedChildDepth.Request(5)
        data = bytes.fromhex('050000000705000000')
        assert message.serialize() == data

    def test_DistributedChildDepth_Request_deserialize(self):
        message = DistributedChildDepth.Request(5)
        data = bytes.fromhex('050000000705000000')
        assert DistributedChildDepth.Request.deserialize(data) == message


class DistributedServerSearchRequest:

    def test_DistributedServerSearchRequest_Request_serialize(self):
        message = DistributedServerSearchRequest.Response(
            distributed_code=3,
            unknown=0,
            username='user0',
            ticket=1234,
            query='Query'
        )
        data = bytes.fromhex('1f0000005d0000000300000000050000007573657230d2040000050000005175657279')
        assert message.serialize() == data

    def test_DistributedServerSearchRequest_Request_deserialize(self):
        message = DistributedServerSearchRequest.Response(
            distributed_code=3,
            unknown=0,
            username='user0',
            ticket=1234,
            query='Query'
        )
        data = bytes.fromhex('1f0000005d0000000300000000050000007573657230d2040000050000005175657279')
        assert DistributedServerSearchRequest.Response.deserialize(data) == message
