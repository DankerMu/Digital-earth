from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class TownForecastParseError(RuntimeError):
    pass


_TOWN_FORECAST_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^Z_SEVP_C_BABJ_(?P<file_ts>\d{14})_P_RFFC-(?P<product>[A-Za-z0-9]+)-(?P<valid>\d{12})-(?P<tail>\d+)\.(?P<ext>TXT|txt)$"
)

_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[,\s]+")

_WEATHER_CODE: Final[dict[int, str]] = {
    0: "晴",
    1: "多云",
    2: "阴",
    3: "阵雨",
    4: "雷阵雨",
    5: "雷阵雨（冰雹）",
    6: "雨夹雪",
    7: "小雨",
    8: "中雨",
    9: "大雨",
    10: "暴雨",
    11: "大暴雨",
    12: "特大暴雨",
    13: "阵雪",
    14: "小雪",
    15: "中雪",
    16: "大雪",
    17: "暴雪",
    18: "雾",
    19: "冻雨",
    20: "沙尘暴",
    21: "小到中雨",
    22: "中到大雨",
    23: "大到暴雨",
    24: "暴雨到大暴雨",
    25: "大暴雨到特大暴雨",
    26: "小到中雪",
    27: "中到大雪",
    28: "大到暴雪",
    29: "浮尘",
    30: "扬沙",
    31: "强沙尘暴",
    53: "霾",
}

_WIND_DIR: Final[dict[int, str]] = {
    1: "东北风",
    2: "东风",
    3: "东南风",
    4: "南风",
    5: "西南风",
    6: "西风",
    7: "西北风",
    8: "北风",
    9: "不定向风",
}

_WIND_SCALE: Final[dict[int, str]] = {
    0: "1～2级",
    1: "3～4级",
    2: "4～5级",
    3: "5～6级",
    4: "6～7级",
    5: "7～8级",
    6: "8～9级",
    7: "9～10级",
    8: "10～11级",
    9: "11～12级",
}


def _format_time_iso(dt: datetime) -> str:
    value = dt.astimezone(timezone.utc).isoformat()
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    return value


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_tail_periods(
    tail: str,
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    if len(tail) < 4 or not tail.isdigit():
        return None, None, None
    step = int(tail[-2:])
    max_lead = int(tail[:-2])
    if step <= 0:
        return None, None, None
    if max_lead % step != 0:
        return max_lead, step, None
    return max_lead, step, max_lead // step


def _coerce_float(value: str) -> Optional[float]:
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed == 999.9:
        return None
    return parsed


def _coerce_int_code(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    return int(value)


class TownForecastLead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_hours: int
    values: list[Optional[float]]
    weather_code: Optional[int] = None
    weather: Optional[str] = None
    wind_dir_code: Optional[int] = None
    wind_dir: Optional[str] = None
    wind_scale_code: Optional[int] = None
    wind_scale: Optional[str] = None
    temp_high_c: Optional[float] = None
    temp_low_c: Optional[float] = None
    temp_c: Optional[float] = None
    summary: Optional[str] = None


class TownForecastStation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str
    lon: Optional[float] = None
    lat: Optional[float] = None
    altitude: Optional[float] = None
    extra: list[str] = Field(default_factory=list)
    leads: list[TownForecastLead] = Field(default_factory=list)


class TownForecastFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    product: str
    issue_time: Optional[str] = None
    valid_time: Optional[str] = None
    station_count: int
    max_lead_hours: Optional[int] = None
    lead_step_hours: Optional[int] = None
    raw_header: list[str] = Field(default_factory=list)
    stations: list[TownForecastStation] = Field(default_factory=list)


def _parse_lead_line(line: str) -> TownForecastLead:
    parts = [p for p in _SPLIT_RE.split(line.strip()) if p]
    if len(parts) < 2:
        raise TownForecastParseError(f"Invalid forecast line: {line!r}")

    try:
        lead_hours = int(float(parts[0]))
    except ValueError as exc:
        raise TownForecastParseError(f"Invalid lead hour value: {parts[0]!r}") from exc

    values = [_coerce_float(value) for value in parts[1:]]

    weather_code = _coerce_int_code(values[18]) if len(values) > 18 else None
    wind_dir_code = _coerce_int_code(values[19]) if len(values) > 19 else None
    wind_scale_code = _coerce_int_code(values[20]) if len(values) > 20 else None

    temp_high_c = values[10] if len(values) > 10 else None
    temp_low_c = values[11] if len(values) > 11 else None
    temp_c = values[0] if len(values) > 0 else None

    weather = _WEATHER_CODE.get(weather_code) if weather_code is not None else None
    wind_dir = _WIND_DIR.get(wind_dir_code) if wind_dir_code is not None else None
    wind_scale = (
        _WIND_SCALE.get(wind_scale_code) if wind_scale_code is not None else None
    )

    summary_parts: list[str] = []
    if weather:
        summary_parts.append(weather)
    if temp_high_c is not None and temp_low_c is not None:
        summary_parts.append(f"{temp_low_c:g}～{temp_high_c:g}℃")
    elif temp_c is not None:
        summary_parts.append(f"{temp_c:g}℃")

    if wind_dir_code == 0 and wind_scale_code == 0:
        summary_parts.append("微风")
    else:
        if wind_dir:
            summary_parts.append(wind_dir)
        if wind_scale:
            summary_parts.append(wind_scale)

    summary = " ".join(summary_parts).strip() if summary_parts else None

    return TownForecastLead(
        lead_hours=lead_hours,
        values=values,
        weather_code=weather_code,
        weather=weather,
        wind_dir_code=wind_dir_code,
        wind_dir=wind_dir,
        wind_scale_code=wind_scale_code,
        wind_scale=wind_scale,
        temp_high_c=temp_high_c,
        temp_low_c=temp_low_c,
        temp_c=temp_c,
        summary=summary,
    )


def parse_town_forecast_file(
    source_path: Union[str, Path],
    *,
    station_ids: Optional[set[str]] = None,
    max_stations: Optional[int] = None,
) -> TownForecastFile:
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"Town forecast TXT file not found: {path}")

    match = _TOWN_FORECAST_NAME_RE.match(path.name)
    product = match.group("product").upper() if match else None
    valid_ts = match.group("valid") if match else None
    tail = match.group("tail") if match else ""

    max_lead, step, expected_periods = _parse_tail_periods(tail)

    lines = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
    if len(lines) < 5:
        raise TownForecastParseError(f"Town forecast file too short: {path.name}")

    product_line_idx = None
    product_line_re = re.compile(r"^(?P<prod>[A-Za-z0-9]+)\s+(?P<ts>\d{10})$")
    for idx, line in enumerate(lines[:10]):
        if product_line_re.match(line):
            product_line_idx = idx
            break
    if product_line_idx is None:
        raise TownForecastParseError(f"Missing product header line in {path.name}")

    prod_match = product_line_re.match(lines[product_line_idx])
    assert prod_match is not None
    header_product = prod_match.group("prod").upper()
    issue_ts = prod_match.group("ts")
    try:
        issue_dt = datetime.strptime(issue_ts, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise TownForecastParseError(
            f"Invalid issue time in header: {issue_ts}"
        ) from exc

    count_line_idx = product_line_idx + 1
    try:
        station_count = int(lines[count_line_idx])
    except ValueError as exc:
        raise TownForecastParseError(
            f"Invalid station count line: {lines[count_line_idx]!r}"
        ) from exc

    valid_time_iso: Optional[str] = None
    if valid_ts:
        try:
            valid_dt = datetime.strptime(valid_ts, "%Y%m%d%H%M").replace(
                tzinfo=timezone.utc
            )
            valid_time_iso = _format_time_iso(valid_dt)
        except ValueError:
            valid_time_iso = None

    issue_time_iso = _format_time_iso(issue_dt)

    if product is None:
        product = header_product
    if product != header_product:
        product = header_product

    cursor = count_line_idx + 1
    stations: list[TownForecastStation] = []

    def should_keep_station(station_id: str) -> bool:
        if station_ids is None:
            return True
        return station_id in station_ids

    for _ in range(station_count):
        if cursor >= len(lines):
            break
        station_line = lines[cursor]
        cursor += 1

        parts = [p for p in _SPLIT_RE.split(station_line) if p]
        if not parts:
            continue
        station_id = parts[0][:5]

        lon = _coerce_float(parts[1]) if len(parts) > 1 else None
        lat = _coerce_float(parts[2]) if len(parts) > 2 else None
        alt = _coerce_float(parts[3]) if len(parts) > 3 else None
        extra = parts[4:]

        leads: list[TownForecastLead] = []
        if expected_periods:
            for _lead in range(expected_periods):
                if cursor >= len(lines):
                    break
                leads.append(_parse_lead_line(lines[cursor]))
                cursor += 1
        else:
            while cursor < len(lines):
                peek = lines[cursor]
                first = _SPLIT_RE.split(peek.strip(), maxsplit=1)[0]
                if len(first) >= 5 and first.isdigit():
                    break
                if len(first) == 5 and not first.isdigit():
                    break
                if len(first) > 3:
                    break
                if not first.isdigit():
                    break
                leads.append(_parse_lead_line(lines[cursor]))
                cursor += 1

        if not should_keep_station(station_id):
            continue

        stations.append(
            TownForecastStation(
                station_id=station_id,
                lon=lon,
                lat=lat,
                altitude=alt,
                extra=extra,
                leads=leads,
            )
        )

        if max_stations is not None and len(stations) >= max_stations:
            break

    return TownForecastFile(
        product=product,
        issue_time=issue_time_iso,
        valid_time=valid_time_iso,
        station_count=station_count,
        max_lead_hours=max_lead,
        lead_step_hours=step,
        raw_header=lines[: count_line_idx + 1],
        stations=stations,
    )
