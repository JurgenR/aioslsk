========
Settings
========

Exporting / Importing
=====================

The settings make use of the pydantic-settings_ library, following examples show how it can be used to export and import the settings to a JSON files.

Writing settings to a JSON file:

.. code-block:: python

    import json
    from aioslsk.settings import Settings, CredentialsSettings

    settings = Settings(
        credentials=CredentialsSettings(username='user', password='testpass')
    )
    settings_filename = 'my_settings.json'

    with open(settings_filename, 'w') as fh:
        fh.write(settings.dump_model(mode='json'))


Reading settings from a JSON file:

.. code-block:: python

    import json
    from aioslsk.settings import Settings, CredentialsSettings

    settings_filename = 'my_settings.json'

    with open(settings_filename, 'r') as fh:
        py_settings = json.load(fh)

    loaded_settings = Settings(**py_settings)


Settings
========

This is a full list of settings used by the library

Credentials
-----------

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

+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
|             Parameter              |  Type   |                                            Description                                            |      Default       |
+====================================+=========+===================================================================================================+====================+
| network.server.hostname            | string  |                                                                                                   | server.slsknet.org |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.server.port                | integer |                                                                                                   | 2416               |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.server.reconnect.auto      | boolean | Automatically try to reconnect to the server when the server disconnects. No attempt to reconnect | false              |
|                                    |         | will be made when: disconnecting, server closed connection, credentials are not set               |                    |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.server.reconnect.timeout   | integer | Timeout after which we should try reconnecting to the server                                      | 10                 |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.listening.port             | integer | Port to listen for other peers (clear)                                                            | 61000              |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.listening.obfuscated_port  | integer | Port to listen for other peers (obfuscated)                                                       | 61001              |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.listening.error_mode       | string  | Defines when an error should be raised when connecting the listening connection (all, any, clear) | clear              |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.peer.obfuscate             | boolean | When true, prefer obfuscated connections as much as possible                                      | false              |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.upnp.enabled               | boolean | Automatically configure UPnP for the listening ports                                              | false              |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.upnp.lease_duration        | integer | Length of the UPnP port mapping lease duration (in seconds)                                       | 0                  |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.upnp.check_interval        | integer | Time between checking UPnP mappings (in seconds)                                                  | 600                |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.upnp.search_timeout        | integer | Maximum time to search for UPnP devices (in seconds)                                              | 10                 |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.limits.upload_speed_kbps   | integer | Upload speed limit in kbps (0 = no limit)                                                         | 0                  |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+
| network.limits.download_speed_kbps | integer | Download speed limit in kbps (0 = no limit)                                                       | 0                  |
+------------------------------------+---------+---------------------------------------------------------------------------------------------------+--------------------+


Sharing
-------

+----------------------+----------------------------------------------+---------------------------------------------------------------------------+-----------------------------+
|      Parameter       |                     Type                     |                                Description                                |           Default           |
+======================+==============================================+===========================================================================+=============================+
| shares.download      | string                                       | Directory to which files will be downloaded to                            | <current working directory> |
+----------------------+----------------------------------------------+---------------------------------------------------------------------------+-----------------------------+
| shares.directories   | array[:class:`.SharedDirectorySettingEntry`] | List of shared directories (see structure for each entry below)           | <empty>                     |
+----------------------+----------------------------------------------+---------------------------------------------------------------------------+-----------------------------+
| shares.scan_on_start | boolean                                      | Schedule a scan as soon as the client starts up (after reading the cache) | true                        |
+----------------------+----------------------------------------------+---------------------------------------------------------------------------+-----------------------------+


The ``shares.directories`` list contains objects which have the following parameters (object of :class:`.SharedDirectorySettingEntry`):

+------------+---------------+-----------------------------------------------------+-----------+
| Parameter  |     Type      |                     Description                     | Mandatory |
+============+===============+=====================================================+===========+
| path       | string        | Maximum amount of simultaneously uploads            | yes       |
+------------+---------------+-----------------------------------------------------+-----------+
| share_mode | string        | Possible values: `everyone`, `friends`, `users`     | yes       |
+------------+---------------+-----------------------------------------------------+-----------+
| users      | array[string] | List of specific users to share this directory with | no        |
+------------+---------------+-----------------------------------------------------+-----------+


Users / Rooms
-------------

+----------------------------+-------------------------------------+----------------------------------------------------------------------------------------+---------+
|         Parameter          |                Type                 |                                      Description                                       | Default |
+============================+=====================================+========================================================================================+=========+
| rooms.auto_join            | boolean                             | Automatically rejoin rooms when logon is successful                                    | true    |
+----------------------------+-------------------------------------+----------------------------------------------------------------------------------------+---------+
| rooms.private_room_invites | boolean                             | Enable or disable private rooms invitations                                            | true    |
+----------------------------+-------------------------------------+----------------------------------------------------------------------------------------+---------+
| rooms.favorites            | array[string]                       | List of rooms that will automatically be joined                                        | <empty> |
+----------------------------+-------------------------------------+----------------------------------------------------------------------------------------+---------+
| users.friends              | array[string]                       | List users considered friends                                                          | <empty> |
+----------------------------+-------------------------------------+----------------------------------------------------------------------------------------+---------+
| users.blocked              | map[string, :class:`.BlockingFlag`] | List of blocked users. Key indicates the username, value is one or more blocking flags | <empty> |
+----------------------------+-------------------------------------+----------------------------------------------------------------------------------------+---------+


Interests
---------

+----------------------------+---------------+-----------------------------------------------------+---------+
|         Parameter          |     Type      |                     Description                     | Default |
+============================+===============+=====================================================+=========+
| interests.liked            | array[string] | List of liked interests                             | <empty> |
+----------------------------+---------------+-----------------------------------------------------+---------+
| interests.hated            | array[string] | List of hated interests                             | <empty> |
+----------------------------+---------------+-----------------------------------------------------+---------+


Search
------

+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+
|               Parameter                |     Type      |                                                                           Description                                                                           | Default |
+========================================+===============+=================================================================================================================================================================+=========+
| searches.receive.max_results           | integer       | Maximum amount of search results returned when replying to search requests from other peers                                                                     | 100     |
+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+
| searches.receive.store_amount          | integer       | Amount of received searches to store in the client                                                                                                              | 500     |
+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+
| searches.send.store_results            | boolean       | Whether to store search results internally                                                                                                                      | true    |
+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+
| searches.send.request_timeout          | integer       | Timeout for sent search requests, when the timeout is reached the request will be removed and search results will no longer be accepted (0 = keep indefinitely) | 0       |
+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+
| searches.send.wishlist_request_timeout | integer       | Timeout for sent wishlist requests (0 = keep indefinitely, -1 = use the interval advertised by the server)                                                      | -1      |
+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+
| searches.wishlist                      | array[object] | List of wishlist items. Object definition is defined below                                                                                                      | <empty> |
+----------------------------------------+---------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------+---------+


Following object should be used for ``searches.wishlist`` object:

+-----------+---------+-------------------------------------------+---------+
| Parameter |  Type   |                Description                | Default |
+===========+=========+===========================================+=========+
| query     | string  | Wishlist item search query                | <empty> |
+-----------+---------+-------------------------------------------+---------+
| enabled   | boolean | Whether this query is enabled or disabled | true    |
+-----------+---------+-------------------------------------------+---------+


Transfers
---------

+-------------------------------+---------+-------------------------------------------------+---------+
|           Parameter           |  Type   |                   Description                   | Default |
+===============================+=========+=================================================+=========+
| transfers.limits.upload_slots | integer | Maximum amount of simultaneously uploads        | 2       |
+-------------------------------+---------+-------------------------------------------------+---------+
| transfers.report_interval     | float   | Transfer progress reporting interval in seconds | 0.250   |
+-------------------------------+---------+-------------------------------------------------+---------+


Debug
-----

+----------------------------+---------------------+----------------------------------------------------+---------+
|         Parameter          |        Type         |                    Description                     | Default |
+============================+=====================+====================================================+=========+
| debug.search_for_parent    | boolean             | Toggle searching for a distributed parent          | true    |
+----------------------------+---------------------+----------------------------------------------------+---------+
| debug.user_ip_overrides    | map[string, string] | Mapping of username and IP addresses, overrides    | <empty> |
+----------------------------+---------------------+----------------------------------------------------+---------+
| debug.log_connection_count | boolean             | Periodically log the amount of current connections | false   |
+----------------------------+---------------------+----------------------------------------------------+---------+


.. _pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
