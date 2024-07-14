==============
SoulSeek Flows
==============

.. contents:

This document describes different flows and details for the SoulSeek protocol

How to read this document
=========================

The order of the actions is (usually) deliberate to keep the order of the messages. For example: when a user leaves a room the first step is to remove the user from the list of joined users. If a subsequent step describes that a message should be sent to all joined users then that list excludes the leaving user itself as the user was removed in the first step.

For some of the checks and input checks the action performed is simply "Continue", in these cases the behaviour has been verified but no error is given. This is usually done in cases where an error was expected but non was given and is a reminder that it has been verified.


Peer Flows
==========

All peer connections use the TCP protocol. The SoulSeek protocol defines 3 types of connections with each its own set of messages. The type of connection is established during the peer initialization message:

* Peer (``P``) : Peer to peer connection for messaging
* Distributed (``D``) : Distributed network connections
* File (``F``) : Peer to peer connection for file transfer

To accept connections from incoming peers there should be at least one listening port opened. However newer clients will open two ports: a non-obfuscated and an obfuscated port.

The obfuscated port is not mandatory and is usually just the obfuscated port + 1. Normally any port can be picked, both ports can be made known to the server using the :ref:`SetListenPort` message. How obfuscation works is described in the :ref:`obfuscation` section

When a peer connection is accepted on the obfuscated port all messaging should be obfuscated with each their own key, this only applies to peer connection though (``P``). Distributed (``D``) and file (``F``) connections are not obfuscated aside from the :ref:`peer-init-messages`.


.. _connecting-to-peer:

Connecting to a peer
--------------------

The process uses the server to request the IP as well as a middle man in case we fail to connect to the other peer. To obtain the IP address and port of the peer the :ref:`GetPeerAddress` message is first requested from the server.

We can connect to them:

1. Attempt to connect to the peer -> connection established
2. Generate a ticket number
3. Send :ref:`PeerInit` over the peer connection

   * ``ticket``
   * ``username``
   * ``connection_type``

We cannot connect to them, but they can connect to us:

1. Attempt to connect to the peer -> connection failure
2. Generate a ticket number, store the associated information (username, connection_type)
3. Send :ref:`ConnectToPeer` to the server

   * ``ticket``
   * ``username``
   * ``connection_type``

4. Incoming connection from peer -> connection is established
5. Receive :ref:`PeerPierceFirewall` over the peer connection (ticket)
6. Look up the ticket and associated information

We cannot connect to them, they cannot connect to us:

1. Attempt to connect to the peer -> connection failure
2. Generate a ticket number
3. Send :ref:`ConnectToPeer` command to the server

   * ``ticket``
   * ``username``
   * ``connection_type``

4. Nothing should happen here, as they cannot connect to us
5. Other peer sends :ref:`CannotConnect` to the server

   * ``ticket`` : ``ticket`` parameter from the :ref:`ConnectToPeer` message

6. Receive :ref:`CannotConnect` from server (ticket)

.. note::

   Other clients don't seem to adhere to this flow: they don't actually wait for the connection to be established and just fires a :ref:`ConnectToPeer` message to the server at the same time as it tries to establish a connection to the peer.


Delivering Search Results
-------------------------

Delivery of search results is the same process for all kinds of search messages:

1. Receive :ref:`FileSearch` from the server

   * ``ticket``
   * ``username``

2. If the query matches:

  1. Initialize peer connection (``P``) for the ``username`` from the request
  2. Send :ref:`PeerSearchReply`

     * ``ticket`` from the original search request and query matches


.. _obfuscation:

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
* Obfuscated message : ``1494ee4a 2028dd95 2850ba2b 4aa37457`` (first 4 bytes are the key)

**De-obfuscated first 4 bytes of the message**

Convert the key to big-endian: ``14 94 ee 4a`` -> ``4a ee 94 14``

Original key:

* Hex: ``4a ee 94 14``
* Bin: ``0100 1010 1110 1110 1001 0100 0001 0100``

Key shifted 31 bits to the right:

* Hex: ``95 dd 28 28``
* Bin: ``1001 0101 1101 1101 0010 1000 0010 1000``

Convert to little-endian: ``95 dd 28 28`` -> ``28 28 dd 95``

XOR the first 4 bytes of the message (``20 28 dd 95``) with the rotated key:

+-----+----+----+----+----+
|     | b3 | b2 | b1 | b0 |
+=====+====+====+====+====+
|     | 28 | 28 | dd | 95 |
+-----+----+----+----+----+
| XOR | 20 | 28 | dd | 95 |
+-----+----+----+----+----+
|     | 08 | 00 | 00 | 00 |
+-----+----+----+----+----+


**De-obfuscated second 4 bytes of the message**

Convert the key to big-endian: ``28 28 dd 95`` -> ``95 dd 28 28``

Original key:

* Hex: ``95 dd 28 28``
* Bin: ``1001 0101 1101 1101 0010 1000 0010 1000``

Key shifted 31 bits to the right:

* Hex: ``2b ba 50 51``
* Bin: ``0010 1011 1011 1010 0101 0000 0101 0001``

Convert to little-endian: ``2b ba 50 51`` -> ``51 50 ba 2b``

XOR the second 4 bytes of the message (``28 50 ba 2b``) with the rotated key:

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

Convert the key to big-endian: ``51 50 ba 2b`` -> ``2b ba 50 51``

Original key:

* Hex: ``2b ba 50 51``
* Bin: ``0010 1011 1011 1010 0101 0000 0101 0001``

Key shifted 31 bits to the right:

* Hex: ``57 74 a0 a2``
* Bin: ``0101 0111 0111 0100 1010 0000 1010 0010``

Convert to little-endian: ``57 74 a0 a2`` -> ``a2 a0 74 57``

XOR the third 4 bytes of the message (``4a a3 74 57``) with the rotated key:

+-----+----+----+----+----+
|     | b3 | b2 | b1 | b0 |
+=====+====+====+====+====+
|     | a2 | a0 | 74 | 57 |
+-----+----+----+----+----+
| XOR | 4a | a3 | 74 | 57 |
+-----+----+----+----+----+
|     | e8 | 03 | 00 | 00 |
+-----+----+----+----+----+


Delivering Search Results
-------------------------

Delivery of search results is the same process for all kinds of search messages:

* :ref:`FileSearch` from the server in case the searcher used :ref:`UserSearch` or :ref:`RoomSearch`
* :ref:`ServerSearchRequest` from the server in case we are branch root
* :ref:`DistributedServerSearchRequest`, :ref:`DistributedSearchRequest` from the distributed peer in case we are in the distributed network

1. Receive search request. All messages contain:

   * ``ticket``
   * ``username``
   * ``query``

2. If the query matches:

  1. Initialize peer connection (``P``) for the ``username`` from the request
  2. Send :ref:`PeerSearchReply`

     * ``ticket`` : from the original search request and file data


Distributed Flows
=================

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

When a client receives a :ref:`GetUserStats` message the client should determine whether to enable or disable accepting children and if enabled, calculate the amount of maximum children.

1. If the ``avg_speed`` returned is smaller than the value received by :ref:`ParentMinSpeed` * 1024 :

   1. Send :ref:`AcceptChildren` (``accept = false``)

2. If the ``avg_speed`` is greater or equal than the value received by :ref:`ParentMinSpeed` * 1024 :

   1. Send :ref:`AcceptChildren` (``accept = true``)
   2. Calculate the ``divider`` from the ``ratio`` returned by :ref:`ParentSpeedRatio`: (``ratio`` / 10) * 1024
   3. Calculate the max number of children : floor(``avg_speed`` / ``divider``)


Example calculations
++++++++++++++++++++

**Calculation 1**

Values:

* ratio=50
* avg_speed=20480

Calculation:

* (50 / 10) * 1024 = 5120
* floor(20480 / 5120) = 4

**Calculation 2**

Values:

* ratio=30
* avg_speed=20480

Calculation:

* (30 / 10) * 1024 = 3072
* floor(20480 / 3072) = 6 (floored from 6.66666666)


.. note::
   With this formula there is a possibility that even when the ``avg_speed`` is greater than the ``min_speed_ratio`` the max amount of children calculated is 0. In this case the :ref:`AcceptChildren` is sent with ``accept=true``, despite the client not accepting any children.


Searches on the distributed network
-----------------------------------

Searches for the branch root (level = 0) will come from the server in the form of a :ref:`ServerSearchRequest` message. The branch root forwards this message as-is directly to its children (level = 1). The children will then convert this message into a :ref:`DistributedSearchRequest` and pass it on to its children (level = 2). It is up to the peer to perform the query on the local filesystem and report the results the peer making the query.

.. note::
   The reason why it is done this way is not clear. The branch root could perfectly convert it into a :ref:`DistributedSearchRequest` itself before passing it on. This would in fact be cleaner as right now the :ref:`DistributedServerSearchRequest` is just a copy of :ref:`ServerSearchRequest`, otherwise this wouldn't parse.

   The naming of these messages is probably incorrect as the ``distributed_code`` parameter of the :ref:`ServerSearchRequest` holds the distributed message ID. Possibly the server could send any distributed command through this that needs to be broadcast over the distributed network.


Transfer Flows
==============

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




Server Connection and Logon
===========================

* SoulSeekQt: server.slsknet.org:2416
* SoulSeek 157: server.slsknet.org:2242

Establishing a connection and logging on:

1. Open a TCP connection to the server
2. Open up at least one listening connection (see :ref:`peer-connections` for more info)
3. Send the :ref:`Login`: message on the server socket

A login response will be received which determines whether the login was successful

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


Server Flows
============

This section describes the flows from a point of view of the server as well as the presumed internal structures.


Structures
----------

**Server structure**

.. _structure-server:

+----------------------------+---------------+---------+----------------------------------------+
|           Field            |     Type      | Default |              Description               |
+============================+===============+=========+========================================+
| peers                      | array[Peer]   | <empty> | Current peer connections to the server |
+----------------------------+---------------+---------+----------------------------------------+
| users                      | array[User]   | <empty> | List of users                          |
+----------------------------+---------------+---------+----------------------------------------+
| rooms                      | array[Room]   | <empty> | List of rooms                          |
+----------------------------+---------------+---------+----------------------------------------+
| privileged_users           | array[string] | <empty> | List of names of privileged users      |
+----------------------------+---------------+---------+----------------------------------------+
| excluded_search_phrases    | array[string] | <empty> |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| motd                       | string        | <empty> | Message of the day                     |
+----------------------------+---------------+---------+----------------------------------------+
| parent_min_speed           | integer       | 1       |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| parent_speed_ratio         | integer       | 50      |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| min_parents_in_cache       | integer       | 10      |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| parent_inactivity_timeout  | integer       | 300     |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| search_inactivity_timeout  | integer       | 0       |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| distributed_alive_interval | integer       | 0       |                                        |
+----------------------------+---------------+---------+----------------------------------------+
| wishlist_interval          | integer       | 720     |                                        |
+----------------------------+---------------+---------+----------------------------------------+

**Peer structure**

.. _structure-peer:

+------------+--------+-----------+-------------------------------------------------+
|   Field    |  Type  |  Default  |                   Description                   |
+============+========+===========+=================================================+
| user       | User   | <not set> | User structure assigned to this peer connection |
+------------+--------+-----------+-------------------------------------------------+
| ip_address | string | 0.0.0.0   | IP address that the peer is connecting from     |
+------------+--------+-----------+-------------------------------------------------+

**QueuedPrivateMessage structure**

+-----------+--------+-----------+--------------------------------------------------------+
|   Field   |  Type  |  Default  |                      Description                       |
+===========+========+===========+========================================================+
| username  | string | <not set> | Username of the sender of the private message          |
+-----------+--------+-----------+--------------------------------------------------------+
| message   | string | <not set> | Message body                                           |
+-----------+--------+-----------+--------------------------------------------------------+
| chat_id   | int    | <not set> | Generated chat ID                                      |
+-----------+--------+-----------+--------------------------------------------------------+
| timestamp | int    | <not set> | Timestamp that the send sent the message to the server |
+-----------+--------+-----------+--------------------------------------------------------+


**UserStatus enumeration**

List of possible user statuses

.. _structure-user-status:

+---------+-------+
| Status  | Value |
+=========+=======+
| OFFLINE | 0     |
+---------+-------+
| AWAY    | 1     |
+---------+-------+
| ONLINE  | 2     |
+---------+-------+

**User structure**

.. _structure-user:

Structure of a user:

+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
|        Field         |     Type      | Default |                                                  Description                                                  |
+======================+===============+=========+===============================================================================================================+
| name                 | string        |         |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| password             | string        | <empty> |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| is_admin             | boolean       | false   |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| status               | integer       | 0       | Current status of the user. Possible values described in :ref:`the user status table <structure-user-status>` |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| avg_speed            | integer       | 0       | Average upload speed                                                                                          |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| uploads              | integer       | 0       |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| shared_file_count    | integer       | 0       |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| shared_folder_count  | integer       | 0       |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| country              | string        | <empty> |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| interests            | array[string] | <empty> |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| hated_interests      | array[string] | <empty> |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| added_users          | array[string] | <empty> | List of users added through the :ref:`AddUser` message                                                        |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| enable_private_rooms | boolean       | false   |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| enable_parent_search | boolean       | false   |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| enable_public_chat   | boolean       | false   |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| accept_children      | boolean       | false   |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| port                 | integer       | 0       |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+
| obfuscated_port      | integer       | 0       |                                                                                                               |
+----------------------+---------------+---------+---------------------------------------------------------------------------------------------------------------+


**Room structure**

.. _structure-room:

+----------------------+---------------------+-------------------------------------------------------------------+
|        Field         |        Type         |                            Description                            |
+======================+=====================+===================================================================+
| name                 | string              | Name of the room                                                  |
+----------------------+---------------------+-------------------------------------------------------------------+
| tickers              | map[string, string] | Ordered map of room tickers. Key=username, value=ticker           |
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


Events
------

Peer Connected
~~~~~~~~~~~~~~

**Actors:**

* ``peer`` : A peer connection

**Actions:**

1. Create a new ``Peer`` structure and add it to the list of ``peers``


.. note::

   If the peer does not perform a valid logon with 1 minute then the peer will be disconnected

   * TODO: Check if performing an invalid logon extends the timeout
   * TODO: If above is true, check whether the same happens with other messages
   * TODO: Check what happens if any other message except logon is sent
   * TODO: Check total timeout of the server. Normally a ping should be sent every 5 minutes, if this is not done and no other messages are sent will the client be disconnected as well?


Peer Disconnected
~~~~~~~~~~~~~~~~~

**Actors:**

* ``peer`` : A peer connection

**Actions:**

1. Remove the ``peer`` from the ``peers`` list
2. If the ``peer`` had a ``user`` structure assigned

   1. For each ``room`` where the user is in the ``joined_users``

      * :ref:`function-leave-room`

   2. :ref:`function-update-user-status`

      * status : ``UserStatus.OFFLINE``


Protocol Message Received
~~~~~~~~~~~~~~~~~~~~~~~~~

**Actors:**

* ``peer`` : A peer connection over which a valid protocol message was sent

**Checks:**



**Actions:**




Messages
--------

Login
~~~~~

The :ref:`Login` message is the first message a peer needs to send to the server

**Message** :ref:`Login`

**Actors:**

* ``user`` : The user attempting to login

**Input Checks:**

* If ``client_version`` is less than TBD

   1. :ref:`function-server-info-message` : message : "Your connection is restricted: You cannot search or chat. Your client version is too old. You need to upgrade to the latest version. Close this client, download new version from http://www.slsknet.org, install it and reconnect."

* If ``username`` is empty:

  1. Send :ref:`Login`

     * success : false
     * reason : ``INVALIDPASS``

* If ``password`` is empty : Continue (there are some reference to a fail reason called ``EMPTYPASSWORD`` but isn't used)
* If ``md5hash`` parameter mismatches with the MD5 hash of the ``username + password`` parameters : Continue

**Checks:**

1. If the user exists in the ``users`` list:

   1. If the ``password`` parameter of the message does not equal the ``password`` of the ``user``:

      1. Send :ref:`Login`

         * success : false
         * reason : ``INVALIDPASS``

   2. If there is ``peer`` in the ``peers`` list with the ``user`` already assigned:

      1. Send :ref:`Kicked` message to the **existing peer**
      2. Disconnect the **existing peer**


**Actions:**

1. If the user does not exist in the ``users`` list:

   1. Create a new user and add it to the ``users`` list

2. Assign the ``user`` to the ``peer`` structure
3. :ref:`function-update-user-status`

   * status : ``UserStatus.ONLINE``

4. Send to the ``user``:

   1. :ref:`Login`

       * success : true
       * greeting : value from ``motd``
       * md5hash : md5hash of the ``password`` of the ``user``

   2. :ref:`function-send-queued-messages`
   3. :ref:`function-room-list-update`
   4. :ref:`ParentMinSpeed` : value from ``parent_min_speed``
   5. :ref:`ParentSpeedRatio` : value from ``parent_speed_ratio``
   6. :ref:`WishlistInterval` : value from ``wishlist_interval``
   7. :ref:`PrivilegedUsers` : list of ``privileged_users``
   8. :ref:`ExcludedSearchPhrases` : list of ``excluded_search_phrases``


Set Listening Ports
~~~~~~~~~~~~~~~~~~~

**Message:** :ref:`SetListenPort`

**Input Checks:**

**Checks:**

* TODO: If initially the obfuscated port was set and not provided the second time, what will the value be? (and vica versa)

**Actions:**

1. Set ``port`` and ``obfuscated_port`` of the ``user``


Get Peer Address
~~~~~~~~~~~~~~~~

**Message:** :ref:`GetPeerAddress`

**Actions:**

1. If there is a peer in the ``peers`` list with the user assigned

   1. :ref:`GetPeerAddress`

      * ``username`` : the ``username`` for which the peer address was requested
      * ``ip`` : ``Peer.ip_address``
      * ``port`` : ``User.port``
      * ``has_obfuscated_port`` : 0 if the ``obfuscated_port`` is 0 otherwise 1
      * ``obfuscated_port`` : ``User.obfuscated_port``

2. If there is a no peer in the ``peers`` list with the user assigned

   1. :ref:`GetPeerAddress`

      * ``username`` : the ``username`` for which the peer address was requested
      * ``ip`` : ``0.0.0.0``
      * ``port`` : ``0``
      * ``has_obfuscated_port`` : ``0``
      * ``obfuscated_port`` : ``0``


Set Status
~~~~~~~~~~

A request to change the current status of the user

**Message:** :ref:`SetStatus`

**Actors:**

* ``user`` : User attempting to change his status

**Input checks:**

* If the ``status`` is not ``UserStatus.ONLINE`` or ``UserStatus.AWAY``: Do nothing

**Checks:**

* If the requested ``status`` equals the ``status`` of the ``user``: Do nothing

**Actions:**

1. :ref:`function-update-user-status`

   * status : ``status`` field from the message


Set Shared Files / Folders
~~~~~~~~~~~~~~~~~~~~~~~~~~

A request to change the amount of files and folders shared

**Message:** :ref:`SharedFoldersFiles`

**Actors:**

* ``user`` : User attempting to change his sharing stats

**Actions:**

1. Change the ``user`` structure:

   * ``shared_file_count``
   * ``shared_folder_count``

2. For each user that has the ``user`` in the ``added_users`` list:

   1. :ref:`GetUserStatus` : with the updated stats

3. For each room where the ``user`` is in the ``joined_users`` list:

   1. For each user in the ``joined_users`` list of that room:

      1. :ref:`GetUserStats` : with the updated stats


Send Upload Speed
~~~~~~~~~~~~~~~~~

A request to update the average upload speed of the user

**Message:** :ref:`SendUploadSpeed`

**Actors:**

* ``user`` : User attempting to change his sharing stats

**Actions:**

Consider ``speed`` being the speed value sent in the message

1. Change the ``user`` structure

   1. Calculate the ``avg_speed`` (floor the result):

      .. math::

         avgspeed = ((avgspeed * uploads) + speed) / (uploads + 1)

   2. Increase the ``uploads`` by 1


Get User Status
~~~~~~~~~~~~~~~

**Message:** :ref:`GetUserStatus`

**Checks:**

* If the user does not exist in the ``users`` list:

  1. :ref:`GetUserStatus`

     * ``username`` : name of the user for which status was requested
     * ``status`` : ``UserStatus.OFFLINE``

**Actions:**

  1. :ref:`GetUserStatus`

     * ``username`` : name of the user for which status was requested
     * ``status`` : ``status`` of the user for which status was requested


Get User Stats
~~~~~~~~~~~~~~

**Message:** :ref:`GetUserStats`

**Checks:**

* If the user does not exist in the ``users`` list:

  1. :ref:`GetUserStats`

     * ``username`` : name of the user for which stats were requested
     * all stats set to 0

**Actions:**

  1. :ref:`GetUserStats`

     * ``username`` : name of the user for which stats were requested
     * stats of the user for which stats were requested


Add A User
~~~~~~~~~~

**Message:** :ref:`AddUser`

**Actors:**

* ``adder`` : User adding a user to his ``added_users``
* ``addee`` : User to be added to the ``added_users``

**Checks:**

* If the ``addee`` does not exist in the list of ``users``

  1. :ref:`AddUser`

     * ``username`` : name of the ``addee``
     * ``exists`` : false


**Actions:**

1. If the ``adder`` and ``addee`` are different (not adding self):

   1. If the ``addee`` is not yet in the list of ``added_users`` of the ``adder``

      1. Add the ``addee`` to the list of ``added_users`` of the ``adder``

2. :ref:`AddUser`

   * ``username`` : name of the ``addee``
   * ``exists`` : true
   * Rest of the field are filled in with the values of the ``addee``


Remove A User
~~~~~~~~~~~~~

**Message:** :ref:`RemoveUser`

**Actors:**

* ``remover`` : User removing a user from his ``added_users``
* ``removee`` : User to be removed from the ``added_users``

**Checks:**

* If the ``remover`` and ``removee`` are the same : Do nothing
* If the ``removee`` is not in the list of ``added_users`` of the ``remover``: Do nothing

**Actions:**

1. Remove the ``removee`` from the list of ``added_users`` of the ``remover``


Private Chat Message
~~~~~~~~~~~~~~~~~~~~

This message is used to send a private chat message to a single user.

**Message:** :ref:`PrivateChatMessage`

**Actors:**

* ``sender`` : User sending the message
* ``receiver`` : User to which the message should be sent

**Input Checks:**

* If the ``username`` is empty : Continue (it should not be possible to have a user with an empty username)
* If the ``message`` is empty : Continue

**Checks:**

* If the ``receiver`` does not exist : Do nothing
* If the ``sender`` is the ``receiver`` : Continue

**Actions:**

1. Generate a ``chat_id``
2. Create a new instance of ``QueuedPrivateMessage`` and add to the ``queued_private_messages`` of the ``receiver``

   * chat_id : Generated ``chat_id``
   * timestamp : Current timestamp
   * message : ``message`` value of the message
   * username : Value of the ``name`` value of the ``sender``

3. If there is a ``peer`` which is associated with the ``receiver``:

   1. Send to the ``receiver``

       1. :ref:`PrivateChatMessage`

          * chat_id : Generated ``chat_id``
          * timestamp : Current timestamp
          * message : ``message`` value of the message
          * username : Value of the ``name`` value of the ``sender``
          * is_direct : true


Private Chat Message Acknowledge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is used to acknowledge that a specific private message has been received. If private messages are not acknowledged they will be resent when the user logs in again.

**Message:** :ref:`PrivateChatMessageAck`

**Actors:**

* ``receiver`` : the user who has received the private message and is using this message to acknowledge he has received it

**Actions:**

1. If the ``chat_id`` exists in the ``queued_private_messages`` of the ``receiver``

   1. Remove the message with ``chat_id`` from the ``queued_private_message`` of the ``receiver``


Private Chat Message Multiple Users
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Message:** :ref:`PrivateChatMessageUsers`

**Actors:**

* ``sender`` : User sending the message to multiple users

**Input Checks:**

* If the ``message`` is empty : Continue
* If the list of ``usernames`` is empty : Continue

**Actions:**

1. For each ``receiver`` in the ``usernames`` parameter of the message

   1. If the ``receiver`` does not exist : Do nothing
   2. If the ``receiver`` exists:

      1. If the ``sender`` is not in the list of ``added_user`` of the ``receiver`` : Do nothing
      2. Create a new instance of ``QueuedPrivateMessage`` and add to the ``queued_private_messages`` of the ``receiver``

         * chat_id : Generated ``chat_id``
         * timestamp : Current timestamp
         * message : ``message`` value of the message
         * username : Value of the ``name`` value of the ``sender``

      3. If there is a ``peer`` which is associated with the ``receiver``:

         1. Send to the ``receiver``

            1. :ref:`PrivateChatMessage`

               * chat_id : Generated ``chat_id``
               * timestamp : Current timestamp
               * message : ``message`` value of the message
               * username : Value of the ``name`` value of the ``sender``
               * is_direct : true


Global Search
~~~~~~~~~~~~~

Perform a search query to everyone on the network.

**Message:** :ref:`FileSearch`

**Actors:**

* ``searcher`` : User requesting a global search

**Actions:**

1. Foreach user who is a distributed root:

   :ref:`DistributedServerSearchRequest`


Room Search
-----------

Performs a search on every one in a single room:

1. Searcher send: :ref:`RoomSearch` : with a `ticket`, the `query` and `room` name
2. Room user receive: :ref:`FileSearch`


**Message:** :ref:`RoomSearch`

**Actors:**

* ``searcher`` : User requesting a room search

**Checks:**

* TODO: If the room does not exist
* TODO: If the user not joined to the room
* TODO: If the query is empty

**Actions:**

1. Foreach user in the list of ``joined_users``:

   1. :ref:`FileSearch`

      * ``username`` : name of the ``searcher``
      * ``ticket`` : ``ticket`` parameter of the request message
      * ``query`` : ``query`` parameter of the request message


.. note::

   * TODO: Verify if request is also sent to self
   * TODO: Verify if it is possible to query non-joined private rooms of which we are member


User Search
-----------

Performs a search query on an individual user

**Message:** :ref:`RoomSearch`

**Actors:**

* ``searcher`` : User requesting to query an individual
* ``searchee`` : User being queried

**Checks:**

* TODO: User does not exist

**Actions:**

1. To ``searchee``:

   1. :ref:`FileSearch`

      * ``username`` : name of the ``searcher``
      * ``ticket`` : ``ticket`` parameter of the request message
      * ``query`` : ``query`` parameter of the request message


.. _room-list:

Room List
~~~~~~~~~

The room list is received after login but can be refreshed by sending another :ref:`RoomList` request.

**Message:** :ref:`RoomList`

**Actions:**

1. :ref:`RoomList`

   * ``rooms`` : public rooms
   * ``rooms_private_owned`` : private rooms for which we are ``owner``
   * ``rooms_private`` : private rooms for which we are in the ``members`` list
   * ``rooms_private_operated`` : private rooms for which we are in the ``operators`` list

.. note::
   Not all public rooms are listed in the initial :ref:`RoomList` message after login; only rooms with 5 or more ``joined_users``.

   It's not clear where this limit comes from, and possibly if the total amount of public rooms is low those rooms are included anyway (and perhaps if it's high the minimum amount of members increases as well)


Room Joining / Creation
~~~~~~~~~~~~~~~~~~~~~~~

Joining and creating the room is combined into one message, it contains the ``name`` of the room and whether the room is ``private``

**Message:** :ref:`JoinRoom`

**Actors:**

* ``joiner`` : user requesting to join the room

**Input Checks:**

* If room ``name`` is empty:

  * :ref:`function-server-info-message` : message : "Could not create room. Reason: Room name empty."

* If room ``name`` contains leading or trailing white spaces:

  * :ref:`function-server-info-message` : message : "Could not create room. Reason: Room name ``name`` contains leading or trailing spaces."

* If room ``name`` contains multiple subsequent white spaces (eg.: "my<2 or more spaces>room"):

  * :ref:`function-server-info-message` : message : "Could not create room. Reason: Room name ``name`` contains multiple following spaces."

* If room ``name`` contains non-ascii characters:

  * :ref:`function-server-info-message` : message : "Could not create room. Reason: Room name ``name`` contains invalid characters."


**Checks:**

* If room exists and ``joiner`` is in the ``joined_users`` list (user already joined):

  * Do nothing

* If room exists and ``joiner`` is not in the ``all_members`` list:

  * Send :ref:`CannotCreateRoom`
  * :ref:`function-server-info-message` : message : "The room you are trying to enter (``name``) is registered as private."


**Actions:**

1. If the room does not exist (or room is unclaimed) and the request is to join a public room (``private=false``):

   1. Create new room or claim the unclaimed room

      * ``name`` : set to desired name
      * ``owner`` : leave empty
      * ``registered_as_public`` : true

2. If the room is unclaimed, is registered as public room (``registered_as_public=true``) and the request is to join a private room (``private=true``):

   * :ref:`function-server-info-message` : message to ``joiner`` : "Room (``name``) is registered as public."

3. If the room does not exist (or room is unclaimed), is not registered as public room (``registered_as_public=false``) and the request is to join a private room (``private=true``):

   1. Create new room or claim the unclaimed room

      * ``name`` : set to desired name
      * ``owner`` : set to room creator
      * ``registered_as_public`` : false

   2. :ref:`function-room-list-update`

4. :ref:`function-join-room`


Leave Room
~~~~~~~~~~

**Message:** :ref:`LeaveRoom`

**Actors:**

* ``leaver`` : user requesting to leave the room

**Checks**

* User is not part of the room : Do nothing
* Room does not exist : Do nothing

**Actions**

1. :ref:`function-leave-room`


Grant Membership in Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Operators and owners of a private room can grant membership to a user allowing that user to join the room. The message contains the ``name`` of the room and the ``username`` of the user that should be given membership.

**Message:** :ref:`PrivateRoomGrantMembership`

**Actors:**

* ``granter`` : User granting membership
* ``grantee`` : User being granted membership

**Checks:**

* If the room ``name`` is not a valid room (public) : Do nothing
* If the room ``name`` is not a valid room (does not exist) : Do nothing
* If the ``grantee`` and ``granter`` are the same : Do nothing
* If the ``granter`` is not the ``owner`` or in the ``operators`` list : Do nothing
* If the ``grantee`` is offline or does not exist:

  * :ref:`function-server-info-message` : message : "user ``grantee`` is not logged in."

* If the ``grantee`` is not accepting private room invites:

  * :ref:`function-server-info-message` : message : "user ``grantee`` hasn't enabled private room add. please message them and ask them to do so before trying to add them again."

* If the ``granter`` is in ``operators`` list and tries to add the ``owner``

  * :ref:`function-server-info-message` : message : "user ``grantee`` is the owner of room ``name``"

* If the ``grantee`` is already in the ``members`` list:

  * :ref:`function-server-info-message` : message : "user ``grantee`` is already a member of room ``name``"


**Actions:**

1. :ref:`function-private-room-grant-membership`


Revoke Membership from Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Removes a member from a private room. The owner can remove operators and members, operators can only remove members. The message contains the ``name`` of the room and the ``username`` of the user that should be revoked membership.

**Message:** :ref:`PrivateRoomRevokeMembership`

**Actors:**

* ``revoker`` : User revoking membership
* ``revokee`` : User being revoked membership

**Checks:**

* If the ``revoker`` and ``revokee`` are the same user : Do nothing
* If the ``revokee`` is not in the ``members`` list : Do nothing
* If the ``revoker`` is in the ``operators`` list and the ``revokee`` is the ``owner`` : Do nothing
* If the ``revoker`` and ``revokee`` are both in the ``operators`` list : Do nothing

**Actions:**

1. :ref:`function-private-room-revoke-membership`


Granting Operator Privileges in a Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Room owners can grant operator privileges to members of a private room, the message contains the ``name`` of the room and the ``username`` of the member that should be granted operator privileges.

**Message:** :ref:`PrivateRoomGrantOperator`

**Actors:**

* ``granter`` : User granting the operator privileges
* ``grantee`` : User having operator privileges granted

**Checks:**

* If ``granter`` is not the ``owner`` : Do nothing
* If user does not exist or is offline (even in ``members`` list):

  * :ref:`function-server-info-message` : message : "user ``grantee`` is not logged in."

* If ``grantee`` is not in the ``members`` list:

  * :ref:`function-server-info-message` : message : "user ``grantee`` must first be a member of room ``name``"

* If ``grantee`` is already in the ``operators`` list:

  * :ref:`function-server-info-message` : message : "user ``grantee`` is already an operator of room ``name``"


**Actions:**

1. :ref:`function-private-room-grant-operator`


Revoking Operator Privileges in a Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Room owners can revoke operator privileges from operator of a private room. The message contains the ``name`` of the room and the ``username`` of the member that should have his operator privileges revoked.

**Message:** :ref:`PrivateRoomRevokeOperator`

**Actors:**

* ``revoker`` : User revoking the operator privileges
* ``revokee`` : User having operator privileges revoked

**Checks:**

* If user does not exist: Do nothing
* If ``revoker`` is not the ``owner`` : Do nothing
* If ``revokee`` is not in the ``members`` list: Do nothing
* If ``revokee`` is not in the ``operators`` list: Do nothing

**Actions:**

1. :ref:`function-private-room-revoke-operator`


Dropping Membership
~~~~~~~~~~~~~~~~~~~

Members themselves can drop their membership from a private room

**Message:** :ref:`PrivateRoomDropMembership`

**Checks:**

* If the user is not in the ``members`` list : Do nothing

**Actions:**

1. :ref:`function-private-room-revoke-membership`
2. If the user is in the ``operators`` list:

   * :ref:`function-private-room-revoke-operator`


Dropping Ownership
~~~~~~~~~~~~~~~~~~

Owners can drop ownership of a private room, this will disband the private room.

**Message:** :ref:`PrivateRoomDropOwnership`

**Checks:**

* If the user tries to drop ownership for a room that does not exist: Do nothing
* If the user tries to drop ownership of a public room: Do nothing
* If the member is not the ``owner``

**Actions:**

1. Reset the ``owner``
2. Empty the ``operators`` list of the room
3. Empty the ``members`` list of the room **but keep a reference to this list**
4. For each member in the stored list:

   * :ref:`function-private-room-revoke-membership`

5. :ref:`function-room-list-update`

.. warning::
   The server will not remove the the owner from the ``joined_users``. The owner should send a second command to leave the room after sending this command. This seems like a mistake that was corrected in the client itself instead of on the server side.


Room Message
~~~~~~~~~~~~

Sending a chat message to a room is done through the :ref:`RoomChatMessage` message

**Message:** :ref:`RoomChatMessage`

**Actors:**

* ``sender`` : User sending a chat message to the room

**Checks:**

* If the room does not exist : Do nothing
* If the user is not in the ``joined_users`` list : Do nothing

**Actions:**

1. For each user in the ``joined_users`` list:

   * :ref:`RoomChatMessage` : with ``sender``, ``message`` and room ``name``

2. If the room is public (``is_private=false``):

   * For each user currently online and has public chat enabled:

     * :ref:`PublicChatMessage` : with ``sender``, ``message`` and room ``name``

.. note::
  Empty message is allowed


Set Room Ticker
~~~~~~~~~~~~~~~

Room tickers are a sort of room wall, where users can place a single message that is visible to everyone in the room. They are sent after the user joins a room using the :ref:`RoomTickers` message and users will be notified of updates through the :ref:`RoomTickerAdded` and :ref:`RoomTickerRemoved` messages.

A room ticker can be set with the :ref:`SetRoomTicker` message for which the actions are described in this section.

**Message:** :ref:`SetRoomTicker`

**Actors:**

* ``user`` : User that requests to set a room ticker


**Input Checks:**

* If the length of the ``ticker`` is greater than 1024 : Do nothing
* TODO: Any characters not allowed?


**Checks:**

* If the room does not exist : Do nothing
* If ``user`` is not in the ``joined_users`` list (public) : Do nothing


**Actions:**

1. If the ``user`` has an entry in ``tickers``

   * Remove the entry of the ``user`` from the ``tickers``
   * For each user in the ``joined_users`` list:

     * :ref:`RoomTickerRemoved` : with room ``name`` and the ``user`` for which the ticker was removed

2. If the ``ticker`` in the :ref:`SetRoomTicker` message is not empty:

   * Add an entry for the ``user`` to the ``tickers``
   * For each user in the ``joined_users`` list:

     * :ref:`RoomTickerAdded` : with room ``name``, ``user`` and the ``ticker``


.. note::
  Tickers are retained even when ownership is dropped for a private room


Enable Public Chat
~~~~~~~~~~~~~~~~~~

**Message:** :ref:`EnablePublicChat`

**Actions:**

1. Set ``enable_public_chat`` to ``true``


Disable Public Chat
~~~~~~~~~~~~~~~~~~~

**Message:** :ref:`EnablePublicChat`

**Actions:**

1. Set ``enable_public_chat`` to ``false``


Add an Interest
~~~~~~~~~~~~~~~

**Message:** :ref:`AddInterest`

**Input Checks:**

* If the ``interest`` is empty : Continue

**Actions:**

1. If the ``interest`` is not present in the list of ``interests``

  1. Add the ``interest`` to the list of ``interests``


Add a Hated Interest
~~~~~~~~~~~~~~~~~~~~

**Message:** :ref:`AddHatedInterest`

**Input Checks:**

* If the ``hated_interest`` is empty : Continue

**Actions:**

1. If the ``hated_interest`` is not present in the list of ``hated_interests``

   1. Add the ``hated_interest`` to the list of ``hated_interests``



Remove an Interest
~~~~~~~~~~~~~~~~~~

**Message:** :ref:`RemoveInterest`

**Input Checks:**

* If the ``interest`` is empty: Continue

**Actions:**

1. If the ``interest`` is present in the list of ``interests``

   1. Remove the ``interest`` from the list of ``interests``


Remove a Hated Interest
~~~~~~~~~~~~~~~~~~~~~~~

**Message:** :ref:`RemoveHatedInterest`

**Input Checks:**

* If the ``hated_interest`` is empty: Continue

**Actions:**

1. If the ``hated_interest`` is present in the list of ``hated_interests``

   1. Remove the ``hated_interest`` from the list of ``hated_interests``


Getting Interests
~~~~~~~~~~~~~~~~~

**Message:** :ref:`GetUserInterests`

**Actors:**

* ``user`` : user for which the interests were requested

**Input Checks:**

* If the ``username`` is empty: continue

**Checks:**

* If the ``user`` does not exist:

  1. :ref:`GetUserInterests`

     * ``username`` : username of the user for which interests were requested
     * ``interests`` : empty list
     * ``hated_interests`` : empty list

**Actions:**

1. :ref:`GetUserInterests`

   * ``username`` : username of the user for which interests were requested
   * ``interests`` : ``interests`` of the ``user``
   * ``hated_interests`` : ``hated_interests`` of the ``user``


Get Global Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~

Requests the global recommendations

**Message:** :ref:`GetGlobalRecommendations`

**Actions:**

Keep a ``counter`` (initially empty) to keep track of a ``score`` for each of the recommendations:

1. Loop over all currently active users (including the current user)

   a. Increase the ``score`` for all of the ``interests`` of the other user by 1
   b. Decrease the ``score`` for all of the ``hated_interests`` of the other user by 1

2. Unverified: Keep only recommendations where the ``score`` is not 0
3. The returned message will contain 2 lists:

   a. The recommendations sorted by score descending (limit to 200)
   b. The unrecommendations sorted by score ascending (limit to 200)


Get Item Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~

Request a set of recommendations can be returned based on the specified item.

**Message:** :ref:`GetItemRecommendations`

**Input Checks:**

* If the ``item`` is empty : Continue

**Actions:**

Keep a ``counter`` (initially empty) to keep track of a ``score`` for each of the recommendations:

1. Loop over all currently active users (excluding the current user)
2. If the ``item`` is in the user's interests:

   a. Increase the ``score`` for all of the ``interests`` of the other user by 1
   b. Decrease the ``score`` for all of the ``hated_interests`` of the other user by 1

3. Keep only recommendations where the ``score`` is not 0
4. The returned message will contain 1 lists:

   a. The recommendations sorted by score descending (limit to 100)


Get Recommendations
~~~~~~~~~~~~~~~~~~~

Request a personalized set of recommendations can be returned based on the interests and hated interests.

**Message:** :ref:`GetRecommendations`

**Actions:**

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
````````

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
~~~~~~~~~~~~~~~~~

The :ref:`GetSimilarUsers` message returns users that have similar interests to you.

**Message:** :ref:`GetSimilarUsers`

**Actions:**

Create an empty list for storing similar users:

1. Loop over all currently active users (excluding the current user)
2. Calculate the amount of ``interests`` in common between the current user and those of the other user
3. If the overlap is greater than 1, add it to the list of similar users
4. Return the list of similar users and the amount of interests in common with that user (limit is unknown)


Get Item Similar Users
~~~~~~~~~~~~~~~~~~~~~~

The :ref:`GetItemSimilarUsers` message returns users that have the interest as provided in the request message (``item``).

**Message:** :ref:`GetItemSimilarUsers`

**Input Checks:**

* If the ``item`` is empty : Continue

**Actions:**

Create an empty list for storing similar users:

1. Loop over all currently active users (including the current user)
2. If the ``item`` is in the ``interests`` of the user add it to the list of similar users
3. Return the list of similar users (limit is unknown)


Functions
---------

This section describes flows that are re-used in several flows

.. _function-update-user-status:

Function: Update user status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Actors:**

* ``user`` : User updating his status

**Actions:**

1. Update the ``status`` field of the ``user`` to the requested status
2. If the requested ``status`` is not ``UserStatus.ONLINE`` or ``UserStatus.OFFLINE``:

   1. Send to ``user``

      1. :ref:`GetUserStatus`

         * ``username`` : the name of the ``user``
         * ``status`` : the new status

3. For each user that has the ``user`` in the ``added_users`` list:

   1. :ref:`GetUserStatus`

      * ``username`` : the name of the ``user``
      * ``status`` : the new status

4. For each room where the ``user`` is in the ``joined_users`` list:

   1. For each user in the ``joined_users`` list of that room:

      1. :ref:`GetUserStatus`

         * ``username`` : the name of the ``user``
         * ``status`` : the new status


.. note::

   This function is used in the following 3 situations:

   * During login: user status goes from offline to online
   * During disconnect: user status goes from online/away to offline
   * When user sets status: user status goes from online to away or vice versa

   Step 2, informing the user itself of the status update, is effectively only executed when the status is changed to the away status. As such this message is only sent when a user changes his status from online to away. This seems to be a bug in the server.


.. _function-send-queued-messages:

Function: Send Queued Messages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Actors:**

* ``receiver`` user that the queued messages need to be delivered to

**Actions:**

1. For each messages in the ``queued_private_messages`` of the ``receiver``

   1. :ref:`PrivateChatMessage`

      * chat_id : ``chat_id`` value of the queued message
      * timestamp : ``timestamp`` value of the message
      * message : ``message`` value of the queued message
      * username : ``username``
      * is_direct : false


.. note::

   Messages are not removed from this list until they are acknowledged


.. _function-room-list-update:

Function: Send Room List Update
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is a collection of messages commonly sent to the peer after performing an action on a private room or after logging on.

**Actions:**

1. Server: Send :ref:`room-list`
2. Server: For each private room where the user is ``owner`` or in the list of ``members``

   * :ref:`PrivateRoomMembers` with room_name and list of ``members``

3. Server: For each private room where the user is ``owner`` or in the list of ``members``

   * :ref:`PrivateRoomOperators` with room_name and list of ``operators``


.. _function-notify-room-owner:

Function: Notify room owner
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Function to notify the room owner. This short function sends a server chat ``message`` to the ``owner`` of a room if the room has an owner.

**Actions:**

1. If the room has its ``owner`` value set:

   * :ref:`function-server-info-message` : to ``owner`` : ``message``


.. _function-join-room:

Function: Join room
~~~~~~~~~~~~~~~~~~~

Function to join the room, checks should already be performed.

**Actors:**

* ``joiner`` : user requesting to join the room

**Actions:**

1. Add the user to the list of ``joined_users``
2. For each user in the ``joined_users`` list:

   1. :ref:`UserJoinedRoom` : with room ``name`` (+ stats) of ``joiner`` of the room

3. Send to ``joiner``:

   1. :ref:`JoinRoom`

     * ``room`` : name of joined room
     * ``usernames`` : list of room ``joined_users``
     * user stats, online status, etc
     * ``owner`` : ``owner`` if ``is_private=true`` for the room
     * ``operators`` : ``owner`` if ``is_private=true`` for the room

   2. :ref:`RoomTickers`

     * ``room`` : name of joined room
     * ``tickers`` : array of room ``tickers``


.. _function-leave-room:

Function: Leave Room
~~~~~~~~~~~~~~~~~~~~

Function to leave a room

**Actors:**

* ``leaver`` : user requesting or being removed from the room

**Actions:**

1. Remove the user from the list of ``joined_users``
2. For each user in the ``joined_users`` list:

   1. :ref:`UserLeftRoom` : with room ``name`` and list (+ stats) of ``leaver`` of the room

3. Send to ``leaver``:

   1. :ref:`LeaveRoom` : with room ``name``


.. _function-private-room-grant-membership:

Function: Grant Membership to Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Function to grant membership to a user from a private room

**Actors:**

* ``granter`` : User granting membership
* ``grantee`` : User being granted membership

**Actions:**

1. Add new member to the ``members`` list
2. For each member in the ``members`` list:

   1. Send :ref:`PrivateRoomGrantMembership` with room name and new member name

3. For the ``grantee``:

   1. Send :ref:`PrivateRoomMembershipGranted` with the room name
   2. :ref:`function-room-list-update`

4. If the ``granter`` is in the list of room ``operators``:

   1. :ref:`function-notify-room-owner` : "User [``grantee``] was added as a member of room [``name``] by operator [``granter``]"

5. If the ``granter`` is the room ``owner``:

   1. :ref:`function-notify-room-owner` : "User ``granter`` is now a member of room ``name``"


.. _function-private-room-revoke-membership:

Function: Revoke Membership from Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Function to revoke membership from a user from a private room

**Actors:**

* ``revokee`` : User having membership revoked

**Actions:**

1. Remove user from the ``members`` list
2. For each member in the ``members`` list:

   1. Send :ref:`PrivateRoomRevokeMembership` with room name and removed member name

3. For the room ``owner``:

   1. :ref:`function-notify-room-owner` : "User ``revokee`` is no longer a member of room ``name``"

4. For the ``revokee``:

   1. Send :ref:`PrivateRoomMembershipRevoked` with the room name

5. If the ``revokee`` is in the ``joined_users`` list:

   1. :ref:`function-leave-room` : for the ``revokee``

6. For the ``revokee``:

   1. :ref:`function-room-list-update`


.. note::
   No specialized message is sent to the owner if an operator removes a member unlike when adding a member


.. _function-private-room-grant-operator:

Function: Grant Operator to Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Function to grant operator privileges to a member of a private room

**Actors:**

* ``granter`` : User granting the operator privileges
* ``grantee`` : User having operator privileges granted

**Actions:**

1. Add the member to the ``operators`` list:
2. For each member in the ``members`` list:

   1. Send :ref:`PrivateRoomGrantOperator` with room name and the name of the new operator

3. For each user in the ``joined_users`` list:

   1. Send :ref:`PrivateRoomGrantOperator` with room name and the name of the new operator

4. For the ``grantee``:

   1. Send :ref:`PrivateRoomOperatorGranted` with the room name
   2. :ref:`function-room-list-update`

5. For the room ``owner``:

   1. :ref:`function-notify-room-owner` : "User ``grantee`` is now an operator of room ``name``"


.. note::
   It is not a mistake that the :ref:`PrivateRoomGrantOperator` message gets sent twice to both the joined users and the members


.. _function-private-room-revoke-operator:

Function: Revoke Operator from Private Room
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Function to revoke operator privileges from a member of a private room

**Actors:**

* ``revoker`` : User revoking the operator privileges
* ``revokee`` : User having operator privileges revoked

**Actions:**

1. Remove the member from the ``operators`` list:
2. For each member in the ``members`` list:

   1. Send :ref:`PrivateRoomRevokeOperator` with room name and the name of the removed operator

3. For each user in the ``joined_users`` list:

   1. Send :ref:`PrivateRoomRevokeOperator` with room name and the name of the removed operator

4. For the ``revokee``:

   1. Send :ref:`PrivateRoomOperatorRevoked` with the room name
   2. :ref:`function-room-list-update`

5. For the room ``owner``:

   1. :ref:`function-notify-room-owner` : "User ``revokee`` is no longer an operator of room ``name``"


.. note::
  It is not a mistake that the :ref:`PrivateRoomRevokeOperator` message gets sent twice to both the joined users and the members


.. _function-server-info-message:

Function: Server Notification Message
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The server will send private chat messages to report errors and information back to the client:

**Actors:**

* ``receiver`` : User receiving a server notification message

**Actions:**

1. Generate a ``chat_id``
2. Server to ``receiver``:

   1. Send :ref:`PrivateChatMessage`

      * chat_id : Generated ``chat_id``
      * timestamp : Current timestamp
      * username : ``server``
      * message = ``message``
      * is_direct = true


Client Flows
============

This section describes some of the flows from the client point of view. Specifically it focuses on the interactions between the client and the server

Private Chat Message
--------------------

**Actors:**

* ``sender`` : User sending a private message
* ``receiver`` : User receiving the private message

**Actions:**

1. ``sender`` to server:

   1. :ref:`PrivateChatMessage` (username = ``receiver``, message = ``message``)

2. Server to ``receiver``

   1. :ref:`PrivateChatMessage` (username = ``sender``, chat_id = ``<generated>``, message = ``message``)

3. ``receiver`` to server:

   1. :ref:`PrivateChatMessageAck` (chat_id = ``<chat_id from received message>``)


.. note::

   Some unresolved questions are:

   * Is a message still delivered after the sender is removed?


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
* Path seperators can be included (backslash and forward slash) but only apply to the directory part of the filename. Query ``my\cool`` will match file ``my\cool\band\song.mp3``, but query ``band\song`` will not match the same file

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
