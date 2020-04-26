=======
py-slsk
=======

.. contents::

Installation
============


Messages
========

The message descriptions can be found here: https://www.museek-plus.org/wiki/SoulseekProtocol

Basic
-----

The length indicators indicate the length in bytes. The length indicators do not include the length bytes themselves.

For non-obfuscated messages the first 4 bytes will contain the length of the message, this length does not include the 4 length bytes themselves.
For obfuscated messages the first 4 bytes will contain the key, the next 4 bytes will contain the length.

There are 3 types of messages:

- Server messages
- Peer messages
- Distributed messages

The second 4 bytes will contain the message ID, message ID

Login (message ID = 1)
----------------------

This message will return more than just a response to the login request, it will return the following:

- RoomList
- ParentMinSpeed
- ParentSpeedRatio
- WishlistInterval
- PrivilegedUsers

Processes
=========

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
