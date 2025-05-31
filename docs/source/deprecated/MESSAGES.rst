=================
Protocol Messages
=================

Deprecated listing of messages, messages are auto-generated based on code definitions

.. contents:
   :local

Data Types
==========

The components of the messages use a little-endian byte order.

+---------+-------------+-------+
|  Type   | Python type | bytes |
+=========+=============+=======+
| uint8   | int         | 1     |
+---------+-------------+-------+
| uint16  | int         | 2     |
+---------+-------------+-------+
| uint32  | int         | 4     |
+---------+-------------+-------+
| uint64  | int         | 8     |
+---------+-------------+-------+
| uchar   | int         | 1     |
+---------+-------------+-------+
| int32   | int         | 4     |
+---------+-------------+-------+
| string  | str         |       |
+---------+-------------+-------+
| boolean | bool        | 1     |
+---------+-------------+-------+

String
------

``string`` datatype consists of a ``uint32`` denoting its length followed by the list of bytes. Strings will be UTF-8 encoded / decoded before sending

Array
-----

``array`` datatype consists of a ``uint32`` denoting the amount of elements followed by its elements.

Bytearr
-------

``bytearr`` datatype consists of a ``uint32`` denoting its length followed by the list of bytes.


Data Structures
===============

.. _Attribute:

Attribute
---------

1. **uint32**: key
2. **uint32**: value


.. _FileData:

FileData
--------

1. **uint8**: unknown
2. **string**: filename
3. **uint64**: filesize
4. **string**: extension
5. Array of file attributes:

   1. :ref:`Attribute`: attributes


.. _DirectoryData:

DirectoryData
-------------

1. **string**: name
2. Array of file data:

   1. :ref:`FileData`: files


.. _UserStats:

UserStats
---------

1. **uint32**: avg_speed
2. **uint32**: uploads
3. **uint32**: shared_file_count
4. **uint32**: shared_folder_count


.. _value-tables:

Value Tables
============

Transfer Direction
------------------

This is only used in the :ref:`PeerTransferRequest` message and indicates the direction in which the file should be sent.

+-------+----------+
| Value | Meaning  |
+=======+==========+
| 0     | upload   |
+-------+----------+
| 1     | download |
+-------+----------+

User Status
-----------

Possible statuses:

+-------+---------+
| Value | Status  |
+=======+=========+
| 0     | offline |
+-------+---------+
| 1     | away    |
+-------+---------+
| 2     | online  |
+-------+---------+


.. _table-file-attributes:

File Attributes
---------------

* Lossless: FLAC, WAV
* Compressed: MP3, M4A, AAC, OGG

+-------+-------------------+----------------------+
| Index |      Meaning      |        Usage         |
+=======+===================+======================+
| 0     | bitrate           | compressed           |
+-------+-------------------+----------------------+
| 1     | length in seconds | compressed, lossless |
+-------+-------------------+----------------------+
| 2     | VBR               | compressed           |
+-------+-------------------+----------------------+
| 4     | sample rate       | lossless             |
+-------+-------------------+----------------------+
| 5     | bitness           | lossless             |
+-------+-------------------+----------------------+


.. _table-upload-permissions:

Upload Permissions
------------------

Permissions indicating who is allowed to initiate an upload a file to the user. Optionally returned in the :ref:`PeerUserInfoReply` message.

+-------+-------------------+
| Value |      Meaning      |
+=======+===================+
| 0     | No-one            |
+-------+-------------------+
| 1     | Everyone          |
+-------+-------------------+
| 2     | User list         |
+-------+-------------------+
| 3     | Permitted list    |
+-------+-------------------+


Message Statuses
================

This is a description of possible statuses of each of the messages used by the protocol:

* USED : Message still works and is in use
* DEPRECATED : Message still works but only used by older clients
* DEPRECATED, DEFUNCT : Message no longer works, has no effect or the server doesn't send it any more
* UNKNOWN


.. _server-messages:

Server Messages
===============

.. _Login:

Login (Code 1)
--------------

Login into the server, this should be the first message sent to the server upon connecting

* The ``md5_hash`` parameter in the request is the MD5 hash of the concatenated ``username`` and ``password``
* The ``md5_hash`` parameter in the response is the MD5 hash of the ``password``

:Code: 1 (0x01)
:Status: USED
:Send:
   1. **string**: username
   2. **string**: password
   3. **uint32**: version
   4. **string**: md5_hash
   5. **uint32**: minor_version
:Receive:
   1. **boolean**: result. true on success, false on failure
   2. If result==true

      1. **string**: greeting
      2. **ip**: ip_address
      3. **string**: md5_hash
      4. **uint8**: privileged

   3. If result==false

      1. **string**: failure_reason


.. note::

   Older client versions (at least 149 or below) would not send the ``md5_hash`` and ``minor_version``


.. _SetListenPort:

SetListenPort (Code 2)
----------------------

Advertise our listening ports to the server

Obfuscated port: this part seems to be optional, either it can be omitted completely or both values set to ``0``

:Code: 2 (0x02)
:Status: USED
:Send:
   1. **uint32**: listening_port
   2. Optional:

      1. **uint32**: has_obfuscated_port
      2. **uint32**: obfuscated_port


.. _GetPeerAddress:

GetPeerAddress (Code 3)
-----------------------

Retrieve the IP address/port of a peer. Obfuscated port: this part is optional, either it can be omitted completely or both values set to ``0`` to indicate there is no obfuscated port

If the peer does the server will respond with IP address set to ``0.0.0.0``, port set to ``0``

:Code: 3 (0x03)
:Status: USED
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. **uint32**: ip
   3. **uint32**: port
   4. Optional:

      1. **uint32**: has_obfuscated_port
      2. **uint16**: obfuscated_port


.. _AddUser:

AddUser (Code 5)
----------------

When a user is added with this message the server will automatically send user status updates using the :ref:`GetUserStatus` message.

When a user sends a message to multiple users using the :ref:`PrivateChatMessageUsers` message then this message will only be received if the sender was added first using this message.

To remove a user use the :ref:`RemoveUser` message. Keep in mind that you will still receive status updates in case you are joined in the same room with the user.

:Code: 5 (0x05)
:Status: USED
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. **boolean**: exist
   3. if exists==true

      1. **uint32**: status
      2. :ref:`UserStats`: user_stats
      3. Optional:

         1. **string**: country_code


.. _RemoveUser:

RemoveUser (Code 6)
-------------------

Remove the tracking of user status which was previously added with the :ref:`AddUser` message.

:Code: 6 (0x06)
:Status: USED
:Send:
   1. **string**: username


.. _GetUserStatus:

GetUserStatus (Code 7)
----------------------

Get the user status. The server will automatically send updates for users that we have added with :ref:`AddUser` or which we share a room with.

:Code: 5 (0x05)
:Status: USED
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. **uint32**: status
   3. **boolean**: privileged


.. _IgnoreUser:

IgnoreUser (Code 11)
--------------------

Sent when we want to ignore a user. Received when another user ignores us

:Code: 11 (0x0B)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: username
:Receive:
   1. **string**: username


.. _UnignoreUser:

UnignoreUser (Code 12)
----------------------

Sent when we want to unignore a user. Received when another user unignores us

:Code: 12 (0x0C)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: username
:Receive:
   1. **string**: username


.. _RoomChatMessage:

RoomChatMessage (Code 13)
-------------------------

Used when sending a message to a room or receiving a message from someone (including self) who sent a message to a room

:Code: 13 (0x0D)
:Status: USED
:Send:
   1. **string**: room_name
   2. **string**: message
:Receive:
   1. **string**: room_name
   2. **string**: username
   3. **string**: message


.. _JoinRoom:

JoinRoom (Code 14)
------------------

Used when we want to join a chat room. If the chat room does not exist it will be created. Upon successfully joining the room the server will send the response message

:Code: 14 (0x0E)
:Status: USED
:Send:
   1. **string**: room_name
   2. Optional:

      1. **uint32**: is_private
:Receive:
   1. **string**: room_name
   2. Array of usernames:

      1. **string**: users

   3. Array of user statuses:

      1. **uint32**: users_status

   4. Array of user stats:

      1. :ref:`UserStats`: users_stats

   5. Array of upload slots free:

      1. **uint32**: users_slots_free

   6. Array of user countries:

      1. **string**: users_countries

   7. Optional:

      1. **string**: owner
      2. Array of operators:

         1. **string**: operator


.. _LeaveRoom:

LeaveRoom (Code 15)
-------------------

Used when we want to leave a chat room. The receive message is confirmation that we left the room

:Code: 15 (0x0F)
:Status: USED
:Send:
   1. **string**: room_name
:Receive:
   1. **string**: room_name


.. _UserJoinedRoom:

UserJoinedRoom (Code 16)
------------------------

Received when a user joined a room

:Code: 16 (0x10)
:Status: USED
:Receive:
   1. **string**: room_name
   2. **string**: username
   3. **uint32**: status
   4. :ref:`UserStats`: user_stats
   5. **uint32**: slots_free
   6. **string**: country_code


.. _UserLeftRoom:

UserLeftRoom (Code 17)
----------------------

Received when a user left a room

:Code: 17 (0x11)
:Status: USED
:Receive:
   1. **string**: room_name
   2. **string**: username


.. _ConnectToPeer:

ConnectToPeer (Code 18)
-----------------------

Received when a peer attempted to connect to us but failed and thus is asking us to attempt to connect to them, likewise when we cannot connect to peer we should send this message to indicate to the other peer that he should try connecting to us

:Code: 18 (0x12)
:Status: USED
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


.. _PrivateChatMessage:

PrivateChatMessage (Code 22)
----------------------------

Send or receive a private message. The ``chat_id`` should be used in the :ref:`PrivateChatMessageAck` message to acknowledge the message has been received. If the acknowledgement is not sent the server will repeat the message on the next logon. The ``is_direct`` boolean indicates whether it is the first attempt to send the message, if the server retries then this parameter will be false.

:Code: 22 (0x16)
:Status: USED
:Send:
   1. **string**: username
   2. **string**: message
:Receive:
   1. **uint32**: chat_id
   2. **uint32**: timestamp
   3. **string**: username
   4. **string**: message
   5. Optional:

      1. **boolean**: is_direct


.. _PrivateChatMessageAck:

PrivateChatMessageAck (Code 23)
-------------------------------

Acknowledge we have received a private message after receiving a :ref:`PrivateChatMessage`

:Code: 23 (0x17)
:Status: USED
:Send:
   1. **uint32**: chat_id


.. _FileSearchRoom:

FileSearchRoom (Code 25)
------------------------

Deprecated message for searching a room

:Code: 25 (0x19)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **uint32**: ticket
   2. **uint32**: room_id
   3. **string**: query


.. _FileSearch:

FileSearch (Code 26)
--------------------

This message is received when another user performed a :ref:`RoomSearch` or :ref:`UserSearch` request and we are part of the room or we are the user the user would like to search in.

:Code: 26 (0x1A)
:Status: USED
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

Used to update the online status. Possible values for ``status``: online = 2, away = 1

:Code: 28 (0x1C)
:Status: USED
:Send:
   1. **uint32**: status


.. _Ping:

Ping (Code 32)
--------------

Send a ping to the server to let it know we are still alive (every 5 minutes)

Older server versions would respond to this message with the response message.

:Code: 32 (0x20)
:Status: USED
:Send: Nothing
:Receive: Nothing


.. _SendConnectTicket:

SendConnectTicket (Code 33)
---------------------------

Deprecated predecessor to :ref:`ConnectToPeer`. A peer would send this message to the server when wanting to create a connection to another peer, the server would then pass to this to the

The value of the ``ticket`` parameter would be used in the :ref:`PeerInit` message.

:Code: 33 (0x21)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: username
   2. **uint32**: ticket
:Receive:
   1. **string**: username
   2. **uint32**: ticket


.. _SendDownloadSpeed:

SendDownloadSpeed (Code 34)
---------------------------

Sent by old clients after download has completed. :ref:`SendUploadSpeed` should be used instead. The ``speed`` value should be in bytes per second

:Code: 34 (0x22)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: username
   2. **uint32**: speed


.. _SharedFoldersFiles:

SharedFoldersFiles (Code 35)
----------------------------

Let the server know the amount of files and directories we are sharing. These would be returned in several messages, for example the :ref:`GetUserStats` and :ref:`AddUser` messages

:Code: 35 (0x23)
:Status: USED
:Send:
   1. **uint32**: shared_folder_count
   2. **uint32**: shared_file_count


.. _GetUserStats:

GetUserStats (Code 36)
----------------------

Request a user's statistics. This message will be received automatically for users with which we share a room

:Code: 36 (0x24)
:Status: USED
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. :ref:`UserStats`: user_stats


.. _Kicked:

Kicked (Code 41)
----------------

You were kicked from the server. This message is currently only known to be sent when the user was logged into at another location

:Code: 41 (0x29)
:Status: USED
:Receive: Nothing


.. _UserSearch:

UserSearch (Code 42)
--------------------

Search for a file on a specific user, the user will receive this query in the form of a :ref:`FileSearch` message

:Code: 42 (0x2A)
:Status: USED
:Send:
   1. **string**: username
   2. **uint32**: ticket
   3. **string**: query


.. _DeprecatedGetItemRecommendations:

DeprecatedGetItemRecommendations (Code 50)
------------------------------------------

Similar to :ref:`GetItemRecommendations` except that no score is returned

:Code: 50 (0x32)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: item
:Receive:
   1. **string**: item
   2. Array of item recommendations:

      1. **string**: recommendation


.. _AddInterest:

AddInterest (Code 51)
---------------------

Adds an interest. This is used when requesting recommendations (eg.: :ref:`GetRecommendations`, ...)

:Code: 51 (0x33)
:Status: DEPRECATED
:Receive:
   1. **string**: interest


.. _RemoveInterest:

RemoveInterest (Code 52)
------------------------

Removes an interest previously added with :ref:`AddInterest` message

:Code: 52 (0x34)
:Status: DEPRECATED
:Receive:
   1. **string**: interest


.. _GetRecommendations:

GetRecommendations (Code 54)
----------------------------

Request the server to send a list of recommendations and unrecommendations. A maximum of 100 each will be returned. The score can be negative.

:Code: 54 (0x36)
:Status: DEPRECATED
:Send: Nothing
:Receive:
   1. Array of recommendations:

      1. **string**: recommendation
      2. **int32**: score

   2. Array of non recommendations:

      1. **string**: unrecommendation
      2. **int32**: score


.. _GetInterests:

GetInterests (Code 55)
----------------------

Request the server the list of interests it currently has stored for us. This was sent by older clients during logon, presumably to sync the interests on the client and the server. Deprecated as the client should just advertise all interests after logon using the :ref:`AddInterest` and :ref:`AddHatedInterest` messages

Not known whether the server still responds to this command

:Code: 55 (0x37)
:Status: DEPRECATED, DEFUNCT
:Send: Nothing
:Receive:
   1. Array of interets:

      1. **string**: interest


.. _GetGlobalRecommendations:

GetGlobalRecommendations (Code 56)
----------------------------------

Get the global list of recommendations. This does not take into account interests or hated interests that were previously added and is just a ranking of interests that other users have set

:Code: 56 (0x38)
:Status: DEPRECATED
:Send: Nothing
:Receive:
   1. Array of recommendations:

      1. **string**: recommendation
      2. **int32**: score

   2. Array of non recommendations:

      1. **string**: recommendation
      2. **int32**: score


.. _GetUserInterests:

GetUserInterests (Code 57)
--------------------------

Get the interests and hated interests of a particular user

:Code: 57 (0x39)
:Status: DEPRECATED
:Send:
   1. **string**: username
:Receive:
   1. **string**: username
   2. Array of interests:

      1. **string**: interests

   3. Array of hated interests:

      1. **string**: hated_interests


.. _ExecuteCommand:

ExecuteCommand (Code 58)
------------------------

Send a command to the server.

The command type has only ever been seen as having value ``admin``, the ``arguments`` array contains the subcommand and arguments. Example when banning a user:

* ``command_type`` : ``admin``
* ``arguments``

   * 0 : ``ban``
   * 1 : ``some user``
   * 2 : probably some extra args, perhaps time limit in case of ban, ... (optional)

:Code: 58 (0x3A)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: command_type
   2. Array of arguments:

      1. **string**: argument


.. _RoomList:

RoomList (Code 64)
------------------

Request or receive the list of rooms. This message will be initially sent after logging on but can also be manually requested afterwards. The initial message after logon will only return a limited number of public rooms (only the rooms with 5 or more users).

Parameter ``rooms_private`` excludes private rooms of which we are owner

Parameter ``rooms_private_owned_user_count`` / ``rooms_private_user_count`` should be the amount of users who have joined the private room, not the amount of members

:Code: 42 (0x2A)
:Status: USED
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


.. _ExactFileSearch:

ExactFileSearch (Code 65)
-------------------------

Used by older clients but doesn't return anything. The ``pathname`` is optional but is still required to be sent.

For the message sending: The first 4 parameters are verified, the meaning of the final 5 bytes is unknown

For the message receiving: message is never seen and is based on other documentation (PySlsk)

:Code: 65 (0x41)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **uint32**: ticket
   2. **string**: filename
   3. **string**: pathname
   4. **uint64**: filesize
   5. **uint32**: checksum
   6. **uint8**: unknown
:Receive:
   1. **string**: username
   2. **uint32**: ticket
   3. **string**: filename
   4. **string**: pathname
   5. **uint64**: filesize
   6. **uint32**: checksum
   7. **uint8**: unknown


.. _AdminMessage:

AdminMessage (Code 66)
----------------------

Sent by the admin when the server is going down for example

:Code: 66 (0x42)
:Status: DEPRECATED, DEFUNCT
:Receive:
   1. **string**: message


.. _GetUserList:

GetUserList (Code 67)
---------------------

Gets all users on the server, no longer used

:Code: 67 (0x43)
:Status: DEPRECATED, DEFUNCT
:Send: Nothing
:Receive:
   1. Array of usernames:

      1. **string**: users

   2. Array of user statuses:

      1. **uint32**: users_status

   3. Array of user stats:

      1. :ref:`UserStats`: users_stats

   4. Array of upload slots free:

      1. **uint32**: users_slots_free

   5. Array of user countries:

      1. **string**: users_countries


.. _TunneledMessage:

TunneledMessage (Code 68)
-------------------------

Tunnel a message through the server to a user

:Code: 68 (0x44)
:Status: DEPRECATED, DEFUNCT
:Send:
   1. **string**: username
   2. **uint32**: ticket
   3. **uint32**: code
   4. **string**: message
:Receive:
   1. **string**: username
   2. **uint32**: ticket
   3. **uint32**: code
   4. **ip**: ip
   5. **uint32**: port
   6. **string**: message


.. _PrivilegedUsers:

PrivilegedUsers (Code 69)
-------------------------

List of users with privileges sent after login

:Code: 69 (0x45)
:Status: USED
:Receive:
   1. Array of privileged users on the server

      1. **string**: users


.. _ToggleParentSearch:

ToggleParentSearch (Code 71)
----------------------------

Indicates whether we want to receive :ref:`PotentialParents` messages from the server. A message should be sent to disable if we have found a parent

:Code: 71 (0x47)
:Status: USED
:Send:
   1. **boolean**: enable


.. _ParentIP:

ParentIP (Code 73)
------------------

IP address of the parent. Not sent by newer clients

:Code: 73 (0x49)
:Status: DEPRECATED
:Send:
   1. **ip_address**: ip_address


.. _Unknown80:

Unknown80 (Code 80)
-------------------

Unknown message used by old client versions. The client would establish 2 connections to the server: to one it would send the :ref:`Login` message, to the other this message would be sent. This second connection seemed to be related to the distributed network as the client would automatically disconnect after :ref:`DistributedAliveInterval` had been reached. It would seem like the server would be the client's parent in this case.

After an interval determined by :ref:`DistributionInterval` the client would send another message over this connection which is described below. There's many unknowns in this message and even the types are unknown as many values were just 0, only known value is the last value which is the second listening port these clients used.

:Code: 80 (0x50)
:Status: DEPRECATED, DEFUNCT
:Send:
   Nothing


Distribution message (code as ``uint8``):

:Code: 1 (0x01)
:Send:
   1. **uint32** : unknown1
   2. **uint32** : unknown2
   3. **uint8** : unknown3 (value ``1``)
   4. **uint32** : port


.. _ParentMinSpeed:

ParentMinSpeed (Code 83)
------------------------

Used for calculating the maximum amount of children we can have in the distributed network. If our average upload speed is below this value then we should accept no children. The average upload speed should be determined by the upload speed returned by :ref:`GetUserStats` (with our own username)

:Code: 83 (0x53)
:Status: USED
:Receive:
   1. **uint32**: parent_min_speed


.. _ParentSpeedRatio:

ParentSpeedRatio (Code 84)
--------------------------

Used for calculating the maximum amount of children we can have in the distributed network.

:Code: 84 (0x54)
:Status: USED
:Receive:
   1. **uint32**: parent_speed_ratio


.. _ParentInactivityTimeout:

ParentInactivityTimeout (Code 86)
---------------------------------

Timeout for the distributed parent

:Code: 86 (0x56)
:Status: DEPRECATED
:Receive:

   1. **uint32**: timeout


.. _SearchInactivityTimeout:

SearchInactivityTimeout (Code 87)
---------------------------------

:Code: 87 (0x57)
:Status: DEPRECATED
:Receive:
   1. **uint32**: timeout


.. _MinParentsInCache:

MinParentsInCache (Code 88)
---------------------------

Amount of parents (received through :ref:`PotentialParents`) we should keep in cache. Message has not been seen being sent by the server

:Code: 88 (0x58)
:Status: DEPRECATED, DEFUNCT
:Receive:
   1. **uint32**: amount


.. _DistributionInterval:

DistributionInterval (Code 89)
------------------------------

:Code: 89 (0x59)
:Status: DEPRECATED, DEFUNCT
:Receive:
   1. **uint32**: interval


.. _DistributedAliveInterval:

DistributedAliveInterval (Code 90)
----------------------------------

Interval at which a :ref:`DistributedPing` message should be sent to the children. Most clients don't send this message out

:Code: 90 (0x5A)
:Status: DEPRECATED
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

Checks whether the requesting user has privileges, `time_left` will be `0` in case the user has no privileges, time left in seconds otherwise.

:Code: 92 (0x5C)
:Status: USED
:Send: Nothing
:Receive:
   1. **uint32**: time_left


.. _ServerSearchRequest:

ServerSearchRequest (Code 93)
-----------------------------



:Code: 93 (0x5D)
:Status: USED
:Receive:
   1. **uint8**: distributed_code
   2. **uint32**: unknown
   3. **string**: username
   4. **uint32**: ticket
   5. **string**: query


.. _AcceptChildren:

AcceptChildren (Code 100)
-------------------------

Tell the server whether or not we are accepting any distributed children, the server *should* take this into account when sending :ref:`PotentialParents` messages to other peers.

:Code: 100 (0x64)
:Status: USED
:Send:
   1. **boolean**: accept


.. _PotentialParents:

PotentialParents (Code 102)
---------------------------

:Code: 102 (0x66)
:Status: USED
:Receive:
   1. Array of potential parents:

      1. **string**: username
      2. **ip_address**: ip
      3. **uint32**: port


.. _WishlistSearch:

WishlistSearch (Code 103)
-------------------------

Perform a wishlist search. The interval at which a client should send this message is determined by the :ref:`WishlistInterval` message

:Code: 103 (0x67)
:Status: USED
:Send:
   1. **uint32**: ticket
   2. **string**: query


.. _WishlistInterval:

WishlistInterval (Code 104)
---------------------------

The server lets us know at what interval we should perform wishlist searches (:ref:`WishlistSearch`). Sent by the server after logon

:Code: 104 (0x68)
:Status: USED
:Receive:

   1. **uint32**: interval


.. _GetSimilarUsers:

GetSimilarUsers (Code 110)
--------------------------

Get a list of similar users

:Code: 110 (0x6E)
:Status: DEPRECATED
:Send: Nothing
:Receive:
   1. Array of similar users:

      1. **string**: username
      2. **uint32**: similar_interests_amount


.. _GetItemRecommendations:

GetItemRecommendations (Code 111)
---------------------------------

Get a list of recommendations based on a single interest

:Code: 111 (0x6F)
:Status: DEPRECATED
:Send:
   1. **string**: item
:Receive:
   1. **string**: item
   2. Array of item recommendations:

      1. **string**: recommendation
      2. **int32**: score


.. _GetItemSimilarUsers:

GetItemSimilarUsers (Code 112)
------------------------------

:Code: 112 (0x70)
:Send:
   1. **string**: item
:Receive:
   1. **string**: item
   2. Array of similar users:

      1. **string**: username


.. _RoomTickers:

RoomTickers (Code 113)
----------------------

List of chat room tickers (room wall)

:Code: 113 (0x71)
:Status: USED
:Receive:
   1. **string**: room
   2. Array of room tickers:

      1. **string**: username
      2. **string**: ticker


.. _RoomTickerAdded:

RoomTickerAdded (Code 114)
--------------------------

A ticker has been added to the room (room wall)

:Code: 114 (0x72)
:Status: USED
:Receive:
   1. **string**: room
   2. **string**: username
   3. **string**: ticker


.. _RoomTickerRemoved:

RoomTickerRemoved (Code 115)
----------------------------

A ticker has been removed to the room (room wall)

:Code: 115 (0x73)
:Status: USED
:Receive:
   1. **string**: room
   2. **string**: username


.. _SetRoomTicker:

SetRoomTicker (Code 116)
------------------------

Add or update a ticker for a room (room wall)

:Code: 116 (0x74)
:Status: USED
:Receive:
   1. **string**: room
   2. **string**: ticker


.. note::

   An empty ``ticker`` value is not allowed in most clients. However, the server does accept it and clears the ticker from the room


.. _AddHatedInterest:

AddHatedInterest (Code 117)
---------------------------

Adds an hated interest. This is used when requesting recommendations (eg.: :ref:`GetRecommendations`, ...)

:Code: 117 (0x75)
:Status: DEPRECATED
:Receive:
   1. **string**: hated_interest


.. _RemoveHatedInterest:

RemoveHatedInterest (Code 118)
------------------------------

Removes a hated interest previously added with :ref:`AddHatedInterest` message

:Code: 118 (0x76)
:Status: DEPRECATED
:Receive:
   1. **string**: hated_interest


.. _RoomSearch:

RoomSearch (Code 120)
---------------------

Perform a search query on all users in the given room, this can only be performed if the room was joined first. The server will send a :ref:`FileSearch` to every user in the requested room

:Code: 120 (0x78)
:Status: USED
:Send:
   1. **string**: room
   2. **uint32**: ticket
   3. **string**: query


.. _SendUploadSpeed:

SendUploadSpeed (Code 121)
--------------------------

Sent to the server right after an upload completed. ``speed`` parameter should be in bytes per second. This should not be the global average upload speed but rather the upload speed for that particular transfer. After this message has been sent the server will recalculate the average speed and increase the amount of uploads for your user.

In exception cases, for example if a transfer was failed midway then resumed, only the speed of the resumed part is taken into account. However this might be client dependent.

:Code: 121 (0x79)
:Status: USED
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
   2. **boolean**: privileged


.. _GiveUserPrivileges:

GiveUserPrivileges (Code 123)
-----------------------------

Gift a user privileges. This only works if the user sending the message has privileges and needs to be less than what the gifting user has left, part of its privileges will be taken.

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
:Status: USED
:Send:
   1. **uint32**: level


.. _BranchRoot:

BranchRoot (Code 127)
---------------------

Notify the server who our branch root user is in the distributed network

:Code: 127 (0x7F)
:Status: USED
:Send:
   1. **string**: username


.. _ChildDepth:

ChildDepth (Code 129)
---------------------

See :ref:`DistributedChildDepth`

Note: SoulSeekQt sends the ``depth`` as a ``uint8``

:Code: 129 (0x81)
:Status: DEPRECATED
:Send:
   1. **uint32**: depth


.. _ResetDistributed:

ResetDistributed (Code 130)
---------------------------

Server requests to reset our parent and children

:Code: 127 (0x7F)
:Status: UNKNOWN
:Receive: Nothing


.. _PrivateRoomMembers:

PrivateRoomMembers (Code 133)
-----------------------------

List of all members that are part of the private room (excludes owner)

:Code: 133 (0x85)
:Status: USED
:Receive:
   1. **string**: room
   2. An array of usernames:

      1. **string**: username


.. _PrivateRoomGrantMembership:

PrivateRoomGrantMembership (Code 134)
-------------------------------------

Add another user to the private room. Only operators and the owner can add members to a private room.

This message is also received by all other members in the private room

:Code: 134 (0x86)
:Status: USED
:Send:
   1. **string**: room
   2. **string**: username
:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomRevokeMembership:

PrivateRoomRevokeMembership (Code 135)
--------------------------------------

Remove another user from the private room. Operators can remove regular members but not other operators or the owner. The owner can remove anyone aside from himself (see :ref:`PrivateRoomDropOwnership`).

This message is also received by all other members in the private room

:Code: 135 (0x87)
:Status: USED
:Send:
   1. **string**: room
   2. **string**: username
:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomDropMembership:

PrivateRoomDropMembership (Code 136)
------------------------------------

Drops membership of a private room, this will not do anything for the owner of the room. See :ref:`PrivateRoomDropOwnership` for owners

:Code: 136 (0x88)
:Status: USED
:Send:
   1. **string**: room


.. _PrivateRoomDropOwnership:

PrivateRoomDropOwnership (Code 137)
-----------------------------------

Drops ownership of a private room, this disbands the entire room.

:Code: 137 (0x89)
:Status: USED
:Send:
   1. **string**: room


.. _PrivateRoomMembershipGranted:

PrivateRoomMembershipGranted (Code 139)
---------------------------------------

Received when the current user has been granted membership to a private room

:Code: 139 (0x8B)
:Status: USED
:Receive:
   1. **string**: room


.. _PrivateRoomMembershipRevoked:

PrivateRoomMembershipRevoked (Code 140)
---------------------------------------

Received when the current user had its membership revoked from a private room

:Code: 140 (0x8C)
:Status: USED
:Usage:
:Receive:
   1. **string**: room


.. _TogglePrivateRoomInvites:

TogglePrivateRoomInvites (Code 141)
-----------------------------------

Enables or disables private room invites (through :ref:`PrivateRoomGrantMembership`)

:Code: 141 (0x8D)
:Status: USED
:Usage:
:Send:
   1. **boolean**: enable
:Receive:
   1. **boolean**: enabled


.. _NewPassword:

NewPassword (Code 142)
----------------------

:Code: 142 (0x8E)
:Status: USED
:Send:
   1. **string**: password


.. _PrivateRoomGrantOperator:

PrivateRoomGrantOperator (Code 143)
-----------------------------------

Grant operator privileges to a member in a private room. This message will also be received by all other members in the room (irrelevant of if they are online or not).

:Code: 143 (0x8F)
:Status: USED
:Send:
   1. **string**: room
   2. **string**: username

:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomRevokeOperator:

PrivateRoomRevokeOperator (Code 144)
------------------------------------

Revoke operator privileges from a member in a private room. This message will also be received by all other members in the room (irrelevant of if they are online or not).

:Code: 144 (0x90)
:Status: USED
:Send:
   1. **string**: room
   2. **string**: username

:Receive:
   1. **string**: room
   2. **string**: username


.. _PrivateRoomOperatorGranted:

PrivateRoomOperatorGranted (Code 145)
-------------------------------------

Received when granted operator privileges in a private room

:Code: 145 (0x91)
:Status: USED
:Receive:
   1. **string**: room


.. _PrivateRoomOperatorRevoked:

PrivateRoomOperatorRevoked (Code 146)
-------------------------------------

Received when operator privileges in a private room were revoked

:Code: 146 (0x92)
:Status: USED
:Receive:
   1. **string**: room


.. _PrivateRoomOperators:

PrivateRoomOperators (Code 148)
-------------------------------

List of operators for a private room.

:Code: 148 (0x94)
:Status: USED
:Receive:
   1. **string**: room
   2. An array of usernames:

      1. **string**: username


.. _PrivateChatMessageUsers:

PrivateChatMessageUsers (Code 149)
----------------------------------

Send a private message to a list of users. This message will only be received by users who have added you using the :ref:`AddUser` message first.

:Code: 149 (0x95)
:Status: USED
:Send:
   1. An array of usernames:

      1. **string**: username

   2. **string**: message


.. _EnablePublicChat:

EnablePublicChat (Code 150)
---------------------------

Enables public chat, see :ref:`PublicChatMessage`

:Code: 150 (0x96)
:Status: USED
:Send: Nothing


.. _DisablePublicChat:

DisablePublicChat (Code 151)
----------------------------

Disables public chat, see :ref:`PublicChatMessage`

:Code: 151 (0x97)
:Status: USED
:Send: Nothing


.. _PublicChatMessage:

PublicChatMessage (Code 152)
----------------------------

When public chat is enabled all messages sent to public rooms will also be sent to us using this message. Use :ref:`EnablePublicChat` and :ref:`DisablePublicChat` to disable or enable receiving these messages.

:Code: 152 (0x98)
:Status: USED
:Receive:
   1. **string**: room
   2. **string**: username
   3. **string**: message


.. _GetRelatedSearches:

GetRelatedSearches (Code 153)
-----------------------------

Usually this is sent by the client right after the :ref:`FileSearch` message using the same `query` to retrieve the related searches for that query

:Code: 153 (0x99)
:Status: DEPRECATED
:Send:
   1. **string**: query
:Receive:
   1. **string**: query
   2. Array of related searches:

      1. **string**: related_searches


.. _ExcludedSearchPhrases:

ExcludedSearchPhrases (Code 160)
--------------------------------

Optionally sent by the server after logging on. Search results containing at least one of the phrases (exact match, case insensitive) should be filtered out before being sent.

It is highly recommended to take this filtering into account as not doing so could jeopardize the network.

:Code: 160 (0xA0)
:Status: USED
:Receive:
   1. Array of excluded search phrases:

      1. **string**: phrases


.. _CannotConnect:

CannotConnect (Code 1001)
-------------------------

:Code: 1001 (0x03E9)
:Status: USED
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
:Status: USED
:Receive:
   1. **string**: room_name


.. _peer-init-messages:

Peer Initialization Messages
============================

These are the first messages sent after connecting to a peer.


.. _PeerPierceFirewall:

PeerPierceFirewall (Code 0)
---------------------------

Sent after connection was successfully established in response to a ConnectToPeer message. The ``ticket`` used here
should be the ticket from that :ref:`ConnectToPeer` message

:Code: 0 (0x00)
:Status: USED
:Send/Receive:
   1. **uint32**: ticket


.. _PeerInit:

PeerInit (Code 1)
-----------------

Sent after direct connection was successfully established (not as a response to a :ref:`ConnectToPeer` received from the server)

The ``ticket`` is usually 0 and was filled in with ``ticket`` value from the :ref:`SendConnectTicket` message by older versions of the client

:Code: 1 (0x01)
:Status: USED
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
:Status: USED
:Send/Receive:
   1. Optional

      1. **uint32**: ticket: some clients seem to send a ticket


.. _PeerSharesReply:

PeerSharesReply (Code 5)
------------------------

Response to PeerSharesRequest. The response should include empty parent directories.

:Code: 5 (0x05)
:Status: USED
:Send/Receive:
   Compressed using gzip:

   1. Array of directories:

      1. :ref:`DirectoryData`: directories

   2. **uint32**: unknown: always 0
   3. Optional: Array of locked directories:

      1. :ref:`DirectoryData`: locked_directories


.. _PeerSearchReply:

PeerSearchReply (Code 9)
------------------------

Response to a search request

:Code: 9 (0x09)
:Status: USED
:Send/Receive:
   Compressed using gzip:

   1. **string**: username
   2. **uint32**: ticket
   3. Array of results:

      1. :ref:`FileData`: results

   4. **boolean**: has_slots_free
   5. **uint32**: avg_speed
   6. **uint32**: queue_size
   7. **uint32**: unknown: always 0
   8. Optional: Array of locked results:

      1. :ref:`FileData`: locked_results


.. _PeerUserInfoRequest:

PeerUserInfoRequest (Code 15)
-----------------------------

Request information from the peer

:Code: 15 (0x0F)
:Status: USED
:Send/Receive: Nothing


.. _PeerUserInfoReply:

PeerUserInfoReply (Code 16)
---------------------------

Response to :ref:`PeerUserInfoRequest`. Possible values for ``upload_permissions`` can be found :ref:`here <table-upload-permissions>`

:Code: 16 (0x10)
:Status: USED
:Send/Receive:
   1. **string**: description
   2. **boolean**: has_picture
   3. If has_picture==true

      1. **bytearr**: picture

   4. **uint32**: upload_slots
   5. **uint32**: queue_size
   6. **boolean**: has_slots_free
   7. Optional:

      1. **uint32**: upload_permissions


.. _PeerDirectoryContentsRequest:

PeerDirectoryContentsRequest (Code 36)
--------------------------------------

Request the file contents of a directory.

:Code: 36 (0x24)
:Status: USED
:Send/Receive:
   1. **uint32**: ticket
   2. **string**: directory


.. _PeerDirectoryContentsReply:

PeerDirectoryContentsReply (Code 37)
------------------------------------

Reply to :ref:`PeerDirectoryContentsRequest`.

Although the returned directories is an array it will only contain one element and will not list files from subdirectories.

:Code: 37 (0x25)
:Status: USED
:Send/Receive:
   1. **uint32**: ticket
   2. **string**: directory
   3. Array of directory data:

      1. :ref:`DirectoryData`: directories


.. _PeerTransferRequest:

PeerTransferRequest (Code 40)
-----------------------------

``filesize`` can be omitted if the direction==1 however a value of ``0`` can be used in this case as well

:Code: 40 (0x28)
:Status: USED
:Send/Receive:
   1. **uint32**: direction
   2. **uint32**: ticket
   3. **string**: filename
   4. Optional:

      1. **uint64**: filesize


.. _PeerTransferReply:

PeerTransferReply (Code 41)
---------------------------

:Code: 41 (0x29)
:Status: USED
:Send/Receive:
   1. **uint32**: ticket
   2. **boolean**: allowed
   3. If allowed==true

      1. **uint32**: filesize

   4. If allowed==false

      1. **string**: reason


.. _PeerTransferQueue:

PeerTransferQueue (Code 43)
---------------------------

Request to place the provided transfer of ``filename`` in the queue

:Code: 43 (0x2B)
:Status: USED
:Send/Receive:
   1. **string**: filename


.. _PeerPlaceInQueueReply:

PeerPlaceInQueueReply (Code 44)
-------------------------------

Response to :ref:`PeerPlaceInQueueRequest`

:Code: 44 (0x2C)
:Status: USED
:Send/Receive:
   1. **string**: filename
   2. **uint32**: place


.. _PeerUploadFailed:

PeerUploadFailed (Code 46)
--------------------------

Sent when uploading failed

:Code: 46 (0x2E)
:Status: USED
:Send/Receive:
   1. **string**: filename


.. _PeerTransferQueueFailed:

PeerTransferQueueFailed (Code 50)
---------------------------------

Sent when placing the transfer in queue failed

:Code: 50 (0x32)
:Status: USED
:Send/Receive:
   1. **string**: filename
   2. **string**: reason


.. _PeerPlaceInQueueRequest:

PeerPlaceInQueueRequest (Code 51)
---------------------------------

Request the place of the transfer in the queue.

:Code: 51 (0x33)
:Status: USED
:Send/Receive:
   1. **string**: filename


.. _PeerUploadQueueNotification:

PeerUploadQueueNotification (Code 52)
-------------------------------------

:Code: 51 (0x33)
:Status: DEPRECATED
:Send/Receive: Nothing


.. _distributed-messages:

Distributed Messages
====================


.. _DistributedPing:

DistributedPing (Code 0)
------------------------

Ping request from the parent. Most clients do not send this.

:Code: 0 (0x00)
:Status: DEPRECATED
:Send/Receive: Nothing


.. _DistributedSearchRequest:

DistributedSearchRequest (Code 3)
---------------------------------

Search request coming from the parent

:Code: 3 (0x03)
:Status: USED
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
:Status: USED
:Send/Receive:
   1. **uint32**: level


.. _DistributedBranchRoot:

DistributedBranchRoot (Code 5)
------------------------------

Distributed branch root

:Code: 5 (0x05)
:Status: USED
:Send/Receive:
   1. **string**: root


.. _DistributedChildDepth:

DistributedChildDepth (Code 7)
------------------------------

Used by SoulSeek NS and still passed on by SoulSeekQt, sent to the parent upon connecting to that parent (although unclear what happens when a peer attaches to another parent while already having children). The parent should increase the ``depth`` by 1 until it reaches the branch root, which should increase by 1 and send it to the server as a :ref:`ChildDepth` message.

:Code: 7 (0x07)
:Status: DEPRECATED
:Send/Receive:
   1. **string**: depth


.. _DistributedServerSearchRequest:

DistributedServerSearchRequest (Code 93)
----------------------------------------

This message exists internally only for deserialization purposes and this is actually a :ref:`ServerSearchRequest`

:Code: 93 (0x5D)
:Status: USED
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
