=======
py-slsk
=======

.. contents::

Installation
============


Usage
=====


Code Structure
==============

Modules
-------

- `slsk`
- `connection`: everything related to physical connections. Also contains the network loop
- `messages`: everything related to parsing and creating of SoulSeek messages
- `network_manager`: higher level network manager
- `server_manager`
-

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
