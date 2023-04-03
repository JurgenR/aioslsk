from __future__ import annotations
import asyncio
import time
from typing import Type


INTERVAL = 0.01


class RateLimiter:

    def __init__(self, limit_bps: int):
        self.limit_bps: int = limit_bps
        self.bucket: int = 0
        self.transfer_amount: int = 0
        self.last_refill: float = 0.0

    @classmethod
    def create_limiter(cls, limit_kbps: int) -> Type[RateLimiter]:
        if limit_kbps == 0:
            return UnlimitedRateLimiter()
        else:
            return LimitedRateLimiter(limit_kbps)

    def is_empty(self) -> bool:
        raise NotImplementedError("method 'is_empty' should be overridden in a subclass")

    def refill(self) -> bool:
        raise NotImplementedError("method 'refill' should be overridden in a subclass")

    def take_tokens(self) -> int:
        raise NotImplementedError("method 'take_tokens' should be overridden in a subclass")

    def add_tokens(self, token_amount: int):
        raise NotImplementedError("method 'add_tokens' should be overridden in a subclass")


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


class LimitedRateLimiter(RateLimiter):
    LOWER_LIMIT = 128
    UPPER_LIMIT = 1024

    def __init__(self, limit_kbps: int):
        super().__init__(limit_bps=limit_kbps * 1024)

    def is_empty(self) -> bool:
        return self.bucket < self.LOWER_LIMIT

    def refill(self) -> bool:
        if self.limit_bps == self.bucket:
            return

        current_time = time.monotonic()
        if self.bucket < self.limit_bps:
            time_passed = current_time - self.last_refill
            new_tokens = (self.limit_bps - self.bucket) * time_passed
            self.add_tokens(int(new_tokens))

        self.last_refill = current_time

        return self.is_empty()

    async def take_tokens(self) -> int:
        while True:
            self.refill()
            if self.bucket >= self.LOWER_LIMIT:
                self.bucket -= self.LOWER_LIMIT
                return self.LOWER_LIMIT

            await asyncio.sleep(0.01)

    def add_tokens(self, token_amount: int):
        self.bucket += token_amount
        if self.bucket > self.limit_bps:
            self.bucket = self.limit_bps
