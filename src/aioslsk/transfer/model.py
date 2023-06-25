import asyncio
from collections import deque
from enum import auto, Enum
import os
import time

SPEED_LOG_INTERVAL = 0.1
SPEED_LOG_ENTRIES = 30


class TransferDirection(Enum):
    UPLOAD = 0
    DOWNLOAD = 1


class TransferState(Enum):
    VIRGIN = auto()
    QUEUED = auto()
    """Transfer is queued and awaiting handling"""
    INITIALIZING = auto()
    """Upload/download is initializing:

    - Download goes into this state when PeerTransferRequest is received
    - Upload goes into this state when we are about to send PeerTransferRequest
      (but doesn't need to be delivered yet)
    """
    INCOMPLETE = auto()
    """Connection was closed during transfer"""
    DOWNLOADING = auto()
    UPLOADING = auto()
    COMPLETE = auto()
    FAILED = auto()
    """Upload/download failed:

    - Download: Other peer rejected the upload for reasons other than 'Queued'
    - Upload: Failure due to for example: file not present, etc...
    """
    ABORTED = auto()
    """Aborted upon user request"""
    REMOTELY_QUEUED = auto()


class Transfer:
    """Class representing a transfer"""
    _UNPICKABLE_FIELDS = ('_speed_log', '_current_task')

    def __init__(self, username: str, remote_path: str, direction: TransferDirection):
        self.state = TransferState.VIRGIN

        self.username: str = username
        self.remote_path: str = remote_path
        """Remote path, this is the path that is shared between peers"""
        self.local_path: str = None
        """Absolute path to the file on disk"""
        self.direction: TransferDirection = direction
        self.place_in_queue: int = None
        """Place in queue, only applicable for downloads"""
        self.fail_reason: str = None

        self.filesize: int = None
        """Filesize in bytes"""
        self._offset: int = None
        """Offset used for resuming downloads. This offset will be used and
        reset by the L{read} method of this object
        """

        self.bytes_transfered: int = 0
        """Amount of bytes transfered (uploads and downloads)"""
        self.bytes_written: int = 0
        """Amount of bytes written to file (downloads)"""
        self.bytes_read: int = 0
        """Amount of bytes read from file (uploads)"""

        self.queue_attempts: int = 0
        self.last_queue_attempt: float = 0.0

        self.upload_request_attempts: int = 0
        self.last_upload_request_attempt: float = 0.0

        self.start_time: float = None
        """Time at which the transfer was started. This is the time the transfer
        entered the DOWNLOADING or UPLOADING state
        """
        self.complete_time: float = None
        """Time at which the transfer was completed. This is the time the
        transfer entered the complete or incomplete state
        """

        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self._current_task: asyncio.Task = None

    def __setstate__(self, state):
        """Called when unpickling"""
        self.__dict__.update(state)
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self._current_task = None

    def __getstate__(self):
        """Called when pickling, removes unpickable fields from the fields to
        store
        """
        state = self.__dict__.copy()
        for unpickable_field in self._UNPICKABLE_FIELDS:
            if unpickable_field in state:
                del state[unpickable_field]

        return state

    def increase_queue_attempts(self):
        self.queue_attempts += 1
        self.last_queue_attempt = time.monotonic()

    def reset_queue_attempts(self):
        self.queue_attempts = 0
        self.last_queue_attempt = 0.0

    def increase_upload_request_attempt(self):
        self.upload_request_attempts += 1
        self.last_upload_request_attempt = time.monotonic()

    def reset_upload_request_attempt(self):
        self.upload_request_attempts = 0
        self.last_upload_request_attempt = 0.0

    def set_state(self, state: TransferState, force: bool = False):
        """Sets the current state for the transfer. This will do nothing in case
        the transfer is already in that state.

        :param state: the new state
        :param force: only used for the QUEUED state, normally we don't allow
            to queue a transfer in case the transfer is processing but in some
            cases it needs to be forced: during loading of transfers from
            cache for transfers who were processing when they were stored or if
            initialization failed (default: False)
        :return: previous state in case state was changed, otherwise None
        """
        if state == self.state:
            return None

        if state == TransferState.QUEUED:
            if force:
                self.reset_times()
            elif self.is_processing():
                # Not allowed to queue processing transfers
                return None

        elif state == TransferState.REMOTELY_QUEUED:
            pass

        elif state == TransferState.INITIALIZING:
            pass

        elif state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()
            self.complete_time = None

        elif state == TransferState.ABORTED:
            # Aborting on a complete state does nothing
            # TODO: Not sure what should # happen in case of INITIALIZING
            if self.state in (TransferState.COMPLETE, TransferState.INCOMPLETE, TransferState.ABORTED):
                return None
            else:
                self._finalize()

        elif state == TransferState.FAILED:

            if self.state != TransferState.ABORTED:
                self._finalize()

        elif state == TransferState.COMPLETE:
            self._finalize()

        elif state == TransferState.INCOMPLETE:
            if self.state in (TransferState.COMPLETE, TransferState.ABORTED):
                return None
            self._finalize()

        old_state = state
        self.state = state
        return old_state

    def _finalize(self):
        self.complete_time = time.time()
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)

    def calculate_offset(self) -> int:
        try:
            offset = os.path.getsize(self.local_path)
        except (OSError, TypeError):
            offset = 0

        self._offset = offset
        self.bytes_transfered = offset
        self.bytes_written = offset
        return offset

    def set_offset(self, offset: int):
        self._offset = offset
        self.bytes_transfered = offset

    def get_offset(self) -> int:
        return self._offset

    def reset_times(self):
        self.start_time = None
        self.complete_time = None
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)

    def get_speed(self) -> float:
        """Retrieve the speed of the transfer

        :return: 0 if the transfer has not yet begun. The current speed if the
            transfer is ongoing. The transfer speed if the transfer was
            complete. Bytes per second
        """
        # Transfer hasn't begun
        if self.start_time is None:
            return 0.0

        # Transfer in progress
        if self.is_transfering():
            if len(self._speed_log) == 0:
                return 0.0

            current_time = time.monotonic()
            bytes_transfered = sum(bytes_sent for _, bytes_sent in self._speed_log)
            oldest_time = self._speed_log[0][0]

            transfer_duration = current_time - oldest_time
            if current_time - oldest_time == 0.0:
                return 0.0

            return bytes_transfered / transfer_duration

        # Transfer complete
        if self.complete_time is None:
            transfer_duration = time.time() - self.start_time
        else:
            transfer_duration = self.complete_time - self.start_time
        if transfer_duration == 0.0:
            return 0.0

        return self.bytes_transfered / transfer_duration

    def add_speed_log_entry(self, bytes_transfered: int):
        current_time = time.monotonic()
        # Create speed log entry
        if len(self._speed_log) == 0:
            self._speed_log.append((current_time, bytes_transfered))
        else:
            if current_time - self._speed_log[-1][0] < SPEED_LOG_INTERVAL:
                last_time_log, last_sent_bytes = self._speed_log.pop()
                self._speed_log.append((last_time_log, bytes_transfered + last_sent_bytes))
            else:
                self._speed_log.append((current_time, bytes_transfered))

    def is_upload(self) -> bool:
        return self.direction == TransferDirection.UPLOAD

    def is_download(self) -> bool:
        return self.direction == TransferDirection.DOWNLOAD

    def is_finalized(self) -> bool:
        return self.state in (TransferState.COMPLETE, TransferState.ABORTED, TransferState.FAILED)

    def is_processing(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING, )

    def is_transfering(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, )

    def is_transfered(self) -> bool:
        return self.filesize == self.bytes_transfered

    def _queue_remotely_task_complete(self, task: asyncio.Task):
        self._current_task = None

    def _upload_task_complete(self, task: asyncio.Task):
        self._current_task = None

    def _download_task_complete(self, task: asyncio.Task):
        self._current_task = None

    def _transfer_progress_callback(self, data: bytes):
        self.bytes_transfered += len(data)
        self.add_speed_log_entry(len(data))

    def __eq__(self, other: 'Transfer'):
        other_vars = (other.remote_path, other.username, other.direction, )
        own_vars = (self.remote_path, self.username, self.direction, )
        return other_vars == own_vars

    def __repr__(self):
        return (
            f"Transfer(username={self.username!r}, remote_path={self.remote_path!r}, "
            f"local_path={self.local_path!r}, direction={self.direction}, "
            f"state={self.state}, _current_task={self._current_task!r})"
        )