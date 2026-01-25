from __future__ import annotations

from pathlib import Path

import pytest


def _load_script_module(monkeypatch: pytest.MonkeyPatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import batch_generate_multilevel_tiles as script  # noqa: E402

    return script


def test_parse_formats_dedupes_and_lowercases(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _load_script_module(monkeypatch)
    assert script._parse_formats([" PNG,webp", "webp", "", "png"]) == ("png", "webp")


def test_parse_levels_dedupes_and_ignores_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script_module(monkeypatch)
    assert script._parse_levels(["", "  ", "850", "850", " 850 "]) == ("850",)


def test_is_surface_level(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _load_script_module(monkeypatch)
    assert script._is_surface_level("sfc") is True
    assert script._is_surface_level(" surface ") is True
    assert script._is_surface_level("850") is False


def test_message_valid_time(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _load_script_module(monkeypatch)
    dt = script._message_valid_time({"validityDate": 20260101, "validityTime": 300})
    assert dt.isoformat() == "2026-01-01T03:00:00+00:00"

    with pytest.raises(ValueError, match="validityDate"):
        script._message_valid_time({"validityTime": 0})


def test_expand_inputs_glob(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = _load_script_module(monkeypatch)
    (tmp_path / "a.grib").write_bytes(b"fake")
    (tmp_path / "b.grib").write_bytes(b"fake")

    out = script._expand_inputs([str(tmp_path / "*.grib")])
    assert [path.name for path in out] == ["a.grib", "b.grib"]
