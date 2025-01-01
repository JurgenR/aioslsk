=====
Usage
=====

Starting the client
===================

.. warning::

    The server has an anti-DDOS mechanism, be careful when connecting and disconnecting too quickly
    or you will get banned


Before starting the client, ensure you create a settings object where you have configured at least
the ``credentials`` section:

.. code-block:: python

    from aioslsk.settings import Settings, CredentialsSettings

    # Create default settings and configure credentials
    settings: Settings = Settings(
        credentials=CredentialsSettings(
            username='my_user',
            password='Secret123'
        )
    )

It's also recommended to configure a listening port and a downloads directory. For the full list of
configuration soptions see: :doc:`./SETTINGS`


Next create and start the client. Calling :meth:`.SoulSeekClient.start` will connect the listening
ports and to the server. Next perform a login and, for example, send a private message:

.. code-block:: python

    import asyncio
    from aioslsk.client import SoulSeekClient
    from aioslsk.commands import PrivateMessageCommand

    async def main():
        client: SoulSeekClient = SoulSeekClient(settings)

        await client.start()
        await client.login()

        # Send a private message
        await client.execute(PrivateMessageCommand('my_friend', 'Hi!'))

        await client.stop()

    asyncio.run(main())


The client can also use the a context manager to automatically start and stop the client:

.. code-block:: python

    import asyncio
    from aioslsk.client import SoulSeekClient
    from aioslsk.commands import PrivateMessageCommand

    async def main():
        async with SoulSeekClient(settings) as client:
            await client.login()
            # Send a private message
            await client.execute(PrivateMessageCommand('my_friend', 'Hi!'))

    asyncio.run(main())


Commands and Events
===================

Command objects are used to send requests to the server. Waiting for a response is optional because
the protocol does not have a proper error handling, sometimes error messages will be returned as a
private message from the ``server`` user, sometimes no error will be returned at all (eg.: when
joining a room).

The list of built-in commands can be found in the :mod:`aioslsk.commands` module but it is of course
possible to create your own commands by extending :class:`.BaseCommand`. Commands can be used with
the client's :meth:`.SoulSeekClient.execute` command or simply by calling the client itself. An
example of setting the user status:

.. code-block:: python

    from aioslsk.user.model import UserStatus
    from aioslsk.commands import SetStatusCommand

    # Setting status to away
    await client.execute(SetStatusCommand(UserStatus.AWAY))

    # Setting status to online
    await client(SetStatusCommand(UserStatus.AWAY))

Example getting a response:

.. code-block:: python

    from aioslsk.user.model import UserStatus
    from aioslsk.commands import GetUserStatusCommand

    # Setting status to away
    status, privileged = await client(
        GetUserStatusCommand('someone'), response=True)


The library also has an array of events to listen for in the :mod:`aioslsk.events` module, callbacks
can be registered through :func:`.SoulSeekClient.events.register` providing the event to listen for
and the callback:

.. code-block:: python

    from aioslsk.events import RoomJoinedEvent

    async def on_room_joined(event: RoomJoinedEvent):
        if not event.user:
            print(f"We have joined room {event.room.name}!")
        else:
            print(f"User {event.user.name} has joined room {event.room.name}!")

    client.events.register(RoomJoinedEvent, on_room_joined)


Searching
=========

Making Requests
---------------

The protocol implements 3 types of search: network, room and user. Following example shows how to
start a search request for each of the types:

.. code-block:: python

    from aioslsk.search.model import SearchRequest

    global_request: SearchRequest = await client.searches.search('my query')
    room_request: SearchRequest = await client.searches.search_room('cool_room', 'my room query')
    user_request: SearchRequest = await client.searches.search_user('other_user', 'my user query')


Wishlist Searches
~~~~~~~~~~~~~~~~~

Wishlist searches are periodic searches made by the client to the server. The interval is determined
by the server. To add a wishlist search simply add an entry to the settings, it will be picked up
at the next interval:

.. code-block:: python

    from aioslsk.settings import Settings, WishlistSettingEntry

    settings: Settings = Settings(...)
    settings.searches.wishlist.append(
        WishlistSettingEntry(query='test', enabled=True)
    )


The :class:`SearchRequestSentEvent` will be emitted when a wishlist search is made. Keep in mind
however that this event is emitted also when making other types of search requests. Look at the type
of the request made to determine whether it is a wishlist search or not.


Manually Removing Requests
~~~~~~~~~~~~~~~~~~~~~~~~~~

Search requests are stored internally but a timeout can be configured to automatically remove them.
Following example shows how to manually remove a search request:

.. code-block:: python

    request: SearchRequest = await client.searches.search('my query')
    # Print Current list of search requests
    print(f"Search request made : {client.searches.requests}")

    # Remove a search request
    client.searches.remove_request(request)

After removal there will be no more :class:`SearchResultEvent` events emitted for the removed
request

Automatically Removing Requests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A timeout can be configured through two settings:

* ``searches.sent.request_timeout``
* ``searches.sent.wishlist_request_timeout``

When a request gets removed an event will be emitted: :class:`SearchRequestRemovedEvent`


Receiving Results
-----------------

Listen to the :class:`.SearchResultEvent` to receive search results:

.. code-block:: python

    from aioslsk.events import SearchResultEvent

    async def search_result_listener(event: SearchResultEvent):
        print(f"got a search result for query: {event.query.query} : {event.query.result}")

    client.register(SearchResultEvent, search_result_listener)


Full list of search results can be accessed through the returned object or the client:

.. code-block:: python

    import asyncio
    from aioslsk.search.model import SearchRequest

    request: SearchRequest = await client.searches.search('my query')

    # Wait a bit for search results
    await asyncio.sleep(5)

    print(f"results: {request.results}")


Received Search Requests
------------------------

The client will participate in the distributed network which means it will automatically connect to
other peers from which it will receive search requests and pass these on to other peers.

An event will be emitted whenever search request is received (:class:`.SearchRequestReceivedEvent`)
which contains the username, query and how many results were returned. The library will by default
store a limited number of search requests which can be accessed through the :attr:`.SearchManager.received_searches`
attribute. The amount of stored search requests can be configured using the ``searches.receive.store_amount`` setting.


Transfers
=========

Managing Transfers
------------------

To start downloading a file:

.. code-block:: python

    from aioslsk.transfer.model import Transfer

    search_request: SearchRequest = await client.searches.search('my query')
    # Wait for a bit and get the first search result
    await asyncio.sleep(5)
    search_result: SearchResult = search_request.results[0]
    # The following will attempt to start the download in the background
    transfer: Transfer = await client.transfers.download(search_result.username, search_result.shared_items[0].filename)

A couple of methods are available to retrieve transfers:

.. code-block:: python

    from aioslsk.transfer.model import Transfer

    all_transfers = list[Transfer] = client.transfers.transfers
    downloads: list[Transfer] = client.transfers.get_downloads()
    uploads: list[Transfer] = client.transfers.get_uploads()


Events are available to listen for the transfer progress:

.. code-block:: python

    from aioslsk.transfer.model import Transfer
    from aioslsk.events import TransferAddedEvent, TransferProgressEvent, TransferRemovedEvent

    async def on_transfer_added(event: TransferAddedEvent):
        if transfer.is_upload():
            print(f"New upload added from {event.transfer.username} with name {event.transfer.filename}!")

    async def on_transfer_progress(event: TransferProgressEvent):
        for transfer, previous, current in event.updates:
            if previous.state != current.state:
                print(f"A transfer moved from state {previous.state} to {current.state}!")

    async def on_transfer_removed(event: TransferRemovedEvent):
        if transfer.is_upload():
            print(f"Upload from {event.transfer.username} with name {event.transfer.filename} removed!")

    client.events.register(TransferAddedEvent, on_transfer_added)
    client.events.register(TransferProgressEvent, on_transfer_progress)
    client.events.register(TransferRemovedEvent, on_transfer_removed)


Managing Transfer States
------------------------

The following methods are available on the :class:`.TransferManager` class for managing the state of
existing transfers:

* :meth:`.TransferManager.queue`
* :meth:`.TransferManager.pause`
* :meth:`.TransferManager.abort`

Transfers can be paused or aborted, aborting will remove the partially downloaded file. To resume
the paused transfer call the :meth:`.TransferManager.queue` method. Aborted transfers can be
requeued as well but since the file was removed the transfer will be restarted from the beginning:

.. code-block:: python

    from aioslsk.transfer.model import Transfer

    # The following will attempt to start the download in the background
    transfer: Transfer = await client.transfers.download('someuser', 'somefile.mp3')

    # Pause the download wait and requeue
    await client.transfers.pause(transfer)
    await asyncio.sleep(5)
    await client.transfers.queue(transfer)

    # Abort and requeue
    await client.transfers.abort(transfer)
    await asyncio.sleep(5)
    await client.transfers.queue(transfer)

The :meth:`.TransferManager.queue` method can also be called on downloads that are already completed
state, in this case the file will be re-downloaded to a new location. This method can also be used
to retry failed downloads (however usually they are failed for a reason, for example if the
uploader does not share the file)


Setting Transfer Limits
-----------------------

There are 3 limits currently in place:

- ``sharing.limits.upload_slots`` : Maximum amount of uploads at a time
- ``sharing.limits.upload_speed_kbps`` : Maximum upload speed
- ``sharing.limits.download_speed_kbps`` : Maximum download speed

The initial limits will be read from the settings. When lowering for example
``sharing.limits.upload_slots`` the limit will be applied as soon as it changes in the settings and
the amount of current uploads drops to the new limit (uploads in progress will be completed). For
the speed limits a method needs to be called before they can are applied:

.. code-block:: python

    client: SoulSeekClient = SoulSeekClient(settings)

    # Modify to upload limit to 100 kbps
    client.network.set_upload_speed_limit(100)

    # Alternatively reload both speed limits after they have changed on the settings
    client.settings.network.limits.upload_limit_kbps = 100
    client.settings.network.limits.download_limit_kbps = 1000
    client.network.load_speed_limits()


Room Management
===============

The :class:`.RoomManager` is responsible for :class:`.Room` object storage and management. All rooms
are stored returned by the server are accessible through the object instance:

.. code-block:: python

    client: SoulSeekClient = SoulSeekClient(settings)

    print(f"There are {len(client.rooms.rooms)} rooms")
    print(f"Currently in {len(client.rooms.get_joined_rooms())} rooms")


Public and private rooms can be joined using the name of the room or an instance of the room. The
server will create the room if it does not exist:

.. code-block:: python

    from aioslsk.commands import JoinRoomCommand

    # Create / join a public room
    await client(JoinRoomCommand('public room'))
    # Create / join a private room
    await client(JoinRoomCommand('secret room', private=True))

Leaving a room works the same way:

.. code-block:: python

    from aioslsk.commands import LeaveRoomCommand

    await client(LeaveRoomCommand('my room'))

Sending a message to a room:

.. code-block:: python

    from aioslsk.commands import RoomMessageCommand

    await client(RoomMessageCommand('my room', 'Hello there!'))

To receive room messages listen to the :class:`.RoomMessageEvent`:

.. code-block:: python

    from aioslsk.events import RoomMessageEvent

    async def room_message_listener(event: RoomMessageEvent):
        print(f"message from {event.message.user.name} in room {event.message.room.name}: {event.message.message}")

    client.events.register(RoomMessageEvent, room_message_listener)


Several commands and events specific to private rooms are available. See the :mod:`aioslsk.commands` and
:mod:`aioslsk.events` references


Private Messages
================

A private message can be sent using the API by calling:

.. code-block:: python

    await client.send_private_message('other user', "Hello there!")

To receive private message listen for the :class:`.PrivateMessageEvent`:

.. code-block:: python

    from aioslsk.events import PrivateMessageEvent

    async def private_message_listener(event: PrivateMessageEvent):
        print(f"private message from {event.message.user.name}: {event.message.message}")

    client.register(PrivateMessageEvent, private_message_listener)


Sharing
=======

The client provides a mechanism for scanning and caching the files you want to share. Directories
you wish to share can be :ref:`added and removed on the fly <shares_add_remove_scan>` or provided
through the settings:

.. code-block:: python

    from aioslsk.settings import (
        Settings,
        CredentialsSettings,
        SharesSettings,
        SharedDirectorySettingEntry,
    )
    from aioslsk.shares.model import DirectoryShareMode

    # Configure credentials, configure to scan the shares on start, and set the
    # desired shared directories
    settings: Settings = Settings(
        credentials=CredentialsSettings(username='my_user', password='Secret123'),
        shares=SharesSettings(
            scan_on_start=True,
            directories=[
                SharedDirectorySettingEntry(
                    'music/metal',
                    share_mode=DirectoryShareMode.EVERYONE
                ),
                SharedDirectorySettingEntry(
                    'music/punk',
                    share_mode=DirectoryShareMode.FRIENDS
                ),
                SharedDirectorySettingEntry(
                    'music/folk',
                    share_mode=DirectoryShareMode.USERS,
                    users=['secret guy']
                )
            ]
        )
    )


When providing a shares cache the client will automatically read and store the shared items based
on what you configured. This example shows how to use the a cache that stores the files using
Python's :py:mod:`shelve` module:

.. code-block:: python

    import asyncio
    from aioslsk.client import SoulSeekClient
    from aioslsk.shares.cache import SharesShelveCache
    from aioslsk.settings import (Settings, CredentialsSettings, SharesSettings)

    async def main():
        settings: Settings = Settings(
            credentials=CredentialsSettings(username='my_user', password='Secret123'),
            shares=SharesSettings(
                scan_on_start=False,
                directories=[
                    # Some directories you wish to share
                ]
            )
        )

        cache = SharesShelveCache(data_directory='documents/shares_cache/')

        async with SoulSeekClient(settings, shares_cache=cache) as client:
            await client.login()

            # If there were shared items stored in the cache this will output
            # the total amount of directories and files shared
            dir_count, file_count = client.shares.get_stats()
            print(f"currently sharing {dir_count} directories and {file_count} files")

            # Manually write the cache to disk
            client.shares.write_cache()

    asyncio.run(main())


.. _shares_add_remove_scan:

Adding / Removing / Scanning Directories
----------------------------------------

It is possible to add, remove or update shared directories on the fly. Following example shows how
to add, remove and scan individual or all directories:

.. code-block:: python

    from aioslsk.shares.model import DirectoryShareMode

    # Add a shared directory only shared with friends
    shared_dir = client.shares.add_shared_directory(
        'my/shared/directory',
        share_mode=DirectoryShareMode.FRIENDS
    )

    # Update the shared directory
    client.shares.update_shared_directory(
        shared_dir,
        share_mode=DirectoryShareMode.EVERYONE
    )

    # Scan the directory files and file attributes
    await client.shares.scan_directory_files(shared_dir)
    await client.shares.scan_directory_file_attributes(shared_dir)

    # Scanning all current shared directories
    await client.shares.scan()

    # Removing a shared directory
    client.shares.remove_shared_directory(shared_dir)

When rescanning an individual or all directories newly found items will be added and items that are
no longer found will be removed. Attributes will be scanned for the newly found files and files that
have been modified.


Defining a custom executor for scanning
---------------------------------------

By default the :py:mod:`asyncio` executor is used for scanning shares. You can play around with
using different types of executors by using the `executor_factory` parameter when creating the
client. The client will call the factory to create a new executor each time the client is started
and will destroy it when :meth:`.SoulSeekClient.stop` is called.

Following example shows how to use a :py:class:`concurrent.futures.ProcessPoolExecutor`:

.. code-block:: python

    from concurrent.futures import ProcessPoolExecutor
    from aioslsk.client import SoulSeekClient

    async def main():
        client: SoulSeekClient = SoulSeekClient(
            settings,
            executor_factory=ProcessPoolExecutor
        )

Another example using :py:class:`concurrent.futures.ThreadPoolExecutor` with a limited number of
threads, in this case a maximum of 3 threads:

.. code-block:: python

    from concurrent.futures import ThreadPoolExecutor
    from aioslsk.client import SoulSeekClient

    def thread_executor_factory() -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=3)

    async def main():
        client: SoulSeekClient = SoulSeekClient(
            settings,
            executor_factory=thread_executor_factory
        )


File naming
-----------

The :class:`.SharesManager` is also responsible for figuring out where downloads should be stored to
and what to do with duplicate file names. By default the original filename will be used for the
local file, when a file already exists a number will be added to name, for example: ``my song.mp3``
to ``my song (1).mp3``. It is possible to implement your own naming strategies.

Example a strategy that places files in a directory containing the current date:

.. code-block:: python

    from datetime import datetime
    import os
    from aioslsk.naming import NamingStrategy, DefaultNamingStrategy

    class DatetimeDirectoryStrategy(NamingStrategy):

        # Override the apply method
        def apply(self, remote_path: str, local_dir: str, local_filename: str) -> tuple[str, str]:
            current_datetime = datetime.now().strftime('%Y-%M-%d')
            return os.path.join(local_dir, current_datetime), local_filename

    # Modify the strategy
    client.shares_manager.naming_strategies = [
        DefaultNamingStrategy(),
        DatetimeDirectoryStrategy(),
    ]


User Management
===============

The :class:`.UserManager` is responsible for :class:`.User` object storage and management. The
library holds a weak reference to user objects and will update that object with incoming data, thus
in order to keep a user a reference can be maintained for it.

.. code-block:: python

    from aioslsk.commands import PeerGetUserInfoCommand, GetUserStatsCommand

    client: SoulSeekClient = SoulSeekClient(settings)

    # Retrieve a user object
    username = 'someone important'
    user = self.client.users.get_user_object(username)

    # Get user info (will be stored in the same object)
    await client(GetUserStatsCommand(username), response=True)
    await client(PeerGetUserInfoCommand(username), response=True)

    print(f"User {user.name} describes himself as '{user.description}'")
    print(f"User {user.name} is sharing {user.shared_file_count} files")


If necessary you can clear certain parameters for a user, the following code will clear the
:attr:`.User.picture` and :attr:`.User.description` attributes:

.. code-block:: python

    from aioslsk.user.model import User

    client: SoulSeekClient = SoulSeekClient(settings)

    user: User = client.users.get_user_object('someone')
    user.clear(info=True)


.. _users-tracking:

User Tracking
-------------

The server will send user updates in the following situations:

1. A user has been added with the :ref:`AddUser` message

   * Automatic user status / privileges updates

2. A user is part of the same room you are in

   * Automatic user status / privileges updates
   * Automatic user shares updates (amount of files / directories shared)

Tracking of a user using the :ref:`AddUser` message can be undone using the :ref:`RemoveUser`
message. Whenever the server sends an update for a user an event will be emitted, the following
events can be listened to:

* :class:`.UserStatusUpdateEvent`
* :class:`.UserStatsUpdateEvent`

There are multiple situations where the library keeps track of a user, internally they are stored as
flags:

* Requested: User has requested to track a user
* Friends: Friends will be automatically tracked (see users-friends_ section below)
* Transfers: Users for which there are unfinished transfers will be tracked to make decisions on upload priority

When the last tracking flag is removed the library will issue a :ref:`RemoveUser` message to the
server and updates will no longer be received. Following example shows how to track/untrack a user
and getting the tracking flags:

.. code-block:: python

    from aioslsk.user.model import TrackingFlag

    client: SoulSeekClient = SoulSeekClient(settings)

    # Track a user. TrackingFlag.REQUESTED is the default flag
    client.users.track_user('interesting user')

    # Get the tracking flags for a user
    flags = client.users.get_tracking_flags('interesting user')
    if TrackingFlag.REQUESTED in flags:
        print("Tracking user because we requested it")

    # Stop tracking a user
    client.users.untrack_user('interesting user')

Sending the command does not necessarily mean the tracking of the user was successful, if the user
we attempted to track does not exist then the tracking will fail. Events related to tracking:

* :class:`.UserTrackingEvent`
* :class:`.UserTrackingFailedEvent`
* :class:`.UserUntrackingEvent`


.. _users-friends:

Friends
-------

A list of friends can found in the settings under ``users.friends``. This list is used to:

* Prioritize uploads
* Lock files depending on whether the user is in the list
* Automatically request the server to track the users in the list after logging on

To add a friend on the fly simply add it to the set:

.. code-block:: python

    from aioslsk.settings import Settings, CredentialsSettings, UsersSettings

    settings: Settings = Settings(
        credentials=CredentialsSettings(username='my_user', password='Secret123'),
        users=UsersSettings(
            friends={
                'good friend',
                'best friend'
            }
        )
    )
    client: SoulSeekClient = SoulSeekClient(settings)

    new_friend = 'awesome friend'

    # Add a new friend to the list and track him
    settings.users.friends.add(new_friend)

    # Remove from the list
    settings.users.friend.discard(new_friend)


Blocking Users
--------------

A list of blocked users can be found in the settings under ``users.blocked``, changes to this list
will automatically be picked up. Different flags can be used to block different actions by the user
which can be found in the :class:`.BlockingFlag` documentation. Note that when using
``BlockingFlag.UPLOADS`` all uploads to that user will be aborted. Unblocking the user will requeue
the uploads:

.. code-block:: python

    from aioslsk.settings import Settings, CredentialsSettings, UsersSettings
    from aioslsk.user.model import BlockingFlag

    settings: Settings = Settings(
        credentials=CredentialsSettings(username='my_user', password='Secret123'),
        users=UsersSettings(
            blocked={
                'bad_user': BlockingFlag.ALL
            }
        )
    )
    client: SoulSeekClient = SoulSeekClient(settings)

    new_blocked_user = 'ultra_bad_user'

    # Add a new blocked user
    settings.users.blocked[new_blocked_user] = BlockingFlag.ALL


Interests and Recommendations
=============================

Interests and hated interests are defined in the settings (``interests`` section) are automatically
advertised to the server after logging on. Commands can be used to add or remove them while after
being logged in:

.. code-block:: python

    from aioslsk.commands import (
        AddInterestCommand,
        AddHatedInterestCommand,
        RemoveInterestCommand,
        RemoveHatedInterestCommand,
    )

    # Adding an interested and hated interest
    await client(AddInterestCommand('funny jokes'))
    await client(AddHatedInterestCommand('unfunny jokes'))

    # Removing them again
    await client(RemoveInterestCommand('funny jokes'))
    await client(RemoveHatedInterestCommand('unfunny jokes'))


Recommendations can be requested and listened for using the commands and events. There are several
commands and events, this example is for getting item recommendations:

.. code-block:: python

    from aioslsk.events import ItemRecommendationsEvent
    from aioslsk.commands import GetItemRecommendationsCommand

    async def on_item_recommendations(event: ItemRecommendationsEvent):
        if len(event.recommendations) > 0:
            print(f"Best recommendation for item {event.item} : {event.recommendations[0]}")

    client.events.register(ItemRecommendationsEvent, on_item_recommendations)

    await client(GetItemRecommendationsCommand('funny jokes'))


Protocol Messages
=================

It is possible to send messages directly to the server or a peer instead of using the shorthand
methods. For this the :attr:`.SoulSeekClient.network` parameter of the client can be used, example
for sending the :class:`.GetUserStatus` message to the server:

.. code-block:: python

    from aioslsk.protocol.messages import GetUserStatus

    client: SoulSeekClient = SoulSeekClient(settings)

    # Example, request user status for 2 users
    await client.network.send_server_messages(
        GetUserStatus.Request("user one"),
        GetUserStatus.Request("user two")
    )

For peers it works the same way, except you need to provide the username as the first parameter and
then the messages you want to send:

.. code-block:: python

    from aioslsk.protocol.messages import PeerUserInfoRequest

    client: SoulSeekClient = SoulSeekClient(settings)

    # Example, request peer user info for user "some user"
    await client.network.send_peer_messages(
        "some user",
        PeerUserInfoRequest.Request()
    )

Keep in mind that sending a messages to peers is more unreliable than sending to the server. The
:meth:`.Network.send_peer_messages` method will raise an exception if a connection to the peer
failed. Both :meth:`.Network.send_peer_messages` and :meth:`.Network.send_server_messages` have a
parameter called ``raise_on_error``, when set to ``True`` an exception will be raised otherwise the
methods will return a list containing tuples containing the message and the result of the message
attempted to send, ``None`` in case of success and an ``Exception`` object in case of failure.


Logging
=======

The library makes use of the standard Python :py:mod:`logging` module. Generally the log levels
used have the following meaning:

* ``ERROR`` : Indicates an unexpected error has occurred, this might indicate: there is an error in
  the library itself, another peer sent us some data that could not be processed or there is some
  invalid configuration
* ``WARNING`` : An error has occurred but the library can recover from it. These messages are
  expected behaviour and can usually be safely ignored. A warning will be logged for example if no
  connection to a peer could be made
* ``INFO`` : High level informational messages such as when an action has
  occurred
* ``DEBUG`` : Messages which are useful for debugging the library itself. When this log level is
  enabled all protocol messages will be logged


Message Fitering
----------------

When enabling the ``DEBUG`` level all protocol messages will be logged, the library provides a way
to filter out certain messages with premade filters defined in the :mod:`aioslsk.log_utils` module,
these filters can be installed on the logging loggers / handlers using both Python or a logging
configuration. The example below filters out all incoming room messages:

.. code-block:: python

    import logging
    from aioslsk.log_utils import MessageFilter
    from aioslsk.protocol.messages import RoomChatMessage

    logger = logging.getLogger('aioslsk.network.connection')
    room_filter = MessageFilter([RoomChatMessage.Response])
    logger.addFilter(room_filter)

The equivelant of this in a logging config file (JSON):

.. code-block:: json

    {
        "filters": {
            "filter_search": {
                "()": "aioslsk.log_utils.MessageFilter",
                "message_types": [
                    "RoomChatMessage.Response"
                ]
            }
        },
        "loggers": {
            "aioslsk": {
                "level": "DEBUG",
                "handlers": [
                    "file_handler"
                ],
                "propagate": false
            },
            "aioslsk.network.connection": {
                "level": "DEBUG",
                "handlers": [
                    "file_handler"
                ],
                "filters": ["filter_search"],
                "propagate": false
            }
        }
    }

A common use case is to filter out distributed search messages, a specific filter is available for
this case: :class:`aioslsk.log_utils.DistributedSearchMessageFilter` :

.. code-block:: json

    {
        "filters": {
            "filter_search": {
                "()": "aioslsk.log_utils.DistributedSearchMessageFilter"
            }
        }
    }


.. note::

    A filter can be applied to a logger and on a handler. When using the logger method the filters
    should be applied to the logger of the :mod:`aioslsk.network.connection` module, applying it to
    the root ``aioslsk`` logger will not work as filters do not get propagated to child loggers


Truncating Messages
-------------------

At the ``DEBUG`` level all incoming and outgoing messages will be outputted to the logging handler.
Messages related to file listings such as search results, peer shares responses, directory listings
can become very long. If you would still like to use this log level but want to truncate the
messages you can modify the output formatting. Here is an example of a formatting string that
truncates messages to 1000 characters:

::

    [%(asctime)s][%(levelname)-8s][%(module)s]: %(message).1000s
