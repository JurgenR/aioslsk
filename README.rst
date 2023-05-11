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

+------------------------------+--------+------------------------------------------------------------------------+-----------+
|          Parameter           |  Type  |                              Description                               |  Default  |
+==============================+========+========================================================================+===========+
| credentials.username         | string | Username used to login                                                 | <not set> |
+------------------------------+--------+------------------------------------------------------------------------+-----------+
| credentials.password         | string | Password used to login                                                 | <not set> |
+------------------------------+--------+------------------------------------------------------------------------+-----------+
| credentials.info.description | string | Personal description, will be returned when a peer request info on you | <not set> |
+------------------------------+--------+------------------------------------------------------------------------+-----------+
| credentials.info.pciture     | string | Picture, will be returned when a peer request info on you              | <not set> |
+------------------------------+--------+------------------------------------------------------------------------+-----------+


Network
-------

+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
|             Parameter             |  Type   |                         Description                          |      Default       |
+===================================+=========+==============================================================+====================+
| network.server.hostname           | string  |                                                              | server.slsknet.org |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.server.port               | integer |                                                              | 2416               |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.listening.port            | integer | Port to listen for other peers (clear)                       | 61000              |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.listening.obfuscated_port | integer | Port to listen for other peers (obfuscated)                  | 61001              |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.use_upnp                  | boolean | Enable UPNP                                                  | false              |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.upnp_lease_duration       | integer | Length of the UPNP lease duration. 0 = indefinitely          | 0                  |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.reconnect.auto            | boolean | Automatically try to reconnect to the server                 | true               |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.reconnect.timeout         | integer | Timeout after which we should try connecting to the server   | 10                 |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+
| network.peer.obfuscate            | boolean | When true, prefer obfuscated connections as much as possible | false              |
+-----------------------------------+---------+--------------------------------------------------------------+--------------------+


Sharing
-------

+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+
|             Parameter              |     Type      |                                    Description                                    |  Default  |
+====================================+===============+===================================================================================+===========+
| sharing.limits.upload_slots        | integer       | Maximum amount of simultaneously uploads                                          | 2         |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+
| sharing.limits.upload_speed_kbps   | integer       | Upload speed limit in kbps (0 = no limit)                                         | 0         |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+
| sharing.limits.download_speed_kbps | integer       | Download speed limit in kbps (0 = no limit)                                       | 0         |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+
| sharing.download                   | string        | Directory to which files will be downloaded to                                    | <not set> |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+
| sharing.directories                | array[string] | List of shared directories                                                        | <not set> |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+
| sharing.index.store_interval       | integer       | Shared items index automatically gets stored, this parameter defines the interval | 120       |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+


Chats / Users
-------------

+----------------------------+---------------+-----------------------------------------------------+---------+
|         Parameter          |     Type      |                     Description                     | Default |
+============================+===============+=====================================================+=========+
| chats.auto_join            | boolean       | Automatically rejoin rooms when logon is successful | true    |
+----------------------------+---------------+-----------------------------------------------------+---------+
| chats.private_room_invites | boolean       | Enable or disable private rooms invitations         | true    |
+----------------------------+---------------+-----------------------------------------------------+---------+
| chats.rooms                | array[string] | List of rooms that will automatically be joined     | <empty> |
+----------------------------+---------------+-----------------------------------------------------+---------+
| users.friends              | array[string] | List users considered friends                       | <empty> |
+----------------------------+---------------+-----------------------------------------------------+---------+
| users.blocked              | array[string] | List of blocked users                               | <empty> |
+----------------------------+---------------+-----------------------------------------------------+---------+


Search
------

+-----------------+---------------+-----------------------------------------------------------------------------------+---------+
|    Parameter    |     Type      |                                    Description                                    | Default |
+=================+===============+===================================================================================+=========+
| search.wishlist | array[string] | List of wishlist items. Should be a dictionary with 2 keys: `query` and `enabled` | <empty> |
+-----------------+---------------+-----------------------------------------------------------------------------------+---------+


Debug
-----

+-------------------------+---------------------+-------------------------------------------------+---------+
|        Parameter        |        Type         |                   Description                   | Default |
+=========================+=====================+=================================================+=========+
| debug.search_for_parent | boolean             | Toggle searching for a distributed parent       | false   |
+-------------------------+---------------------+-------------------------------------------------+---------+
| debug.user_ip_overrides | map[string, string] | Mapping of username and IP addresses, overrides | <empty> |
+-------------------------+---------------------+-------------------------------------------------+---------+


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
