from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .connection import Connection, DataConnection, PeerConnection
    from .messages import Message


class TransferListener(ABC):

    @abstractmethod
    def on_transfer_offset(self, offset: int, connection: PeerConnection):
        pass

    @abstractmethod
    def on_transfer_ticket(self, ticket: int, connection: PeerConnection):
        pass

    @abstractmethod
    def on_transfer_data_received(self, data: bytes, connection: PeerConnection):
        pass

    @abstractmethod
    def on_transfer_data_sent(self, bytes_sent: int, connection: PeerConnection):
        pass


class ConnectionStateListener(ABC):

    def on_state_changed(self, connection: Connection, close_reason=None):
        pass


class MessageListener(ABC):

    def on_message(self, message: Message, connection: DataConnection):
        pass


class ListeningConnectionListener(ABC):

    def on_peer_accepted(self, connection: PeerConnection):
        pass
