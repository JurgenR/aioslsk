import asyncio
from typing import List


class BaseManager:

    def start(self):
        pass

    def stop(self) -> List[asyncio.Task]:
        return []
