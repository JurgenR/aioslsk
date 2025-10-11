=======
aioslsk
=======

aioslsk is a Python library for the SoulSeek protocol built on top of asyncio.

Supported Python versions are currently 3.10 - 3.14

You can find the full documentation `here <http://aioslsk.readthedocs.io/>`_

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
    from aioslsk.commands import PrivateMessageCommand
    from aioslsk.settings import Settings, CredentialsSettings

    # Create default settings and configure credentials
    settings: Settings = Settings(
        credentials=CredentialsSettings(
            username='my_user',
            password='Secret123'
        )
    )

    async def main():
        client: SoulSeekClient = SoulSeekClient(settings)

        await client.start()
        await client.login()

        # Send a private message
        await client.execute(PrivateMessageCommand('my_friend', 'Hi!'))

        await client.stop()

    asyncio.run(main())


Development
===========

Install poetry_ and setup the project dependencies by running:

.. code-block:: shell

    poetry install


A tool is available to start the client for debugging purposes (try out commands to the server, ...):

1. Create a ``settings.json`` file containing valid credentials in the ``tools/debug/`` directory (or
   pass a path using ``--settings``). To generate a simple settings file:

   .. code-block:: shell

       poetry run python -m aioslsk.settings generate -u "Hello" -p "World" > tools/debug/settings.json

2. To start the REPL run:

   .. code-block:: shell

       # Reads from tools/debug/settings.json
       poetry run python -m tools.debug.debug_mode
       # Reads from specific file
       poetry run python -m tools.debug.debug_mode --settings ~/custom_settings.json

3. Run an example command (the ``aioslsk.commands`` module is aliased to the ``cmds`` variable):

   .. code-block:: python

        await client(cmds.GetPeerAddressCommand('some user'), response=True)

4. To close the REPL execute ``exit()`` or press ``Ctrl+Z``

Optionally the script takes a ``--cache-dir`` that will read/write the transfer and shares cache
from the given directory


Building the documentation
--------------------------

.. code-block:: shell

    cd docs/
    poetry run make html


Running Tests
-------------

Running all tests:

.. code-block:: shell

    poetry run pytest tests/

Running all tests with code coverage report:

.. code-block:: shell

    poetry run pytest --cov=aioslsk --cov-report term-missing tests/

By default the logs are only shown in case of failure. To enable all logging output during testing
run the tests as follows:

.. code-block:: shell

    poetry run pytest tests/ -o log_cli=true


Mock Server
~~~~~~~~~~~

A mock server implementation is available for testing, to start the server run:

.. code-block:: shell

    # By default the server listens on port 2416
    poetry run python -m tests.e2e.mock.server
    # Specifying multiple listening ports
    poetry run python -m tests.e2e.mock.server --port 2416 2242

Configure the hostname or IP of the server in your client and connect. If such configuration is not
possible you can add an entry to the ``hosts`` file of your system. For example:

::

    127.0.0.1      server.slsknet.org


Use ``--help`` to get a list of available options.

Dependencies
------------

The package uses several dependencies:

* mutagen_ : library used for extracting audio metadata
* aiofiles_ : asyncio library for filesystem management
* async-upnp-client_ : library for managing UPnP configuration
* pydantic-settings_ : library for managing settings
* async-timeout_ : library providing timeout class

.. _poetry: https://python-poetry.org/
.. _mutagen: https://github.com/quodlibet/mutagen
.. _aiofiles: https://github.com/Tinche/aiofiles
.. _async-upnp-client: https://github.com/StevenLooman/async_upnp_client
.. _pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
.. _async-timeout: https://github.com/aio-libs/async-timeout
