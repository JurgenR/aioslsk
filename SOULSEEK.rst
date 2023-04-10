==============
SoulSeek Flows
==============

.. contents:

This document describes different flows and details for the SoulSeek protocol

Messages
========

The messages described can be found here: https://www.museek-plus.org/wiki/SoulseekProtocol . There are a lot of mistakes and missing details in this document.


Server Connection and Logon
===========================

1. Open a TCP connection to server.slsknet.org:2416
2. Open up at least one listening connection, a second one can be opened for obfuscated connections. The SoulSeekQt client always takes the configured port + 1 as the obfuscated port.
3. Send the Login_ command on the server socket. Most of the parameters here are self explanatory except for the client version and minor version.

A login response will be received which determines whether the login was successful or not along with the following commands providing some information:

- RoomList: List of chatrooms
- ParentMinSpeed: No idea yet
- ParentSpeedRatio: No idea yet
- WishlistInterval: No idea yet
- PrivilegedUsers

After the response we send the following requests back to the server with some information about us:

- CheckPrivileges: Check if we have privileges
- SetListenPort: The listening port(s), obfuscated and non-obfuscated
- SetStatus: Our status (offline, away, available)
- HaveNoParents_ : Related to Distributed Connections, should initually be true
- BranchRoot_ : Related to Distributed Connections, should initially be our own username
- BranchLevel_ : Related to Distributed Connections, should initially be 0
- SharedFoldersFiles: Number of directories and files we are sharing
- AddUser_ : Using our own username as parameter
- AcceptChildren: This is used to prevent the server from advertising us through NetInfo_

After connection is complete, send a Ping_ command out every 5 minutes.


_Question 1:_ I'm assuming the client version has some impact on how the server communicates to the peer, but the differences are unknown.

_Question 2:_ What client versions are in existance?


Establishing a peer connection
==============================

We can connect to them:

1. Attempt to connect to the peer -> connection established
2. Generate a ticket number
3. Send PeerInit_ over the peer connection (ticket, username, connection_type)

We cannot connect to them, but they can connect to us:

1. Attempt to connect to the peer -> connection failure
2. Generate a ticket number
3. Send ConnectToPeer_ to the server(ticket, username, connection_type)
4. Incoming connection from peer -> connection is established
5. Receive PeerPierceFirewall_ over the peer connection (ticket)
6. Look up ticket

We cannot connect to them, they cannot connect to us:

1. Attempt to connect to the peer -> connection failure
2. Generate a ticket number
3. Send ConnectToPeer_ command to the server (ticket, username, connection_type)
4. Nothing should happen here, as they cannot connect to us
5. Receive CannotConnect_ from server (ticket)

_Note:_ The SoulSeekQt client doesn't seem to adhere to this flow: it doesn't actually wait for the connection to be established and just fires a ConnectToPeer_ message to the server at the same time as it tries to establish a connection to the peer.

_Note:_ The SoulSeekQt client usually also sends a GetPeerAddress_ message before connecting, presumably to get the obfuscation port if it exists.

_Question 1:_ Why do we need a ticket number for PeerInit_ ? -> most clients seem to just send 0

_Question 2:_ Some clients appear to send a PeerInit_ instead of PeerPierceFirewall_ ?


Transfers
=========

Downloads
---------

For downloading we need the `username`, `filename` and `slotsfree` returned by a PeerSearchReply_ . Uploads are just the opposite of the download process.

Request a file download (peer has slotsfree):

1. Initiate a connection to the Peer
2. Send: PeerTransferQueue_ message containing the filename
3. Receive: PeerTransferRequest_ message. Store the ticket and the filesize
4. Send: PeerTransferReply_ message containing the ticket. If the `allowed` flag is set the other peer will now attempt to establish a connection for uploading, if it is not set the transfer should be aborted.


The peer will create a new file connection to start uploading the file.

1. Receive: PeerInit_ or PeerPierceFirewall_ (messages after this will no longer be obfuscated)
2. Receive: ticket (not contained in a message)
3. Send: offset (not contained in a message)
4. Receive data


Queue a file download (peer does not have slotsfree):

1. Initiate a connection to the Peer
2. Send: PeerTransferQueue_ message containing the filename
3. (If after 60s the ticket is not handled) Send: PeerPlaceInQueueRequest_ containing the filename
4. Receive: PeerPlaceInQueueReply_ which contains the filename and place in queue


Uploads
-------

The original Windows SoulSeek client also has the ability to send files.


Distributed Connections
=======================

Obtaining a parent
------------------

When HaveNoParents_ is enabled then every 60 seconds the server will send the client a NetInfo_ command (containing 10 possible peers) until we disable our search for a parent using the HaveNoParents_ command. The NetInfo_ command contains a list with each entry containg: username, IP address and port. Upon receiving this command the client will attempt to open up a connection to each of the IP addresses in the list to find a suitable parent.

After establishing a distributed connection with one of the potential parents the peer will send out a DistributedBranchLevel and DistributedBranchRoot over the distributed connection. If the peer is selected to be the parent the other potential parents are disconnected and the following messages are then send to the server to let it know where we are in the hierarchy:

* BranchLevel_ : BranchLevel from the parent + 1
* BranchRoot_ : The BranchRoot received from the parent
* HaveNoParents_ : Set to false to disable receiving NetInfo_ commands

Once the parent is set our parent will send us search requests in the form of
DistributedSearchRequest commands.


_Note:_ Branch Root is not always sent when the potential parent has branch level 0

_Question 1:_ Is there a picking process for the parent? It seems to be first come first serve.

_Question 2:_ When a parent disconnects, are all the children disconnected?


Obtaining children
------------------

The AcceptChildren_ command tells the server whether we want to have any children, this is probably used in combination with the HaveNoParents_ command which enables searching for parents. Enabling it will cause us to be listed in NetInfo_ commands sent to other peers. It is not mandatory to have a parent and to obtain children if we ourselves are the branch root (branch level is 0).

The process is very similar to the one to obtain a parent except that this time we are in the role of the other peer; we need to advertise the branch level and branch root using the DistributedBranchLevel and DistributedBranchRoot commands.


Searches on the network
-----------------------

Searches for the branch root (level = 0) will come from the server in the form of a ServerSearchRequest.


Searching
=========

Query rules
-----------

* Exclusion: dash-character gets used to exclude terms. Example: `-mp3`, would exclude all mp3 files
* Wildcard: asterisk-character for wildcard searches. Example: `*oney`, would match 'honey' and 'money'
* Sentence matching: double quotes would get used to keep terms together. Example: `"my song"` would perform an exact match for those terms. This no longer seems to be implemented.

Undescribed rules (matching):

* Searches are case-insensitive
* Placement of terms is irrelevant. This also applies to exclusions `-mp3 song` is the same as `song -mp3`
* Wildcard/exclusion: placement is irrelevant
* Wildcard: can only be used in the beginning of the word. `some*` is not valid and neither is `some*thing`
* Wildcard: doesn't need to match a character. Query `*song.mp3` will match `song.mp3`
* Wildcard: query `song *` will return something
* Exclusion: there are results for queries using only exclusions but it does not seem official. Example `-mp3`, returns a limited number of results and some results even containing string `mp3`

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


_Note:_ extension is empty for anything but mp3 and flac

_Note:_ Couldn't find any other than these. Number 3 seems to be missing, could this be something used in the past or maybe for video? Theoretically we could invent new attributes here, like something for video, images, extra metadata for music files. The official clients don't seem to do anything with the extra attributes


Rooms and Chats
===============


After joining a room, we will automatically be receiving GetUserStatus_ updates from the server



Reference:

.. _Login: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode1
.. _GetPeerAddress: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode3
.. _AddUser: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode5
.. _GetUserStatus: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode7
.. _ConnectToPeer: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode18
.. _Ping: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode32
.. _HaveNoParents: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode71
.. _BranchLevel: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode126
.. _BranchRoot: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode127
.. _NetInfo: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode102
.. _CannotConnect: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode1001
.. _PeerPierceFirewall: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode0
.. _PeerInit: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode1
.. _PeerSearchReply: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode9
.. _UserInfoRequest: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode15
.. _UserInfoReply: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode16
.. _PeerTransferReply:
.. _PeerTransferRequest: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode40
.. _PeerTransferQueue: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode43
.. _PeerPlaceInQueueReply: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode44
.. _PeerPlaceInQueueRequest: https://www.museek-plus.org/wiki/SoulseekProtocol#PeerCode51
