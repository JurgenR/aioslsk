from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import Deque, List, Optional, Tuple

from .state import TransferState, TransferStateListener, VirginState

logger = logging.getLogger(__name__)


SPEED_LOG_INTERVAL = 0.1
SPEED_LOG_ENTRIES = 30


class TransferDirection(Enum):
    UPLOAD = 0
    DOWNLOAD = 1


@dataclass(frozen=True, eq=True)
class TransferProgressSnapshot:
    """Represents the current progress of a transfer, used for reporting
    progress back to the user
    """
    state: TransferState.State
    bytes_transfered: int
    speed: float
    start_time: Optional[float] = None
    complete_time: Optional[float] = None


class Transfer:
    """Class representing a transfer"""
    _UNPICKABLE_FIELDS = (
        '_speed_log',
        '_transfer_task',
        '_remotely_queue_task',
        'progress_snapshot',
        'state_listeners'
    )

    def __init__(self, username: str, remote_path: str, direction: TransferDirection):
        self.state: TransferState = VirginState(self)

        self.username: str = username
        self.remote_path: str = remote_path
        """Remote path, this is the path that is shared between peers"""
        self.local_path: Optional[str] = None
        """Absolute path to the file on disk"""
        self.direction: TransferDirection = direction

        self.remotely_queued: bool = False
        """Indicites whether the transfer queue message was received by the peer
        """
        self.place_in_queue: Optional[int] = None
        self.fail_reason: Optional[str] = None

        self.filesize: Optional[int] = None
        """Filesize in bytes"""
        self._offset: int = 0
        """Offset used for resuming downloads. This offset will be used and
        reset by the L{read} method of this object
        """

        self.bytes_transfered: int = 0
        """Amount of bytes transfered"""

        self.queue_attempts: int = 0
        self.last_queue_attempt: float = 0.0

        self.upload_request_attempts: int = 0
        self.last_upload_request_attempt: float = 0.0

        self.start_time: Optional[float] = None
        """Time at which the transfer was started. This is the time the transfer
        entered the DOWNLOADING or UPLOADING state
        """
        self.complete_time: Optional[float] = None
        """Time at which the transfer was completed. This is the time the
        transfer entered the complete or incomplete state
        """

        self.progress_snapshot: TransferProgressSnapshot = self.take_progress_snapshot()
        """Snapshot of the transfer progress"""
        self._speed_log: Deque[Tuple[float, int]] = deque(maxlen=SPEED_LOG_ENTRIES)
        self._remotely_queue_task: Optional[asyncio.Task] = None
        self._transfer_task: Optional[asyncio.Task] = None
        self.state_listeners: List[TransferStateListener] = []

    def __setstate__(self, obj_state):
        """Called when unpickling"""
        self.__dict__.update(obj_state)

        self.__dict__['state'] = TransferState.init_from_state(obj_state['state'], self)
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self._remotely_queue_task = None
        self._transfer_task = None
        self.state_listeners = []
        self.progress_snapshot = self.take_progress_snapshot()

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

    def reset_progress(self):
        """Resets progress of the entire transfer"""
        self.reset_times()
        self.bytes_transfered = 0
        self._offset = 0
        self.local_path = None
        self.fail_reason = None
        self.remotely_queued = False
        self.place_in_queue = None

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
        """Set the complete time only if the start time has not been set"""
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

    async def transition(self, state: TransferState):
        old_state = self.state
        logger.debug(f"transitioning transfer state from {old_state.VALUE.name} to {state.VALUE.name}")
        self.state = state

        for listener in self.state_listeners:
            await listener.on_transfer_state_changed(
                self, old_state.VALUE, self.state.VALUE
            )

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
        if self.is_transferring():
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
        """Return true if the transfer is in a finalized state"""
        return self.state.VALUE in (
            TransferState.COMPLETE,
            TransferState.ABORTED,
            TransferState.FAILED,
        )

    def is_processing(self) -> bool:
        """Return true if an attempt is being made to start transferring the
        file or the transfer is currently in progress.
        """
        return self.state.VALUE in (
            TransferState.DOWNLOADING,
            TransferState.UPLOADING,
            TransferState.INITIALIZING,
        )

    def is_transferring(self) -> bool:
        """Return true if the transfer is in progress"""
        return self.state.VALUE in (
            TransferState.DOWNLOADING,
            TransferState.UPLOADING,
        )

    def is_transfered(self) -> bool:
        return self.filesize == self.bytes_transfered

    def get_tasks(self) -> List[asyncio.Task]:
        tasks = []
        if self._remotely_queue_task is not None:
            tasks.append(self._remotely_queue_task)
        if self._transfer_task is not None:
            tasks.append(self._transfer_task)
        return tasks

    def cancel_tasks(self) -> List[asyncio.Task]:
        """Cancels all tasks for the transfer, this method returns the tasks
        which have been cancelled
        """
        tasks = []
        if self._remotely_queue_task is not None:
            tasks.append(self._remotely_queue_task)
            self._remotely_queue_task.cancel()

        if self._transfer_task is not None:
            tasks.append(self._transfer_task)
            self._transfer_task.cancel()

        return tasks

    def take_progress_snapshot(self) -> TransferProgressSnapshot:
        snapshot = TransferProgressSnapshot(
            state=self.state.VALUE if isinstance(self.state, TransferState) else self.state,
            bytes_transfered=self.bytes_transfered,
            speed=self.get_speed(),
            start_time=self.start_time,
            complete_time=self.complete_time
        )
        self.progress_snapshot = snapshot
        return snapshot

    def _remotely_queue_task_complete(self, task: asyncio.Task):
        self._remotely_queue_task = None

    def _transfer_task_complete(self, task: asyncio.Task):
        self._transfer_task = None

    def _transfer_progress_callback(self, data: bytes):
        self.bytes_transfered += len(data)
        self.add_speed_log_entry(len(data))

    def __eq__(self, other: object):
        if not isinstance(other, Transfer):
            return NotImplemented
        other_vars = (other.remote_path, other.username, other.direction, )
        own_vars = (self.remote_path, self.username, self.direction, )
        return other_vars == own_vars

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}(username={self.username!r}, "
            f"remote_path={self.remote_path!r}, direction={self.direction}, "
            f"local_path={self.local_path}, state={self.state})"
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"{self.__class__.__name__}(username={self.username!r}, "
            f"remote_path={self.remote_path!r}, direction={self.direction})"
        )
