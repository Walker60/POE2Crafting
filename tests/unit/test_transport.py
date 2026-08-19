"""RateLimiter's header-parsing and backoff logic -- generic since trade2's
exact rate-limit header names aren't documented (see
poe2craft.pricing.transport's module docstring)."""
from poe2craft.pricing.transport import RateLimiter
from pricing_fakes import FakeResponse


def _sleeper():
    slept: list[float] = []
    return slept, slept.append


def test_wait_sleeps_the_fallback_delay_before_any_response_seen():
    slept, sleep = _sleeper()
    limiter = RateLimiter(sleep=sleep, fallback_delay=2.0)
    limiter.wait()
    assert slept == [2.0]


def test_observe_learns_delay_from_a_rate_limit_style_header():
    slept, sleep = _sleeper()
    limiter = RateLimiter(sleep=sleep, fallback_delay=1.0)
    response = FakeResponse(status_code=200, _json={}, headers={"X-Rate-Limit-Account": "10:60:0,5:10:0"})
    retry = limiter.observe(response)
    assert retry is None  # not itself rate-limited
    limiter.wait()
    assert slept == [1.0]  # unchanged -- both triples' restricted-seconds field is 0 (not currently throttled)


def test_observe_returns_retry_delay_and_raises_it_on_429_via_retry_after():
    slept, sleep = _sleeper()
    limiter = RateLimiter(sleep=sleep, fallback_delay=1.0)
    response = FakeResponse(status_code=429, _json={}, headers={"Retry-After": "5"})
    retry = limiter.observe(response)
    assert retry == 5.0
    limiter.wait()
    assert slept == [5.0]  # next wait honors the learned delay


def test_observe_falls_back_to_fallback_delay_when_no_header_parses():
    slept, sleep = _sleeper()
    limiter = RateLimiter(sleep=sleep, fallback_delay=3.0)
    limiter.observe(FakeResponse(status_code=200, _json={}, headers={}))
    limiter.wait()
    assert slept == [3.0]
