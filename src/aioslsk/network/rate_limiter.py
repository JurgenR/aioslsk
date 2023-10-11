from __future__ import annotations
import asyncio
import time


INTERVAL = 0.01


class RateLimiter:

    def __init__(self, limit_bps: int):
        self.limit_bps: int = limit_bps
        self.bucket: int = 0
        self.last_refill: float = 0.0

    @classmethod
    def create_limiter(cls, limit_kbps: int) -> RateLimiter:
        """Creates a new `RateLimiter` instance based on the provided
        `limit_kbps`
        """
        if limit_kbps == 0:
            return UnlimitedRateLimiter()
        else:
            return LimitedRateLimiter(limit_kbps)

    def is_empty(self) -> bool:
        """Returns if the bucket is empty"""
        raise NotImplementedError("method 'is_empty' should be overridden in a subclass")

    def refill(self) -> bool:
        """Refill the bucket"""
        raise NotImplementedError("method 'refill' should be overridden in a subclass")

    async def take_tokens(self) -> int:
        """Takes tokens from the bucket"""
        raise NotImplementedError("method 'take_tokens' should be overridden in a subclass")

    def add_tokens(self, token_amount: int):
        """Adds tokens to the bucket"""
        raise NotImplementedError("method 'add_tokens' should be overridden in a subclass")

    def copy_tokens(self, other: 'RateLimiter'):
        """Copies to tokens from another rate limiter instance"""
        raise NotImplementedError("method 'copy_tokens' should be overridden in a subclass")


class UnlimitedRateLimiter(RateLimiter):
    UPPER_LIMIT = 8192

    def __init__(self):
        super().__init__(limit_bps=0)

    def is_empty(self) -> bool:
        return False

    def refill(self) -> bool:
        return False

    async def take_tokens(self) -> int:
        return self.UPPER_LIMIT

    def add_tokens(self, token_amount: int):
        pass

    def copy_tokens(self, other: RateLimiter):
        pass


class LimitedRateLimiter(RateLimiter):
    LOWER_LIMIT = 128
    UPPER_LIMIT = 1024

    def __init__(self, limit_kbps: int):
        super().__init__(limit_bps=limit_kbps * 1024)

    def is_empty(self) -> bool:
        return self.bucket < self.LOWER_LIMIT

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
                self.bucket -= self.LOWER_LIMIT
                return self.LOWER_LIMIT

            await asyncio.sleep(0.01)

    def add_tokens(self, token_amount: int):
        self.bucket += token_amount
        if self.bucket > self.limit_bps:
            self.bucket = self.limit_bps

    def copy_tokens(self, other: RateLimiter):
        self.add_tokens(other.bucket)
        self.last_refill = other.last_refill
