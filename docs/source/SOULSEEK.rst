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
* :ref:`ToggleParentSearch` : Setting to false disables receiving :ref:`PotentialParents` messages
* :ref:`AcceptChildren`: See :ref:`max-children` setting

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


.. _max-children:

Max children
~~~~~~~~~~~~

Clients limit the amount of children depending on the upload speed that is currently stored on the server. Whenever a :ref:`GetUserStats` message is received (for the logged in user) this limit is re-calculated and depends on the :ref:`ParentSpeedRatio` and :ref:`ParentMinSpeed` values the server sent after logon.

When a client receives a :ref:`GetUserStats` message the client should determine whether to enable or disable accepting children and if enabled, calculate the amount of maximum children:

1. If the ``avg_speed`` returned is smaller than the value received by :ref:`ParentMinSpeed` * 1024 : Send :ref:`AcceptChildren` (``accept = false``)
2. If the ``avg_speed`` is greater or equal than the value received by :ref:`ParentMinSpeed` * 1024 :

  1. Send :ref:`AcceptChildren` (``accept = true``)
  2. Calculate the ``divider`` from the ``ratio`` returned by :ref:`ParentSpeedRatio`: (``ratio`` / 10) * 1024
  3. Calculate the max number of children : floor(``avg_speed`` / ``divider``)


Example calculation 1 (``ratio=50``, ``avg_speed=20480``):

* (50 / 10) * 1024 = 5120
* floor(20480 / 5120) = 4

Example calculation 1 (``ratio=30``, ``avg_speed=20480``):

* (30 / 10) * 1024 = 3072
* floor(20480 / 3072) = 6 (floored from 6.66666666)


.. note::
  The formula for calculating the max amount of parents can be 0, clients still seem to enable :ref:`AcceptChildren` regardless


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
4. Uploader send: :ref:`PeerUploadFailed`: filename=<local path>


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

* User send :ref:`SetStatus`

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

Chat
====

Private Chat Message
--------------------

Actors:

* ``sender`` : User sending a private message
* ``receiver`` : User receiving the private message

Actions:

1. Sender -> Server: Send :ref:`PrivateChatMessage`

  * username = ``receiver``

2. Server -> Client 2: Send :ref:`PrivateChatMessage` with username of sender (Client 1) and automatically generated ``chat_id``
3. Client 2 -> Server: Send :ref:`PrivateChatMessageAck` with automatically generated ``chat_id``

.. _server-info-message:

Server Notification Message
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The server will send private chat messages to report errors and information back to the client:

1. Server -> Client: Send :ref:`PrivateChatMessage`

  * username = ``server``
  * is_admin = ``true``
  * chat_id = ``<generated>``
  * message = ``<desired_message>``)

2. Client -> Server: Send :ref:`PrivateChatMessageAck`

  * chat_id ``<chat_id from received message>``


Rooms
=====

After joining a room, we will automatically be receiving :ref:`GetUserStatus` and :ref:`GetUserStats` updates from the server for users in the room.

A room can be described as having the following structure:

+----------------------+---------------------+-------------------------------------------------------------------+
|        Field         |        Type         |                            Description                            |
+======================+=====================+===================================================================+
| name                 | string              | Name of the room                                                  |
+----------------------+---------------------+-------------------------------------------------------------------+
| tickers              | map[string, string] | Map of room tickers. Key=username, value=ticker                   |
+----------------------+---------------------+-------------------------------------------------------------------+
| joined_users         | array[string]       | List of users currently in the room                               |
+----------------------+---------------------+-------------------------------------------------------------------+
| registered_as_public | boolean             | Tracks if the room was ever registered as public (default: false) |
+----------------------+---------------------+-------------------------------------------------------------------+
| owner                | array[string]       | [Optional] Private Rooms. Owner of the room                       |
+----------------------+---------------------+-------------------------------------------------------------------+
| members              | array[string]       | [Optional] Private Rooms. Members of the room (excludes owner)    |
+----------------------+---------------------+-------------------------------------------------------------------+
| operators            | array[string]       | [Optional] Private Rooms. Users with operator privileges          |
+----------------------+---------------------+-------------------------------------------------------------------+

Calculated values:

+-------------+---------------+--------------------------------------------------------------------------------------------+
|    Field    |     Type      |                                        Description                                         |
+=============+===============+============================================================================================+
| status      | RoomStatus    | Returns the current status of the room with 3 possible values:                             |
|             |               | * RoomStatus.PRIVATE : If ``owner`` value is set                                           |
|             |               | * RoomStatus.PUBLIC : If ``owner`` value is not set and ``joined_users`` list is not empty |
|             |               | * RoomStatus.UNCLAIMED : If ``owner`` value is not set and ``joined_users`` list is empty  |
+-------------+---------------+--------------------------------------------------------------------------------------------+
| all_members | array[string] | Returns the list of members including the owner (if there is any)                          |
+-------------+---------------+--------------------------------------------------------------------------------------------+

.. warning::
  It's important to understand that rooms never get immediately destroyed (possibly they do get cleaned up after some time has passed without activity).

  If a room was public it cannot be claimed as a private room

  If ownership is dropped for a private room the ``owner``, ``members`` and ``operators`` values simply get reset and all ``joined_users`` except for the ``owner`` get kicked. This effectively makes the private room a public room until the ``owner`` leaves, at which point the room becomes unclaimed and can be claimed again as a private or public room.


.. _room-list:

Room List
---------

The room list is received after login but can be refreshed by sending another :ref:`RoomList` request. The :ref:`RoomList` message consists of lists of rooms categorized by room type:

* ``rooms`` : public rooms
* ``rooms_private_owned`` : private rooms for which we are ``owner``
* ``rooms_private`` : private rooms for which we are in the ``members`` list
* ``rooms_private_operated`` : private rooms for which we are in the ``operators`` list

.. note::
  Not all public rooms are listed in the initial :ref:`RoomList` message after login; only rooms with 5 or more ``joined_users``.

  It's not clear where this limit comes from, and possibly if the total amount of public rooms is low those rooms are included anyway (and perhaps if it's high the minimum amount of members increases as well)


.. _function-private-room-list-update:

Function: Send Private Room List Update
---------------------------------------

This is a collection of messages commonly called after performing an action on a private room:

1. Server: Send :ref:`room-list`
2. Server: For each private room where the user is ``owner`` or in the list of ``members``

  * :ref:`PrivateRoomMembers` with room_name and list of ``members``

3. Server: For each private room where the user is ``owner`` or in the list of ``members``

  * :ref:`PrivateRoomOperators` with room_name and list of ``operators``


Room Joining / Creation
-----------------------

To join a room a :ref:`JoinRoom` message is sent to the server, containing the ``name`` of the room and whether the room is ``private``. If the room does not exist it is created.

Actors:

* ``joiner`` : user requesting to join the room


Input Checks:

* If room ``name`` is empty:

  * :ref:`server-info-message` : message : "Could not create room. Reason: Room name empty."

* If room ``name`` contains leading or trailing white spaces:

  * :ref:`server-info-message` : message : "Could not create room. Reason: Room name ``name`` contains leading or trailing spaces."

* If room ``name`` contains multiple subsequent white spaces (eg.: "my  room"):

  * :ref:`server-info-message` : message : "Could not create room. Reason: Room name ``name`` contains multiple following spaces."

* If room ``name`` contains non-ascii characters:

  * :ref:`server-info-message` : message : "Could not create room. Reason: Room name ``name`` contains invalid characters."


Checks:

* If room exists and ``joiner`` is in the ``joined_users`` list (user already joined):

  * Do nothing

* If room exists and ``joiner`` is not in the ``all_members`` list:

  * Send :ref:`CannotCreateRoom`
  * :ref:`server-info-message` : message : "The room you are trying to enter (``name``) is registered as private."


Actions:

1. If the room does not exist (or room is unclaimed) and the request is to join a public room (``private=false``):

  1. Create new room or claim the unclaimed room

    * ``name`` : set to desired name
    * ``owner`` : leave empty
    * ``registered_as_public`` : true

2. If the room is unclaimed, is registered as public room (``registered_as_public=true``) and the request is to join a private room (``private=true``):

  * :ref:`server-info-message` : message to ``joiner`` : "Room (``name``) is registered as public."

3. If the room does not exist (or room is unclaimed), is not registered as public room (``registered_as_public=false``) and the request is to join a private room (``private=true``):

  1. Create new room or claim the unclaimed room

    * ``name`` : set to desired name
    * ``owner`` : set to room creator
    * ``registered_as_public`` : false

  2. :ref:`function-private-room-list-update`

4. :ref:`function-join-room`


Grant Membership in Private Room
--------------------------------

Operators and owners of a private room can grant membership to a user allowing that user to join the room. This can be done using the :ref:`PrivateRoomGrantMembership` message, the message contains the ``name`` of the room and the ``username`` of the user that should be given membership.

Actors:

* ``granter`` : User granting membership
* ``grantee`` : User being granted membership

Checks:

* If the room ``name`` is not a valid room (public) : Do nothing
* If the room ``name`` is not a valid room (does not exist) : Do nothing
* If the ``grantee`` and ``granter`` are the same : Do nothing
* If the ``granter`` is not the ``owner`` or in the ``operators`` list : Do nothing
* If the ``grantee`` is offline or does not exist:

  * :ref:`server-info-message` : message : "user ``grantee`` is not logged in."

* If the ``grantee`` is not accepting private room invites:

  * :ref:`server-info-message` : message : "user ``grantee`` hasn't enabled private room add. please message them and ask them to do so before trying to add them again."

* If the ``granter`` is in ``operators`` list and tries to add the ``owner``

  * :ref:`server-info-message` : message : "user ``grantee`` is the owner of room ``name``"

* If the ``grantee`` is already in the ``members`` list:

  * :ref:`server-info-message` : message : "user ``grantee`` is already a member of room ``name``"


Actions:

1. :ref:`function-private-room-grant-membership`


Revoke Membership from Private Room
-----------------------------------

Removes a member from a private room. The owner can remove operators and members, operators can only remove members. This can be done using the :ref:`PrivateRoomRevokeMembership` message, the message contains the ``name`` of the room and the ``username`` of the user that should be revoked membership.

Actors:

* ``revoker`` : User revoking membership
* ``revokee`` : User being revoked membership

Checks:

* If the ``revoker`` and ``revokee`` are the same user : Do nothing
* If the ``revokee`` is not in the ``members`` list : Do nothing
* If the ``revoker`` is in the ``operators`` list and the ``revokee`` is the ``owner`` : Do nothing
* If the ``revoker`` and ``revokee`` are both in the ``operators`` list : Do nothing

Actions:

1. :ref:`function-private-room-revoke-membership`


Granting Operator Privileges in a Private Room
----------------------------------------------

Room owners can grant operator privileges to members of a private room by using the :ref:`PrivateRoomGrantOperator` message, the message contains the ``name`` of the room and the ``username`` of the member that should be granted operator privileges.

Actors:

* ``granter`` : User granting the operator privileges
* ``grantee`` : User having operator privileges granted

Checks:

* If ``granter`` is not the ``owner`` : Do nothing
* If user does not exist or is offline (even in ``members`` list):

  * :ref:`server-info-message` : message : "user ``grantee`` is not logged in."

* If ``grantee`` is not in the ``members`` list:

  * :ref:`server-info-message` : message : "user ``grantee`` must first be a member of room ``name``"

* If ``grantee`` is already in the ``operators`` list:

  * :ref:`server-info-message` : message : "user ``grantee`` is already an operator of room ``name``"


Actions:

1. :ref:`function-private-room-grant-operator`


Revoking Operator Privileges in a Private Room
----------------------------------------------

Room owners can revoke operator privileges from operator of a private room by using the :ref:`PrivateRoomRevokeOperator` message, the message contains the ``name`` of the room and the ``username`` of the member that should have his operator privileges revoked.

Actors:

* ``revoker`` : User revoking the operator privileges
* ``revokee`` : User having operator privileges revoked

Checks:

* If user does not exist: Do nothing
* If ``revoker`` is not the ``owner`` : Do nothing
* If ``revokee`` is not in the ``members`` list: Do nothing
* If ``revokee`` is not in the ``operators`` list: Do nothing

Actions:

1. :ref:`function-private-room-revoke-operator`


Dropping Membership
-------------------

Members themselves can drop their membership by using the :ref:`PrivateRoomDropMembership` message.

Checks:

* If the user is not in the ``members`` list : Do nothing

Actions:

1. :ref:`function-private-room-revoke-membership`
2. If the user is in the ``operators`` list:

  * :ref:`function-private-room-revoke-operator`


Dropping Ownership
------------------

Owners can drop ownership of a private room, this will disband the private room. This is done through the :ref:`PrivateRoomDropOwnership` message.

Checks:

* If the user tries to drop ownership for a room that does not exist: Do nothing
* If the user tries to drop ownership of a public room: Do nothing
* TODO: If the member is not the ``owner``

Actions:

1. Reset the ``owner``
2. Empty the ``operators`` list of the room
3. Empty the ``members`` list of the room but keep a reference to this list
4. For each member in the list:

  * :ref:`function-private-room-revoke-membership`

5. :ref:`function-private-room-list-update`


.. warning::
  The server will not automatically notify the owner himself that he has left the room. The owner should send a second command to leave the room after sending this command. This seems like a mistake that was corrected in the client itself instead of on the server side.

.. _function-notify-room-owner:

Function: Notify room owner
---------------------------

Function to notify the room owner. This short function sends a server chat ``message`` to the ``owner`` of a room if the room has an owner.

Actions:

1. If the room has its ``owner`` value set:

  * :ref:`server-info-message` : to ``owner`` : ``message``


.. _function-join-room:

Function: Join room
-------------------

Function to join the room, checks should already be performed.

Actors:

* ``joiner`` : user requesting to join the room

Actions:

1. Add the user to the list of ``joined_users``
2. For each user in the list of ``joined_users``:

  * :ref:`UserJoinedRoom` : with room ``name`` (+ stats) of ``joiner`` of the room

3. Send to ``joiner``:

  * :ref:`JoinRoom`

    * ``room`` : name of joined room
    * ``usernames`` : list of room ``joined_users``
    * user stats, online status, etc
    * ``owner`` : ``owner`` if ``is_private=true`` for the room
    * ``operators`` : ``owner`` if ``is_private=true`` for the room

  * :ref:`RoomTickers`

    * ``room`` : name of joined room
    * ``tickers`` : array of room ``tickers``


.. _function-leave-room:

Function: Leave Room
--------------------

Function to leave a room

Actors:

* ``leaver`` : user requesting or being removed from the room

Actions:

1. Remove the user from the list of ``joined_users``
2. For each user in the list of ``joined_users``:

  * :ref:`UserLeftRoom` : with room ``name`` and list (+ stats) of ``leaver`` of the room

3. Send to ``leaver``:

  * :ref:`LeaveRoom` : with room ``name``


.. _function-private-room-grant-membership:

Function: Grant Membership to Private Room
------------------------------------------

Function to grant membership to a user from a private room

Actors:

* ``granter`` : User granting membership
* ``grantee`` : User being granted membership

Actions:

1. Add new member to the ``members`` list
2. For each member in the ``members`` list:

  * Send :ref:`PrivateRoomGrantMembership` with room name and new member name

3. For the ``grantee``:

  * Send :ref:`PrivateRoomMembershipGranted` with the room name
  * :ref:`function-private-room-list-update`

4. If the ``granter`` is in the list of room ``operators``:

  * :ref:`function-notify-room-owner` : "User [``grantee``] was added as a member of room [``name``] by operator [``granter``]"

5. If the ``granter`` is the room ``owner``:

  * :ref:`function-notify-room-owner` : "User ``granter`` is now a member of room ``name``"


.. _function-private-room-revoke-membership:

Function: Revoke Membership from Private Room
---------------------------------------------

Function to revoke membership from a user from a private room

Actors:

* ``revokee`` : User having membership revoked

Actions:

1. Remove user from the ``members`` list
2. For each member in the ``members`` list:

  * Send :ref:`PrivateRoomRevokeMembership` with room name and removed member name

3. For the room ``owner``:

  * :ref:`function-notify-room-owner` : "User ``revokee`` is no longer a member of room ``name``"

4. For the ``revokee``:

  * Send :ref:`PrivateRoomMembershipRevoked` with the room name

5. If the ``revokee`` is in the ``joined_users`` list:

  * :ref:`function-leave-room` : for the ``revokee``

6. For the ``revokee``:

  * :ref:`function-private-room-list-update`


.. note::
  No specialized message is sent to the owner if an operator removes a member unlike when adding a member


.. _function-private-room-grant-operator:

Function: Grant Operator to Private Room
----------------------------------------

Function to grant operator privileges to a member of a private room

Actors:

* ``granter`` : User granting the operator privileges
* ``grantee`` : User having operator privileges granted

Actions:

1. Add the member to the ``operators`` list:
2. For each member in the ``members`` list:

  * Send :ref:`PrivateRoomGrantOperator` with room name and the name of the new operator

3. For each user in the ``joined_users`` list:

  * Send :ref:`PrivateRoomGrantOperator` with room name and the name of the new operator

4. For the ``grantee``:

  * Send :ref:`PrivateRoomOperatorGranted` with the room name
  * :ref:`function-private-room-list-update`

5. For the room ``owner``:

  * :ref:`function-notify-room-owner` : "User ``grantee`` is now an operator of room ``name``"


.. note::
  It is not a mistake that the :ref:`PrivateRoomGrantOperator` message gets sent twice to both the joined users and the members


.. _function-private-room-revoke-operator:

Function: Revoke Operator from Private Room
-------------------------------------------

Function to revoke operator privileges from a member of a private room

Actors:

* ``revoker`` : User revoking the operator privileges
* ``revokee`` : User having operator privileges revoked

Actions:

1. Remove the member from the ``operators`` list:
2. For each member in the ``members`` list:

  * Send :ref:`PrivateRoomRevokeOperator` with room name and the name of the removed operator

3. For each user in the ``joined_users`` list:

  * Send :ref:`PrivateRoomRevokeOperator` with room name and the name of the removed operator

4. For the ``revokee``:

  * Send :ref:`PrivateRoomOperatorRevoked` with the room name
  * :ref:`function-private-room-list-update`

5. For the room ``owner``:

  * :ref:`function-notify-room-owner` : "User ``revokee`` is no longer an operator of room ``name``"


.. note::
  It is not a mistake that the :ref:`PrivateRoomRevokeOperator` message gets sent twice to both the joined users and the members


Interests / Recommendations
===========================

The protocol implements a recommendation system: you can add interests and hated interests and the server can return recommendations for those interests based on what other users have.


Getting / Adding / Removing Interests
-------------------------------------

There are 4 messages for managing your own interests:

* :ref:`AddInterest`
* :ref:`RemoveInterest`
* :ref:`AddHatedInterest`
* :ref:`RemoveHatedInterest`

Using the :ref:`GetUserInterests` message the interests of a user can be retrieved

.. note::
  The server does not persist interests or hated interests after disconnect


Get Global Recommendations
--------------------------

Through the :ref:`GetGlobalRecommendations` message the global recommendations can be returned.

Keep a ``counter`` (initially empty) to keep track of a ``score`` for each of the recommendations:

1. Loop over all currently active users (including the current user)

  a. Increase the ``score`` for all of the ``interests`` of the other user by 1
  b. Decrease the ``score`` for all of the ``hated_interests`` of the other user by 1

2. Unverified: Keep only recommendations where the ``score`` is not 0
3. The returned message will contain 2 lists:

  a. The recommendations sorted by score descending (limit to 200)
  b. The unrecommendations sorted by score ascending (limit to 200)


Get Item Recommendations
------------------------

Through the :ref:`GetItemRecommendations` message a set of recommendations can be returned based on the specified item.

Keep a ``counter`` (initially empty) to keep track of a ``score`` for each of the recommendations:

1. Loop over all currently active users (excluding the current user)
2. If the ``item`` is in the user's interests:

   a. Increase the ``score`` for all of the ``interests`` of the other user by 1
   b. Decrease the ``score`` for all of the ``hated_interests`` of the other user by 1

3. Keep only recommendations where the ``score`` is not 0
4. The returned message will contain 1 lists:

   a. The recommendations sorted by score descending (limit to 100)


Get Recommendations
-------------------

Through the :ref:`GetRecommendations` message a personalized set of recommendations can be returned based on the interests and hated interests.

Keep a ``counter`` (initially empty) to keep track of a ``score`` for each of the recommendations:

1. Loop over all currently active users (excluding the current user)
2. Loop over all the current user's ``interests``

  1. If the current interest is in the ``interests`` of the other user:

    a. Increase the ``score`` for all of the ``interests`` of the other user by 1
    b. Decrease the ``score`` for all of the ``hated_interests`` of the other user by 1

  2. If the current interest is in the ``hated_interests`` of the other user

    a. Decrease the ``score`` for all of the ``interests`` of the other user by 1

3. Loop over all the current user's ``hated_interests``

  1. If the current hated interest is in the ``interests`` of the other user:

  a. Decrease the ``score`` for all of the ``interests`` of the other user by 1

4. Keep only recommendations that are not in the current user's ``interests`` or ``hated_interests``
5. Keep only recommendations where the ``score`` is not 0
6. The returned message will contain 2 lists:

  a. The recommendations sorted by score descending (limit to 100)
  b. The unrecommendations sorted by score ascending (limit to 100)


.. note::
  Keep in mind that the recommendations list can (partially) match the unrecommendations list and vice versa if the limit is not reached. Example: if there are 5 items returned those 5 items will be in both lists


Examples
~~~~~~~~

Following examples are to illustrate how the algorithm works:

**Example 1**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item1 | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests |       |       |
+-----------------+-------+-------+

Recommendations:

* item2 (score = 1)


**Example 2**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       |       | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests | item1 | item3 |
+-----------------+-------+-------+

Recommendations:

* item2 (score = -1)


**Example 3**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item1 | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests | item1 | item3 |
+-----------------+-------+-------+

Recommendations:

* item2 (score = -1)


**Example 4**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item1 | item1 |
+-----------------+-------+-------+
|                 | item2 | item2 |
+-----------------+-------+-------+
| Hated interests |       | item3 |
+-----------------+-------+-------+
|                 |       | item4 |
+-----------------+-------+-------+

Recommendations:

* item3 (score = -2)
* item4 (score = -2)


**Example 5**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       |       | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests | item3 | item3 |
+-----------------+-------+-------+
|                 |       | item4 |
+-----------------+-------+-------+

Recommendations: Empty list


**Example 6**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item3 | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests |       | item3 |
+-----------------+-------+-------+
|                 |       | item4 |
+-----------------+-------+-------+

Recommendations:

* item1 (score = -1)
* item2 (score = -1)


**Example 7**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       |       | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests | item1 | item3 |
+-----------------+-------+-------+
|                 |       | item4 |
+-----------------+-------+-------+

Recommendations:

* item2 (score = -1)


**Example 8**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item3 | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests | item1 | item3 |
+-----------------+-------+-------+
|                 |       | item4 |
+-----------------+-------+-------+

Recommendations:

* item2 (score = -2)


**Example 9**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item1 | item1 |
+-----------------+-------+-------+
|                 | item2 | item2 |
+-----------------+-------+-------+
|                 |       | item5 |
+-----------------+-------+-------+
| Hated interests |       | item3 |
+-----------------+-------+-------+
|                 |       | item4 |
+-----------------+-------+-------+

Recommendations:

* item5 (score = 2)
* item3 (score = -2)
* item4 (score = -2)


**Example 10**

+-----------------+-------+-------+
|                 |  You  | Other |
+=================+=======+=======+
| Interests       | item1 | item1 |
+-----------------+-------+-------+
|                 |       | item2 |
+-----------------+-------+-------+
| Hated interests |       | item2 |
+-----------------+-------+-------+

Recommendations: Empty list


Get Similar Users
-----------------

The :ref:`GetSimilarUsers` message returns users that have similar interests to you.

Create an empty list for storing similar users:

1. Loop over all currently active users (excluding the current user)
2. Calculate the amount of ``interests`` in common between the current user and those of the other user
3. If the overlap is greater than 1, add it to the list of similar users
4. Return the list of similar users and the amount of interests in common with that user (limit is unknown)


Get Item Similar Users
----------------------

The :ref:`GetItemSimilarUsers` message returns users that have the interest as provided in the request message (``item``).

Create an empty list for storing similar users:

1. Loop over all currently active users (including the current user)
2. If the ``item`` is in the ``interests`` of the user add it to the list of similar users
3. Return the list of similar users (limit is unknown)
