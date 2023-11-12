from abc import ABC
import asyncio
from typing import List


class BaseManager(ABC):
    """Base class for manager instances. This class provides hooks that will
    get called during starting and stopping of the client
    """

    async def load_data(self):
        """Load the data for the manager. This method gets called during client
        client start-up before any connection is made
        """

    async def store_data(self):
        """Stores data from the manager. This gets called during the client
        shutdown
        """

    async def start(self):
        """Optionally performs a start action on the manager. Gets called after
        loading the data but before connecting
        """

    async def stop(self) -> List[asyncio.Task]:
        """Cancel all running tasks

        :return: list of all cancelled tasks
        """
        return []
