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
