=======
py-slsk
=======

.. contents::

Installation
============


Messages
========

The message descriptions can be found here: https://www.museek-plus.org/wiki/SoulseekProtocol

The length indicators indicate the length in bytes. The length indicators do not include the length bytes themselves.

For non-obfuscated messages the first 4 bytes will contain the length of the message, this length does not include the 4 length bytes themselves.
For obfuscated messages the first 4 bytes will contain the key, the next 4 bytes will contain the length.

There are 3 types of messages:

- Server messages
- Peer messages
- Distributed messages

The second 4 bytes will contain the message ID, message ID

Processes
=========

Server connection
-----------------

The first message sent to the server is a Login (message ID = 1) with the username and password.

This message will return more than just a response to the login request, it will return the following:

- RoomList: List of chatrooms
- ParentMinSpeed: No idea yet
- ParentSpeedRatio: No idea yet
- WishlistInterval: No idea yet
- PrivilegedUsers

After the response we send the following requests back to the server with some information about us:

- CheckPrivileges: Check if we have privileges
- SetListenPort: The listening port(s), obfuscated and non-obfuscated
- SetStatus: Our status (offline, away, available)
- HaveNoParents: No idea yet, seems like we have no parents
- BranchRoot: No idea yet, seems to be our own username
- BranchLevel: No idea yet, should be 0
- SharedFoldersFiles: Number of directories and files we are sharing
- AddUser: Using our own username as parameter, this might be useful for checking if everything arrived on the server side
- AcceptChildren: No idea yet,

The listening socket
--------------------

Two listening sockets are set up, one where the messages are sent to as cleartext and the other where the messages are sent to obfuscated. The obfuscated port will be the unobfuscated port + 1

Upon accepting a connection the following process is followed:

Distributed connections
-----------------------

Once every 60 seconds the server will send us a NetInfo message, this message contains 10 users and their IP addresses.

Upon connecting to a user the following are sent:

#. Send PeerInit: With connection type D
#. Recv Branch Level:
#. Recv Branch Root:
#. Recv: SearchRequest

Searching
---------

FileSearch is weird in the SoulSeekQt client, it seems to send 2 requests in one packet:

- Length of packet
- Message ID=26 (FileSearch)
- Ticket number
- Query string

Which is expected but then it is followed by:

- Length of packet
- Message ID=153 (?)
- Query string

The server completely repeats the last part of the search query + 4 bytes containing 0x00

After this the clients start reporting the results. However there is a problem, most clients seem to send a request to the server which is then relayed to our client that requests that we connect to them (this is supposed to be the procedure when the clients fail to connect to us) but they also attempt to connect themselves. When we respond to the request from the server by connecting to the peers we will receive nothing on this connection if the connection the peer opened to us succeeded. These connections remain open indefinitely. When there are many results this many connections will be opened to your machine, thus we are runnning against a limit in the Selector module.

Looking at code from other projects I can see that all other connections from that peer are closed when we the peer tries to establish a connection himself. I also noticed when search results are received that the timeout for these connections is set to a very low value. Eg.: 2 seconds, otherwise it takes 60+ seconds to disconnect by timeout. There is no possible built-in way to set the timeout for a connection (using selector module) so this might have to implemented manually.
