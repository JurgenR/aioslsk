import asyncio
from collections import deque
from enum import Enum
import logging
import os
import time

from .state import TransferState, VirginState

logger = logging.getLogger(__name__)


SPEED_LOG_INTERVAL = 0.1
SPEED_LOG_ENTRIES = 30


class TransferDirection(Enum):
    UPLOAD = 0
    DOWNLOAD = 1


class Transfer:
    """Class representing a transfer"""
    _UNPICKABLE_FIELDS = ('_speed_log', '_current_task')

    def __init__(self, username: str, remote_path: str, direction: TransferDirection):
        self.state: TransferState = VirginState(self)

        self.username: str = username
        self.remote_path: str = remote_path
        """Remote path, this is the path that is shared between peers"""
        self.local_path: str = None
        """Absolute path to the file on disk"""
        self.direction: TransferDirection = direction

        self.remotely_queued: bool = False
        """Indicites whether the queue message was received by the peer"""
        self.place_in_queue: int = None
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

    def __setstate__(self, obj_state):
        """Called when unpickling"""
        self.__dict__.update(obj_state)
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self._current_task = None
        self.__dict__['state'] = TransferState.init_from_state(obj_state['state'], self)

    def __getstate__(self):
        """Called when pickling, removes unpickable fields from the fields to
        store
        """
        obj_state = self.__dict__.copy()
        for unpickable_field in self._UNPICKABLE_FIELDS:
            if unpickable_field in obj_state:
                del obj_state[unpickable_field]

        obj_state['state'] = obj_state['state'].VALUE

        return obj_state

    def reset_times(self):
        """Clear all time related variables"""
        self.start_time = None
        self.complete_time = None
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)

    def set_start_time(self):
        """Set the start time, clear the complete time"""
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self.start_time = time.time()
        self.complete_time = None

    def set_complete_time(self):
        """Set the complete time if the start time has been set"""
        if self.start_time is not None:
            self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
            self.complete_time = time.time()

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

    def transition(self, state: TransferState):
        if self.state.VALUE != state.VALUE:
            logger.debug(f"transitioning transfer state from {self.state!r} to {state!r}")
            self.state = state

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
        return self.state.VALUE in (
            TransferState.COMPLETE,
            TransferState.ABORTED,
            TransferState.FAILED,
        )

    def is_processing(self) -> bool:
        return self.state.VALUE in (
            TransferState.DOWNLOADING,
            TransferState.UPLOADING,
            TransferState.INITIALIZING,
        )

    def is_transfering(self) -> bool:
        return self.state.VALUE in (
            TransferState.DOWNLOADING,
            TransferState.UPLOADING,
        )

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