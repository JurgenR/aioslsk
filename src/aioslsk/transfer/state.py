"""Implementation of the state design pattern for transfers"""
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Transfer


class TransferState:

    class State(Enum):
        VIRGIN = 0
        QUEUED = 1
        REMOTELY_QUEUED = 2
        INITIALIZING = 3
        INCOMPLETE = 4
        DOWNLOADING = 5
        UPLOADING = 6
        COMPLETE = 7
        FAILED = 8
        ABORTED = 9

    VALUE = None
    VIRGIN = State.VIRGIN
    QUEUED = State.QUEUED
    INITIALIZING = State.INITIALIZING
    INCOMPLETE = State.INCOMPLETE
    DOWNLOADING = State.DOWNLOADING
    UPLOADING = State.UPLOADING
    COMPLETE = State.COMPLETE
    FAILED = State.FAILED
    ABORTED = State.ABORTED
    REMOTELY_QUEUED = State.REMOTELY_QUEUED

    def __init__(self, transfer: 'Transfer'):
        self.transfer: 'Transfer' = transfer

    @classmethod
    def init_from_state(cls, state: State, transfer: 'Transfer'):
        for subcls in cls.__subclasses__():
            if subcls.VALUE == state:
                return subcls(transfer)

        raise Exception(f"no state class for state : {state}")

    def fail(self, reason: str = None):
        pass

    def abort(self):
        pass

    def queue(self):
        pass

    def remotely_queue(self):
        pass

    def initialize(self):
        pass

    def complete(self):
        pass

    def incomplete(self):
        pass

    def start_processing(self):
        pass


class VirginState(TransferState):
    """State representing a newly added transfer. From here we can go to any
    state. This is used when loading transfers from database
    """
    VALUE = TransferState.VIRGIN

    def queue(self):
        self.transfer.transition(QueuedState(self.transfer))


class QueuedState(TransferState):
    """Transfer is locally queued

    Possible transitions:
    - Initializing: Uploads, requesting the peer if upload is allowed
    - RemotelyQueued: Downloads, the peer has received our request for download
    - Aborted: We have aborted the transfer
    - Failed:
        - Download: peer explicitly rejected our queue request
        - Upload: peer explicitly rejected our transfer request
        - Upload: peer requested a file which is not shared
    """
    VALUE = TransferState.QUEUED

    def initialize(self):
        self.transfer.transition(InitializingState(self.transfer))

    def remotely_queue(self):
        self.transfer.transition(RemotelyQueuedState(self.transfer))

    def fail(self, reason=None):
        self.transfer.fail_reason = reason
        self.transfer.transition(FailedState(self.transfer))

    def abort(self):
        self.transfer.transition(AbortedState(self.transfer))


class RemotelyQueuedState(TransferState):
    """Remotely queued state is only applicable for downloads. This indicates
    the peer has received our request for download

    Possible transitions:
    - DownloadingState: Download, transfer has started
    - Aborted: We have aborted the transfer
    - Failed:
        - Download: peer explicitly rejected our queue request
    """
    VALUE = TransferState.REMOTELY_QUEUED

    def fail(self, reason=None):
        self.transfer.fail_reason = reason
        self.transfer.transition(FailedState(self.transfer))

    def abort(self):
        self.transfer.transition(AbortedState(self.transfer))

    def start_processing(self):
        self.transfer.set_start_time()
        self.transfer.transition(DownloadingState(self.transfer))


class InitializingState(TransferState):
    """Initializing state is only applicable for uploads. This indicates we are
    attempting to establish a connection to the peer to start uploading a file

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

    def abort(self):
        self.transfer.transition(AbortedState(self.transfer))

    def queue(self):
        self.transfer.transition(QueuedState(self.transfer))

    def fail(self, reason=None):
        self.transfer.fail_reason = reason
        self.transfer.transition(FailedState(self.transfer))

    def start_processing(self):
        self.transfer.set_start_time()
        self.transfer.transition(UploadingState(self.transfer))


class _ProcessingState(TransferState):

    def fail(self, reason: str = None):
        self.transfer.fail_reason = reason
        self.transfer.set_complete_time()
        self.transfer.transition(FailedState(self.transfer))

    def complete(self):
        self.transfer.set_complete_time()
        self.transfer.transition(CompleteState(self.transfer))

    def abort(self):
        self.transfer.set_complete_time()
        self.transfer.transition(AbortedState(self.transfer))


class DownloadingState(_ProcessingState):
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

    def incomplete(self):
        self.transfer.set_complete_time()
        self.transfer.transition(IncompleteState(self.transfer))


class UploadingState(_ProcessingState):
    VALUE = TransferState.UPLOADING

    """
    Possible transitions:
    - CompleteState: Transfer has successfully completed
    - FailedState:
        - Could not open local file
        - Received PeerUploadFailed message from peer
    - Aborted: We have aborted the transfer
    """


class CompleteState(TransferState):
    """
    Possible transitions:
    - QueueState: Attempt transfer again
    """
    VALUE = TransferState.COMPLETE

    def queue(self):
        self.transfer.reset_times()
        self.transfer.transition(QueuedState(self.transfer))


class IncompleteState(TransferState):
    """State only used for downloads. The transfer should enter this state if an
    error occured during transfering but there was no explicit error from the
    other peer. In this state it should be possible to retry the transfer.

    Possible transitions:
    - QueueState: when attempting to retry transfers
    - AbortedState: We have aborted the transfer
    """
    VALUE = TransferState.INCOMPLETE

    def fail(self, reason: str = None):
        self.transfer.fail_reason = reason
        self.transfer.transition(FailedState(self.transfer))

    def queue(self):
        self.transfer.reset_times()
        self.transfer.transition(QueuedState(self.transfer))

    def abort(self):
        self.transfer.transition(AbortedState(self.transfer))


class FailedState(TransferState):
    """

    Possible transitions:
    - CompleteState: When re-initializing the transfer
    - QueuedState: Attempt transfer again
    """
    VALUE = TransferState.FAILED

    def queue(self):
        self.transfer.reset_times()
        self.transfer.transition(QueuedState(self.transfer))


class AbortedState(TransferState):
    """

    Possible transitions:
    - QueuedState: Attempt transfer again
    """
    VALUE = TransferState.ABORTED

    def queue(self):
        self.transfer.reset_times()
        self.transfer.transition(QueuedState(self.transfer))
