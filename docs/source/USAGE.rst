=====
Usage
=====

Starting the client
===================

.. warning::

    The server has an anti-DDOS mechanism, be careful when connecting / disconnecting too quickly or you will get banned


Before starting the client, ensure you create a settings object where you have configured at least the `credentials` section:

.. code-block:: python

    from aioslsk.settings import Settings, CredentialsSettings

    # Create default settings and configure credentials
    settings: Settings = Settings(
        credentials=CredentialsSettings(
            username='my_user',
            password='Secret123'
        )
    )

It's also recommended to configure a listening port and a downloads directory. For the full list of configuration options see:


Next create and start the client. Calling `.start()` will connect the listening ports and to the server. Next perform a login and, for example, send a private message:

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

Command objects are used to send requests to the server. Waiting for a response is optional because the protocol does not have a proper error handling, sometimes error messages will be returned as a private message from the ``server`` user, sometimes no error will be returned at all (eg.: when joining a room).

The list of built-in commands can be found in the `aioslsk.commands` module but it is of course possible to create your own commands by extending `BaseCommand`. Commands can be used with the client's `.execute()` command or simply by calling the client itself. An example of setting the user status:

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


The library also has an array of events to listen for in the `aioslsk.events` module, callbacks can be registered through `client.events.register()` providing the event to listen for and the callback:

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

The protocol implements 3 types of search: network, room and user.

.. code-block:: python

    global_search_request = await client.search('my query')
    user_search_request = await client.search_user('my user query', 'other user')
    room_search_request = await client.search_room('my room query', 'cool room')


Listen to the ``SearchResultEvent`` to receive search results:

.. code-block:: python

    from aioslsk.events import SearchResultEvent

    async def search_result_listener(event: SearchResultEvent):
        print(f"got a search result for query: {event.}")
        print(f"message from {event.message.user.name} in room {event.message.room.name}: {event.message.message}")

    client.register(SearchResultEvent, search_result_listener)


Full list of search results can always be accessed through the returned object or the client:

.. code-block:: python

    from aioslsk.search import SearchRequest, SearchResult

    search_request: SearchRequest = await client.search('my query')
    print(f"results: {search_request.results}")

    results = client.get_search_results_for_ticket(search_request.ticket)
    print(f"results: {search_request.results}")


Transfers
=========

To start downloading a file:

.. code-block:: python

    from aioslsk.transfer.model import Transfer

    search_request: SearchRequest = await client.search('my query')
    search_result: SearchResult = search_request.results[0]
    transfer: Transfer = await client.download(search_result.user, search_result.shared_items[0].filename)


Retrieving the transfers:

.. code-block:: python

    from aioslsk.transfer.model import Transfer

    all_transfers = List[Transfer] = client.transfers.transfers
    downloads: List[Transfer] = client.transfers.get_downloads()
    uploads: List[Transfer] = client.transfers.get_uploads()

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


Setting Limits
--------------

There are 3 limits currently in place:

- `sharing.limits.upload_slots` : Maximum amount of uploads at a time
- `sharing.limits.upload_speed_kbps` : Maximum upload speed
- `sharing.limits.download_speed_kbps` : Maximum download speed

The initial limits will be read from the settings. When lowering for example `sharing.limits.upload_slots` the limit will be applied as soon as it changes in the settings and the amount of current uploads drops to the new limit (uploads in progress will be completed). For the speed limits a method needs to be called before they can are applied:

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

The `RoomManager` is responsible for `Room` object storage and management. All rooms are stored returned by the server are accessible through the object instance:

.. code-block:: python

    client: SoulSeekClient = SoulSeekClient(settings)

    print(f"There are {len(client.rooms.rooms)} rooms")
    print(f"Currently in {len(client.rooms.get_joined_rooms())} rooms")


Public and private rooms can be joined using the name of the room or an instance of the room. The server will create the room if it does not exist:

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

To receive room messages listen to the ``RoomMessageEvent``:

.. code-block:: python

    from aioslsk.events import RoomMessageEvent

    async def room_message_listener(event: RoomMessageEvent):
        print(f"message from {event.message.user.name} in room {event.message.room.name}: {event.message.message}")

    client.events.register(RoomMessageEvent, room_message_listener)


Private Messages
================

A private message can be sent using the API by calling:

.. code-block:: python

    await client.send_private_message('other user', "Hello there!")

To receive private message listen for the ``PrivateMessageEvent``:

.. code-block:: python

    from aioslsk.events import PrivateMessageEvent

    async def private_message_listener(event: PrivateMessageEvent):
        print(f"private message from {event.message.user.name}: {event.message.message}")

    client.register(PrivateMessageEvent, private_message_listener)


Sharing
=======

Adding / Removing Directories
-----------------------------

The client provides a mechanism for scanning and caching the files you want to share. Since it's possible to share millions of files the file information is stored in memory as well as in a cache on disk. When starting the client through `client.start()` the cache will be read and the files configured in the settings will be scanned.

It is possible to add or remove shared directories on the fly.

.. code-block:: python

    client.shares_manager.add_shared_directory()
    client.shares_manager.remove_shared_directory()


File naming
-----------

The `SharesManager` is also responsible for figuring out where downloads should be stored to and what to do with duplicate file names. By default the original filename will be used for the local file, when a file already exists a number will be added to name, for example: `my song.mp3` to `my song (1).mp3`. It is possible to implement your own naming strategies.

Example a strategy that places files in a directory containing the current date:

.. code-block:: python

    from datetime import datetime
    import os
    from aioslsk.naming import NamingStrategy, DefaultNamingStrategy

    class DatetimeDirectoryStrategy(NamingStrategy):

        # Override the apply method
        def apply(self, remote_path: str, local_dir: str, local_filename: str) -> Tuple[str, str]:
            current_datetime = datetime.now().strftime('%Y-%M-%d')
            return os.path.join(local_dir, current_datetime), local_filename

    # Modify the strategy
    client.shares_manager.naming_strategies = [
        DefaultNamingStrategy(),
        DatetimeDirectoryStrategy(),
    ]


User Management
===============

The `UserManager` is responsible for `User` object storage and management. The library holds a weak reference to user objects and will update that object with incoming data, thus in order to keep a user a reference can be maintained for it.

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


If necessary you can clear certain parameters for a user, the following code will clear the ``picture`` and ``description`` attributes:

.. code-block:: python

    from aioslsk.user.model import User

    client: SoulSeekClient = SoulSeekClient(settings)

    user: User = client.users.get_user_object('someone')
    user.clear(info=True)


User Tracking
-------------

The server will automatically send updates for users in the following situations:

1. A user has been added with the `AddUser` message

    * Automatic user status / privileges updates

2. A user is part of the same room you are in:

    * Automatic user status / privileges updates
    * Automatic user sharing updates

Internally, the library will automatically track users as well:

* Users added to the friends list in the settings. These users will automatically be tracked after logging on
* Users for which we have open transfers. Tracked to make decisions on which transfers to start next and prioritization
* Users in the same room

If a user is tracked it holds a reference to the `User` object.


Protocol Messages
=================

It is possible to send messages directly to the server or a peer instead of using the shorthand methods. For this the `network` parameter of the client can be used, example for sending the `GetUserStatus` message to the server:

.. code-block:: python

    from aioslsk.protocol.messages import GetUserStatus

    client: SoulSeekClient = SoulSeekClient(settings)

    # Example, request user status for 2 users
    await client.network.send_server_messages(
        GetUserStatus.Request("user one"),
        GetUserStatus.Request("user two")
    )

For peers it works the same way, except you need to provide the username as the first parameter and then the messages you want to send:

.. code-block:: python

    from aioslsk.protocol.messages import PeerUserInfoRequest

    client: SoulSeekClient = SoulSeekClient(settings)

    # Example, request peer user info for user "some user"
    await client.network.send_peer_messages(
        "some user",
        PeerUserInfoRequest.Request()
    )

Keep in mind that sending a messages to peers is more unreliable than sending to the server. The `send_peer_messages` method will raise an exception if a connection to the peer failed. Both `send_peer_messages` and `send_server_messages` have an parameter called `raise_on_error`, when set to `True` an exception will be raised otherwise the methods will return a list containing tuples containing the message and the result of the message attempted to send, `None` in case of success and an `Exception` object in case of failure.
