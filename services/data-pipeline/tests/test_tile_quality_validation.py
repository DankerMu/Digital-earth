from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


def _write_legend(path: Path, *, stops: list[dict[str, object]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": "Legend",
        "unit": "unit",
        "type": "gradient",
        "min": -20,
        "max": 40,
        "version": "test",
        "colorStops": stops
        or [
            {"value": -20, "color": "#0000FF"},
            {"value": 0, "color": "#00FF00"},
            {"value": 40, "color": "#FF0000"},
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_png(path: Path, rgba: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(rgba.astype(np.uint8, copy=False), mode="RGBA")
    img.save(path, format="PNG", optimize=True)
    img.close()


def test_parse_time_key_accepts_tile_keys_and_iso() -> None:
    from validation.tile_quality import parse_time_key

    key = parse_time_key("20260101T000000Z")
    assert key == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    iso = parse_time_key("2026-01-01T00:00:00Z")
    assert iso == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    assert parse_time_key("unknown") is None
    assert parse_time_key("not-a-time") is None


def test_parse_time_key_assumes_utc_when_timezone_missing() -> None:
    from validation.tile_quality import parse_time_key

    parsed = parse_time_key("2026-01-01T00:00:00")
    assert parsed == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_hex_rgb_rejects_invalid_values() -> None:
    from validation.tile_quality import _parse_hex_rgb

    with pytest.raises(ValueError, match="Invalid hex color"):
        _parse_hex_rgb("nope")
    with pytest.raises(ValueError, match="Invalid hex color"):
        _parse_hex_rgb("#GGGGGG")


def test_helpers_cover_edge_cases(tmp_path: Path) -> None:
    from validation.tile_quality import (
        _legend_extreme_colors,
        _load_legend_summary,
        _parse_tile_relpath,
        _read_json,
        _serialize_dt,
        _reservoir_sample_paths,
        _analyze_tile_pixels,
        TileRef,
    )

    assert _serialize_dt(None) is None

    non_object = tmp_path / "not_object.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected JSON object"):
        _read_json(non_object)

    legend = tmp_path / "legend.json"
    legend.write_text(
        json.dumps(
            {
                "type": "gradient",
                "stops": [
                    {"value": 0, "color": "#000000"},
                    {"value": 10, "color": "#ffffff"},
                ],
            }
        ),
        encoding="utf-8",
    )
    summary = _load_legend_summary(legend)
    assert len(summary.stops) == 2

    assert _legend_extreme_colors({}) is None
    assert (
        _legend_extreme_colors({"colorStops": [{"value": 0, "color": "#000000"}]})
        is None
    )
    assert (
        _legend_extreme_colors(
            {
                "stops": [
                    "bad",
                    {"value": float("nan"), "color": "#000000"},
                    {"value": 0, "color": 123},
                ]
            }
        )
        is None
    )

    bad_relpaths = [
        Path("a/b/c.png"),  # too short
        Path("a/b/c/d/e"),  # no suffix
        Path("a/b/c/d/e.txt"),  # unsupported extension
        Path("layer/time/z/x/not-int.png"),  # invalid y
        Path("20260101T000000Z/0/0/0.png"),  # missing layer
    ]
    for rel in bad_relpaths:
        assert _parse_tile_relpath(rel, run_id="run", tiles_root=tmp_path) is None

    # Cover reservoir sampling replacement branch.
    rng = random.Random(1)
    paths = [tmp_path / "a.png", tmp_path / "b.png"]
    picked = _reservoir_sample_paths(paths, sample_size=1, rng=rng)
    assert picked == [paths[1]]

    assert _reservoir_sample_paths(paths, sample_size=0, rng=rng) == []

    with pytest.raises(Exception, match="Expected RGBA"):
        _analyze_tile_pixels(np.zeros((1, 1, 3), dtype=np.uint8), legend=None)

    ref = TileRef(
        run_id="run",
        layer="ecmwf/temp",
        time="20260101T000000Z",
        level=None,
        zoom=0,
        x=0,
        y=0,
        format="png",
        relative_path="ecmwf/temp/20260101T000000Z/0/0/0.png",
        absolute_path=str(tmp_path / "x"),
        legend_path=None,
    )
    assert ref.key().startswith("run/ecmwf/temp")


def test_validate_tile_detects_blank_tile(tmp_path: Path) -> None:
    from validation.tile_quality import validate_tile

    tiles_root = tmp_path / "tiles"
    legend_path = tiles_root / "ecmwf" / "temp" / "legend.json"
    _write_legend(legend_path)

    rgba = np.zeros((10, 10, 4), dtype=np.uint8)
    rgba[0, 0] = np.array([0, 255, 0, 255], dtype=np.uint8)

    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    sample = validate_tile(
        tiles_root,
        tile_path,
        run_id="run",
        blank_transparent_fraction=0.9,
        embed_preview=False,
    )
    codes = {issue.code for issue in sample.issues}
    assert "blank_tile" in codes
    assert sample.tile.layer == "ecmwf/temp"
    assert sample.tile.time == "20260101T000000Z"
    assert sample.tile.level == "sfc"


def test_validate_tile_detects_extreme_saturation(tmp_path: Path) -> None:
    from validation.tile_quality import validate_tile

    tiles_root = tmp_path / "tiles"
    _write_legend(tiles_root / "ecmwf" / "temp" / "legend.json")

    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[..., :3] = np.array([255, 0, 0], dtype=np.uint8)
    rgba[..., 3] = 255

    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    sample = validate_tile(
        tiles_root,
        tile_path,
        run_id="run",
        blank_transparent_fraction=0.9,
        extreme_color_fraction=0.05,
        embed_preview=False,
    )
    codes = {issue.code for issue in sample.issues}
    assert "extreme_max_saturation" in codes
    assert sample.metrics.extreme_max_fraction == 1.0


def test_validate_tile_embeds_preview_and_prefers_level_legend(tmp_path: Path) -> None:
    from validation.tile_quality import validate_tile

    tiles_root = tmp_path / "tiles"
    _write_legend(tiles_root / "ecmwf" / "temp" / "legend.json")
    _write_legend(tiles_root / "ecmwf" / "temp" / "sfc" / "legend.json")

    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., :3] = np.array([0, 255, 0], dtype=np.uint8)
    rgba[..., 3] = 255
    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    sample = validate_tile(
        tiles_root,
        tile_path,
        run_id="run",
        embed_preview=True,
        preview_size=64,
    )
    assert sample.preview_png_base64 is not None
    assert sample.tile.legend_path is not None
    assert sample.tile.legend_path.endswith("/ecmwf/temp/sfc/legend.json")


def test_validate_tile_flags_missing_and_invalid_legend(tmp_path: Path) -> None:
    from validation.tile_quality import validate_tile

    tiles_root = tmp_path / "tiles"

    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., 3] = 255

    tile_path = tiles_root / "cldas" / "tmp" / "unknown" / "0" / "0" / "0.png"
    _write_png(tile_path, rgba)

    missing = validate_tile(
        tiles_root,
        tile_path,
        run_id="run",
        embed_preview=False,
    )
    missing_codes = {issue.code for issue in missing.issues}
    assert "missing_legend" in missing_codes
    assert "time_unparseable" in missing_codes

    # Now add an invalid legend file and ensure it is detected.
    legend_path = tiles_root / "cldas" / "tmp" / "legend.json"
    legend_path.parent.mkdir(parents=True, exist_ok=True)
    legend_path.write_text("{", encoding="utf-8")

    invalid = validate_tile(
        tiles_root,
        tile_path,
        run_id="run",
        embed_preview=False,
    )
    invalid_codes = {issue.code for issue in invalid.issues}
    assert "invalid_legend" in invalid_codes


def test_validate_tile_flags_threshold_missing_extreme_min_and_time_before_run(
    tmp_path: Path,
) -> None:
    from validation.tile_quality import parse_time_key, validate_tile

    tiles_root = tmp_path / "tiles"

    legend_path = tiles_root / "ecmwf" / "temp" / "legend.json"
    legend_path.parent.mkdir(parents=True, exist_ok=True)
    legend_path.write_text(
        json.dumps(
            {
                "title": "Legend",
                "unit": "unit",
                "type": "gradient",
                "colorStops": [
                    {"value": -20, "color": "#0000FF"},
                    {"value": 0, "color": "#00FF00"},
                    {"value": 40, "color": "#FF0000"},
                ],
            }
        ),
        encoding="utf-8",
    )

    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[..., :3] = np.array([0, 0, 255], dtype=np.uint8)
    rgba[..., 3] = 255

    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    sample = validate_tile(
        tiles_root,
        tile_path,
        run_id="20260101T030000Z",
        run_time=parse_time_key("20260101T030000Z"),
        extreme_color_fraction=0.05,
        embed_preview=False,
    )
    codes = {issue.code for issue in sample.issues}
    assert "legend_missing_thresholds" in codes
    assert "extreme_min_saturation" in codes
    assert "time_before_run" in codes


def test_validate_tile_checks_time_alignment_when_run_time_provided(
    tmp_path: Path,
) -> None:
    from validation.tile_quality import parse_time_key, validate_tile

    tiles_root = tmp_path / "tiles"
    _write_legend(tiles_root / "ecmwf" / "temp" / "legend.json")

    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., 3] = 255

    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T010000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    sample = validate_tile(
        tiles_root,
        tile_path,
        run_id="20260101T000000Z",
        run_time=parse_time_key("20260101T000000Z"),
        embed_preview=False,
    )
    codes = {issue.code for issue in sample.issues}
    assert "lead_time_unexpected" in codes


def test_validate_tiles_handles_invalid_legend_summary_and_should_fail_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from validation.tile_quality import should_fail, validate_tiles

    tiles_root = tmp_path / "tiles"
    (tiles_root / "ecmwf" / "temp").mkdir(parents=True, exist_ok=True)
    (tiles_root / "ecmwf" / "temp" / "legend.json").write_text("{", encoding="utf-8")

    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    report = validate_tiles(
        tiles_root,
        run_id="run",
        sample_size=10,
        seed=42,
        embed_previews=False,
    )
    assert report.issues_total >= 1
    assert report.issues_by_code.get("invalid_legend") == 1
    assert report.legends and report.legends[0].min is None

    assert should_fail(report, fail_on="none") is False
    assert should_fail(report, fail_on="error") is True
    assert should_fail(report, fail_on="warning") is True
    with pytest.raises(ValueError, match="fail_on"):
        should_fail(report, fail_on="nope")

    # Cover validate_tile's exception path when ECMWF config lookup fails.
    import ecmwf.config as ecmwf_config

    def boom():  # type: ignore[return-value]
        raise RuntimeError("boom")

    monkeypatch.setattr(ecmwf_config, "get_ecmwf_variables_config", boom)
    _ = validate_tiles(
        tiles_root,
        run_id="run",
        run_time=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        sample_size=1,
        seed=0,
        embed_previews=False,
    )


def test_validate_tiles_raises_for_missing_root(tmp_path: Path) -> None:
    from validation.tile_quality import validate_tiles

    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="tiles_root not found"):
        validate_tiles(missing)


def test_legend_preview_base64_handles_invalid_stops() -> None:
    from validation.tile_quality import LegendSummary, _legend_preview_base64

    assert (
        _legend_preview_base64(
            LegendSummary(
                path="legend.json",
                type="gradient",
                unit=None,
                min=None,
                max=None,
                version=None,
                stops=[],
            )
        )
        is None
    )

    assert (
        _legend_preview_base64(
            LegendSummary(
                path="legend.json",
                type="gradient",
                unit=None,
                min=None,
                max=None,
                version=None,
                stops=[
                    {"value": 0, "color": "#000000"},
                    {"value": float("nan"), "color": "#ffffff"},
                    {"value": 10, "color": 123},
                ],
            )
        )
        is None
    )


def test_validate_tiles_writes_reports_and_cli_exits_nonzero(
    tmp_path: Path, capsys
) -> None:
    from validation.tile_quality import main

    tiles_root = tmp_path / "tiles"
    output_dir = tmp_path / "report"
    _write_legend(tiles_root / "ecmwf" / "temp" / "legend.json")

    rgba = np.zeros((10, 10, 4), dtype=np.uint8)
    rgba[0, 0] = np.array([0, 255, 0, 255], dtype=np.uint8)

    tile_path = (
        tiles_root / "ecmwf" / "temp" / "20260101T000000Z" / "sfc" / "0" / "0" / "0.png"
    )
    _write_png(tile_path, rgba)

    exit_code = main(
        [
            "--tiles-root",
            str(tiles_root),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "run",
            "--sample-size",
            "5",
            "--seed",
            "123",
            "--no-embed-previews",
        ]
    )
    assert exit_code == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["issues_total"] >= 1

    assert (output_dir / "report.json").is_file()
    assert (output_dir / "report.html").is_file()
