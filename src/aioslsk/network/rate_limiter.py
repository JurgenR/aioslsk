from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
import time


INTERVAL = 0.01


class RateLimiter(ABC):

    def __init__(self, limit_bps: int):
        self.limit_bps: int = limit_bps
        self.bucket: int = 0
        self.last_refill: float = 0.0

    @classmethod
    def create_limiter(cls, limit_kbps: int) -> RateLimiter:
        """Creates a new :class:`.RateLimiter` instance based on the provided
        ``limit_kbps``
        """
        if limit_kbps == 0:
            return UnlimitedRateLimiter()
        else:
            return LimitedRateLimiter(limit_kbps)

    @abstractmethod
    def is_empty(self) -> bool:
        """Returns if the bucket is empty"""
        ...

    @abstractmethod
    def refill(self) -> bool:
        """Refill the bucket"""
        ...

    @abstractmethod
    async def take_tokens(self) -> int:
        """Takes tokens from the bucket"""
        ...

    @abstractmethod
    def add_tokens(self, token_amount: int):
        """Adds tokens to the bucket"""
        ...

    @abstractmethod
    def copy_tokens(self, other: 'RateLimiter'):
        """Copies to tokens from another rate limiter instance"""
        ...


class UnlimitedRateLimiter(RateLimiter):
    CHUNK_SIZE = 256 * 1024
    """Amount of bytes handed out per :meth:`take_tokens` call. Larger chunks
    mean fewer reads/writes per transferred byte
    """
    MIN_BUCKET_SIZE = CHUNK_SIZE
    """Deprecated alias of :attr:`CHUNK_SIZE`, kept for backwards
    compatibility. Note that overriding this alias in a subclass has no effect

    .. deprecated:: 1.7.0
    """

    def __init__(self):
        super().__init__(limit_bps=0)

    def is_empty(self) -> bool:
        return False

    def refill(self) -> bool:
        return False

    async def take_tokens(self) -> int:
        return self.CHUNK_SIZE

    def add_tokens(self, token_amount: int):
        pass

    def copy_tokens(self, other: RateLimiter):
        pass


class LimitedRateLimiter(RateLimiter):
    MIN_CHUNK_SIZE = 128
    """Smallest chunk :meth:`take_tokens` will hand out. Only has an effect
    below a limit of 12.5 KiB/s, where a polling interval worth of tokens is
    less than this: it keeps very low limits from producing a chunk, and thus a
    file read and a socket write, every few bytes
    """

    MIN_BUCKET_SIZE = MIN_CHUNK_SIZE
    """Deprecated alias of :attr:`MIN_CHUNK_SIZE`, kept for backwards
    compatibility. Note that overriding this alias in a subclass has no effect
    """

    MAX_CHUNK_SIZE = 64 * 1024
    MAX_CHUNK_DURATION = 0.1
    """Upper bound for a single chunk expressed in seconds worth of the limit,
    keeps transfers smooth when the limit is low
    """

    def __init__(self, limit_kbps: int):
        super().__init__(limit_bps=limit_kbps * 1024)
        self.min_chunk_size: int = self._clamp_chunk_size(self.limit_bps * INTERVAL)
        self.max_chunk_size: int = self._clamp_chunk_size(self.limit_bps * self.MAX_CHUNK_DURATION)
        self._lock: asyncio.Lock = asyncio.Lock()

    def _clamp_chunk_size(self, size: float) -> int:
        return max(self.MIN_CHUNK_SIZE, min(self.MAX_CHUNK_SIZE, int(size)))

    def is_empty(self) -> bool:
        return self.bucket < self.MIN_CHUNK_SIZE

    def refill(self) -> bool:
        if self.limit_bps == self.bucket:
            return False

        current_time = time.monotonic()
        if self.bucket < self.limit_bps:
            time_passed = current_time - self.last_refill
            new_tokens = (self.limit_bps - self.bucket) * time_passed
            self.add_tokens(int(new_tokens))

        self.last_refill = current_time

        return self.is_empty()

    async def take_tokens(self) -> int:
        """Takes a chunk of tokens from the bucket, waiting until tokens are
        available.

        The limiter is shared between connections. Waiters are served one at a
        time in FIFO order (``asyncio.Lock`` wakes waiters in order) and a
        transfer asking for its next chunk queues behind the others, so the
        bandwidth is shared round-robin. Without this, whichever waiter happens
        to poll first takes everything that accumulated and waiters polling in
        a fixed phase just behind it can be starved indefinitely.

        Chunks are between :attr:`min_chunk_size` and :attr:`max_chunk_size`
        (both scale with the limit) instead of a fixed small amount: per-chunk
        overhead would otherwise cap throughput and waste CPU. Everything
        available is taken, leaving nothing just below the threshold for the
        next caller to find.
        """
        async with self._lock:
            while True:
                self.refill()
                if self.bucket >= self.min_chunk_size:
                    amount = min(self.bucket, self.max_chunk_size)
                    self.bucket -= amount
                    return amount

                await asyncio.sleep(INTERVAL)

    def add_tokens(self, token_amount: int):
        self.bucket += token_amount
        if self.bucket > self.limit_bps:
            self.bucket = self.limit_bps

    def copy_tokens(self, other: RateLimiter):
        self.add_tokens(other.bucket)
        self.last_refill = other.last_refill
