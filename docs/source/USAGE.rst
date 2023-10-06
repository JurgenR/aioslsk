=====
Usage
=====

Starting the client
===================

Before starting the client, ensure you create a settings object where you have configured at least the `credentials` section:

.. code-block:: python

    from aioslsk.settings import Settings

    # Create default settings and configure credentials
    settings: Settings = Settings.create()
    settings.set('credentials.username', 'my_user')
    settings.set('credentials.password', 'Secret123')

It's also recommended to configure a listening port and a downloads directory. For the full list of configuration options see:


Next create and start the client. Calling `.start()` will connect the network, listening ports, and peform a login using the configured:

.. code-block:: python

    import asyncio
    from aioslsk.client import SoulSeekClient

    async def main():
        client: SoulSeekClient = SoulSeekClient(settings)

        await client.start()

        # Send a private message
        await client.send_private_message('my_friend', 'Hi!')

        await client.stop()

    asyncio.run(main())


The client can also use the a context manager to automatically start and stop:

.. code-block:: python

    import asyncio
    from aioslsk.client import SoulSeekClient

    async def main():
        async with SoulSeekClient(settings):
            # Send a private message
            await client.send_private_message('my_friend', 'Hi!')

    asyncio.run(main())


Configuration and Settings
==========================



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

    downloads: List[Transfer] = client.get_downloads()
    uploads: List[Transfer] = client.get_uploads()


Rooms
=====

Public and private rooms can be joined using the name of the room or an instance of the room. The server will create the room if it does not exist:

.. code-block:: python

    # Create / join a public room
    await client.join_room('my room')
    # Create / join a private room
    await client.join_room('my room', private=True)

Leaving a room works the same way:

.. code-block:: python

    await client.leave_room('my room')

Sending a message to a room:

.. code-block:: python

    await client.send_room_message('my room', 'Hello there!')

To receive room messages listen to the ``RoomMessageEvent``:

.. code-block:: python

    from aioslsk.events import RoomMessageEvent

    async def room_message_listener(event: RoomMessageEvent):
        print(f"message from {event.message.user.name} in room {event.message.room.name}: {event.message.message}")

    client.register(RoomMessageEvent, room_message_listener)


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

The client provides a mechanism for scanning and caching the files you want to share. Since it's possible to share millions of files the file information is stored in memory as well as in a cache on disk. When starting the client through `client.start()` the cache will be read and the files configured in the settings will be scanned.

It is possible to add or remove shared directories on the fly.

.. code-block:: python

    client.shares_manager.add_shared_directory()

    client.shares_manager.remove_shared_directory()

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
