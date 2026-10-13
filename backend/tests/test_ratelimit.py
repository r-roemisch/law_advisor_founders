from founder_legal_guide.ratelimit import RateLimiter


def test_sliding_window_per_client():
    now = [0.0]
    limiter = RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.check("a") is None and limiter.check("a") is None
    assert limiter.check("a") == 60.0
    assert limiter.check("b") is None  # other clients are unaffected
    now[0] = 61
    assert limiter.check("a") is None


def test_zero_disables_the_limit():
    limiter = RateLimiter(0, 60)
    assert all(limiter.check("a") is None for _ in range(100))
