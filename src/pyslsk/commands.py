from pyslsk.transfer import Transfer
from dataclasses import dataclass


@dataclass(frozen=True)
class InitPeerConnectionCommand:
    ticket: int
    username: str
    typ: str
    ip: str = None
    port: int = None
    transfer: Transfer = None
    messages = None


@dataclass(frozen=True)
class QueueTransferCommand:
    pass
