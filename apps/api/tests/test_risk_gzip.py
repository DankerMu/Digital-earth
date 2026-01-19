from __future__ import annotations

from routers.risk import _accepts_gzip


def test_accepts_gzip_parses_qvalues_and_wildcards() -> None:
    assert _accepts_gzip(None) is False
    assert _accepts_gzip(" , , ") is False

    # Malformed params should not crash and should fall back to defaults.
    assert _accepts_gzip("gzip;q") is True
    assert _accepts_gzip("gzip;foo=1") is True

    # Non-numeric q-values should disable gzip.
    assert _accepts_gzip("gzip;q=oops") is False
    assert _accepts_gzip("gzip;q=-1") is False

    # Clamp q-values > 1
    assert _accepts_gzip("gzip;q=2") is True

    # Wildcards should be honored when gzip isn't specified explicitly.
    assert _accepts_gzip("*;q=0.5") is True
    assert _accepts_gzip("*;q=0") is False
