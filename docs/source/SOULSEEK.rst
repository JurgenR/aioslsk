==============
SoulSeek Flows
==============

.. contents:

This document describes different flows and details for the SoulSeek protocol


Server Connection and Logon
===========================

* SoulSeekQt: server.slsknet.org:2416
* SoulSeek 157: server.slsknet.org:2242

Establishing a connection and logging on:

1. Open a TCP connection to the server
2. Open up at least one listening connection (see :ref:`peer-connections` for more info)
3. Send the :ref:`Login`: command on the server socket

A login response will be received which determines whether the login was successful along with the following commands providing some information:

* :ref:`RoomList`
* :ref:`ParentMinSpeed`
* :ref:`ParentSpeedRatio`
* :ref:`WishlistInterval`
* :ref:`PrivilegedUsers`

After the response we send the following messages back to the server with some information about us:

* :ref:`CheckPrivileges` : Check if we have privileges
* :ref:`SetListenPort` : The listening port(s), obfuscated and non-obfuscated
* :ref:`SetStatus` : Our status (offline, away, available)
* :ref:`SharedFoldersFiles` : Number of directories and files we are sharing
* :ref:`AddUser` : Using our own username as parameter

We also send messages to advertise we have no parent:

* :ref:`ToggleParentSearch` : Should initually be true
* :ref:`BranchRoot` : Initially our own username
* :ref:`BranchLevel` : Initially should be ``0``
* :ref:`AcceptChildren` : Accept child connections


After connection is complete, send a :ref:`Ping` command to the server every 5 minutes.

Exception Cases
---------------

* No check on hash seems currently performed
* No check on password length seems currently performed (empty password allowed)
* Logon with an empty username results in failure reason ``INVALIDUSERNAME``
* If the user was previously logged in with and the password does not match results in failure reason ``INVALIDPASS``
* If the credentials are valid but the user is logged in elsewhere the other user will receive message :ref:`Kicked` and the connection will be terminated

Disconnecting
=============

Upon disconnect the user gets logged out:

1. Server: Change the user status to Offline
2. Server: Remove the user from all joined rooms
3. Server: Send :ref:`GetUserStatus` to all users currently tracking the disconnected

TODO: Which values are reset?


.. _peer-connections:

Peer Connections
================

All peer connections use the TCP protocol. The SoulSeek protocol defines 3 types of connections with each its own set of messages. The type of connection is established during the peer initialization message:

* Peer (``P``) : Peer to peer connection for messaging
* Distributed (``D``) : Distributed network connections
* File (``F``) : Peer to peer connection for file transfer

To accept connections from incoming peers there should be at least one listening port opened. However newer clients will open two ports: a non-obfuscated and an obfuscated port.

The obfuscated port is not mandatory and is usually just the obfuscated port + 1. Normally any port can be picked, both ports can be made known to the server using the :ref:`SetListenPort` message.

When a peer connection is accepted on the obfuscated port all messaging should be obfuscated with each their own key, this only applies to peer connection though (``P``). Distributed (``D``) and file (``F``) connections are not obfuscated aside from the :ref:`peer-init-messages`.


.. _connecting-to-peer:

Connecting to a peer
--------------------

The process uses the server to request the IP as well as a middle man in case we fail to connect to the other peer. To obtain the IP address and port of the peer the :ref:`GetPeerAddress` message is first requested from the server.

We can connect to them:

1. Attempt to connect to the peer -> connection established
2. Generate a ticket number
3. Send :ref:`PeerInit` over the peer connection (ticket, username, connection_type)

We cannot connect to them, but they can connect to us:

1. Attempt to connect to the peer -> connection failure
2. Generate a ticket number, story the associated information (username, connection_type)
3. Send :ref:`ConnectToPeer` to the server(ticket, username, connection_type)
4. Incoming connection from peer -> connection is established
5. Receive :ref:`PeerPierceFirewall` over the peer connection (ticket)
6. Look up the ticket and associated information

We cannot connect to them, they cannot connect to us:

1. Attempt to connect to the peer -> connection failure
2. Generate a ticket number
3. Send :ref:`ConnectToPeer` command to the server (ticket, username, connection_type)
4. Nothing should happen here, as they cannot connect to us
5. Receive :ref:`CannotConnect` from server (ticket)

.. note::
   Other clients don't seem to adhere to this flow: they don't actually wait for the connection to be established and just fires a :ref:`ConnectToPeer` message to the server at the same time as it tries to establish a connection to the peer.

.. note::
   Question 1: Why do we need a ticket number for :ref:`PeerInit` ? -> most clients seem to just send ``0``


Obfuscation
-----------

Obfuscation is possible only through the peer connection type (``P``) and the peer initialization messages (:ref:`PeerInit` and :ref:`PeerPierceFirewall`). If a distributed or file connection is made only the initialization messages can be obfuscated, after that the client should switch to sending/received messages non-obfuscated.

When messages are obfuscated the first 4 bytes are the key which is randomly generated for each message. To decode the first 4 bytes of the actual message the following steps should be taken:

1. Convert the key to an integer (from little-endian)
2. Perform a circular shift of 31 bits to the right
3. Convert back to bytes (to little-endian)
4. XOR the first 4 bytes with the 4 bytes of the rotated key

For the next 4 bytes, perform the same operation but rotate the resulting key again.

Example
~~~~~~~

* Original message :   ``08000000 79000000 e8030000``
* Obfuscated message : ``1494ee4a 2028dd95 2850ba2b 4aa37457``

**First 4 bytes**

Convert to big-endian: ``14 94 ee 4a`` -> ``4a ee 94 14``

Original key:

Hex: ``4a ee 94 14``
Bin: ``0100 1010 1110 1110 1001 0100 0001 0100``

Key shifted 31 bits to the right:

* Hex: ``95 dd 28 28``
* Bin: ``1001 0101 1101 1101 0010 1000 0010 1000``

Convert to little-endian: ``95 dd 28 28`` -> ``28 28 dd 95``

XOR the first 4 bytes (``20 28 dd 95``) with the rotated key:

+-----+----+----+----+----+
|     | b3 | b2 | b1 | b0 |
+=====+====+====+====+====+
|     | 28 | 28 | dd | 95 |
+-----+----+----+----+----+
| XOR | 20 | 28 | dd | 95 |
+-----+----+----+----+----+
|     | 08 | 00 | 00 | 00 |
+-----+----+----+----+----+


**Second 4 bytes**

Convert to big-endian: ``28 28 dd 95`` -> ``95 dd 28 28``

Original key:

* Hex: ``95 dd 28 28``
* Bin: ``1001 0101 1101 1101 0010 1000 0010 1000``

Key shifted 31 bits to the right:

* Hex: ``2b ba 50 51``
* Bin: ``0010 1011 1011 1010 0101 0000 0101 0001``

Convert to little-endian: ``2b ba 50 51`` -> ``51 50 ba 2b``

XOR the second 4 bytes (``28 50 ba 2b``) with the rotated key:

+-----+----+----+----+----+
|     | b3 | b2 | b1 | b0 |
+=====+====+====+====+====+
|     | 51 | 50 | ba | 2b |
+-----+----+----+----+----+
| XOR | 28 | 50 | ba | 2b |
+-----+----+----+----+----+
|     | 79 | 00 | 00 | 00 |
+-----+----+----+----+----+


**Third 4 bytes**

Convert to big-endian: ``51 50 ba 2b`` -> ``2b ba 50 51``

Original key:

* Hex: ``2b ba 50 51``
* Bin: ``0010 1011 1011 1010 0101 0000 0101 0001``

Key shifted 31 bits to the right:

* Hex: ``57 74 a0 a2``
* Bin: ``0101 0111 0111 0100 1010 0000 1010 0010``

Convert to little-endian: ``57 74 a0 a2`` -> ``a2 a0 74 57``

XOR the third 4 bytes (``4a a3 74 57``) with the rotated key:

+-----+----+----+----+----+
|     | b3 | b2 | b1 | b0 |
+=====+====+====+====+====+
|     | a2 | a0 | 74 | 57 |
+-----+----+----+----+----+
| XOR | 4a | a3 | 74 | 57 |
+-----+----+----+----+----+
|     | e8 | 03 | 00 | 00 |
+-----+----+----+----+----+


Distributed Network
===================

Obtaining a parent
------------------

When :ref:`ToggleParentSearch` is enabled then every 60 seconds the server will send the client a :ref:`PotentialParents` command (containing a maximum of 10 possible parents) until we disable our search for a parent using the :ref:`ToggleParentSearch` command. The :ref:`PotentialParents` command contains a list with each entry containing: username, IP address and port. Upon receiving this command the client will attempt to open up a connection to each of the IP addresses in the list to find a suitable parent.

After establishing a distributed connection with one of the potential parents the peer will send out a :ref:`DistributedBranchLevel` and :ref:`DistributedBranchRoot` over the distributed connection. If the peer is selected to be the parent the other potential parents are disconnected and the following messages are then send to the server to let it know where we are in the hierarchy:

* :ref:`BranchLevel` : BranchLevel from the parent + 1
* :ref:`BranchRoot` : The BranchRoot received from the parent as-is
* :ref:`ToggleParentSearch` : Set to false to disable receiving :ref:`PotentialParents` commands
* :ref:`AcceptChildren`: Ideally set to true

Once the parent is set it will start sending us search requests or if we are branch root the server will send us search requests.

.. note::
   Branch Root is not always sent when the potential parent has branch level 0. In this case the branch root value is implied from the connected user.

.. note::
   The implementation currently differs from the original clients. The implementation will make the first peer that sends a :ref:`DistributedBranchLevel` and :ref:`DistributedBranchRoot` (except if level was 0, see above).


List of open questions:

* If the parent is disconnected, are the children disconnected as well? If no, are the new branch root/level values re-advertised?
* Is it possible to force becoming branch root?


Obtaining children
------------------

The :ref:`AcceptChildren` command tells the server whether we want to have any children, this is used in combination with the :ref:`ToggleParentSearch` command which enables searching for parents. Enabling it will cause us to be listed in :ref:`PotentialParents` commands sent to other peers. It is not mandatory to have a parent and to obtain children if we ourselves are the branch root (branch level is 0).

The process is very similar to the one to obtain a parent except that this time we are in the role of the other peer; we need to advertise the branch level and branch root using the :ref:`DistributedBranchLevel` and :ref:`DistributedBranchRoot` commands as soon as another peer establishes.


Searches on the distributed network
-----------------------------------

Searches for the branch root (level = 0) will come from the server in the form of a :ref:`ServerSearchRequest` message. The branch root forwards this message as-is directly to its children (level = 1). The children will then convert this message into a :ref:`DistributedSearchRequest` and pass it on to its children (level = 2). It is up to the peer to perform the query on the local filesystem and report the results the peer making the query.

.. note::
   The reason why it is done this way is not clear. The branch root could perfectly convert it into a :ref:`DistributedSearchRequest` itself before passing it on. This would in fact be cleaner as right now the :ref:`DistributedServerSearchRequest` is just a copy of :ref:`ServerSearchRequest`, otherwise this wouldn't parse.

   The naming of these messages is probably incorrect as the ``distributed_code`` parameter of the :ref:`ServerSearchRequest` holds the distributed message ID. Possibly the server could send any distributed command through this that needs to be broadcast over the distributed network.


Transfers
=========

Downloads
---------

For downloading we need only the ``username`` and ``filename`` returned by a :ref:`PeerSearchReply`.

Request a file download (peer has free upload slots):

1. Initiate a connection a peer connection (``P``)
2. Send: :ref:`PeerTransferQueue` : ``filename``
3. Receive: :ref:`PeerTransferRequest` : ``direction=1``. Store the ``ticket`` and the ``filesize``
4. Send: :ref:`PeerTransferReply` : containing the ``ticket``. If the ``allowed`` flag is set the other peer will now attempt to establish a connection for uploading, if it is not set the transfer should be aborted.


When the peer is ready for uploading it will create a new file connection (``F``) :

1. Receive: :ref:`PeerInit`: or :ref:`PeerPierceFirewall`
2. Receive: ``ticket``
3. Send: ``offset``
4. Receive data until ``filesize`` is reached
5. Close connection
6. (the uploader will send a :ref:`SendUploadSpeed` message to the server with the average upload speed)

Queue a file download (peer does not have any free upload slots):

1. Initiate a peer connection (``P``)
2. Send: :ref:`PeerTransferQueue` message containing the filename
3. (If after 60s the ticket is not handled) Send: :ref:`PeerPlaceInQueueRequest` containing the filename
4. Receive: :ref:`PeerPlaceInQueueReply` which contains the filename and place in queue

.. warning::
   It is up to the downloader to close the file connection, the downloader confirms he has received all bytes by closing. If the uploader closes the connection as soon as all data is sent the file will be incomplete on the downloader side.


Uploads
-------

The original Windows SoulSeek client also has the ability to upload files to another user.

Successful upload
~~~~~~~~~~~~~~~~~

Uploader opens a new peer connection (``P``):

1. Uploader send: :ref:`PeerUploadQueueNotification`
2. Uploader send: :ref:`PeerTransferRequest` : ``direction=1``, ``filename=<local path>``, ``filesize=<set>``
3. Receiver send: :ref:`PeerTransferReply`: allowed=true

Uploader opens a new file connection (``F``) and proceeds with uploading

.. note::
   It seems like the :ref:`PeerUploadQueueNotification` is stored as subsequent uploads do not require this message to be sent


Upload not allowed
~~~~~~~~~~~~~~~~~~

Uploader opens a new peer connection (``P``):

1. Uploader send: :ref:`PeerUploadQueueNotification`
2. Uploader send: :ref:`PeerTransferRequest` : direction=1, filename=<local path>, filesize=<set>
3. Receiver send: :ref:`PeerTransferReply`: allowed=false, reason='Cancelled'
3. Uploader send: :ref:`PeerUploadFailed`: filename=<local path>


Searching
=========

Query rules
-----------

* Exclusion: dash-character gets used to exclude terms. Example: ``-mp3``, would exclude all mp3 files
* Wildcard: asterisk-character for wildcard searches. Example: ``*oney``, would match 'honey' and 'money'
* Sentence matching: double quotes would get used to keep terms together. Example: ``"my song"`` would perform an exact match for those terms. This no longer seems to be implemented.

Undescribed rules (matching):

* Searches are case-insensitive
* Placement of terms is irrelevant. This also applies to exclusions ``-mp3 song`` is the same as ``song -mp3``
* Wildcard/exclusion: placement is irrelevant
* Wildcard: can only be used in the beginning of the word. ``some*`` is not valid and neither is ``some*thing``
* Wildcard: doesn't need to match a character. Query ``*song.mp3`` will match ``song.mp3```
* Wildcard: query ``song *`` will return something
* Exclusion: there are results for queries using only exclusions but it does not seem official. Example ``-mp3``, returns a limited number of results and some results even containing string ``mp3``

The algorithm for matching can be described as:

1. Split the query into search terms using whitespace
2. Foreach term match the item's path in the form of:

   a. <non-word character or start of string>
   b. when using wildcard: <0 or more word characters>
   c. escaped search term
   d. <non-word character or end of string>

Word characters are alphanumeric characters or unicode word characters


Attributes
----------

Each search results returns a list of attributes containing information about the file.

Investigated different file formats and which attributes they return in which the following formats were checked: FLAC, MP3, M4A, OGG, AAC, WAV. It seems like there's a categorization of the different formats, based on the category certain attributes will be returned:

* Lossless: FLAC, WAV
* Compressed: MP3, M4A, AAC, OGG

Attribute table:

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


.. note::
   The ``extension`` parameter is empty for anything but mp3 and flac

.. note::
   Couldn't find any other than these. Number 3 seems to be missing, could this be something used in the past or maybe for video? Theoretically we could invent new attributes here, like something for video, images, extra metadata for music files. The official clients don't seem to do anything with the extra attributes


Global Search
-------------

Perform a query to everyone on the network.

1. Searcher: Send :ref:`FileSearch`
2. Server: Send :ref:`ServerSearchRequest` to distributed network roots (level = 0)
3. Roots (level 0): Send :ref:`DistributedServerSearchRequest`
4. Roots children: (level 1): Send :ref:`DistributedSearchRequest`


Room Search
-----------

Performs a search on every one in a single room:

1. Searcher send: :ref:`RoomSearch` : with a `ticket`, the `query` and `room` name
2. Room user receive: :ref:`FileSearch`


User Search
-----------

Searches an individual user:

1. Searcher send :ref:`UserSearch` : with a `ticket`, the `query` and `username`
2. Target user receive: :ref:`FileSearch`


Delivering Search Results
-------------------------

Delivery of search results is the same process for all kinds of search messages:

1. Receive :ref:`FileSearch`. Containing `ticket` and `username`
2. If the query matches:

   1. Initialize peer connection (``P``) for the `username` from the request
   2. Send :ref:`PeerSearchReply` : `ticket` from the original search request and query matches


Users
=====

There's two situations where the server will automatically send updates for a user:

* User was explicitly added with the :ref:`AddUser` message
* User is part of a room we are currently in

The updates will come in the form of two messages:

* :ref:`GetUserStatus` : update on user status and privileges
* :ref:`GetUserStats` : update on user stats (shared files/folders, upload stats)

The following describes the behaviour when another user modifies his status / stats:

* User logs in:

   * TODO

* User send :ref:`SetUserStatus`

   * Server send: :ref:`GetUserStatus` to all users in all rooms the user has joined (includes the user sending the update)
   * Server send: :ref:`GetUserStatus` to all users that have sent an :ref:`AddUser` message

* User disconnects (offline)

   * Presumably a :ref:`GetUserStatus` is sent to all users in the rooms the user had joined. But the user is removed from all rooms before the update is sent
   * Server send: :ref:`GetUserStatus` to all users that have sent an :ref:`AddUser` message

* User send :ref:`SharedFoldersFiles`

   * Server send: :ref:`GetUserStats` to all users in all rooms the user has joined (includes the user sending the update)

* User send :ref:`SendUploadSpeed`

   * No updates sent

* Adding privileges to a user

   * TODO


Rooms
=====

After joining a room, we will automatically be receiving :ref:`GetUserStatus` updates from the server.

Only private rooms have an owner, operators and members.


Room List
---------

The room list is received after login but can be refreshed by sending another :ref:`RoomList` request. The :ref:`RoomList` message consists of lists of rooms categorized by room type:

* ``rooms`` : public rooms
* ``rooms_private_owned`` : private rooms which we own
* ``rooms_private`` : private rooms which we are part of. this excludes the rooms in rooms_private_owned
* ``rooms_private_operated`` : private rooms in which we are operator

.. note::
   Not all public rooms are listed in the initial :ref:`RoomList` message after login; only rooms with 5 or more joined users


Room Joining / Creation
-----------------------

To join a public room a :ref:`JoinRoom` message is sent to the server, containing the name of the room and whether the room is private. If the room does not yet exist it is created.

Creating a public room:

1. Send :ref:`JoinRoom` (is_private=0)
2. Receive:

  * :ref:`UserJoinedRoom`
  * :ref:`JoinRoom` : with our own username
  * :ref:`RoomTickers`

Creating a private room:

1. Send :ref:`JoinRoom` (is_private=1)
2. Receive:

  * :ref:`RoomList` : updated list of rooms. See 'Room List' section on what would be expected here
  * :ref:`PrivateRoomMembers` : list of users in the room (exluding ourself)
  * :ref:`PrivateRoomOperators` : list of operators
  * :ref:`UserJoinedRoom` : with our own username
  * :ref:`JoinRoom` : with our own username
  * :ref:`RoomTickers`

.. note::
   Messages :ref:`PrivateRoomMembers`, :ref:`PrivateRoomOperators` seems to be repeated for private rooms we are already part of

.. note::
   Possibly on the server side the joining happens after some of these messages are sent. In the :ref:`RoomList` message the `rooms_private_owned_user_count` is 0, in the PrivateRoomsUsers message the list of users is empty. The

.. note::
   :ref:`PrivateRoomMembers` returns the users which are part of the room (excluding the owner) while :ref:`RoomList` rooms_private_user_count only return the amount of online users


Room Leaving
------------

From the user leaving the room:

1. Send: :ref:`LeaveRoom` : with room name
2. Receive:

   * :ref:`LeaveRoom` : with room name

Other users in the room:

1. Receive:

   * :ref:`UserLeftRoom` : with room name and user name


Add User to Private Room
------------------------

Owners and operators can add users to rooms.

User adding another user:

1. Send: :ref:`PrivateRoomGrantMembership` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomGrantMembership` : with room name and user name
   * Server message: User <user_name> is now a member of room <room_name>

The added user:

1. Receive:

   * :ref:`PrivateRoomGrantMembership` : with room name and user name
   * :ref:`PrivateRoomMembershipGranted` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : users of the room (excluding the owner?)
   * :ref:`PrivateRoomOperators`

The owner of the room:

1. Receive:

   * :ref:`PrivateRoomGrantMembership` : with room name and user name
   * Server message: User [<user_name>] was added as a member of room [<room_name>] by operator [<operator_name>]

Other members in room:

TODO

Other members not in room:

TODO


Removing User from Private Room
-------------------------------

Owners can remove operators and members, operators can only remove members.

User removing another user (owner):

1. Send: :ref:`PrivateRoomRevokeMembership` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomRevokeMembership` : with room name and user name
   * Server message: User <user_name> is no longer a member of room <room_name>

User being removed:

1. Receive:

   * :ref:`PrivateRoomMembershipRevoked` : with room name
   * :ref:`LeaveRoom` : with room name
   * :ref:`RoomList`

The owner of the room:

1. Receive:

   * :ref:`PrivateRoomRevokeMembership` : with room name and user name
   * Server message: User <user_name> is no longer a member of room <room_name>

Other members in room:

TODO

Other members not in room:

TODO


Granting Operator to Private Room
---------------------------------

User granting operator:

1. Send: :ref:`PrivateRoomGrantOperator` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomGrantOperator` : with room name and user name (got this twice for some reason, perhaps a bug in the server? Should probably be :ref:`PrivateRoomOperatorGranted`)
   * Server message: User <user_name> is now an operator of room <room_name>

User receiving operator:

TODO

Other members in the room:

TODO

Other members not in the room:

TODO


Revoking Operator from Private Room
-----------------------------------

User revoking operator:

1. Send: :ref:`PrivateRoomRevokeOperator` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomRevokeOperator` : with room name and user name (got this twice for some reason, perhaps a bug in the server? Should probably be :ref:`PrivateRoomRevokeOperator`)
   * Server message: User <user_name> is no longer an operator of room <room_name>

User for which operator was revoked:

1. Receive:

   * :ref:`PrivateRoomRevokeOperator` : with room name and user name (got this twice)
   * :ref:`PrivateRoomOperatorRevoked` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : for all private rooms we are part of
   * :ref:`PrivateRoomOperators` : for all private rooms we are part of


Dropping Membership
-------------------

Dropping membership can only be done for a private room. This function does nothing for the owner, he needs to drop ownership.

As regular member
~~~~~~~~~~~~~~~~~

Member dropping membership:

1. Send: PrivateRoomDropMembership : with room name
2. Receive:

   * :ref:`PrivateRoomMembershipRevoked` : with room name
   * :ref:`LeaveRoom` : with room name
   * :ref:`RoomList`


Received by owner:

1. Receive:

   * :ref:`PrivateRoomRevokeMembership` : with room name and user name
   * Server message: User <user_name> is no longer a member of room <room_name>
   * :ref:`UserLeftRoom` : with room name and user name

Received by operator:

1. Receive:

   * :ref:`PrivateRoomRevokeMembership` : with room name and user name
   * :ref:`UserLeftRoom` : with room name and user name


As operator
~~~~~~~~~~~

Operator dropping membership:

1. Send: PrivateRoomDropMembership : with room name
2. Receive:

   * :ref:`PrivateRoomMembershipRevoked` : with room name
   * :ref:`LeaveRoom` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : for private rooms we are still part of
   * :ref:`PrivateRoomOperators` : for private rooms we are still part of
   * :ref:`PrivateRoomOperatorRevoked`
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : for private rooms
   * :ref:`PrivateRoomOperators` : for private rooms

Received by owner:

1. Receive:

   * :ref:`PrivateRoomRevokeMembership`
   * Server message: User <user_name> is no longer a member of room <room_name>
   * :ref:`UserLeftRoom`
   * :ref:`PrivateRoomRevokeOperator` (twice)
   * Server message: User <user_name> is no longer an operator of room <room_name>

Received by member:

1. Receive:

   * :ref:`PrivateRoomRevokeMembership`
   * :ref:`UserLeftRoom`
   * :ref:`PrivateRoomRevokeOperator` (twice)


Dropping Ownership
------------------

Owner dropping ownership:

1. Send: PrivateRoomDropOwnership : with room name
2. Receive:

   * :ref:`UserLeftRoom` : with room name and user name for all other users in the room
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : for private rooms we are still part of
   * :ref:`PrivateRoomOperators` : for private rooms we are still part of

Received by operator:

1. Receive:

   * :ref:`PrivateRoomMembershipRevoked` : with room name
   * :ref:`LeaveRoom` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : for private rooms we are still part of
   * :ref:`PrivateRoomOperators` : for private rooms we are still part of
   * :ref:`PrivateRoomOperatorRevoked`
   * :ref:`RoomList`
   * :ref:`PrivateRoomMembers` : for private rooms
   * :ref:`PrivateRoomOperators` : for private rooms

Received by member:

1. Receive:

   * :ref:`UserLeftRoom` : for the operator that was in the room
   * :ref:`PrivateRoomRevokeOperator` : for the operator that was in the room
   * :ref:`PrivateRoomMembershipRevoked`
   * :ref:`LeaveRoom`
   * :ref:`RoomList`


Exception cases
---------------

* Joining/creating: a room that exists as a private room

  * CannotCreateRoom: with the room name
  * Server message: The room you are trying to enter (<room_name>) is registered as private.

* Joining/creating: Multiple spaces in between words ("my   room")

  * Server message: Could not create room. Reason: Room name <room_name> contains multiple following spaces.

* Joining/creating: Spaces between or after room name ("room ", " room")

  * Server message: Could not create room. Reason: Room name <room_name> contains leading or trailing spaces.

* Joining/creating: Non-ascii characters in room name

  * Server message: Could not create room. Reason: Room name <room_name> contains invalid characters.

* Joining/creating: Empty room name

  * Server message: Could not create room. Reason: Room name empty.

* Add User to Room: Adding a user who does not have private rooms enabled

  * Server message: user <user_name> hasn't enabled private room add. please message them and ask them to do so before trying to add them again.
