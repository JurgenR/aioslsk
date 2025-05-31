=================
Protocol Messages
=================

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

.. data-structures::


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

Message Structure
=================

All messages, except the file connection messages, must be preceded with a header. This header contains
the ``length`` of the message and the ``message_code``.

* The ``length`` of the header is represented as a ``uint32`` and should exclude the length itself.
* The ``message_code`` is also represented as a ``uint32`` for all messages **except** for the
  :ref:`peer-init-messages` where it is represented as a ``uint8``
* The ``body`` is optional

Header structure thus looks as follows:

+--------+--------------+----------+
|  Type  |     Name     | Optional |
+========+==============+==========+
| uint32 | length       | No       |
+--------+--------------+----------+
| uint32 | message_code | No       |
+--------+--------------+----------+
| any    | body         | Yes      |
+--------+--------------+----------+


.. _server-messages:

Server Messages
===============

.. server-messages::


.. _peer-init-messages:

Peer Initialization Messages
============================

.. peer-init-messages::


.. _peer-messages:

Peer Messages
=============

.. peer-messages::


.. _distributed-messages:

Distributed Messages
====================

.. distributed-messages::


.. _file-messages:

File Messages
=============

File connection does not have a header format but after peer initialization two values are exchanged:

1. **uint32**: ticket
2. **uint64**: offset
