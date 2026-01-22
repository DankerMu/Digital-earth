from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_grid_statistics_accumulator_basic_stats() -> None:
    from statistics.accumulator import GridStatisticsAccumulator

    acc = GridStatisticsAccumulator(shape=(2, 2))
    acc.update(np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32))
    acc.update(np.array([[2.0, 2.0], [np.nan, 0.0]], dtype=np.float32))

    result = acc.finalize()

    assert result.count.tolist() == [[2, 1], [1, 2]]
    np.testing.assert_allclose(result.sum, [[3.0, 2.0], [3.0, 4.0]], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result.mean, [[1.5, 2.0], [3.0, 2.0]], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result.min, [[1.0, 2.0], [3.0, 0.0]], rtol=0, atol=1e-6)
    np.testing.assert_allclose(result.max, [[2.0, 2.0], [3.0, 4.0]], rtol=0, atol=1e-6)


def test_grid_statistics_accumulator_rejects_shape_mismatch() -> None:
    from statistics.accumulator import GridStatisticsAccumulator

    acc = GridStatisticsAccumulator(shape=(2, 2))
    with pytest.raises(ValueError, match="shape mismatch"):
        acc.update(np.zeros((1, 2), dtype=np.float32))


def test_exact_percentiles_matches_numpy() -> None:
    from statistics.accumulator import exact_percentiles

    samples = [np.full((2, 2), float(v), dtype=np.float32) for v in range(1, 7)]
    out = exact_percentiles(samples=samples, percentiles=[10, 50, 90])

    np.testing.assert_allclose(out[10.0], np.full((2, 2), 1.5, dtype=np.float32))
    np.testing.assert_allclose(out[50.0], np.full((2, 2), 3.5, dtype=np.float32))
    np.testing.assert_allclose(out[90.0], np.full((2, 2), 5.5, dtype=np.float32))


def test_p2_quantiles_remain_nan_until_initialized() -> None:
    from statistics.accumulator import GridStatisticsAccumulator

    acc = GridStatisticsAccumulator(shape=(1, 1), percentiles=[50])

    for v in range(1, 5):
        acc.update(np.array([[float(v)]], dtype=np.float32))
        result = acc.finalize()
        assert np.isnan(result.percentiles[50.0][0, 0])

    acc.update(np.array([[5.0]], dtype=np.float32))
    result = acc.finalize()
    assert float(result.percentiles[50.0][0, 0]) == pytest.approx(3.0)


def test_p2_quantiles_produces_reasonable_estimates() -> None:
    from statistics.accumulator import GridStatisticsAccumulator

    acc = GridStatisticsAccumulator(shape=(1, 1), percentiles=[50, 90])
    for v in range(1, 51):
        acc.update(np.array([[float(v)]], dtype=np.float32))

    result = acc.finalize()
    p50 = float(result.percentiles[50.0][0, 0])
    p90 = float(result.percentiles[90.0][0, 0])

    assert 20.0 < p50 < 35.0
    assert 40.0 < p90 <= 50.0


def test_validate_percentiles_rejects_out_of_range() -> None:
    from statistics.accumulator import exact_percentiles

    with pytest.raises(ValueError, match="percentiles must be in"):
        exact_percentiles(samples=[np.zeros((1, 1), dtype=np.float32)], percentiles=[0])


def test_write_exact_percentiles_empty_samples(tmp_path: Path) -> None:
    from statistics.accumulator import exact_percentiles

    out = exact_percentiles(samples=[], percentiles=[50])
    assert 50.0 in out
    assert out[50.0].size == 0
