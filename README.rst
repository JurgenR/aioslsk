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
        settings: Settings = Settings.create_default()
        settings.set('credentials.username', 'my_user')
        settings.set('credentials.password', 'Secret123')

        await client.start()

        # Send a private message
        await client.send_private_message('my_friend', 'Hi!')

        await client.stop()

    asyncio.run(main())


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
