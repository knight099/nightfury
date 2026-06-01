from app.services.digest.sampler import sample_evenly


def test_sample_below_cap_returns_unchanged():
    items = list(range(50))
    assert sample_evenly(items, cap=200) == items


def test_sample_at_cap_returns_unchanged():
    items = list(range(200))
    assert sample_evenly(items, cap=200) == items


def test_sample_above_cap_returns_evenly_spaced():
    items = list(range(1000))
    sampled = sample_evenly(items, cap=10)
    assert len(sampled) == 10
    assert sampled[0] == 0
    assert sampled[-1] == 999
    diffs = [b - a for a, b in zip(sampled, sampled[1:])]
    assert max(diffs) - min(diffs) <= 1


def test_sample_empty_list():
    assert sample_evenly([], cap=10) == []


def test_sample_cap_one():
    assert sample_evenly(list(range(100)), cap=1) == [0]
