from __future__ import annotations

import argparse
import base64
import html
import io
import json
import random
from dataclasses import asdict, dataclass, field
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np
from PIL import Image


class TileQualityValidationError(RuntimeError):
    pass


TileIssueSeverity = str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_hex_rgb(value: str) -> tuple[int, int, int]:
    normalized = (value or "").strip()
    if not normalized.startswith("#") or len(normalized) != 7:
        raise ValueError(f"Invalid hex color: {value!r}")
    try:
        r = int(normalized[1:3], 16)
        g = int(normalized[3:5], 16)
        b = int(normalized[5:7], 16)
    except ValueError as exc:
        raise ValueError(f"Invalid hex color: {value!r}") from exc
    return r, g, b


def parse_time_key(value: str) -> Optional[datetime]:
    raw = (value or "").strip()
    if raw == "" or raw.lower() == "unknown":
        return None

    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%MZ"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TileRef:
    run_id: str
    layer: str
    time: str
    level: Optional[str]
    zoom: int
    x: int
    y: int
    format: str
    relative_path: str
    absolute_path: str
    legend_path: Optional[str]

    def key(self) -> str:
        level = self.level or "-"
        return f"{self.run_id}/{self.layer}/{level}/{self.time}/{self.zoom}/{self.x}/{self.y}.{self.format}"


@dataclass(frozen=True)
class LegendSummary:
    path: str
    type: Optional[str]
    unit: Optional[str]
    min: Optional[float]
    max: Optional[float]
    version: Optional[str]
    stops: Sequence[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TileMetrics:
    width: int
    height: int
    total_pixels: int
    transparent_pixels: int
    transparent_fraction: float
    opaque_pixels: int
    extreme_min_fraction: Optional[float]
    extreme_max_fraction: Optional[float]
    min_color_rgb: Optional[tuple[int, int, int]]
    max_color_rgb: Optional[tuple[int, int, int]]


@dataclass(frozen=True)
class TileIssue:
    severity: TileIssueSeverity
    code: str
    message: str


@dataclass(frozen=True)
class TileSample:
    tile: TileRef
    metrics: TileMetrics
    issues: Sequence[TileIssue]
    preview_png_base64: Optional[str] = None


@dataclass(frozen=True)
class ValidationReport:
    run_id: str
    tiles_root: str
    started_at: str
    finished_at: str
    sample_size_requested: int
    sample_size_actual: int
    seed: int
    thresholds: dict[str, float]
    legends: Sequence[LegendSummary]
    samples: Sequence[TileSample]
    issues_total: int
    issues_by_code: dict[str, int]


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _load_legend_summary(path: Path) -> LegendSummary:
    legend = _read_json(path)
    stops_raw = legend.get("colorStops")
    if stops_raw is None:
        stops_raw = legend.get("stops")
    stops = stops_raw if isinstance(stops_raw, list) else []
    return LegendSummary(
        path=str(path),
        type=legend.get("type") if isinstance(legend.get("type"), str) else None,
        unit=legend.get("unit") if isinstance(legend.get("unit"), str) else None,
        min=float(legend["min"])
        if isinstance(legend.get("min"), (int, float))
        else None,
        max=float(legend["max"])
        if isinstance(legend.get("max"), (int, float))
        else None,
        version=legend.get("version")
        if isinstance(legend.get("version"), str)
        else None,
        stops=[item for item in stops if isinstance(item, dict)],
    )


def _legend_extreme_colors(
    legend: dict[str, Any],
) -> Optional[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    stops_raw = legend.get("colorStops")
    if stops_raw is None:
        stops_raw = legend.get("stops")
    if not isinstance(stops_raw, list) or len(stops_raw) < 2:
        return None

    stops: list[tuple[float, tuple[int, int, int]]] = []
    for stop in stops_raw:
        if not isinstance(stop, dict):
            continue
        value = stop.get("value")
        color = stop.get("color")
        if not isinstance(value, (int, float)) or not np.isfinite(float(value)):
            continue
        if not isinstance(color, str):
            continue
        stops.append((float(value), _parse_hex_rgb(color)))

    if len(stops) < 2:
        return None
    stops.sort(key=lambda item: item[0])
    return stops[0][1], stops[-1][1]


def _thumbnail_base64(img: Image.Image, *, size: int = 128) -> str:
    rgba = img.convert("RGBA")
    rgba.thumbnail((size, size))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG", optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return encoded


def _parse_tile_relpath(
    rel_path: Path,
    *,
    run_id: str,
    tiles_root: Path,
) -> Optional[TileRef]:
    parts = rel_path.as_posix().split("/")
    if len(parts) < 5:
        return None

    filename = parts[-1]
    if "." not in filename:
        return None
    stem, ext = filename.rsplit(".", 1)
    ext_norm = ext.lower()
    if ext_norm not in {"png", "webp"}:
        return None

    try:
        zoom = int(parts[-3])
        x = int(parts[-2])
        y = int(stem)
    except ValueError:
        return None

    prefix = parts[:-3]
    if not prefix:
        return None

    time_index: Optional[int] = None
    for idx in range(len(prefix) - 1, -1, -1):
        if parse_time_key(prefix[idx]) is not None:
            time_index = idx
            break
    if time_index is None:
        time_index = len(prefix) - 1

    layer_parts = prefix[:time_index]
    if not layer_parts:
        return None
    time_key = prefix[time_index]
    level_parts = prefix[time_index + 1 :]
    level = "/".join(level_parts) if level_parts else None
    layer = "/".join(layer_parts)

    abs_path = (tiles_root / rel_path).resolve()
    return TileRef(
        run_id=run_id,
        layer=layer,
        time=time_key,
        level=level,
        zoom=zoom,
        x=x,
        y=y,
        format=ext_norm,
        relative_path=rel_path.as_posix(),
        absolute_path=str(abs_path),
        legend_path=None,
    )


def _resolve_legend_path(tiles_root: Path, tile: TileRef) -> Optional[Path]:
    layer_dir = tiles_root / tile.layer
    if tile.level:
        candidate = layer_dir / tile.level / "legend.json"
        if candidate.is_file():
            return candidate
    candidate = layer_dir / "legend.json"
    if candidate.is_file():
        return candidate
    return None


def _iter_candidate_tiles(tiles_root: Path) -> Iterable[Path]:
    for path in tiles_root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {".png", ".webp"}:
            continue
        yield path


def _reservoir_sample_paths(
    paths: Iterable[Path], *, sample_size: int, rng: random.Random
) -> list[Path]:
    if sample_size <= 0:
        return []

    sample: list[Path] = []
    seen = 0
    for path in paths:
        seen += 1
        if len(sample) < sample_size:
            sample.append(path)
            continue
        j = rng.randrange(seen)
        if j < sample_size:
            sample[j] = path
    return sample


def _analyze_tile_pixels(
    rgba: np.ndarray,
    *,
    legend: Optional[dict[str, Any]],
) -> TileMetrics:
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise TileQualityValidationError("Expected RGBA pixels array")

    height = int(rgba.shape[0])
    width = int(rgba.shape[1])
    total = width * height
    alpha = rgba[..., 3]
    transparent_mask = alpha == 0
    transparent_pixels = int(np.count_nonzero(transparent_mask))
    opaque_pixels = int(total - transparent_pixels)
    transparent_fraction = float(transparent_pixels / total) if total else 0.0

    extreme_min_fraction: Optional[float] = None
    extreme_max_fraction: Optional[float] = None
    min_rgb: Optional[tuple[int, int, int]] = None
    max_rgb: Optional[tuple[int, int, int]] = None

    if legend is not None and opaque_pixels > 0:
        extremes = _legend_extreme_colors(legend)
        if extremes is not None:
            min_rgb, max_rgb = extremes
            rgb = rgba[..., :3]
            opaque_mask = ~transparent_mask
            min_mask = (
                (rgb[..., 0] == min_rgb[0])
                & (rgb[..., 1] == min_rgb[1])
                & (rgb[..., 2] == min_rgb[2])
                & opaque_mask
            )
            max_mask = (
                (rgb[..., 0] == max_rgb[0])
                & (rgb[..., 1] == max_rgb[1])
                & (rgb[..., 2] == max_rgb[2])
                & opaque_mask
            )
            extreme_min_fraction = float(np.count_nonzero(min_mask) / opaque_pixels)
            extreme_max_fraction = float(np.count_nonzero(max_mask) / opaque_pixels)

    return TileMetrics(
        width=width,
        height=height,
        total_pixels=total,
        transparent_pixels=transparent_pixels,
        transparent_fraction=transparent_fraction,
        opaque_pixels=opaque_pixels,
        extreme_min_fraction=extreme_min_fraction,
        extreme_max_fraction=extreme_max_fraction,
        min_color_rgb=min_rgb,
        max_color_rgb=max_rgb,
    )


def validate_tile(
    tiles_root: Path,
    tile_path: Path,
    *,
    run_id: str,
    blank_transparent_fraction: float = 0.9,
    extreme_color_fraction: float = 0.05,
    embed_preview: bool = True,
    preview_size: int = 128,
    run_time: Optional[datetime] = None,
) -> TileSample:
    rel = tile_path.resolve().relative_to(tiles_root.resolve())
    tile = _parse_tile_relpath(rel, run_id=run_id, tiles_root=tiles_root)
    if tile is None:
        raise TileQualityValidationError(f"Unrecognized tile path: {tile_path}")

    legend_path = _resolve_legend_path(tiles_root, tile)
    legend_payload: Optional[dict[str, Any]] = None
    legend_summary: Optional[LegendSummary] = None
    legend_error: Optional[str] = None
    if legend_path is not None:
        try:
            legend_payload = _read_json(legend_path)
            legend_summary = _load_legend_summary(legend_path)
        except Exception as exc:  # noqa: BLE001
            legend_payload = None
            legend_summary = None
            legend_error = str(exc)

    tile = replace(tile, legend_path=str(legend_path) if legend_path else None)

    img = Image.open(tile_path)
    try:
        rgba = np.asarray(img.convert("RGBA"))
        metrics = _analyze_tile_pixels(rgba, legend=legend_payload)
        preview = _thumbnail_base64(img, size=preview_size) if embed_preview else None
    finally:
        img.close()

    issues: list[TileIssue] = []
    if metrics.transparent_fraction > blank_transparent_fraction:
        issues.append(
            TileIssue(
                severity="error",
                code="blank_tile",
                message=(
                    f"Transparent fraction {metrics.transparent_fraction:.3f} exceeds "
                    f"threshold {blank_transparent_fraction:.3f}"
                ),
            )
        )

    if legend_path is None:
        issues.append(
            TileIssue(
                severity="error",
                code="missing_legend",
                message="Legend file not found for tile layer/level",
            )
        )
    elif legend_payload is None:
        issues.append(
            TileIssue(
                severity="error",
                code="invalid_legend",
                message=f"Legend file could not be parsed: {legend_error or 'unknown error'}",
            )
        )

    if legend_summary is not None and legend_payload is not None:
        if legend_summary.min is None or legend_summary.max is None:
            issues.append(
                TileIssue(
                    severity="warning",
                    code="legend_missing_thresholds",
                    message="Legend missing min/max thresholds",
                )
            )

    if (
        metrics.extreme_min_fraction is not None
        and metrics.extreme_max_fraction is not None
        and metrics.opaque_pixels > 0
    ):
        if metrics.extreme_min_fraction > extreme_color_fraction:
            issues.append(
                TileIssue(
                    severity="warning",
                    code="extreme_min_saturation",
                    message=(
                        f"Min-color pixels fraction {metrics.extreme_min_fraction:.3f} exceeds "
                        f"threshold {extreme_color_fraction:.3f}"
                    ),
                )
            )
        if metrics.extreme_max_fraction > extreme_color_fraction:
            issues.append(
                TileIssue(
                    severity="warning",
                    code="extreme_max_saturation",
                    message=(
                        f"Max-color pixels fraction {metrics.extreme_max_fraction:.3f} exceeds "
                        f"threshold {extreme_color_fraction:.3f}"
                    ),
                )
            )

    tile_time = parse_time_key(tile.time)
    if tile_time is None:
        issues.append(
            TileIssue(
                severity="warning",
                code="time_unparseable",
                message=f"Tile time key is not parseable: {tile.time!r}",
            )
        )
    elif run_time is not None:
        lead_hours = (tile_time - run_time).total_seconds() / 3600.0
        if lead_hours < 0:
            issues.append(
                TileIssue(
                    severity="error",
                    code="time_before_run",
                    message=f"Tile valid time is before run time (lead={lead_hours:.2f}h)",
                )
            )
        else:
            expected = None
            if tile.layer.startswith("ecmwf/"):
                try:
                    from ecmwf.config import get_ecmwf_variables_config

                    expected = set(get_ecmwf_variables_config().lead_times_hours())
                except Exception:  # noqa: BLE001
                    expected = None
            if expected is not None:
                lead_int = int(round(lead_hours))
                if abs(lead_hours - lead_int) > 1e-6 or lead_int not in expected:
                    issues.append(
                        TileIssue(
                            severity="warning",
                            code="lead_time_unexpected",
                            message=f"Lead time {lead_hours:.2f}h not in configured lead_time_hours",
                        )
                    )

    return TileSample(
        tile=tile,
        metrics=metrics,
        issues=issues,
        preview_png_base64=preview,
    )


def validate_tiles(
    tiles_root: str | Path,
    *,
    run_id: Optional[str] = None,
    run_time: Optional[datetime] = None,
    sample_size: int = 20,
    seed: int = 0,
    blank_transparent_fraction: float = 0.9,
    extreme_color_fraction: float = 0.05,
    embed_previews: bool = True,
    preview_size: int = 128,
) -> ValidationReport:
    root = Path(tiles_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"tiles_root not found: {root}")

    resolved_run_id = (run_id or "").strip() or root.name
    rng = random.Random(int(seed))

    started = _utc_now()
    sampled_paths = _reservoir_sample_paths(
        _iter_candidate_tiles(root), sample_size=sample_size, rng=rng
    )
    samples: list[TileSample] = []
    legends_by_path: dict[str, LegendSummary] = {}

    for tile_path in sampled_paths:
        sample = validate_tile(
            root,
            tile_path,
            run_id=resolved_run_id,
            blank_transparent_fraction=float(blank_transparent_fraction),
            extreme_color_fraction=float(extreme_color_fraction),
            embed_preview=bool(embed_previews),
            preview_size=int(preview_size),
            run_time=run_time,
        )
        samples.append(sample)
        if sample.tile.legend_path and sample.tile.legend_path not in legends_by_path:
            try:
                legends_by_path[sample.tile.legend_path] = _load_legend_summary(
                    Path(sample.tile.legend_path)
                )
            except Exception:  # noqa: BLE001
                legends_by_path[sample.tile.legend_path] = LegendSummary(
                    path=sample.tile.legend_path,
                    type=None,
                    unit=None,
                    min=None,
                    max=None,
                    version=None,
                    stops=[],
                )

    issues_total = sum(len(sample.issues) for sample in samples)
    issues_by_code: dict[str, int] = {}
    for sample in samples:
        for issue in sample.issues:
            issues_by_code[issue.code] = issues_by_code.get(issue.code, 0) + 1

    finished = _utc_now()
    return ValidationReport(
        run_id=resolved_run_id,
        tiles_root=str(root),
        started_at=_serialize_dt(started) or "",
        finished_at=_serialize_dt(finished) or "",
        sample_size_requested=int(sample_size),
        sample_size_actual=len(samples),
        seed=int(seed),
        thresholds={
            "blank_transparent_fraction": float(blank_transparent_fraction),
            "extreme_color_fraction": float(extreme_color_fraction),
        },
        legends=sorted(legends_by_path.values(), key=lambda item: item.path),
        samples=samples,
        issues_total=issues_total,
        issues_by_code=dict(sorted(issues_by_code.items(), key=lambda item: item[0])),
    )


def report_has_errors(report: ValidationReport) -> bool:
    for sample in report.samples:
        for issue in sample.issues:
            if issue.severity == "error":
                return True
    return False


def report_has_alerts(report: ValidationReport) -> bool:
    return report.issues_total > 0


def should_fail(report: ValidationReport, *, fail_on: str) -> bool:
    normalized = (fail_on or "").strip().lower()
    if normalized in {"none", "never", "false"}:
        return False
    if normalized in {"error", "errors"}:
        return report_has_errors(report)
    if normalized in {"warning", "warnings", "any"}:
        return report_has_alerts(report)
    raise ValueError("fail_on must be one of: none, error, warning, any")


def write_json_report(report: ValidationReport, *, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _legend_preview_base64(
    legend: LegendSummary, *, width: int = 256, height: int = 20
) -> Optional[str]:
    stops_raw = legend.stops
    if not stops_raw or len(stops_raw) < 2:
        return None
    stops: list[tuple[float, tuple[int, int, int]]] = []
    for stop in stops_raw:
        value = stop.get("value")
        color = stop.get("color")
        if not isinstance(value, (int, float)) or not np.isfinite(float(value)):
            continue
        if not isinstance(color, str):
            continue
        stops.append((float(value), _parse_hex_rgb(color)))
    if len(stops) < 2:
        return None
    stops.sort(key=lambda item: item[0])
    values = np.array([item[0] for item in stops], dtype=np.float64)
    colors = np.array([item[1] for item in stops], dtype=np.float64)
    xs = np.linspace(values[0], values[-1], num=int(width), dtype=np.float64)
    idx = np.searchsorted(values, xs, side="right")
    idx = np.clip(idx, 1, len(values) - 1)
    left = idx - 1
    right = idx
    denom = values[right] - values[left]
    denom = np.where(denom == 0.0, 1.0, denom)
    frac = (xs - values[left]) / denom
    frac = np.clip(frac, 0.0, 1.0)[:, None]
    rgb = colors[left] * (1.0 - frac) + colors[right] * frac
    row = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    img_arr = np.tile(row[None, :, :], (int(height), 1, 1))
    img = Image.fromarray(img_arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_html_report(report: ValidationReport) -> str:
    title = f"Tile Quality Report: {report.run_id}"

    rows: list[str] = []
    for sample in report.samples:
        issues = "<br/>".join(
            f"{html.escape(issue.severity)}:{html.escape(issue.code)} - {html.escape(issue.message)}"
            for issue in sample.issues
        )
        preview = (
            f'<img src="data:image/png;base64,{sample.preview_png_base64}" width="96" height="96" />'
            if sample.preview_png_base64
            else ""
        )
        level = sample.tile.level or "-"
        rows.append(
            "<tr>"
            f"<td>{preview}</td>"
            f"<td>{html.escape(sample.tile.layer)}</td>"
            f"<td>{html.escape(level)}</td>"
            f"<td>{html.escape(sample.tile.time)}</td>"
            f"<td>{sample.tile.zoom}</td>"
            f"<td>{sample.tile.x}</td>"
            f"<td>{sample.tile.y}</td>"
            f"<td>{sample.metrics.transparent_fraction:.3f}</td>"
            f"<td>{'' if sample.metrics.extreme_min_fraction is None else f'{sample.metrics.extreme_min_fraction:.3f}'}</td>"
            f"<td>{'' if sample.metrics.extreme_max_fraction is None else f'{sample.metrics.extreme_max_fraction:.3f}'}</td>"
            f"<td><code>{html.escape(sample.tile.relative_path)}</code></td>"
            f"<td>{issues}</td>"
            "</tr>"
        )

    legends_html: list[str] = []
    for legend in report.legends:
        preview = _legend_preview_base64(legend)
        preview_html = (
            f'<img src="data:image/png;base64,{preview}" width="256" height="20" />'
            if preview
            else ""
        )
        legends_html.append(
            "<tr>"
            f"<td><code>{html.escape(legend.path)}</code></td>"
            f"<td>{html.escape(legend.type or '')}</td>"
            f"<td>{html.escape(legend.unit or '')}</td>"
            f"<td>{'' if legend.min is None else legend.min}</td>"
            f"<td>{'' if legend.max is None else legend.max}</td>"
            f"<td><code>{html.escape(legend.version or '')}</code></td>"
            f"<td>{preview_html}</td>"
            "</tr>"
        )

    issues_summary = "".join(
        f"<li><code>{html.escape(code)}</code>: {count}</li>"
        for code, count in report.issues_by_code.items()
    )

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8" />',
            f"<title>{html.escape(title)}</title>",
            "<style>",
            "body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }",
            "table { border-collapse: collapse; width: 100%; }",
            "th, td { border: 1px solid #ddd; padding: 8px; vertical-align: top; }",
            "th { background: #f6f6f6; text-align: left; }",
            "code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }",
            ".summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }",
            ".card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fff; }",
            ".card h3 { margin: 0 0 8px 0; font-size: 14px; }",
            ".card p { margin: 0; font-size: 14px; }",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>{html.escape(title)}</h1>",
            '<div class="summary">',
            '<div class="card"><h3>Tiles Root</h3>'
            f"<p><code>{html.escape(report.tiles_root)}</code></p></div>",
            '<div class="card"><h3>Sample</h3>'
            f"<p>{report.sample_size_actual} / {report.sample_size_requested}</p></div>",
            f'<div class="card"><h3>Issues</h3><p>{report.issues_total}</p></div>',
            f'<div class="card"><h3>Seed</h3><p>{report.seed}</p></div>',
            "</div>",
            "<h2>Issue Summary</h2>",
            f"<ul>{issues_summary}</ul>",
            "<h2>Legends</h2>",
            "<table>",
            "<thead><tr><th>Path</th><th>Type</th><th>Unit</th><th>Min</th><th>Max</th><th>Version</th><th>Preview</th></tr></thead>",
            "<tbody>",
            *legends_html,
            "</tbody></table>",
            "<h2>Sampled Tiles</h2>",
            "<table>",
            "<thead><tr>"
            "<th>Preview</th><th>Layer</th><th>Level</th><th>Time</th>"
            "<th>Z</th><th>X</th><th>Y</th>"
            "<th>Blank%</th><th>Min%</th><th>Max%</th>"
            "<th>Path</th><th>Issues</th>"
            "</tr></thead>",
            "<tbody>",
            *rows,
            "</tbody></table>",
            "</body></html>",
        ]
    )


def write_html_report(report: ValidationReport, *, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(report), encoding="utf-8")
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m validation.tile_quality",
        description="Randomly sample tiles and validate blank ratio, extremes, and time alignment.",
    )
    parser.add_argument("--tiles-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--run-time", default=None, help="Optional run time ISO8601 or YYYYMMDDTHHMMSSZ"
    )
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--blank-threshold", type=float, default=0.9)
    parser.add_argument("--extreme-threshold", type=float, default=0.05)
    parser.add_argument(
        "--fail-on",
        default="warning",
        choices=("none", "error", "warning", "any"),
        help="Exit non-zero when issues are found (default: warning).",
    )
    parser.add_argument("--no-embed-previews", action="store_true")
    parser.add_argument("--preview-size", type=int, default=128)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    run_time = parse_time_key(str(args.run_time)) if args.run_time else None

    report = validate_tiles(
        args.tiles_root,
        run_id=args.run_id,
        run_time=run_time,
        sample_size=int(args.sample_size),
        seed=int(args.seed),
        blank_transparent_fraction=float(args.blank_threshold),
        extreme_color_fraction=float(args.extreme_threshold),
        embed_previews=not bool(args.no_embed_previews),
        preview_size=int(args.preview_size),
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json_report(report, output_path=output_dir / "report.json")
    html_path = write_html_report(report, output_path=output_dir / "report.html")

    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "tiles_root": report.tiles_root,
                "sample_size": report.sample_size_actual,
                "issues_total": report.issues_total,
                "report_json": str(json_path),
                "report_html": str(html_path),
            },
            ensure_ascii=False,
        )
    )

    return 1 if should_fail(report, fail_on=str(args.fail_on)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
