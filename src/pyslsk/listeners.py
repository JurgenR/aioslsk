from __future__ import annotations
from abc import ABC, abstractmethod


class TransferListener(ABC):
    @abstractmethod
    def on_transfer_offset(self, offset: int, connection: 'PeerConnection'):
        pass

    @abstractmethod
    def on_transfer_ticket(self, ticket: int, connection: 'PeerConnection'):
        pass

    @abstractmethod
    def on_transfer_data_received(self, data: bytes, connection: 'PeerConnection'):
        pass

    @abstractmethod
    def on_transfer_data_sent(self, bytes_sent: int, connection: 'PeerConnection'):
        pass
