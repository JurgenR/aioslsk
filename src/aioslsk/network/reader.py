import asyncio
from abc import ABC, abstractmethod
from aioslsk.protocol.primitives import MessageDataclass
from typing import Generic, TypeVar


T = TypeVar('T')


class Reader(ABC, Generic[T]):

    def __init__(self, reader: asyncio.StreamReader):
        self.reader: asyncio.StreamReader = reader

    @abstractmethod
    async def read(self) -> T:
        pass


class MessageReader(Reader):

    def __init__(self, reader: asyncio.StreamReader, obfuscated: bool):
        super().__init__(reader)
        self.obfuscated: bool = obfuscated

    async def read(self) -> bytes:
        pass


class DataReader(Reader):
    pass

