========
Messages
========

.. contents:

Data formats
============

The components of the messages use a little-endian byte order.

+--------+-------------+-------+
| Type   | Python type | Usage |
+========+=============+=======+
| uint8  | int         |       |
+--------+-------------+-------+
| uint16 | int         |       |
+--------+-------------+-------+
| uint32 | int         |       |
+--------+-------------+-------+
| uint64 | int         |       |
+--------+-------------+-------+
| uchar  | int         |       |
+--------+-------------+-------+
| string | str         |       |
+--------+-------------+-------+
| bool   | bool        |       |
+--------+-------------+-------+


Data Structures
===============


Server Messages
===============


Login (Code 1)
--------------

:Code: 1 (0x01)

:Usage: Login into the server, this should be the first message sent to the server upon connecting

:Send:

1. **string**: username
2. **string**: password
3. **uint32**:
4. **string**: MD5 hash of concatenated username and password
5. **uint32**: minor_version

:Receive:

1. **bool**: result. true on success, false on failure
2. If result==true

   1. **string**: greeting
   2. **ip**: ip_address
   3. **string**: md5_hash , hash of the password
   4. **uint8**: privileged

3. If result==false

   1. **string**: failure_reason


SetListenPort (Code 2)
----------------------

:Code: 2 (0x02)

:Usage: Advertise our listening ports to the server

Obfuscated port: this part seems to be optional, either it can be omitted completely or both values set to 0

:Send:

1. **uint32**: listening port
2. Optional:

   1. **uint32**: has obfuscated listening port
   2. **uint32**: obfuscated listening port


GetPeerAddress (Code 3)
-----------------------

:Code: 3 (0x03)

:Usage: Retrieve the IP address/port of a peer

Obfuscated port: this part seems to be optional, either it can be omitted completely or both values set to 0

If the peer does not exist we will receive a response with IP address, port set to `0`

:Send:

1. **string**: username

:Receive:

1. **string**: username
2. **uint32**: IP address
3. **uint32**: listening port
4. Optional:

   1. **uint32**: has obfuscated listening port
   2. **uint32**: obfuscated listening port


AddUser (Code 5)
----------------

:Code: 5 (0x05)

:Usage: Track a user

:Send:

1. **string**: username

:Receive:

1. **string**: username
2. **bool**: exist
3. if exists==true

   1. **uint32**: status
   2. **uint32**: average upload speed
   3. **uint64**: download_number
   4. **uint32**: shared_files
   5. **uint32**: shared_directories
   6. Optional:

      1. **string**: country_code


GetUserStatus (Code 7)
----------------------

:Code: 5 (0x05)

:Usage: Get the user status, we will get updates on this automatically if we have performed AddUser

:Send:

1. **string**: username

:Receive:

1. **string**: username
2. **uint32**: status
3. **bool**: privileged


ChatRoomMessage (Code 13)
-------------------------

:Code: 13 (0x0D)

:Usage: Used to send/receive a message to/from a room

:Send:

1. **string**: room_name
2. **string**: message

:Receive:

1. **string**: room_name
2. **string**: username
3. **string**: message


ChatJoinRoom (Code 14)
----------------------

:Code: 14 (0x0E)

:Usage: Used when we want to join a chat room

:Send:

1. **string**: room_name

:Receive:

1. **string**: room_name
2. Array of usernames:

   1. **string**: username

3. Array of user statuses:

   1. **uint32**: status

4. Array of user info:

   1. 1234

5. Array of upload slots free:

   1. **uint32**: slots_free

6. Array of user countries:

   1. **string**: country_code

7. Optional:

   1. **string**: owner
   2. Array of operators:

      1. **string**: operator


ChatLeaveRoom (Code 15)
-----------------------

:Code: 15 (0x0F)

:Usage: Used when we want to leave a chat room. The receive is for confirmation

:Send:

1. **string**: room_name

:Receive:

1. **string**: room_name


ChatUserJoinedRoom (Code 16)
----------------------------

:Code: 16 (0x10)

:Usage: Received when a user joined a room

:Receive:

1. **string**: room_name
2. **string**: username
3. **uint32**: status
4. **uint32**: average_speed
5. **uint64**: download_number
6. **uint32**: shared_files
7. **uint32**: shared_directories
8. **uint32**: slots_free
9. **string**: country_code


ChatUserJoinedRoom (Code 17)
----------------------------

:Code: 17 (0x11)

:Usage: Received when a user left a room

:Receive:

1. **string**: room_name
2. **string**: username


ConnectToPeer (Code 18)
-----------------------

:Code: 18 (0x12)

:Usage: Received when a peer attempted to connect to us but failed and thus is asking us to attempt to connect to them

:Send:

1. **uint32**: ticket
2. **string**: username
3. **string**: connection_type

:Receive:

1. **string**: username
2. **string**: connection_type
3. **uint32**: ip_address
4. **uint32**: port
5. **uint32**: ticket
6. **uint8**: privileged
7. Optional:

   1. **uint32**: has_obfuscated_port
   2. **uint32**: obfuscated_port


ChatPrivateMessage (Code 22)
----------------------------

:Code: 22 (0x16)

:Usage: Send or receive a private message

:Send:

1. **string**: username
2. **string**: message

:Receive:

1. **uint32**: chat_id
2. **uint32**: timestamp
3. **string**: username
4. **string**: message
5. Optional:
   1. **bool**: is_admin


ChatPrivateMessage (Code 23)
----------------------------

:Code: 23 (0x17)

:Usage: Acknowledge we have received a private message

:Send:

1. **uint32**: chat_id


FileSearch (Code 26)
--------------------

:Code: 26 (0x1A)

:Usage: Unknown, file searches usually come from the distributed connection or ServerSearch message

:Send:

1. **uint32**: ticket
2. **string**: query

:Receive:

1. **string**: username
2. **uint32**: ticket
3. **string**: query


SetStatus (Code 28)
-------------------

:Code: 28 (0x1C)

:Usage: Update our status

:Send:

1. **uint32**: status


Ping (Code 32)
--------------

:Code: 32 (0x20)

:Usage: Send a ping to the server to let it know we are still alive (every 5 minutes)

:Send:

Empty message


SharedFoldersFiles (Code 35)
----------------------------

:Code: 35 (0x23)

:Usage: Let the server know the amount of files and directories we are sharing

:Send:

1. **uint32**: shared_directories
2. **uint32**: shared_files


GetUserStats (Code 36)
----------------------

:Code: 36 (0x24)

:Usage: Get more user information, we will automatically receive updates if we added a user using AddUser

:Send:

1. **string**: username

:Receive:

1. **string**: username
2. **uint32**: average_speed
3. **uint64**: download_number
4. **uint32**: shared_files
5. **uint32**: shared_directories


Kicked (Code 41)
----------------

:Code: 42 (0x2A)

:Usage: You were kicked from the server. This message is sent when


:Receive:

Nothing


UserSearch (Code 42)
--------------------

:Code: 42 (0x2A)

:Usage: Unknown

:Send:

1. **string**: username
2. **uint32**: ticket
3. **string**: query


HaveNoParent (Code 71)
----------------------

:Code: 71 (0x47)

:Usage: Indicates whether we have a distributed parent. If not the server will start sending us NetInfo messages every 60 seconds

:Send:

1. **bool**: have_no_parent


ParentIP (Code 73)
------------------

:Code: 73 (0x49)

*Usage*:

:Send:

1. **uint32**: ip_address


ParentMinSpeed (Code 83)
------------------------

:Code: 83 (0x53)

*Usage*:

:Receive:

1. **uint32**: parent_min_speed


ParentSpeedRatio (Code 84)
--------------------------

:Code: 84 (0x54)

*Usage*:

:Receive:

1. **uint32**: parent_speed_ratio



ParentInactivityTimeout (Code 86)
---------------------------------

:Code: 86 (0x56)

*Usage*: Timeout for the distributed parent

:Receive:

1. **uint32**: timeout


SearchInactivityTimeout (Code 87)
---------------------------------

:Code: 87 (0x57)

*Usage*:

:Receive:

1. **uint32**: timeout


MinParentsInCache (Code 88)
---------------------------

:Code: 88 (0x58)

*Usage*:

:Receive:

1. **uint32**: amount


DistributedAliveInterval (Code 90)
----------------------------------

:Code: 90 (0x5A)

*Usage*:

:Receive:

1. **uint32**: interval


AddPrivilegedUser (Code 91)
---------------------------

:Code: 91 (0x5B)

*Usage*:

:Send:

1. **string**: username


CheckPrivileges (Code 92)
-------------------------

:Code: 92 (0x5C)

*Usage*:

:Send:

Nothing

:Receive:

1. **uint32**: time_left


ServerSearchRequest (Code 93)
-----------------------------

:Code: 93 (0x5D)

*Usage*:

:Receive:

1. **uint8**: distributed_code
2. **uint32**: unknown
3. **string**: username
4. **uint32**: ticket
5. **string**: query


AcceptChildren (Code 100)
-------------------------

:Code: 100 (0x64)

*Usage*:

:Send:

1. **bool**: accept


PotentialParents (Code 102)
---------------------------

:Code: 102 (0x66)

*Usage*:

:Receive:

1. Array of potential parents:

   1. **string**: username
   2. **ip_address**: ip
   3. **uint32**: port


WishlistSearch (Code 103)
-------------------------

:Code: 103 (0x67)

*Usage*: Perform a wishlist search

:Send:

1. **uint32**: username
2. **string**: query


WishlistInterval (Code 104)
---------------------------

:Code: 104 (0x68)

*Usage*: The server lets us know at what interval we should perform wishlist searches

:Receive:

1. **uint32**: interval


GetSimilarUsers (Code 110)
--------------------------

:Code: 110 (0x6E)

*Usage*:

:Send:

Nothing

:Receive:

1. Array of similar users:

   1. **string**: username
   2. **uint32**: status


GetItemRecommendations (Code 111)
---------------------------------

:Code: 111 (0x6F)

*Usage*:

:Send:

1. **string**: recommendation

:Receive:

1. Array of item recommendations:

   1. **string**: recommendation
   2. **uint32**: number


ChatRoomTickers (Code 113)
--------------------------

:Code: 113 (0x71)

*Usage*: List of chat room tickers (room wall)

:Receive:

1. **string**: room
2. Array of room tickers:

   1. **string**: username
   2. **string**: ticker


ChatRoomTickerAdded (Code 114)
------------------------------

:Code: 114 (0x72)

*Usage*: A ticker has been added to the room (room wall)

:Receive:

1. **string**: room
2. **string**: username
3. **string**: ticker


ChatRoomTickerRemoved (Code 115)
--------------------------------

:Code: 115 (0x73)

*Usage*: A ticker has been removed to the room (room wall)

:Receive:

1. **string**: room
2. **string**: username


ChatRoomTickerSet (Code 116)
----------------------------

:Code: 116 (0x74)

*Usage*: Add or update a ticker for a room (room wall)

:Receive:

1. **string**: room
2. **string**: ticker


ChatRoomSearch (Code 120)
-------------------------

:Code: 120 (0x78)

*Usage*:

:Send:

1. **string**: room
2. **uint32**: ticket
3. **string**: query


ChatRoomSearch (Code 120)
-------------------------

:Code: 120 (0x78)

*Usage*: Send upload speed, sent to the server right after an upload completed

:Send:

1. **uint32**: speed


GetUserPrivileges (Code 122)
----------------------------

:Code: 122 (0x7A)

*Usage*: Retrieve whether a user has privileges

:Send:

Nothing

:Receive:

1. **string**: username
2. **bool**: privilged


GiveUserPrivileges (Code 123)
-----------------------------

:Code: 123 (0x7B)

*Usage*:

:Send:

1. **string**: username
2. **uint32**: days

PrivilegesNotification (Code 124)
---------------------------------

:Code: 124 (0x7C)

*Usage*:

:Send:

1. **uint32**: notification_id
2. **string**: username


PrivilegesNotificationAck (Code 125)
------------------------------------

:Code: 125 (0x7D)

*Usage*:

:Send:

1. **uint32**: notification_id


BranchLevel (Code 126)
----------------------

:Code: 126 (0x7E)

*Usage*: Notify the server which branch level we are at in the distributed network

:Send:

1. **uint32**: level


BranchRoot (Code 127)
---------------------

:Code: 127 (0x7F)

*Usage*: Notify the server who our branch root user is in the distributed network

:Send:

1. **string**: username


ChildDepth (Code 129)
---------------------

:Code: 129 (0x81)

*Usage*:

:Send:

1. **uint32**: depth


PrivateRoomUsers (Code 133)
---------------------------

:Code: 133 (0x85)

*Usage*:

:Receive:

1. **string**: room
2. An array of usernames:

   1. **string**: username


PrivateRoomAddUser (Code 134)
-----------------------------

:Code: 134 (0x86)

*Usage*:

:Send:

1. **string**: room
2. **string**: username

:Receive:

1. **string**: room
2. **string**: username


PrivateRoomRemoveUser (Code 135)
--------------------------------

:Code: 135 (0x87)

*Usage*:

:Send:

1. **string**: room
2. **string**: username

:Receive:

1. **string**: room
2. **string**: username


PrivateRoomDropMembership (Code 136)
------------------------------------

:Code: 136 (0x88)

*Usage*:

:Send:

1. **string**: room


PrivateRoomDropOwnership (Code 137)
-----------------------------------

:Code: 137 (0x89)

*Usage*:

:Send:

1. **string**: room



PrivateRoomAdded (Code 139)
---------------------------

:Code: 139 (0x8B)

*Usage*:

:Receive:

1. **string**: room


PrivateRoomRemoved (Code 140)
-----------------------------

:Code: 140 (0x8C)

*Usage*:

:Receive:

1. **string**: room


TogglePrivateRooms (Code 141)
-----------------------------

:Code: 141 (0x8D)

*Usage*:

:Send:

1. **bool**: enable

:Receive:

1. **bool**: enabled


NewPassword (Code 142)
----------------------

:Code: 142 (0x8E)

*Usage*:

:Send:

1. **string**: password


PrivateRoomAddOperator (Code 143)
---------------------------------

:Code: 143 (0x8F)

*Usage*:

:Send:

1. **string**: room
2. **string**: username

:Receive:

1. **string**: room
2. **string**: username


PrivateRoomRemoveOperator (Code 144)
------------------------------------

:Code: 144 (0x90)

*Usage*:

:Send:

1. **string**: room
2. **string**: username

:Receive:

1. **string**: room
2. **string**: username


PrivateRoomOperatorAdded (Code 145)
-----------------------------------

:Code: 145 (0x91)

*Usage*:

:Receive:

1. **string**: room


PrivateRoomOperatorRemoved (Code 146)
-------------------------------------

:Code: 146 (0x92)

*Usage*:

:Receive:

1. **string**: room


PrivateRoomOperators (Code 148)
-------------------------------

:Code: 148 (0x94)

*Usage*:

:Receive:

1. **string**: room
2. An array of usernames:

   1. **string**: username



ChatMessageUsers (Code 149)
---------------------------

:Code: 149 (0x95)

*Usage*:

:Send:

1. An array of usernames:

   1. **string**: username

2. **string**: message




ChatEnablePublic (Code 150)
---------------------------

:Code: 150 (0x96)

*Usage*:

:Send:

Nothing


ChatDisablePublic (Code 151)
----------------------------

:Code: 151 (0x97)

*Usage*:

:Send:

Nothing


ChatPublicMessage (Code 152)
----------------------------

:Code: 152 (0x98)

*Usage*:

:Receive:

1. **string**: room
2. **string**: username
3. **string**: message


FileSearchEx (Code 153)
-----------------------

:Code: 153 (0x99)

*Usage*:

:Send:

1. **string**: query

:Receive:

1. **string**: query
2. **uint32**: unknown


CannotConnect (Code 1001)
-----------------------

:Code: 1001 (0x03E9)

*Usage*:

:Send:

1. **uint32**: ticket
2. **string**: username

:Receive:

1. **uint32**: ticket
2. **string**: username


Initialization Messages
=======================

These are the first messages sent after connecting to a peer.


PeerPierceFirewall (Code 0)
---------------------------

:Code: 0 (0x00)

:Usage: Sent after connection was successfully established in response to a ConnectToPeer message. The `ticket` used here should be the ticket from that ConnectToPeer message

:Send/Receive:

1. **uint32**: ticket


PeerInit (Code 1)
-----------------

:Code: 1 (0x01)

:Usage: Sent after direct connection was successfully established (not as a response to a ConnectToPeer received from the server)

:Send/Receive:

1. **string**: username
2. **string**: connection_type
3. **uint32**: ticket


Peer Messages
=============


PeerSharesRequest (Code 4)
--------------------------

:Code: 4 (0x04)

:Usage: Request all the shared files/directories from a peer

:Send/Receive:

No message body


PeerSharesReply (Code 5)
------------------------

:Code: 4 (0x04)

:Usage: Response to PeerSharesRequest

:Send/Receive:

Compressed using gzip:

1.


PeerUserInfoRequest (Code 15)
-----------------------------

:Code: 15 (0x0F)

:Usage: Request information from the peer

:Send/Receive:

No message body


PeerUserInfoReply (Code 16)
---------------------------

:Code: 16 (0x10)

:Usage: Response to PeerUserInfoRequest

:Send/Receive:

1. **string**: description
2. **bool**: has_picture
3. If has_picture==true

   1. **string**: picture

4. **uint32**: slots_free
5. **uint32**: total_uploads
6. **bool**: has_slots_free


PeerTransferRequest (Code 40)
-----------------------------

:Code: 40 (0x28)

:Usage:

:Send/Receive:

1. **uint32**: direction
2. **uint32**: ticket
3. **string**: filename
4. Optional:
   1. **uint64**: filesize . Can be omitted if the direction==1 however a value of `0` can be used in this case as well


PeerTransferReply (Code 41)
---------------------------

:Code: 41 (0x29)

:Usage:

:Send/Receive:

1. **uint32**: ticket
2. **bool**: allowed
3. If allowed==true

   1. **uint32**: filesize

4. If allowed==false

   1. **string**: reason
