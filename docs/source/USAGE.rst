=====
Usage
=====


Configuration / Settings
========================

The projects has 2 caches: the transfer cache and the shares cache.


Searching
=========

The protocol implements 3 types of search: network, room and user.



Transfers
=========


Rooms
=====

Public and private rooms can be joined using the name of the room or an instance of the room. Rooms will be created if the room does not exist

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


