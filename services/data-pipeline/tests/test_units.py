from __future__ import annotations

import numpy as np
import pytest


def test_kelvin_to_celsius_scalar() -> None:
    from units.converter import kelvin_to_celsius

    assert kelvin_to_celsius(273.15) == pytest.approx(0.0)
    assert kelvin_to_celsius(0.0) == pytest.approx(-273.15)


def test_meters_to_mm_scalar() -> None:
    from units.converter import meters_to_mm

    assert meters_to_mm(0.0) == pytest.approx(0.0)
    assert meters_to_mm(0.001) == pytest.approx(1.0)


def test_converter_functions_handle_numpy_arrays() -> None:
    from units.converter import kelvin_to_celsius, meters_to_mm

    temps_k = np.array([273.15, 274.15], dtype=np.float32)
    out_c = kelvin_to_celsius(temps_k)
    assert np.allclose(out_c, np.array([0.0, 1.0], dtype=np.float32), atol=1e-3)

    precip_m = np.array([0.0, 0.01], dtype=np.float32)
    out_mm = meters_to_mm(precip_m)
    assert np.allclose(out_mm, np.array([0.0, 10.0], dtype=np.float32), atol=1e-6)
