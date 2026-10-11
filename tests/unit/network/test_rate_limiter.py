import asyncio
import time
from typing import Optional
from unittest.mock import patch, MagicMock
from aioslsk.network.rate_limiter import INTERVAL, LimitedRateLimiter, RateLimiter, UnlimitedRateLimiter
import pytest


DEFAULT_LIMIT = 50


@pytest.fixture
def limited_limiter() -> LimitedRateLimiter:
    return RateLimiter.create_limiter(DEFAULT_LIMIT)


@pytest.fixture
def unlimited_limiter() -> UnlimitedRateLimiter:
    return RateLimiter.create_limiter(0)


class TestRateLimiter:

    @pytest.mark.parametrize(
        "limit_kbps, expected_type",
        [
            (0, UnlimitedRateLimiter),
            (1, LimitedRateLimiter)
        ]
    )
    def test_whenCreateLimiter_shouldReturnCorrectInstance(self, limit_kbps, expected_type):
        limiter = RateLimiter.create_limiter(limit_kbps)
        assert type(limiter) == expected_type


class TestLimitedRateLimiter:

    @pytest.mark.parametrize(
        "bucket_value",
        [0, LimitedRateLimiter.MIN_BUCKET_SIZE - 1, ]
    )
    def test_whenBucketBelowThreshold_isEmptyReturnsTrue(
        self,
        limited_limiter: LimitedRateLimiter,
        bucket_value: int
    ):

        limited_limiter.bucket = bucket_value
        assert limited_limiter.is_empty() is True

    @pytest.mark.parametrize(
        "bucket_value",
        [LimitedRateLimiter.MIN_BUCKET_SIZE, LimitedRateLimiter.MIN_BUCKET_SIZE + 1]
    )
    def test_whenBucketAboveThreshold_isEmptyReturnsFalse(
        self,
        limited_limiter: LimitedRateLimiter,
        bucket_value
    ):

        limited_limiter.bucket = bucket_value
        assert limited_limiter.is_empty() is False

    def test_whenAddTokensAndBucketFull_shouldNotAddToBucket(
        self,
        limited_limiter: LimitedRateLimiter
    ):

        limited_limiter.bucket = limited_limiter.limit_bps
        limited_limiter.add_tokens(50)
        assert limited_limiter.bucket == limited_limiter.limit_bps

    def test_whenAddTokensAndBucketNotFull_shouldAddToBucket(
        self,
        limited_limiter: LimitedRateLimiter
    ):

        limited_limiter.bucket = limited_limiter.limit_bps - 49
        limited_limiter.add_tokens(50)
        assert limited_limiter.bucket == limited_limiter.limit_bps

    @pytest.mark.parametrize(
        "time_diff,expected_bucket",
        [
            (0.5, (DEFAULT_LIMIT * 1024) / 2),
            (1.0, DEFAULT_LIMIT * 1024),
            (1.5, DEFAULT_LIMIT * 1024)
        ]
    )
    def test_whenRefillBucket_shouldRefill(
        self,
        limited_limiter: LimitedRateLimiter,
        time_diff: float,
        expected_bucket: int
    ):

        limited_limiter.bucket = 0
        limited_limiter.last_refill = 0.0

        with patch('time.monotonic', return_value=time_diff):
            limited_limiter.refill()

        assert limited_limiter.bucket == expected_bucket
        assert limited_limiter.last_refill == time_diff

    def test_whenRefillBucket_andBucketFull_shouldNotRefill(
        self,
        limited_limiter: LimitedRateLimiter
    ):

        limited_limiter.bucket = limited_limiter.limit_bps
        limited_limiter.refill()

        assert limited_limiter.bucket == limited_limiter.limit_bps
        assert limited_limiter.last_refill == 0.0

    @pytest.mark.parametrize("bucket_offset", [None, -1])
    @pytest.mark.asyncio
    async def test_whenTakeTokens_andBucketEmpty_shouldWaitForTokens(
        self,
        limited_limiter: LimitedRateLimiter,
        bucket_offset: Optional[int]
    ):

        if bucket_offset is None:
            limited_limiter.bucket = 0
        else:
            limited_limiter.min_chunk_size + bucket_offset

        # Spy on the objects refill method
        with patch.object(limited_limiter, 'refill', wraps=limited_limiter.refill) as wrapped_refill:
            # Patch asyncio.sleep and time.monotonic:
            # 1. asyncio.sleep to verify how many times it is called
            # 2. asyncio.sleep will internally called time.monotonic and mess
            #    with our time.monotonic side_effect
            # 3. asyncio.sleep to not delay the execution
            # 4. time.monotonic returns 0.0 the first time to verify the wait
            #    sleep is executed when take_tokens is called. And a value to
            #    verify tokens are returned when the bucket is refilled
            with patch('time.monotonic', side_effect=[0.0, 1.0, ]), patch('asyncio.sleep') as sleep_func:
                assert await limited_limiter.take_tokens() > 0
                assert wrapped_refill.call_count == 2
                assert sleep_func.call_count == 1

    @pytest.mark.parametrize("bucket_offset", [0, 1])
    @pytest.mark.asyncio
    async def test_whenTakeTokens_andBucketNotEmpty_shouldReturnTokens(
        self,
        limited_limiter: LimitedRateLimiter,
        bucket_offset: int
    ):

        bucket_size = limited_limiter.min_chunk_size + bucket_offset
        limited_limiter.bucket = bucket_size
        limited_limiter.refill = MagicMock(return_value=False)
        assert await limited_limiter.take_tokens() == bucket_size
        assert limited_limiter.bucket == 0

    @pytest.mark.asyncio
    async def test_whenTakeTokens_andBelowMinChunk_shouldKeepWaitingUntilMinChunk(
        self,
        limited_limiter: LimitedRateLimiter
    ):

        limited_limiter.bucket = 0
        below_min = limited_limiter.min_chunk_size - 1
        refills = iter([below_min, limited_limiter.min_chunk_size])

        def refill():
            limited_limiter.bucket = next(refills)

        limited_limiter.refill = MagicMock(side_effect=refill)
        with patch('asyncio.sleep') as sleep_func:
            assert await limited_limiter.take_tokens() == limited_limiter.min_chunk_size
            assert sleep_func.call_count == 1
        assert limited_limiter.bucket == 0

    @pytest.mark.asyncio
    async def test_whenTakeTokens_andBucketAboveMaxChunk_shouldReturnMaxChunk(
        self,
        limited_limiter: LimitedRateLimiter
    ):

        limited_limiter.bucket = limited_limiter.max_chunk_size + 10
        limited_limiter.refill = MagicMock(return_value=False)
        assert await limited_limiter.take_tokens() == limited_limiter.max_chunk_size
        assert limited_limiter.bucket == 10

    @pytest.mark.parametrize(
        "limit_kbps,expected_min_chunk_size,expected_max_chunk_size",
        [
            (
                1,
                LimitedRateLimiter.MIN_BUCKET_SIZE,
                LimitedRateLimiter.MIN_BUCKET_SIZE
            ),
            (
                50,
                int(50 * 1024 * INTERVAL),
                int(50 * 1024 * LimitedRateLimiter.MAX_CHUNK_DURATION)
            ),
            (
                100_000,
                LimitedRateLimiter.MAX_CHUNK_SIZE,
                LimitedRateLimiter.MAX_CHUNK_SIZE
            ),
        ]
    )
    def test_chunkSizes_shouldScaleWithLimit(
        self,
        limit_kbps: int,
        expected_min_chunk_size: int,
        expected_max_chunk_size: int
    ):

        limiter = LimitedRateLimiter(limit_kbps)
        assert limiter.min_chunk_size == expected_min_chunk_size
        assert limiter.max_chunk_size == expected_max_chunk_size

    @pytest.mark.asyncio
    async def test_whenTakeTokens_andOthersWaiting_shouldQueueBehindWaiters(
        self,
        limited_limiter: LimitedRateLimiter
    ):

        # Two transfers start waiting on an empty bucket
        limited_limiter.bucket = 0
        limited_limiter.last_refill = time.monotonic()
        order: list[str] = []

        async def transfer(name: str):
            await limited_limiter.take_tokens()
            order.append(name)

        waiters = [asyncio.create_task(transfer('b')), asyncio.create_task(transfer('c'))]
        await asyncio.sleep(0)

        # Tokens become available and a third transfer asks for tokens before
        # the waiting transfers have polled again: it should not jump the queue
        limited_limiter.bucket = limited_limiter.max_chunk_size * 3
        await transfer('a')
        await asyncio.gather(*waiters)

        assert order == ['b', 'c', 'a']


class TestLimitedRateLimiterConcurrency:
    """Multiple transfers share a single rate limiter instance, these tests
    verify the available bandwidth gets divided between them instead of being
    claimed by one transfer

    The transfers are driven the same way :meth:`.PeerConnection.send_file`
    drives them: take tokens from the limiter, then write that amount of bytes
    to a socket. Writing to an actual socket in between calls to
    ``take_tokens`` is what makes the transfers settle into a fixed polling
    rhythm, which is what caused transfers to be starved
    """

    @staticmethod
    async def _measure_transfers(
        limiter: LimitedRateLimiter,
        transfer_count: int,
        stagger: float = 0.1,
        warmup: float = 0.4,
        duration: float = 0.8
    ) -> tuple[list[int], float]:

        """Runs ``transfer_count`` transfers sharing the ``limiter``, returns
        the amount of bytes each transfer sent during the measuring window and
        how long that window actually took
        """
        payload = bytes(LimitedRateLimiter.MAX_CHUNK_SIZE)
        sent = [0] * transfer_count
        running = True

        async def discard(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            while await reader.read(65536):
                pass
            writer.close()

        async def transfer(idx: int):
            # Transfers rarely start at the exact same time
            await asyncio.sleep(idx * stagger)
            _, writer = await asyncio.open_connection('127.0.0.1', port)
            try:
                while running:
                    tokens = await limiter.take_tokens()
                    sent[idx] += tokens
                    writer.write(payload[:tokens])
                    await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(discard, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        # Start from an empty bucket instead of the startup burst
        limiter.last_refill = time.monotonic()

        tasks = [asyncio.create_task(transfer(idx)) for idx in range(transfer_count)]
        try:
            # Wait for all transfers to have started before measuring
            await asyncio.sleep(stagger * transfer_count + warmup)

            start_values, start_time = list(sent), time.monotonic()
            await asyncio.sleep(duration)
            measured = [
                total - start_value
                for total, start_value in zip(sent, start_values)
            ]
            elapsed = time.monotonic() - start_time

        finally:
            running = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            server.close()
            await server.wait_closed()

        return measured, elapsed

    @pytest.mark.parametrize(
        "limit_kbps,transfer_count",
        [
            (20, 4),
            (200, 8),
        ]
    )
    @pytest.mark.asyncio
    async def test_whenMultipleTransfers_shouldNotStarveTransfers(
        self,
        limit_kbps: int,
        transfer_count: int
    ):

        limiter = LimitedRateLimiter(limit_kbps)

        measured, _ = await self._measure_transfers(limiter, transfer_count)

        assert sum(measured) > 0
        # A transfer getting (next to) nothing means the other transfers took
        # all the tokens before it got a chance to poll the limiter
        fair_share = sum(measured) / transfer_count
        assert min(measured) > fair_share / 2

    @pytest.mark.asyncio
    async def test_whenMultipleTransfers_shouldRespectLimit(self):
        limit_kbps = 50
        limiter = LimitedRateLimiter(limit_kbps)

        measured, elapsed = await self._measure_transfers(limiter, 4)

        # Generous margins: the point is that the limit is still being applied
        # to the transfers combined, not to each transfer individually
        assert sum(measured) <= limit_kbps * 1024 * elapsed * 1.5
        assert sum(measured) >= limit_kbps * 1024 * elapsed * 0.5


class TestUnlimitedRateLimiter:

    def test_whenRefill_shouldReturnFalse(self, unlimited_limiter: UnlimitedRateLimiter):
        assert unlimited_limiter.refill() is False
        assert unlimited_limiter.last_refill == 0.0

    def test_whenIsEmpty_shouldReturnFalse(self, unlimited_limiter: UnlimitedRateLimiter):
        assert unlimited_limiter.is_empty() is False

    def test_whenAddTokens_shouldNotAdd(self, unlimited_limiter: UnlimitedRateLimiter):
        unlimited_limiter.add_tokens(1)
        assert unlimited_limiter.bucket == 0
        assert unlimited_limiter.last_refill == 0.0

    @pytest.mark.asyncio
    async def test_whenTakeTokens_shouldReturnMinBucketSize(
        self,
        unlimited_limiter: UnlimitedRateLimiter
    ):

        assert await unlimited_limiter.take_tokens() == UnlimitedRateLimiter.MIN_BUCKET_SIZE
