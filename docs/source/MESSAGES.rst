========
Messages
========

.. contents:
   :local

Data Types
==========

The components of the messages use a little-endian byte order.

+--------+-------------+-------+
| Type   | Python type | bytes |
+========+=============+=======+
| uint8  | int         | 1     |
+--------+-------------+-------+
| uint16 | int         | 2     |
+--------+-------------+-------+
| uint32 | int         | 4     |
+--------+-------------+-------+
| uint64 | int         | 8     |
+--------+-------------+-------+
| uchar  | int         | 1     |
+--------+-------------+-------+
| string | str         |       |
+--------+-------------+-------+
| bool   | bool        | 1     |
+--------+-------------+-------+

String
------

String datatype consists of a ``uint32`` denoting its length followed by the list of bytes.

Array
-----

Array datatype consists of a ``uint32`` denoting the amount of elements followed by its elements.


Data Structures
===============

Attribute
---------

1. **uint32**: key
2. **uint32**: value


FileData
--------

1. **uint8**: unknown
2. **string**: filename
3. **uint64**: filesize
4. **string**: extension
5. Array of file attributes:

   1. **Attribute**: attributes


DirectoryData
-------------

1. **string**: name
2. Array of file data:

   1. **FileData**: files


.. _server-messages:

Server Messages
===============

.. _Login:

Login (Code 1)
--------------

Login into the server, this should be the first message sent to the server upon connecting

:Code: 1 (0x01)
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


.. _SetListenPort:

SetListenPort (Code 2)
----------------------

Advertise our listening ports to the server

Obfuscated port: this part seems to be optional, either it can be omitted completely or both values set to 0

:Code: 2 (0x02)
:Send:
   1. **uint32**: listening port
   2. Optional:

      1. **uint32**: has obfuscated listening port
      2. **uint32**: obfuscated listening port


.. _GetPeerAddress:

GetPeerAddress (Code 3)
-----------------------

Retrieve the IP address/port of a peer. Obfuscated port: this part seems to be optional, either it can be omitted completely or both values set to ``0``

If the peer does not exist we will receive a response with IP address, port set to ``0``


:Code: 3 (0x03)
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. **uint32**: IP address
   3. **uint32**: listening port
   4. Optional:

      1. **uint32**: has obfuscated listening port
      2. **uint32**: obfuscated listening port


.. _AddUser:

AddUser (Code 5)
----------------

Track a user

:Code: 5 (0x05)
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


.. _RemoveUser:

RemoveUser (Code 6)
-------------------

Untrack a user

:Code: 6 (0x06)
:Send:
   1. **string**: username


.. _GetUserStatus:

GetUserStatus (Code 7)
----------------------

Get the user status, we will get updates on this automatically if we have performed AddUser

:Code: 5 (0x05)
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. **uint32**: status
   3. **bool**: privileged


.. _ChatRoomMessage:

ChatRoomMessage (Code 13)
-------------------------

Used to send/receive a message to/from a room

:Code: 13 (0x0D)
:Send:
   1. **string**: room_name
   2. **string**: message
:Receive:
   1. **string**: room_name
   2. **string**: username
   3. **string**: message


.. _ChatJoinRoom:

ChatJoinRoom (Code 14)
----------------------

Used when we want to join a chat room

:Code: 14 (0x0E)
:Send:
   1. **string**: room_name
   2. Optional:

      1. **uint32**: is_private
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


.. _ChatLeaveRoom:

ChatLeaveRoom (Code 15)
-----------------------

Used when we want to leave a chat room. The receive is for confirmation

:Code: 15 (0x0F)
:Send:
   1. **string**: room_name
:Receive:
   1. **string**: room_name


.. _ChatUserJoinedRoom:

ChatUserJoinedRoom (Code 16)
----------------------------

Received when a user joined a room

:Code: 16 (0x10)
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


.. _ChatUserLeftRoom:

ChatUserLeftRoom (Code 17)
--------------------------

Received when a user left a room

:Code: 17 (0x11)
:Receive:
   1. **string**: room_name
   2. **string**: username


.. _ConnectToPeer:

ConnectToPeer (Code 18)
-----------------------

Received when a peer attempted to connect to us but failed and thus is asking us to attempt to connect to them

:Code: 18 (0x12)
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


.. _ChatPrivateMessage:

ChatPrivateMessage (Code 22)
----------------------------

Send or receive a private message

:Code: 22 (0x16)
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


.. _ChatAckPrivateMessage:

ChatAckPrivateMessage (Code 23)
-------------------------------

Acknowledge we have received a private message

:Code: 23 (0x17)
:Send:
   1. **uint32**: chat_id


.. _FileSearch:

FileSearch (Code 26)
--------------------

Unknown, file searches usually come from the distributed connection or ServerSearch message

:Code: 26 (0x1A)
:Send:
   1. **uint32**: ticket
   2. **string**: query
:Receive:
   1. **string**: username
   2. **uint32**: ticket
   3. **string**: query


.. _SetStatus:

SetStatus (Code 28)
-------------------

Update our status

:Code: 28 (0x1C)
:Send:
   1. **uint32**: status


.. _Ping:

Ping (Code 32)
--------------

Send a ping to the server to let it know we are still alive (every 5 minutes)

:Code: 32 (0x20)
:Send: Nothing


.. _SharedFoldersFiles:

SharedFoldersFiles (Code 35)
----------------------------

Let the server know the amount of files and directories we are sharing

:Code: 35 (0x23)
:Send:
   1. **uint32**: shared_directories
   2. **uint32**: shared_files


.. _GetUserStats:

GetUserStats (Code 36)
----------------------

Get more user information, we will automatically receive updates if we added a user using AddUser

:Code: 36 (0x24)
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. **uint32**: average_speed
   3. **uint64**: download_number
   4. **uint32**: shared_files
   5. **uint32**: shared_directories


.. _Kicked:

Kicked (Code 41)
----------------

You were kicked from the server. This message is sent when the user was logged into at another location

:Code: 42 (0x2A)
:Receive: Nothing


.. _UserSearch:

UserSearch (Code 42)
--------------------

:Code: 42 (0x2A)
:Send:
   1. **string**: username
   2. **uint32**: ticket
   3. **string**: query


.. _RoomList:

RoomList (Code 64)
------------------

:Code: 42 (0x2A)
:Send: Nothing
:Receive:
   1. Array of room names:

      1. **string**: rooms

   2. Array of users count in ``rooms``:

      1. **uint32**: rooms_user_count

   3. Array of owned private rooms:

      1. **string**: rooms_private_owned

   4. Array of users count in ``rooms_private_owned``:

      1. **uint32**: rooms_private_owned_user_count

   5. Array of private rooms we are a member of:

      1. **string**: rooms_private

   6. Array of users count in ``rooms_private``:

      1. **uint32**: rooms_private_user_count

   7. Array of rooms in which we are operator:

      1. **string**: rooms_private_operated


.. _PrivilegedUsers:

PrivilegedUsers (Code 69)
-------------------------

Indicates whether we want to receive `PotentialParents` messages from the server. A message should be sent to disable if we have found a parent

:Code: 69 (0x45)
:Receive:
   1. Array of privileged users on the server

      1. **string**: users


.. _ToggleParentSearch:

ToggleParentSearch (Code 71)
----------------------------

Indicates whether we want to receive :ref:`PotentialParents` messages from the server. A message should be sent to disable if we have found a parent

:Code: 71 (0x47)
:Send:
   1. **bool**: enable


.. _ParentIP:

ParentIP (Code 73)
------------------

IP address of the parent. Not sent by newer clients

:Code: 73 (0x49)
:Send:
   1. **uint32**: ip_address


.. _ParentMinSpeed:

ParentMinSpeed (Code 83)
------------------------

:Code: 83 (0x53)
:Receive:
   1. **uint32**: parent_min_speed


.. _ParentSpeedRatio:

ParentSpeedRatio (Code 84)
--------------------------

:Code: 84 (0x54)
:Receive:
   1. **uint32**: parent_speed_ratio


.. _ParentInactivityTimeout:

ParentInactivityTimeout (Code 86)
---------------------------------

Timeout for the distributed parent

:Code: 86 (0x56)
:Receive:

   1. **uint32**: timeout


.. _SearchInactivityTimeout:

SearchInactivityTimeout (Code 87)
---------------------------------

:Code: 87 (0x57)
:Receive:
   1. **uint32**: timeout


.. _MinParentsInCache:

MinParentsInCache (Code 88)
---------------------------

Amount of parents (received through PotentialParents) we should keep in cache. Message has not been seen yet being sent by the server

:Code: 88 (0x58)
:Receive:
   1. **uint32**: amount


.. _DistributedAliveInterval:

DistributedAliveInterval (Code 90)
----------------------------------

:Code: 90 (0x5A)
:Receive:
   1. **uint32**: interval


.. _AddPrivilegedUser:

AddPrivilegedUser (Code 91)
---------------------------

:Code: 91 (0x5B)
:Send:
   1. **string**: username


.. _CheckPrivileges:

CheckPrivileges (Code 92)
-------------------------

:Code: 92 (0x5C)
:Send: Nothing
:Receive:
   1. **uint32**: time_left


.. _ServerSearchRequest:

ServerSearchRequest (Code 93)
-----------------------------

:Code: 93 (0x5D)
:Receive:
   1. **uint8**: distributed_code
   2. **uint32**: unknown
   3. **string**: username
   4. **uint32**: ticket
   5. **string**: query


.. _AcceptChildren:

AcceptChildren (Code 100)
-------------------------

:Code: 100 (0x64)
:Send:
   1. **bool**: accept


.. _PotentialParents:

PotentialParents (Code 102)
---------------------------

:Code: 102 (0x66)
:Receive:
   1. Array of potential parents:

      1. **string**: username
      2. **ip_address**: ip
      3. **uint32**: port


.. _WishlistSearch:

WishlistSearch (Code 103)
-------------------------

Perform a wishlist search

:Code: 103 (0x67)
:Send:
   1. **uint32**: username
   2. **string**: query


.. _WishlistInterval:

WishlistInterval (Code 104)
---------------------------

The server lets us know at what interval we should perform wishlist searches

:Code: 104 (0x68)
:Receive:

   1. **uint32**: interval


.. _GetSimilarUsers:

GetSimilarUsers (Code 110)
--------------------------

:Code: 110 (0x6E)
:Send: Nothing
:Receive:
   1. Array of similar users:

      1. **string**: username
      2. **uint32**: status


.. _GetItemRecommendations:

GetItemRecommendations (Code 111)
---------------------------------

:Code: 111 (0x6F)
:Send:
   1. **string**: recommendation
:Receive:
   1. Array of item recommendations:

      1. **string**: recommendation
      2. **uint32**: number


.. _ChatRoomTickers:

ChatRoomTickers (Code 113)
--------------------------

List of chat room tickers (room wall)

:Code: 113 (0x71)
:Receive:
   1. **string**: room
   2. Array of room tickers:

      1. **string**: username
      2. **string**: ticker


.. _ChatRoomTickerAdded:

ChatRoomTickerAdded (Code 114)
------------------------------

A ticker has been added to the room (room wall)

:Code: 114 (0x72)
:Receive:
   1. **string**: room
   2. **string**: username
   3. **string**: ticker


.. _ChatRoomTickerRemoved:

ChatRoomTickerRemoved (Code 115)
--------------------------------

A ticker has been removed to the room (room wall)

:Code: 115 (0x73)
:Receive:
   1. **string**: room
   2. **string**: username


.. _ChatRoomTickerSet:

ChatRoomTickerSet (Code 116)
----------------------------

Add or update a ticker for a room (room wall)

:Code: 116 (0x74)
:Receive:
   1. **string**: room
   2. **string**: ticker


.. _ChatRoomSearch:

ChatRoomSearch (Code 120)
-------------------------

:Code: 120 (0x78)
:Send:
   1. **string**: room
   2. **uint32**: ticket
   3. **string**: query


.. _SendUploadSpeed:

SendUploadSpeed (Code 121)
--------------------------

Send upload speed, sent to the server right after an upload completed

:Code: 121 (0x79)
:Send:
   1. **uint32**: speed


.. _GetUserPrivileges:

GetUserPrivileges (Code 122)
----------------------------

Retrieve whether a user has privileges

:Code: 122 (0x7A)
:Send: Nothing
:Receive:
   1. **string**: username
   2. **bool**: privileged


.. _GiveUserPrivileges:

GiveUserPrivileges (Code 123)
-----------------------------

:Code: 123 (0x7B)
:Send:
   1. **string**: username
   2. **uint32**: days

.. _PrivilegesNotification:

PrivilegesNotification (Code 124)
---------------------------------

:Code: 124 (0x7C)
:Send:
   1. **uint32**: notification_id
   2. **string**: username


.. _PrivilegesNotificationAck:

PrivilegesNotificationAck (Code 125)
------------------------------------

:Code: 125 (0x7D)
:Send:
   1. **uint32**: notification_id


.. _BranchLevel:

BranchLevel (Code 126)
----------------------

Notify the server which branch level we are at in the distributed network

:Code: 126 (0x7E)
:Send:
   1. **uint32**: level


.. _BranchRoot:

BranchRoot (Code 127)
---------------------

Notify the server who our branch root user is in the distributed network

:Code: 127 (0x7F)
:Send:
   1. **string**: username


.. _ChildDepth:

ChildDepth (Code 129)
---------------------

:Code: 129 (0x81)
:Send:
   1. **uint32**: depth


.. _PrivateRoomUsers:

PrivateRoomUsers (Code 133)
---------------------------

List of all users that are part of the private room

:Code: 133 (0x85)
:Receive:
   1. **string**: room
   2. An array of usernames:

      1. **string**: username


.. _PrivateRoomAddUser:

PrivateRoomAddUser (Code 134)
-----------------------------

Add another user to the private room. Only operators and the owner can add members to a private room

:Code: 134 (0x86)
:Send:
   1. **string**: room
   2. **string**: username
:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomRemoveUser:

PrivateRoomRemoveUser (Code 135)
--------------------------------

Remove another user from the private room. Operators can remove regular members but not other operators or the owner. The owner can remove anyone aside from himself (see `PrivateRoomDropOwnership`).

:Code: 135 (0x87)
:Send:
   1. **string**: room
   2. **string**: username
:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomDropMembership:

PrivateRoomDropMembership (Code 136)
------------------------------------

:Code: 136 (0x88)
:Send:
   1. **string**: room


.. _PrivateRoomDropOwnership:

PrivateRoomDropOwnership (Code 137)
-----------------------------------

Drops ownership of a private room, this disbands the entire room.

:Code: 137 (0x89)
:Send:
   1. **string**: room


.. _PrivateRoomAdded:

PrivateRoomAdded (Code 139)
---------------------------

The current user was added to the private room

:Code: 139 (0x8B)
:Receive:
   1. **string**: room


.. _PrivateRoomRemoved:

PrivateRoomRemoved (Code 140)
-----------------------------

The current user was removed from the private room

:Code: 140 (0x8C)
:Usage:
:Receive:
   1. **string**: room


.. _TogglePrivateRooms:

TogglePrivateRooms (Code 141)
-----------------------------

Enables or disables private room invites (through `PrivateRoomAddUser`)

:Code: 141 (0x8D)
:Usage:
:Send:
   1. **bool**: enable
:Receive:
   1. **bool**: enabled


.. _NewPassword:

NewPassword (Code 142)
----------------------

:Code: 142 (0x8E)
:Send:
   1. **string**: password


.. _PrivateRoomAddOperator:

PrivateRoomAddOperator (Code 143)
---------------------------------

:Code: 143 (0x8F)
:Send:
   1. **string**: room
   2. **string**: username

:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomRemoveOperator:

PrivateRoomRemoveOperator (Code 144)
------------------------------------

:Code: 144 (0x90)
:Send:
   1. **string**: room
   2. **string**: username

:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomOperatorAdded:

PrivateRoomOperatorAdded (Code 145)
-----------------------------------

:Code: 145 (0x91)
:Receive:
   1. **string**: room


.. _PrivateRoomOperatorRemoved:

PrivateRoomOperatorRemoved (Code 146)
-------------------------------------

:Code: 146 (0x92)
:Receive:
   1. **string**: room


.. _PrivateRoomOperators:

PrivateRoomOperators (Code 148)
-------------------------------

:Code: 148 (0x94)
:Receive:
   1. **string**: room
   2. An array of usernames:

      1. **string**: username



.. _ChatMessageUsers:

ChatMessageUsers (Code 149)
---------------------------

:Code: 149 (0x95)
:Send:
   1. An array of usernames:

      1. **string**: username

   2. **string**: message




.. _ChatEnablePublic:

ChatEnablePublic (Code 150)
---------------------------

:Code: 150 (0x96)
:Send: Nothing


.. _ChatDisablePublic:

ChatDisablePublic (Code 151)
----------------------------

:Code: 151 (0x97)
:Send: Nothing


.. _ChatPublicMessage:

ChatPublicMessage (Code 152)
----------------------------

:Code: 152 (0x98)
:Receive:
   1. **string**: room
   2. **string**: username
   3. **string**: message


.. _FileSearchEx:

FileSearchEx (Code 153)
-----------------------

:Code: 153 (0x99)
:Send:
   1. **string**: query
:Receive:
   1. **string**: query
   2. **uint32**: unknown


.. _CannotConnect:

CannotConnect (Code 1001)
-------------------------

:Code: 1001 (0x03E9)
:Send:
   1. **uint32**: ticket
   2. **string**: username
:Receive:
   1. **uint32**: ticket
   2. **string**: username


.. _CannotCreateRoom:

CannotCreateRoom (Code 1003)
----------------------------

Sent by the server when attempting to create/join a private room which already exists or the user is not part of

:Code: 1003 (0x03EB)
:Receive:
   1. **string**: room_name


.. _peer-init-messages:

Peer Initialization Messages
============================

These are the first messages sent after connecting to a peer.


.. _PeerPierceFirewall:

PeerPierceFirewall (Code 0)
---------------------------

Sent after connection was successfully established in response to a ConnectToPeer message. The `ticket` used here should be the ticket from that ConnectToPeer message

:Code: 0 (0x00)
:Send/Receive:
   1. **uint32**: ticket


.. _PeerInit:

PeerInit (Code 1)
-----------------

Sent after direct connection was successfully established (not as a response to a ConnectToPeer received from the server)

:Code: 1 (0x01)
:Send/Receive:
   1. **string**: username
   2. **string**: connection_type
   3. **uint32**: ticket


.. _peer-messages:

Peer Messages
=============


.. _PeerSharesRequest:

PeerSharesRequest (Code 4)
--------------------------

Request all shared files/directories from a peer

:Code: 4 (0x04)
:Send/Receive:
   1. Optional

      1. **uint32**: ticket: some clients seem to send a ticket


.. _PeerSharesReply:

PeerSharesReply (Code 5)
------------------------

Response to PeerSharesRequest

:Code: 5 (0x05)
:Send/Receive:
   Compressed using gzip:

   1. Array of directories:

      1. **DirectoryData**: directories

   2. **uint32**: unknown: always 0
   3. Optional: Array of locked directories:

      1. **DirectoryData**: locked_directories


.. _PeerSearchReply:

PeerSearchReply (Code 9)
------------------------

Response to a search request

:Code: 9 (0x09)
:Send/Receive:
   Compressed using gzip:

   1. **string**: username
   2. **uint32**: ticket
   3. Array of results:

      1. **FileData**: results

   4. **bool**: has_slots_free
   5. **uint32**: avg_speed
   6. **uint32**: queue_size
   7. **uint32**: unknown: always 0
   8. Optional: Array of locked results:

      1. **FileData**: locked_results


.. _PeerUserInfoRequest:

PeerUserInfoRequest (Code 15)
-----------------------------

Request information from the peer

:Code: 15 (0x0F)
:Send/Receive: Nothing


.. _PeerUserInfoReply:

PeerUserInfoReply (Code 16)
---------------------------

Response to PeerUserInfoRequest

:Code: 16 (0x10)
:Send/Receive:
   1. **string**: description
   2. **bool**: has_picture
   3. If has_picture==true

      1. **string**: picture

   4. **uint32**: slots_free
   5. **uint32**: total_uploads
   6. **bool**: has_slots_free


.. _PeerDirectoryContentsRequest:

PeerDirectoryContentsRequest (Code 36)
--------------------------------------

Request the file contents of a directory

:Code: 36 (0x24)
:Send/Receive:
   1. **uint32**: ticket
   2. **string**: directory


.. _PeerDirectoryContentsReply:

PeerDirectoryContentsReply (Code 36)
--------------------------------------

Request the file contents of a directory

:Code: 36 (0x24)
:Send/Receive:
   1. **uint32**: ticket
   2. **string**: directory
   3. Array of directory data:

      1. **DirectoryData**: directories


.. _PeerTransferRequest:

PeerTransferRequest (Code 40)
-----------------------------

:Code: 40 (0x28)
:Send/Receive:
   1. **uint32**: direction
   2. **uint32**: ticket
   3. **string**: filename
   4. Optional:

      1. **uint64**: filesize . Can be omitted if the direction==1 however a value of `0` can be used in this case as well


.. _PeerTransferReply:

PeerTransferReply (Code 41)
---------------------------

:Code: 41 (0x29)
:Send/Receive:
   1. **uint32**: ticket
   2. **bool**: allowed
   3. If allowed==true

      1. **uint32**: filesize

   4. If allowed==false

      1. **string**: reason


.. _PeerTransferQueue:

PeerTransferQueue (Code 43)
---------------------------

Request to place the provided transfer of `filename` in the queue

:Code: 43 (0x2B)
:Send/Receive:
   1. **string**: filename


.. _PeerPlaceInQueueReply:

PeerPlaceInQueueReply (Code 44)
-------------------------------

Response to PeerPlaceInQueueRequest

:Code: 44 (0x2C)
:Send/Receive:
   1. **string**: filename
   2. **uint32**: place


.. _PeerUploadFailed:

PeerUploadFailed (Code 46)
--------------------------

Sent when uploading failed

:Code: 46 (0x2E)
:Send/Receive:
   1. **string**: filename


.. _PeerTransferQueueFailed:

PeerTransferQueueFailed (Code 50)
---------------------------------

Sent when placing the transfer in queue failed

:Code: 50 (0x32)
:Send/Receive:
   1. **string**: filename
   2. **string**: reason


.. _PeerPlaceInQueueRequest:

PeerPlaceInQueueRequest (Code 51)
---------------------------------

Request the place of the transfer in the queue.

:Code: 51 (0x33)
:Send/Receive:
   1. **string**: filename


.. _PeerUploadQueueNotification:

PeerUploadQueueNotification (Code 52)
-------------------------------------

:Code: 51 (0x33)
:Send/Receive: Nothing


.. _distributed-messages:

Distributed Messages
====================


.. _DistributedPing:

DistributedPing (Code 0)
------------------------

Ping request from the parent. Most clients do not send this.

:Code: 0 (0x00)
:Send/Receive: Nothing


.. _DistributedSearchRequest:

DistributedSearchRequest (Code 3)
---------------------------------

Search request coming from the parent

:Code: 3 (0x03)
:Send/Receive:
   1. **uint32**: unknown: unknown value, seems like this is always 0x31
   2. **string**: username
   3. **uint32**: ticket
   4. **string**: query


.. _DistributedBranchLevel:

DistributedBranchLevel (Code 4)
-------------------------------

Distributed branch level

:Code: 4 (0x04)
:Send/Receive:
   1. **uint32**: level


.. _DistributedBranchRoot:

DistributedBranchRoot (Code 5)
------------------------------

Distributed branch root

:Code: 5 (0x05)
:Send/Receive:
   1. **string**: root


.. _DistributedChildDepth:

DistributedChildDepth (Code 7)
------------------------------

How many children the peer has (unverified). This is sent by some clients to the parent after they are added and updates are sent afterwards. Usage is a unknown.

:Code: 7 (0x07)
:Send/Receive:
   1. **string**: depth


.. _DistributedServerSearchRequest:

DistributedServerSearchRequest (Code 93)
----------------------------------------

This message exists internally only for deserialization purposes and this is actually a `ServerSearchRequest`.

:Code: 93 (0x5D)
:Send/Receive:
   1. **uint8**: distributed_code
   2. **uint32**: unknown: unknown value, seems like this is always 0x31
   3. **string**: username
   4. **uint32**: ticket
   5. **string**: query


.. _file-messages:

File Messages
=============

File connection does not have a message format but after peer initialization two values are exchanged:

1. **uint32**: ticket
2. **uint64**: offset
