"""Implementation of the state design pattern for transfers"""
import asyncio
from enum import Enum
import logging
from typing import Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Transfer

logger = logging.getLogger(__name__)


class TransferStateListener(Protocol):

    async def on_transfer_state_changed(
            self, transfer: 'Transfer', old: 'TransferState.State', new: 'TransferState.State'):
        ...


class TransferState:
    """Represents a transfer state and its possible transitions

    Each transition method will return a boolean to indicate whether the
    transition was done.
    """

    class State(Enum):
        UNSET = -1
        VIRGIN = 0
        QUEUED = 1
        INITIALIZING = 3
        INCOMPLETE = 4
        DOWNLOADING = 5
        UPLOADING = 6
        COMPLETE = 7
        FAILED = 8
        ABORTED = 9
        TRANSFERRING = 10

    UNSET = State.UNSET
    VIRGIN = State.VIRGIN
    QUEUED = State.QUEUED
    INITIALIZING = State.INITIALIZING
    INCOMPLETE = State.INCOMPLETE
    DOWNLOADING = State.DOWNLOADING
    UPLOADING = State.UPLOADING
    COMPLETE = State.COMPLETE
    FAILED = State.FAILED
    ABORTED = State.ABORTED
    TRANSFERRING = State.TRANSFERRING

    VALUE = UNSET

    def __init__(self, transfer: 'Transfer'):
        self.transfer: 'Transfer' = transfer

    @classmethod
    def init_from_state(cls, state: State, transfer: 'Transfer'):
        for subcls in cls.__subclasses__():
            if subcls.VALUE == state:
                return subcls(transfer)

        raise Exception(f"no state class for state : {state}")

    async def fail(self, reason: Optional[str] = None) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.FAILED.name}")
        return False

    async def abort(self) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.ABORTED.name}")
        return False

    async def queue(self, remotely: bool = False) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.QUEUED.name}")
        return False

    async def initialize(self) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.INITIALIZING.name}")
        return False

    async def complete(self) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.COMPLETE.name}")
        return False

    async def incomplete(self) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.INCOMPLETE.name}")
        return False

    async def start_transferring(self) -> bool:
        logger.warning(
            f"attempted to make undefined state transition from {self.VALUE.name} to {self.TRANSFERRING.name}")
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.transfer!r})"


class VirginState(TransferState):
    """State representing a newly added transfer"""
    VALUE = TransferState.VIRGIN

    async def queue(self, remotely: bool = False) -> bool:
        self.transfer.remotely_queued = remotely
        await self.transfer.transition(QueuedState(self.transfer))
        return True


class QueuedState(TransferState):
    """Transfer is queued

    Possible transitions:
    - Initializing: Uploads, requesting the peer if upload is allowed
    - Aborted: We have aborted the transfer
    - Failed:
        - Download: peer explicitly rejected our queue request
        - Upload: peer explicitly rejected our transfer request
        - Upload: peer requested a file which is not shared
    """
    VALUE = TransferState.QUEUED

    async def initialize(self) -> bool:
        await self.transfer.transition(InitializingState(self.transfer))
        return True

    async def fail(self, reason=None) -> bool:
        self.transfer.fail_reason = reason
        await self.transfer.transition(FailedState(self.transfer))
        return True

    async def abort(self) -> bool:
        await self.transfer.transition(AbortedState(self.transfer))
        return True


class InitializingState(TransferState):
    """Initializing state:

    - Uploads: This indicates we are attempting to establish a connection to the
    peer to start uploading a file
    - Downloads: The download will quickly go into this state when the transfer
    ticket has been received over a file connection

    Possible transitions:
    - UploadingState: Upload, transfer has started
    - QueueState:
        - Failed to send PeerTransferRequest message
        - Timeout receiving PeerTransferReply message
        - Failed to make file connection
        - Timeout waiting for transfer offset
        - Failed to send transfer ticket
    - AbortedState: We have aborted the transfer
    - FailedState:
        - PeerTransferReply was not allowed
    """
    VALUE = TransferState.INITIALIZING

    async def abort(self) -> bool:
        await self.transfer.transition(AbortedState(self.transfer))
        return True

    async def queue(self, remotely: bool = False):
        self.transfer.remotely_queued = remotely
        await self.transfer.transition(QueuedState(self.transfer))
        return True

    async def fail(self, reason=None) -> bool:
        self.transfer.fail_reason = reason
        await self.transfer.transition(FailedState(self.transfer))
        return True

    async def start_transferring(self) -> bool:
        self.transfer.remotely_queued = False
        self.transfer.set_start_time()
        if self.transfer.is_upload():
            await self.transfer.transition(UploadingState(self.transfer))
        else:
            await self.transfer.transition(DownloadingState(self.transfer))
        return True


class DownloadingState(TransferState):
    """
    Possible transitions:
    - CompleteState: Transfer has successfully completed
    - IncompleteState:
        - Failed to send transfer offset
        - Connection was closed before all bytes were transfered
    - FailedState:
        - Could not open local file
        - Received PeerUploadFailed message from peer
    - Aborted: We have aborted the transfer
    """
    VALUE = TransferState.DOWNLOADING

    async def fail(self, reason: Optional[str] = None) -> bool:
        self.transfer.fail_reason = reason
        self.transfer.set_complete_time()
        await self.transfer.transition(FailedState(self.transfer))
        return True

    async def complete(self) -> bool:
        self.transfer.set_complete_time()
        await self.transfer.transition(CompleteState(self.transfer))
        return True

    async def abort(self) -> bool:
        tasks = self.transfer.get_tasks()
        logger.debug(
            f"aborting download: cancelling tasks : {tasks}")
        results = await asyncio.gather(*self.transfer.cancel_tasks(), return_exceptions=True)
        logger.debug(
            f"aborting download: completed cancelling tasks : {tasks} : results : {results}")
        self.transfer.set_complete_time()
        await self.transfer.transition(AbortedState(self.transfer))
        return True

    async def incomplete(self) -> bool:
        self.transfer.set_complete_time()
        await self.transfer.transition(IncompleteState(self.transfer))
        return True


class UploadingState(TransferState):
    VALUE = TransferState.UPLOADING

    """
    Possible transitions:
    - CompleteState: Transfer has successfully completed
    - FailedState:
        - Could not open local file
        - Received PeerUploadFailed message from peer
    - Aborted: We have aborted the transfer
    """

    async def fail(self, reason: Optional[str] = None) -> bool:
        self.transfer.fail_reason = reason
        self.transfer.set_complete_time()
        await self.transfer.transition(FailedState(self.transfer))
        return True

    async def complete(self) -> bool:
        self.transfer.set_complete_time()
        await self.transfer.transition(CompleteState(self.transfer))
        return True

    async def abort(self) -> bool:
        tasks = self.transfer.get_tasks()
        logger.debug(
            f"aborting upload: cancelling tasks : {tasks}")
        results = await asyncio.gather(*self.transfer.cancel_tasks(), return_exceptions=True)
        logger.debug(
            f"aborting upload: completed cancelling tasks : {tasks} : results : {results}")
        self.transfer.set_complete_time()
        await self.transfer.transition(AbortedState(self.transfer))
        return True


class CompleteState(TransferState):
    """
    Possible transitions:
    - QueueState: Attempt transfer again
    """
    VALUE = TransferState.COMPLETE

    async def queue(self, remotely: bool = False) -> bool:
        self.transfer.remotely_queued = remotely
        self.transfer.reset_times()
        await self.transfer.transition(QueuedState(self.transfer))
        return True


class IncompleteState(TransferState):
    """State only used for downloads. The transfer should enter this state if an
    error occured during transferring but there was no explicit error from the
    other peer. In this state it should be possible to retry the transfer.

    Possible transitions:
    - QueueState: when attempting to retry transfers
    - AbortedState: We have aborted the transfer
    """
    VALUE = TransferState.INCOMPLETE

    async def fail(self, reason: Optional[str] = None) -> bool:
        self.transfer.fail_reason = reason
        await self.transfer.transition(FailedState(self.transfer))
        return True

    async def queue(self, remotely: bool = False) -> bool:
        self.transfer.remotely_queued = remotely
        self.transfer.reset_times()
        await self.transfer.transition(QueuedState(self.transfer))
        return True

    async def initialize(self) -> bool:
        self.transfer.reset_times()
        await self.transfer.transition(InitializingState(self.transfer))
        return True

    async def abort(self) -> bool:
        await self.transfer.transition(AbortedState(self.transfer))
        return True


class FailedState(TransferState):
    """

    Possible transitions:
    - CompleteState: When re-initializing the transfer
    - QueuedState: Attempt transfer again
    """
    VALUE = TransferState.FAILED

    async def queue(self, remotely: bool = False) -> bool:
        self.transfer.remotely_queued = remotely
        self.transfer.reset_times()
        await self.transfer.transition(QueuedState(self.transfer))
        return True


class AbortedState(TransferState):
    """

    Possible transitions:
    - QueuedState: Attempt transfer again
    """
    VALUE = TransferState.ABORTED

    async def queue(self, remotely: bool = False) -> bool:
        # Reset all progress if the transfer is requeued after being aborted,
        # the file should be deleted anyway
        self.transfer.remotely_queued = remotely
        self.transfer.reset_progress()
        await self.transfer.transition(QueuedState(self.transfer))
        return True
