from pjm_nowcast.stats.descriptive import percentile, sample_std, summarize


def test_percentile_edges():
    assert percentile([], 50) is None
    assert percentile([7], 5) == 7
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([0, 10], 50) == 5


def test_sample_std():
    assert sample_std([1]) is None
    assert sample_std([]) is None
    s = sample_std([2, 4, 4, 4, 5, 5, 7, 9])
    assert s is not None
    assert abs(s - 2.138) < 0.01


def test_summarize_skips_none():
    s = summarize([None, 10.0, 20.0])
    assert s.n == 2
    assert s.last == 20.0
    assert s.min == 10.0
    assert s.max == 20.0
    assert s.mean == 15.0
