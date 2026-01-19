from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON: {path}: {exc}") from exc


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _metric(summary: dict[str, Any], name: str) -> dict[str, Any]:
    metrics = summary.get("metrics") or {}
    m = metrics.get(name)
    if isinstance(m, dict):
        return m
    return {}


def _metric_value(summary: dict[str, Any], name: str, key: str) -> Optional[float]:
    m = _metric(summary, name)
    values = m.get("values") or {}
    return _as_float(values.get(key))


def _duration_seconds(summary: dict[str, Any]) -> Optional[float]:
    state = summary.get("state") or {}

    ms = _as_float(state.get("testRunDurationMs"))
    if ms is not None and ms >= 0:
        return ms / 1000.0

    duration = state.get("testRunDuration")
    if isinstance(duration, str) and duration:
        return _parse_k6_duration_seconds(duration)

    count = _metric_value(summary, "http_reqs", "count")
    rate = _metric_value(summary, "http_reqs", "rate")
    if count is not None and rate is not None and rate > 0:
        return count / rate

    return None


def _parse_k6_duration_seconds(raw: str) -> Optional[float]:
    text = raw.strip()
    if not text:
        return None

    units = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    total = 0.0
    buf = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isdigit() or ch == ".":
            buf += ch
            i += 1
            continue

        if not buf:
            return None

        if text.startswith("ms", i):
            unit = "ms"
            i += 2
        else:
            unit = ch
            i += 1

        multiplier = units.get(unit)
        if multiplier is None:
            return None

        try:
            total += float(buf) * multiplier
        except ValueError:
            return None
        buf = ""

    if buf:
        return None
    return total


def _bytes_per_second(summary: dict[str, Any], metric_name: str) -> Optional[float]:
    rate = _metric_value(summary, metric_name, "rate")
    if rate is not None and rate >= 0:
        return rate
    total = _metric_value(summary, metric_name, "count")
    duration = _duration_seconds(summary)
    if total is None or duration is None or duration <= 0:
        return None
    return total / duration


def _format_percent(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _format_ms(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f} ms"


def _format_number(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 100:
        return f"{value:.0f}"
    return f"{value:.2f}"


def _format_bytes(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    v = float(value)
    unit = "B"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(v) < 1024.0:
            break
        v /= 1024.0
    if unit == "B":
        return f"{v:.0f} {unit}"
    return f"{v:.2f} {unit}"


def _format_mbps(bytes_per_second: Optional[float]) -> str:
    if bytes_per_second is None:
        return "n/a"
    mbps = (bytes_per_second * 8.0) / 1_000_000.0
    return f"{mbps:.2f} Mbps"


@dataclass(frozen=True)
class DerivedMetrics:
    duration_seconds: Optional[float]
    total_requests: Optional[float]
    rps: Optional[float]
    error_rate: Optional[float]
    latency_avg_ms: Optional[float]
    latency_p95_ms: Optional[float]
    latency_p99_ms: Optional[float]
    cdn_hits: Optional[float]
    cdn_misses: Optional[float]
    cdn_unknown: Optional[float]
    cdn_hit_rate: Optional[float]
    cdn_miss_rate: Optional[float]
    bandwidth_client_bytes_per_s: Optional[float]
    bandwidth_origin_bytes_per_s: Optional[float]
    bandwidth_origin_conservative_bytes_per_s: Optional[float]


def _compute_derived(summary: dict[str, Any]) -> DerivedMetrics:
    duration_s = _duration_seconds(summary)

    total_reqs = _metric_value(summary, "http_reqs", "count")
    rps = _metric_value(summary, "http_reqs", "rate")
    error_rate = _metric_value(summary, "http_req_failed", "rate")

    latency_avg = _metric_value(summary, "http_req_duration", "avg")
    latency_p95 = _metric_value(summary, "http_req_duration", "p(95)")
    latency_p99 = _metric_value(summary, "http_req_duration", "p(99)")

    hits = _metric_value(summary, "cdn_hits", "count")
    misses = _metric_value(summary, "cdn_misses", "count")
    unknown = _metric_value(summary, "cdn_unknown", "count")

    denom = None
    hit_rate = None
    miss_rate = None
    if hits is not None and misses is not None:
        denom = hits + misses
        if denom > 0:
            hit_rate = hits / denom
            miss_rate = misses / denom

    client_bps = _bytes_per_second(summary, "bytes_total")
    origin_bps = _bytes_per_second(summary, "bytes_miss")

    conservative_origin_bps = None
    miss_bps = _bytes_per_second(summary, "bytes_miss")
    unknown_bps = _bytes_per_second(summary, "bytes_unknown")
    if miss_bps is not None and unknown_bps is not None:
        conservative_origin_bps = miss_bps + unknown_bps
    elif miss_bps is not None:
        conservative_origin_bps = miss_bps
    elif unknown_bps is not None:
        conservative_origin_bps = unknown_bps

    return DerivedMetrics(
        duration_seconds=duration_s,
        total_requests=total_reqs,
        rps=rps,
        error_rate=error_rate,
        latency_avg_ms=latency_avg,
        latency_p95_ms=latency_p95,
        latency_p99_ms=latency_p99,
        cdn_hits=hits,
        cdn_misses=misses,
        cdn_unknown=unknown,
        cdn_hit_rate=hit_rate,
        cdn_miss_rate=miss_rate,
        bandwidth_client_bytes_per_s=client_bps,
        bandwidth_origin_bytes_per_s=origin_bps,
        bandwidth_origin_conservative_bytes_per_s=conservative_origin_bps,
    )


def _recommendations(
    derived: DerivedMetrics, config: dict[str, Any], scenario: str
) -> dict[str, Any]:
    recs: list[str] = []

    if derived.error_rate is not None and derived.error_rate > 0.01:
        recs.append(
            f"Error rate {_format_percent(derived.error_rate)} is high; reduce load and verify origin health (CPU/mem/IO), upstream timeouts, and CDN/origin TLS."
        )

    if derived.latency_p95_ms is not None and derived.latency_p95_ms > 1500:
        recs.append(
            f"P95 latency {_format_ms(derived.latency_p95_ms)} is high; consider increasing CDN cache TTL, enabling compression, and optimizing origin response time."
        )

    if derived.cdn_hit_rate is None:
        recs.append(
            "CDN hit rate could not be computed (missing cdn_hits/cdn_misses). Ensure CDN cache headers are present (e.g. cf-cache-status/x-cache) and rerun."
        )
    else:
        if derived.cdn_hit_rate < 0.8:
            recs.append(
                f"CDN hit rate {_format_percent(derived.cdn_hit_rate)} is low; review cache key (query params, headers), and raise TTL for immutable/versioned tiles."
            )
        elif derived.cdn_hit_rate < 0.95:
            recs.append(
                f"CDN hit rate {_format_percent(derived.cdn_hit_rate)} is moderate; consider pre-warming popular tiles and tuning TTL/stale-while-revalidate."
            )

    if derived.cdn_unknown is not None and derived.cdn_unknown > 0:
        recs.append(
            "Some responses could not be classified as HIT/MISS; configure config.cdn.hit_header_name + hit/miss values for your CDN for more accurate origin estimates."
        )

    cache_cfg = config.get("cache") or {}
    immutable = bool(cache_cfg.get("content_is_immutable"))
    update_interval_s = _as_float(cache_cfg.get("update_interval_seconds"))

    ttl_s = _as_float(cache_cfg.get("suggested_ttl_seconds"))
    if ttl_s is None:
        if immutable:
            ttl_s = 7 * 24 * 3600
        elif update_interval_s is not None and update_interval_s > 0:
            ttl_s = max(60.0, min(update_interval_s * 0.8, 24 * 3600))
        else:
            ttl_s = 300.0

    swr_s = _as_float(cache_cfg.get("stale_while_revalidate_seconds"))
    if swr_s is None:
        swr_s = 300.0 if immutable else 60.0

    sie_s = _as_float(cache_cfg.get("stale_if_error_seconds"))
    if sie_s is None:
        sie_s = 24 * 3600.0

    cache_control = (
        f"public, max-age={int(ttl_s)}, s-maxage={int(ttl_s)}, "
        f"stale-while-revalidate={int(swr_s)}, stale-if-error={int(sie_s)}"
    )

    edge_limit_rps = None
    if derived.rps is not None and derived.rps > 0:
        edge_limit_rps = int(math.ceil(derived.rps * 1.5))

    origin_fetch_rps = None
    if derived.rps is not None and derived.cdn_miss_rate is not None:
        origin_fetch_rps = derived.rps * derived.cdn_miss_rate

    per_ip_rps = _as_float((config.get("rate_limit") or {}).get("per_ip_rps"))
    if per_ip_rps is None:
        if derived.rps is None:
            per_ip_rps = 30.0
        elif derived.rps < 500:
            per_ip_rps = 30.0
        elif derived.rps < 2000:
            per_ip_rps = 50.0
        else:
            per_ip_rps = 100.0

    params: dict[str, Any] = {
        "scenario": scenario,
        "cache_control_suggestion": cache_control,
        "edge_rate_limit_rps_suggestion": edge_limit_rps,
        "edge_rate_limit_burst_suggestion": (
            edge_limit_rps * 2 if edge_limit_rps else None
        ),
        "edge_per_ip_rps_suggestion": int(per_ip_rps),
        "edge_per_ip_burst_suggestion": int(per_ip_rps * 2),
        "origin_fetch_rps_estimate": origin_fetch_rps,
    }

    return {"notes": recs, "suggested_params": params}


def _render_markdown(
    meta: dict[str, Any], derived: DerivedMetrics, recs: dict[str, Any]
) -> str:
    lines: list[str] = []
    lines.append("# Load Test Report")
    lines.append("")
    lines.append("## Meta")
    lines.append("")
    for k in ("run_id", "env", "scenario", "base_url", "tile_path_template"):
        if k in meta:
            lines.append(f"- {k}: `{meta[k]}`")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- duration: {_format_number(derived.duration_seconds)} s")
    lines.append(f"- requests: {_format_number(derived.total_requests)}")
    lines.append(f"- rps: {_format_number(derived.rps)}")
    lines.append(f"- error_rate: {_format_percent(derived.error_rate)}")
    lines.append(
        f"- latency: avg {_format_ms(derived.latency_avg_ms)}, p95 {_format_ms(derived.latency_p95_ms)}, p99 {_format_ms(derived.latency_p99_ms)}"
    )
    lines.append(
        f"- cdn hit rate: {_format_percent(derived.cdn_hit_rate)} (unknown: {_format_number(derived.cdn_unknown)})"
    )
    lines.append(
        f"- bandwidth: client {_format_mbps(derived.bandwidth_client_bytes_per_s)}, origin(est) {_format_mbps(derived.bandwidth_origin_bytes_per_s)}"
    )
    lines.append(
        f"- origin bandwidth conservative(est): {_format_mbps(derived.bandwidth_origin_conservative_bytes_per_s)}"
    )
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    notes = recs.get("notes") or []
    if notes:
        for n in notes:
            lines.append(f"- {n}")
    else:
        lines.append(
            "- No issues detected by heuristics; verify with monitoring (CDN dashboards + origin metrics)."
        )
    lines.append("")

    lines.append("## Suggested Params")
    lines.append("")
    params = recs.get("suggested_params") or {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, float):
            lines.append(f"- {k}: `{v:.2f}`")
        else:
            lines.append(f"- {k}: `{v}`")
    lines.append("")

    return "\n".join(lines)


def _render_html(
    meta: dict[str, Any], derived: DerivedMetrics, recs: dict[str, Any]
) -> str:
    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    cards = [
        ("Env", esc(meta.get("env"))),
        ("Scenario", esc(meta.get("scenario"))),
        ("Base URL", f"<code>{esc(meta.get('base_url'))}</code>"),
        ("Path Template", f"<code>{esc(meta.get('tile_path_template'))}</code>"),
        ("Requests", esc(_format_number(derived.total_requests))),
        ("RPS", esc(_format_number(derived.rps))),
        ("Error Rate", esc(_format_percent(derived.error_rate))),
        ("P95 Latency", esc(_format_ms(derived.latency_p95_ms))),
        ("CDN Hit Rate", esc(_format_percent(derived.cdn_hit_rate))),
        ("Origin BW (est)", esc(_format_mbps(derived.bandwidth_origin_bytes_per_s))),
        (
            "Origin BW (cons.)",
            esc(_format_mbps(derived.bandwidth_origin_conservative_bytes_per_s)),
        ),
    ]

    notes = recs.get("notes") or []
    notes_html = (
        "<ul>" + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>"
        if notes
        else "<p>No issues detected by heuristics; verify with monitoring.</p>"
    )

    params = recs.get("suggested_params") or {}
    params_rows = "".join(
        f"<tr><td><code>{esc(k)}</code></td><td><code>{esc(v)}</code></td></tr>"
        for k, v in params.items()
        if v is not None
    )

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8" />',
            f"<title>{esc(meta.get('run_id', 'loadtest'))}</title>",
            "<style>",
            "body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }",
            "table { border-collapse: collapse; width: 100%; }",
            "th, td { border: 1px solid #ddd; padding: 8px; vertical-align: top; }",
            "th { background: #f6f6f6; text-align: left; }",
            "code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }",
            ".summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }",
            ".card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fff; }",
            ".card h3 { margin: 0 0 8px 0; font-size: 14px; }",
            ".card p { margin: 0; font-size: 14px; word-break: break-all; }",
            "</style>",
            "</head>",
            "<body>",
            "<h1>Load Test Report</h1>",
            f"<p><code>{esc(meta.get('run_id'))}</code></p>",
            '<div class="summary">',
            *[
                f'<div class="card"><h3>{esc(title)}</h3><p>{value}</p></div>'
                for title, value in cards
            ],
            "</div>",
            "<h2>Recommendations</h2>",
            notes_html,
            "<h2>Suggested Params</h2>",
            "<table>",
            "<thead><tr><th>Key</th><th>Value</th></tr></thead>",
            "<tbody>",
            params_rows,
            "</tbody>",
            "</table>",
            "</body></html>",
        ]
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python infra/loadtest/report/generate_report.py",
        description="Generate JSON/HTML/Markdown report from k6 --summary-export output.",
    )
    parser.add_argument(
        "--summary", required=True, help="Path to k6 summary-export JSON."
    )
    parser.add_argument(
        "--config", required=True, help="Path to load test env config JSON."
    )
    parser.add_argument(
        "--scenario", required=True, help="Scenario name (ramp|sustained|spike)."
    )
    parser.add_argument("--out-dir", required=True, help="Output directory.")
    parser.add_argument("--run-id", default=None, help="Optional run identifier.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    summary_path = Path(args.summary).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    summary = _read_json(summary_path)
    config = _read_json(config_path)

    run_id = (
        str(args.run_id)
        if args.run_id
        else dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    env_name = str(config.get("name") or "unknown")
    base_url = str(config.get("base_url") or "")
    tile_path_template = str((config.get("tile") or {}).get("path_template") or "")

    derived = _compute_derived(summary)
    recs = _recommendations(derived, config, scenario=str(args.scenario))

    meta = {
        "run_id": run_id,
        "env": env_name,
        "scenario": str(args.scenario),
        "base_url": base_url,
        "tile_path_template": tile_path_template,
        "summary_json": str(summary_path),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
    }

    report = {
        "meta": meta,
        "derived": derived.__dict__,
        "recommendations": recs,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / "report.json", json.dumps(report, ensure_ascii=False, indent=2))
    _write(out_dir / "report.md", _render_markdown(meta, derived, recs))
    _write(out_dir / "report.html", _render_html(meta, derived, recs))

    print(json.dumps({"out_dir": str(out_dir), "run_id": run_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
