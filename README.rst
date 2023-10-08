=======
aioslsk
=======

aioslsk is a Python library for the SoulSeek protocol built on top of asyncio.

Supported Python versions are currently 3.8 - 3.11

Documentation:



Installation
============

.. code-block:: shell

    pip install aioslsk


Quick Start
===========

Starting the client and sending a private message:

.. code-block:: python

    import asyncio
    from aioslsk.client import SoulSeekClient
    from aioslsk.settings import Settings

    async def main():
        client: SoulSeekClient = SoulSeekClient(settings)

        # Create default settings and configure credentials
        settings: Settings = Settings.create()
        settings.set('credentials.username', 'my_user')
        settings.set('credentials.password', 'Secret123')

        await client.start()

        # Send a private message
        await client.send_private_message('my_friend', 'Hi!')

        await client.stop()

    asyncio.run(main())


Settings Parameters
===================

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
| credentials.info.picture     | string | Picture, will be returned when a peer request info on you              | <not set> |
+------------------------------+--------+------------------------------------------------------------------------+-----------+


Network
-------

+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
|             Parameter             |  Type   |                                            Description                                            |      Default       |
+===================================+=========+===================================================================================================+====================+
| network.server.hostname           | string  |                                                                                                   | server.slsknet.org |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.server.port               | integer |                                                                                                   | 2416               |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.listening.port            | integer | Port to listen for other peers (clear)                                                            | 61000              |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.listening.obfuscated_port | integer | Port to listen for other peers (obfuscated)                                                       | 61001              |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.listening.error_mode      | string  | Defines when an error should be raised when connecting the listening connection (all, any, clear) | clear              |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.use_upnp                  | boolean | Automatically configure UPnP for the listening ports                                              | false              |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.upnp_lease_duration       | integer | Length of the UPNP lease duration. 0 = indefinitely                                               | 0                  |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.reconnect.auto            | boolean | Automatically try to reconnect to the server when the server disconnects                          | true               |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.reconnect.timeout         | integer | Timeout after which we should try reconnecting to the server                                      | 10                 |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.peer.obfuscate            | boolean | When true, prefer obfuscated connections as much as possible                                      | false              |
+-----------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+


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
| sharing.directories                | array[object] | List of shared directories (see structure for each entry below)                   | <empty>   |
+------------------------------------+---------------+-----------------------------------------------------------------------------------+-----------+

The `sharing.directories` list contains objects which have the following parameters:

+------------+---------------+-----------------------------------------------------+-----------+
| Parameter  |     Type      |                     Description                     | Mandatory |
+============+===============+=====================================================+===========+
| path       | string        | Maximum amount of simultaneously uploads            | yes       |
+------------+---------------+-----------------------------------------------------+-----------+
| share_mode | string        | Possible values: `everyone`, `friends`, `users`     | yes       |
+------------+---------------+-----------------------------------------------------+-----------+
| users      | array[string] | List of specific users to share this directory with | no        |
+------------+---------------+-----------------------------------------------------+-----------+


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

+----------------------------+---------------------+----------------------------------------------------+---------+
|         Parameter          |        Type         |                    Description                     | Default |
+============================+=====================+====================================================+=========+
| debug.search_for_parent    | boolean             | Toggle searching for a distributed parent          | false   |
+----------------------------+---------------------+----------------------------------------------------+---------+
| debug.user_ip_overrides    | map[string, string] | Mapping of username and IP addresses, overrides    | <empty> |
+----------------------------+---------------------+----------------------------------------------------+---------+
| debug.log_connection_count | boolean             | Periodically log the amount of current connections | false   |
+----------------------------+---------------------+----------------------------------------------------+---------+


Development
===========

Install poetry_ and setup the project dependencies by running:

.. code-block:: shell

    poetry install


Dependencies
------------

The package uses several dependencies:

* mutagen_ : library used for extracting audio metadata
* aiofiles_ : asyncio library for filesystem management
* async-upnp-client_ : library for managing UPnP configuration


Building the documentation
--------------------------

.. code-block:: bash

    cd docs/
    poetry run make html


Running Tests
-------------

Running all tests:

.. code-block:: bash

    poetry run pytest tests/

Running all tests with code coverage report:

.. code-block:: bash

    poetry run pytest --cov=aioslsk --cov-report term-missing tests/


.. _poetry: https://python-poetry.org/
.. _mutagen: https://github.com/quodlibet/mutagen
.. _aiofiles: https://github.com/Tinche/aiofiles
.. _async-upnp-client: https://github.com/StevenLooman/async_upnp_client
