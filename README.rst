======
pyslsk
======

.. contents::

Installation
============


Usage
=====

Create a `Configuration` object pointing with the locations in which to store settings/configs, ...

.. code-block:: python

    config = Configuration(
        settings_directory="/my/settings/directory",
        data_directory="/my/data/directory"
    )




Parameters
==========

User
----

+-------------------------+------------------------------------------------------------------------+-----------+
|        Parameter        |                              Description                               |  Default  |
+=========================+========================================================================+===========+
| credentials.username    | Username used to login                                                 | <not set> |
+-------------------------+------------------------------------------------------------------------+-----------+
| credentials.password    | Password used to login                                                 | <not set> |
+-------------------------+------------------------------------------------------------------------+-----------+
| credentials.description | Personal description, will be returned when a peer request info on you | <not set> |
+-------------------------+------------------------------------------------------------------------+-----------+


Network
-------

+-----------------------------+---------------------------------------------------------------------------+--------------------+
|          Parameter          |                                Description                                |      Default       |
+=============================+===========================================================================+====================+
| network.server_hostname     |                                                                           | server.slsknet.org |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.server_port         |                                                                           | 2416               |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.listening_port      | Port to listen for other peers, the obfuscated port will be this port + 1 | 61000              |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.use_upnp            | Enable UPNP                                                               | false              |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.upnp_lease_duration | Length of the UPNP lease duration. 0 = indefinitely                       | 0                  |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.timeout.peer        | Peer connection timeout                                                   | 10                 |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.timeout.distributed | Distributed connection timeout                                            | 120                |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.reconnect.auto      | Automatically try to reconnect                                            | true               |
+-----------------------------+---------------------------------------------------------------------------+--------------------+


Sharing
-------

+------------------------------------+------------------------------------------------+-----------+
|             Parameter              |                  Description                   |  Default  |
+====================================+================================================+===========+
| sharing.limits.upload_slots        | Maximum amount of simultaneously uploads       | 2         |
+------------------------------------+------------------------------------------------+-----------+
| sharing.limits.upload_speed_kbps   | Upload speed limit in kbps (0 = no limit)      | 0         |
+------------------------------------+------------------------------------------------+-----------+
| sharing.limits.download_speed_kbps | Download speed limit in kbps (0 = no limit)    | 0         |
+------------------------------------+------------------------------------------------+-----------+
| sharing.download                   | Directory to which files will be downloaded to | <not set> |
+------------------------------------+------------------------------------------------+-----------+
| sharing.directories                | List of shared directories                     | <not set> |
+------------------------------------+------------------------------------------------+-----------+


Chats / Users
-------------

+----------------------------+-----------------------------------------------------+---------+
|         Parameter          |                     Description                     | Default |
+============================+=====================================================+=========+
| chats.auto_join            | Automatically rejoin rooms when logon is successfil | true    |
+----------------------------+-----------------------------------------------------+---------+
| chats.private_room_invites | Enable or disable private rooms invitations         | true    |
+----------------------------+-----------------------------------------------------+---------+
| chats.rooms                | List of rooms that will automatically be joined     | <empty> |
+----------------------------+-----------------------------------------------------+---------+
| users.friends              | List users considered friends                       | <empty> |
+----------------------------+-----------------------------------------------------+---------+
| users.blocked              | List of blocked users                               | <empty> |
+----------------------------+-----------------------------------------------------+---------+


Debug
-----

+-------------------------+-------------------------------------------------+---------+
|        Parameter        |                   Description                   | Default |
+=========================+=================================================+=========+
| debug.search_for_parent | Toggle searching for a distributed parent       | false   |
+-------------------------+-------------------------------------------------+---------+
| debug.user_ip_overrides | Mapping of username and IP addresses, overrides | <empty> |
+-------------------------+-------------------------------------------------+---------+


Code Structure
==============


Connection Management
---------------------

The `connection` module is based on the Python built-in `socket` and `selector` modules. By default there are 3 types of connections all inheriting from the `Connection` class:

- ServerConnection: Represents the connection to the SoulSeek server
- ListeningConnection: Listens for incoming sockets and creates PeerConnection objects
- PeerConnection: Connections made by peers and to peers

The `NetworkLoop` class contains the `selector` and a `run` for the main network loop.

All sockets are configured to be non-blocking sockets.


Running Tests
=============

Running all tests:

.. code-block:: bash

    poetry run pytest tests/

Running all tests with code coverage report:

.. code-block:: bash

    poetry run pytest --cov=pyslsk --cov-report term-missing tests/
