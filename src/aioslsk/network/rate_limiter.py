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
    MIN_BUCKET_SIZE = 8192

    def __init__(self):
        super().__init__(limit_bps=0)

    def is_empty(self) -> bool:
        return False

    def refill(self) -> bool:
        return False

    async def take_tokens(self) -> int:
        return self.MIN_BUCKET_SIZE

    def add_tokens(self, token_amount: int):
        pass

    def copy_tokens(self, other: RateLimiter):
        pass


class LimitedRateLimiter(RateLimiter):
    MIN_BUCKET_SIZE = 128

    def __init__(self, limit_kbps: int):
        super().__init__(limit_bps=limit_kbps * 1024)

    def is_empty(self) -> bool:
        return self.bucket < self.MIN_BUCKET_SIZE

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
        while True:
            is_empty = self.refill()
            if not is_empty:
                self.bucket -= self.MIN_BUCKET_SIZE
                return self.MIN_BUCKET_SIZE

            await asyncio.sleep(INTERVAL)

    def add_tokens(self, token_amount: int):
        self.bucket += token_amount
        if self.bucket > self.limit_bps:
            self.bucket = self.limit_bps

    def copy_tokens(self, other: RateLimiter):
        self.add_tokens(other.bucket)
        self.last_refill = other.last_refill
