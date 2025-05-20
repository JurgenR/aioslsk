======
Custom
======

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


Server Messages
===============

.. server-messages::


Peer Initialization Messages
============================


