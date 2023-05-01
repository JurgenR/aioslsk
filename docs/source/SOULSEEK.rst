==============
SoulSeek Flows
==============

.. contents:

This document describes different flows and details for the SoulSeek protocol


Server Connection and Logon
===========================

* SoulSeekQt: server.slsknet.org:2416
* SoulSeek: 208.76.170.59:2242

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


After connection is complete, send a :ref:`Ping` command out every 5 minutes.

Exception Cases
---------------

* No check on hash seems currently performed
* No check on password length seems currently performed (empty password allowed)
* Logon with an empty username results in failure reason ``INVALIDUSERNAME``
* If the user was previously logged in with and the password does not match results in failure reason ``INVALIDPASS``
* If the credentials are valid but the user is logged in the other user will receive message :ref:`Kicked` and the connection will be terminated


.. _peer-connections:

Peer Connections
================

All peer connections use the TCP protocol. The SoulSeek protocol defines 3 types of connections with each its own set of messages. The type of connection is established during the peer initialization message:

* Peer (``P``) : Peer to peer connection for messaging
* Distributed (``D``) : Distributed network connections
* File (``P``) : Peer to peer connection for file transfer

To accept connections from incoming peers there should be at least one listening port opened. However newer clients will open two ports: a non-obfuscated and an obfuscated port.

The obfuscated port is not mandatory and is usually just the obfuscated port + 1. Normally any port can be picked, both ports can be made known to the server using the :ref:`SetListenPort` message.

When a peer connection is accepted on the obfuscated port all messaging should be obfuscated, this only applies to peer connection though (``P``). Distributed (``D``) and file (``F``) connections are not obfuscated aside from the :ref:`peer-init-messages`.


.. _connecting-to-peer:

Connecting to a peer
--------------------

The process uses the server as a middle man in case we fail to connect to the other peer. To obtain the IP address and port of the peer the :ref:`GetPeerAddress` message is first requested from the server.

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

.. note::
   Question 2: Some clients appear to send a :ref:`PeerInit` instead of :ref:`PeerPierceFirewall` ?


Distributed Connections
=======================

Obtaining a parent
------------------

When :ref:`ToggleParentSearch` is enabled then every 60 seconds the server will send the client a :ref:`PotentialParents` command (containing 10 possible parents) until we disable our search for a parent using the :ref:`ToggleParentSearch` command. The :ref:`PotentialParents` command contains a list with each entry containing: username, IP address and port. Upon receiving this command the client will attempt to open up a connection to each of the IP addresses in the list to find a suitable parent.

After establishing a distributed connection with one of the potential parents the peer will send out a :ref:`DistributedBranchLevel` and :ref:`DistributedBranchRoot` over the distributed connection. If the peer is selected to be the parent the other potential parents are disconnected and the following messages are then send to the server to let it know where we are in the hierarchy:

* :ref:`BranchLevel` : BranchLevel from the parent + 1
* :ref:`BranchRoot` : The BranchRoot received from the parent
* :ref:`ToggleParentSearch` : Set to false to disable receiving :ref:`PotentialParents` commands

Once the parent is set it will start sending us search requests or if we are branch root the server will send us search request.


.. note::
   Branch Root is not always sent when the potential parent has branch level 0

.. note::
   Question 1: Is there a picking process for the parent? It seems to be first come first serve.

.. note::
   Question 2: When a parent disconnects, are all the children disconnected?


Obtaining children
------------------

The :ref:`AcceptChildren` command tells the server whether we want to have any children, this is probably used in combination with the :ref:`ToggleParentSearch` command which enables searching for parents. Enabling it will cause us to be listed in :ref:`PotentialParents` commands sent to other peers. It is not mandatory to have a parent and to obtain children if we ourselves are the branch root (branch level is 0).

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
2. Send: :ref:`PeerTransferQueue` message containing the ``filename``
3. Receive: :ref:`PeerTransferRequest` message. Store the ``ticket`` and the ``filesize``
4. Send: :ref:`PeerTransferReply` message containing the ``ticket``. If the ``allowed`` flag is set the other peer will now attempt to establish a connection for uploading, if it is not set the transfer should be aborted.


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

The original Windows SoulSeek client also has the ability to send files.


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


Rooms
=====

After joining a room, we will automatically be receiving :ref:`GetUserStatus` updates from the server.

Only private rooms have an owner and operators.

Room List
---------

The room list is received after login but can be refreshed by sending another :ref:`RoomList` request. The :ref:`RoomList` message consists of lists of rooms categorized by room type:

* ``rooms`` : all public rooms
* ``rooms_private_owned`` : private rooms which we own
* ``rooms_private`` : private rooms which we are part of. this excludes the rooms in rooms_private_owned
* ``rooms_private_operated`` : private rooms in which we are operator

.. note::
   Not all public rooms are listed in the initial :ref:`RoomList` message after login. Possibly (needs investigation) it returns only the rooms with more than 5 members.


Room Joining / Creation
-----------------------

To join a public room a :ref:`ChatJoinRoom` message is sent to the server, containing the name of the room and whether the room is private. If the room does not yet exist it is created.

Creating a public room:

1. Send :ref:`ChatJoinRoom` (is_private=0)
2. Receive:

  * :ref:`ChatUserJoinedRoom`
  * :ref:`ChatJoinRoom` : with our own username
  * :ref:`ChatRoomTickers`

Creating a private room:

1. Send :ref:`ChatJoinRoom` (is_private=1)
2. Receive:

  * :ref:`RoomList` : updated list of rooms. See 'Room List' section on what would be expected here
  * :ref:`PrivateRoomUsers` : list of users in the room (exluding ourself)
  * :ref:`PrivateRoomOperators` : list of operators
  * :ref:`ChatUserJoinedRoom` : with our own username
  * :ref:`ChatJoinRoom` : with our own username
  * :ref:`ChatRoomTickers`

.. note::
   Messages :ref:`PrivateRoomUsers`, :ref:`PrivateRoomOperators` seems to be repeated for private rooms we are already part of

.. note::
   Possibly on the server side the joining happens after some of these messages are sent. In the :ref:`RoomList` message the `rooms_private_owned_user_count` is 0, in the PrivateRoomsUsers message the list of users is empty. The

.. note::
   :ref:`PrivateRoomUsers` returns the users which are part of the room (excluding the owner) while :ref:`RoomList` rooms_private_user_count only return the amount of online users


Room Leaving
------------

From the user leaving the room:

1. Send: :ref:`ChatLeaveRoom` : with room name
2. Receive:

   * :ref:`ChatLeaveRoom` : with room name

Other users in the room:

1. Receive:

   * :ref:`ChatUserLeftRoom` : with room name and user name


Add User to Private Room
------------------------

Owners and operators can add users to rooms.

User adding another user:

1. Send: :ref:`PrivateRoomAddUser` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomAddUser` : with room name and user name
   * Server message: User <user_name> is now a member of room <room_name>

The added user:

1. Receive:

   * :ref:`PrivateRoomAddUser` : with room name and user name
   * :ref:`PrivateRoomAdded` : with room name
   * :ref:`RoomList`

The owner of the room:

1. Receive:

   * :ref:`PrivateRoomAddUser` : with room name and user name
   * Server message: User [<user_name>] was added as a member of room [<room_name>] by operator [<operator_name>]


Removing User from Private Room
-------------------------------

Owners can remove operators and members, operators can only remove members.

User removing another user (owner):

1. Send: :ref:`PrivateRoomRemoveUser` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomRemoveUser` : with room name and user name
   * Server message: User <user_name> is no longer a member of room <room_name>

User being removed:

1. Receive:

   * :ref:`PrivateRoomRemoved` : with room name
   * :ref:`ChatLeaveRoom` : with room name
   * :ref:`RoomList`

The owner of the room:

1. Receive:

   * :ref:`PrivateRoomRemoveUser` : with room name and user name
   * Server message: User <user_name> is no longer a member of room <room_name>


Granting Operator to Private Room
---------------------------------

User granting operator:

1. Send: :ref:`PrivateRoomAddOperator` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomAddOperator` : with room name and user name (got this twice for some reason, perhaps a bug in the server? Should probably be PrivateRoomOperatorAdded)
   * Server message: User <user_name> is now an operator of room <room_name>


Revoking Operator from Private Room
-----------------------------------

User revoking operator:

1. Send: :ref:`PrivateRoomRemoveOperator` : with room name and user name
2. Receive:

   * :ref:`PrivateRoomRemoveOperator` : with room name and user name (got this twice for some reason, perhaps a bug in the server? Should probably be :ref:`PrivateRoomRemoveOperator`)
   * Server message: User <user_name> is no longer an operator of room <room_name>

User for which operator was revoked:

1. Receive:

   * :ref:`PrivateRoomRemoveOperator` : with room name and user name (got this twice)
   * :ref:`PrivateRoomOperatorRemoved` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomUsers` : for all private rooms we are part of
   * :ref:`PrivateRoomOperators` : for all private rooms we are part of


Dropping Membership
-------------------

Dropping membership can only be done for a private room. This function does nothing for the owner, he needs to drop ownership.

As regular member
~~~~~~~~~~~~~~~~~

Member dropping membership:

1. Send: PrivateRoomDropMembership : with room name
2. Receive:

   * :ref:`PrivateRoomRemoved` : with room name
   * :ref:`ChatLeaveRoom` : with room name
   * :ref:`RoomList`


Received by owner:

1. Receive:

   * :ref:`PrivateRoomRemoveUser` : with room name and user name
   * Server message: User <user_name> is no longer a member of room <room_name>
   * :ref:`ChatUserLeftRoom` : with room name and user name

Received by operator:

1. Receive:

   * :ref:`PrivateRoomRemoveUser` : with room name and user name
   * :ref:`ChatUserLeftRoom` : with room name and user name


As operator
~~~~~~~~~~~

Operator dropping membership:

1. Send: PrivateRoomDropMembership : with room name
2. Receive:

   * :ref:`PrivateRoomRemoved` : with room name
   * :ref:`ChatLeaveRoom` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomUsers` : for private rooms we are still part of
   * :ref:`PrivateRoomOperators` : for private rooms we are still part of
   * :ref:`PrivateRoomOperatorRemoved`
   * :ref:`RoomList`
   * :ref:`PrivateRoomUsers` : for private rooms
   * :ref:`PrivateRoomOperators` : for private rooms

Received by owner:

1. Receive:

   * :ref:`PrivateRoomRemoveUser`
   * Server message: User <user_name> is no longer a member of room <room_name>
   * :ref:`ChatUserLeftRoom`
   * :ref:`PrivateRoomRemoveOperator` (twice)
   * Server message: User <user_name> is no longer an operator of room <room_name>

Received by member:

1. Receive:

   * :ref:`PrivateRoomRemoveUser`
   * :ref:`ChatUserLeftRoom`
   * :ref:`PrivateRoomRemoveOperator` (twice)


Dropping Ownership
------------------

Owner dropping ownership:

1. Send: PrivateRoomDropOwnership : with room name
2. Receive:

   * :ref:`ChatUserLeftRoom` : with room name and user name for all other users in the room
   * :ref:`RoomList`
   * :ref:`PrivateRoomUsers` : for private rooms we are still part of
   * :ref:`PrivateRoomOperators` : for private rooms we are still part of

Received by operator:

1. Receive:

   * :ref:`PrivateRoomRemoved` : with room name
   * :ref:`ChatLeaveRoom` : with room name
   * :ref:`RoomList`
   * :ref:`PrivateRoomUsers` : for private rooms we are still part of
   * :ref:`PrivateRoomOperators` : for private rooms we are still part of
   * :ref:`PrivateRoomOperatorRemoved`
   * :ref:`RoomList`
   * :ref:`PrivateRoomUsers` : for private rooms
   * :ref:`PrivateRoomOperators` : for private rooms

Received by member:

1. Receive:

   * :ref:`ChatUserLeftRoom` : for the operator that was in the room
   * :ref:`PrivateRoomRemoveOperator` : for the operator that was in the room
   * :ref:`PrivateRoomRemoved`
   * :ref:`ChatLeaveRoom`
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

* Joing/creating: Non-ascii characters in room name

  * Server message: Could not create room. Reason: Room name <room_name> contains invalid characters.

* Joining/creating: Empty room name

  * Server message: Could not create room. Reason: Room name empty.

* Add User to Room: Adding a user who does not have private rooms enabled

  * Server message: user <user_name> hasn't enabled private room add. please message them and ask them to do so before trying to add them again.
