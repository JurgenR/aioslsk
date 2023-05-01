=======
aioslsk
=======

aioslsk is a Python library for the SoulSeek protocol built on top of asyncio.

.. contents::

Installation
============

Package
-------


Development
-----------

Install poetry_ and setup the project dependencies by running:

.. code-block:: shell

    poetry install


Usage
=====

Create a `Configuration` object pointing with the locations in which to store settings/configs, ...

.. code-block:: python

    config = Configuration(
        settings_directory="/my/settings/directory",
        data_directory="/my/data/directory"
    )


Configuration Parameters
========================

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
| network.reconnect.auto      | Automatically try to reconnect to the server                              | true               |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.reconnect.timeout   | Timeout after which we should try connecting to the server                | 10                 |
+-----------------------------+---------------------------------------------------------------------------+--------------------+
| network.peer.obfuscate      | When true, prefer obfuscated connections as much as possible              | false              |
+-----------------------------+---------------------------------------------------------------------------+--------------------+


Sharing
-------

+------------------------------------+-----------------------------------------------------------------------------------+-----------+
|             Parameter              |                                    Description                                    |  Default  |
+====================================+===================================================================================+===========+
| sharing.limits.upload_slots        | Maximum amount of simultaneously uploads                                          | 2         |
+------------------------------------+-----------------------------------------------------------------------------------+-----------+
| sharing.limits.upload_speed_kbps   | Upload speed limit in kbps (0 = no limit)                                         | 0         |
+------------------------------------+-----------------------------------------------------------------------------------+-----------+
| sharing.limits.download_speed_kbps | Download speed limit in kbps (0 = no limit)                                       | 0         |
+------------------------------------+-----------------------------------------------------------------------------------+-----------+
| sharing.download                   | Directory to which files will be downloaded to                                    | <not set> |
+------------------------------------+-----------------------------------------------------------------------------------+-----------+
| sharing.directories                | List of shared directories                                                        | <not set> |
+------------------------------------+-----------------------------------------------------------------------------------+-----------+
| sharing.index.store_interval       | Shared items index automatically gets stored, this parameter defines the interval | 120       |
+------------------------------------+-----------------------------------------------------------------------------------+-----------+


Chats / Users
-------------

+----------------------------+-----------------------------------------------------+---------+
|         Parameter          |                     Description                     | Default |
+============================+=====================================================+=========+
| chats.auto_join            | Automatically rejoin rooms when logon is successful | true    |
+----------------------------+-----------------------------------------------------+---------+
| chats.private_room_invites | Enable or disable private rooms invitations         | true    |
+----------------------------+-----------------------------------------------------+---------+
| chats.rooms                | List of rooms that will automatically be joined     | <empty> |
+----------------------------+-----------------------------------------------------+---------+
| users.friends              | List users considered friends                       | <empty> |
+----------------------------+-----------------------------------------------------+---------+
| users.blocked              | List of blocked users                               | <empty> |
+----------------------------+-----------------------------------------------------+---------+


Search
------

+-----------------+-----------------------------------------------------------------------------------+---------+
| Parameter       | Description                                                                       | Default |
+=================+===================================================================================+=========+
| search.wishlist | List of wishlist items. Should be a dictionary with 2 keys: `query` and `enabled` | <empty> |
+-----------------+-----------------------------------------------------------------------------------+---------+


Debug
-----

+-------------------------+-------------------------------------------------+---------+
|        Parameter        |                   Description                   | Default |
+=========================+=================================================+=========+
| debug.search_for_parent | Toggle searching for a distributed parent       | false   |
+-------------------------+-------------------------------------------------+---------+
| debug.user_ip_overrides | Mapping of username and IP addresses, overrides | <empty> |
+-------------------------+-------------------------------------------------+---------+


Building the documentation
==========================

.. code-block:: bash

    cd docs/
    poetry run make html


Running Tests
=============

Running all tests:

.. code-block:: bash

    poetry run pytest tests/

Running all tests with code coverage report:

.. code-block:: bash

    poetry run pytest --cov=aioslsk --cov-report term-missing tests/


.. _poetry: https://python-poetry.org/
