from unittest.mock import patch, MagicMock
from pyslsk.network.rate_limiter import LimitedRateLimiter, RateLimiter, UnlimitedRateLimiter
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
        [0, LimitedRateLimiter.LOWER_LIMIT - 1, ]
    )
    def test_whenBucketBelowThreshold_isEmptyReturnsTrue(self, limited_limiter: LimitedRateLimiter, bucket_value: int):
        limited_limiter.bucket = bucket_value
        assert limited_limiter.is_empty() is True

    @pytest.mark.parametrize(
        "bucket_value",
        [LimitedRateLimiter.LOWER_LIMIT, LimitedRateLimiter.LOWER_LIMIT + 1]
    )
    def test_whenBucketAboveThreshold_isEmptyReturnsFalse(self, limited_limiter: LimitedRateLimiter, bucket_value):
        limited_limiter.bucket = bucket_value
        assert limited_limiter.is_empty() is False

    def test_whenAddTokensAndBucketFull_shouldNotAddToBucket(self, limited_limiter: LimitedRateLimiter):
        limited_limiter.bucket = limited_limiter.limit_bps
        limited_limiter.add_tokens(50)
        assert limited_limiter.bucket == limited_limiter.limit_bps

    def test_whenAddTokensAndBucketNotFull_shouldAddToBucket(self, limited_limiter: LimitedRateLimiter):
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
    def test_whenRefillBucket_shouldRefill(self, limited_limiter: LimitedRateLimiter, time_diff: float, expected_bucket: int):
        limited_limiter.bucket = 0
        limited_limiter.last_refill = 0.0

        with patch('time.monotonic', return_value=time_diff):
            limited_limiter.refill()

        assert limited_limiter.bucket == expected_bucket
        assert limited_limiter.last_refill == time_diff

    def test_whenRefillBucket_andBucketFull_shouldNotRefill(self, limited_limiter: LimitedRateLimiter):
        limited_limiter.bucket = limited_limiter.limit_bps
        limited_limiter.refill()

        assert limited_limiter.bucket == limited_limiter.limit_bps
        assert limited_limiter.last_refill == 0.0

    @pytest.mark.parametrize(
        "bucket_size",
        [
            0,
            LimitedRateLimiter.LOWER_LIMIT - 1
        ]
    )
    @pytest.mark.asyncio
    async def test_whenTakeTokens_andBucketEmpty_shouldWaitForTokens(self, limited_limiter: LimitedRateLimiter, bucket_size: int):
        limited_limiter.bucket = bucket_size
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

    @pytest.mark.parametrize(
        "bucket_size,expected_bucket_size",
        [
            (LimitedRateLimiter.LOWER_LIMIT, 0),
            (LimitedRateLimiter.LOWER_LIMIT + 1, 1)
        ]
    )
    @pytest.mark.asyncio
    async def test_whenTakeTokens_andBucketNotEmpty_shouldReturnTokens(self, limited_limiter: LimitedRateLimiter, bucket_size: int, expected_bucket_size: int):
        limited_limiter.bucket = bucket_size
        limited_limiter.refill = MagicMock(return_value=False)
        assert await limited_limiter.take_tokens() == LimitedRateLimiter.LOWER_LIMIT
        assert limited_limiter.bucket == expected_bucket_size


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
    async def test_whenTakeTokens_shouldReturnUpperLimit(self, unlimited_limiter: UnlimitedRateLimiter):
        assert await unlimited_limiter.take_tokens() == UnlimitedRateLimiter.UPPER_LIMIT
