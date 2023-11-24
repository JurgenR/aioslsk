=======
aioslsk
=======

aioslsk is a Python library for the SoulSeek protocol built on top of asyncio.

Supported Python versions are currently 3.8 - 3.11

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

1. Create a ``settings.json`` file containing valid credentials in the ``tools/debug/`` directory (or pass a path using ``--settings``)
2. Run ``poetry run python -m tools.debug.debug_mode`` to start the REPL
3. Run an example command: ``>>> await client(cmds.GetPeerAddressCommand('some user'), response=True)``
4. To close the REPL execute ``exit()`` or press ``Ctrl+Z``

Optionally the script takes a ``--cache-dir`` that will read/write the transfer and shares cache from the given directory


Dependencies
------------

The package uses several dependencies:

* mutagen_ : library used for extracting audio metadata
* aiofiles_ : asyncio library for filesystem management
* async-upnp-client_ : library for managing UPnP configuration
* pydantic-settings_ : library for managing settings
* async-timeout_ : library providing timeout class


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

Running the mock server:

.. code-block:: shell

    poetry run python -m tests.e2e.mock.server
    poetry run python -m tests.e2e.mock.server --port 12345


.. _poetry: https://python-poetry.org/
.. _mutagen: https://github.com/quodlibet/mutagen
.. _aiofiles: https://github.com/Tinche/aiofiles
.. _async-upnp-client: https://github.com/StevenLooman/async_upnp_client
.. _pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
.. _async-timeout: https://github.com/aio-libs/async-timeout
