from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from digital_earth_config.local_data import LocalDataPaths

LocalDataKind = Literal["cldas", "ecmwf", "town_forecast"]


def _format_time_iso(dt: datetime) -> str:
    value = dt.astimezone(timezone.utc).isoformat()
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    return value


class LocalFileIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LocalDataKind
    path: str
    relative_path: str
    size: int
    mtime_ns: int
    time: Optional[str] = None
    variable: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path", "relative_path", mode="before")
    @classmethod
    def _normalize_paths(cls, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        return value


class LocalFileIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str
    root_dir: str
    items: list[LocalFileIndexItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "LocalFileIndex":
        if self.schema_version != 1:
            raise ValueError(
                f"Unsupported local index schema_version={self.schema_version}"
            )
        return self


_CLDAS_RE: Final[re.Pattern[str]] = re.compile(
    r"^CHINA_WEST_(?P<resolution>[0-9]+P[0-9]+)_HOR-(?P<var>[A-Za-z0-9]+)-(?P<ts>\d{10})\.nc$",
    re.IGNORECASE,
)


def index_cldas_file(path: Path, *, root_dir: Path) -> Optional[LocalFileIndexItem]:
    match = _CLDAS_RE.match(path.name)
    if not match:
        return None

    ts = match.group("ts")
    try:
        dt = datetime.strptime(ts, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    try:
        relative_path = str(path.resolve().relative_to(root_dir.resolve()))
    except ValueError:
        relative_path = str(path.resolve())
    stat = path.stat()
    resolution = match.group("resolution").upper()
    variable = match.group("var").upper()

    return LocalFileIndexItem(
        kind="cldas",
        path=str(path.resolve()),
        relative_path=relative_path,
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        time=_format_time_iso(dt),
        variable=variable,
        meta={"resolution": resolution, "timestamp": ts},
    )


_ECMWF_RE: Final[re.Pattern[str]] = re.compile(
    r"^W_NAFP_C_ECMF_(?P<file_ts>\d{14})_P_C1D(?P<c1d>\d{17})\.(?P<ext>grib2?|GRIB2?)$",
)


def _parse_ecmwf_valid_time(*, year: int, value: str) -> Optional[datetime]:
    if len(value) != 7 or not value.isdigit():
        return None
    month = int(value[0:2])
    day = int(value[2:4])
    hour = int(value[4:6])
    minute_tens = int(value[6])
    minute = minute_tens * 10
    if minute_tens < 0 or minute_tens > 5:
        return None
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None


def index_ecmwf_file(path: Path, *, root_dir: Path) -> Optional[LocalFileIndexItem]:
    match = _ECMWF_RE.match(path.name)
    if not match:
        return None

    file_ts = match.group("file_ts")
    c1d = match.group("c1d")

    try:
        file_dt = datetime.strptime(file_ts, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None

    init_token = c1d[:8]
    valid_token = c1d[8:-2]
    subset = c1d[-2:]
    try:
        init_dt = datetime.strptime(
            f"{file_dt.year}{init_token}", "%Y%m%d%H%M"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    valid_dt = _parse_ecmwf_valid_time(year=file_dt.year, value=valid_token)
    if valid_dt is None:
        return None

    if valid_dt < init_dt:
        try:
            valid_dt = valid_dt.replace(year=valid_dt.year + 1)
        except ValueError:
            valid_dt = valid_dt + timedelta(days=365)

    lead_hours = int(round((valid_dt - init_dt).total_seconds() / 3600))

    try:
        relative_path = str(path.resolve().relative_to(root_dir.resolve()))
    except ValueError:
        relative_path = str(path.resolve())
    stat = path.stat()

    return LocalFileIndexItem(
        kind="ecmwf",
        path=str(path.resolve()),
        relative_path=relative_path,
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        time=_format_time_iso(valid_dt),
        variable=None,
        meta={
            "file_timestamp": file_ts,
            "file_time": _format_time_iso(file_dt),
            "init_time": _format_time_iso(init_dt),
            "valid_time": _format_time_iso(valid_dt),
            "lead_hours": lead_hours,
            "subset": subset,
            "c1d": c1d,
        },
    )


_TOWN_FORECAST_RE: Final[re.Pattern[str]] = re.compile(
    r"^Z_SEVP_C_BABJ_(?P<file_ts>\d{14})_P_RFFC-(?P<product>[A-Za-z0-9]+)-(?P<valid>\d{12})-(?P<tail>\d+)\.(?P<ext>TXT|txt)$"
)


def index_town_forecast_file(
    path: Path, *, root_dir: Path
) -> Optional[LocalFileIndexItem]:
    match = _TOWN_FORECAST_RE.match(path.name)
    if not match:
        return None

    file_ts = match.group("file_ts")
    valid_ts = match.group("valid")
    product = match.group("product").upper()
    tail = match.group("tail")

    try:
        file_dt = datetime.strptime(file_ts, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        valid_dt = datetime.strptime(valid_ts, "%Y%m%d%H%M").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None

    try:
        relative_path = str(path.resolve().relative_to(root_dir.resolve()))
    except ValueError:
        relative_path = str(path.resolve())
    stat = path.stat()

    return LocalFileIndexItem(
        kind="town_forecast",
        path=str(path.resolve()),
        relative_path=relative_path,
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        time=_format_time_iso(valid_dt),
        variable=product,
        meta={
            "product": product,
            "file_timestamp": file_ts,
            "file_time": _format_time_iso(file_dt),
            "valid_timestamp": valid_ts,
            "valid_time": _format_time_iso(valid_dt),
            "tail": tail,
        },
    )


def index_discovered_file(
    *, kind: LocalDataKind, path: Path, root_dir: Path
) -> Optional[LocalFileIndexItem]:
    if kind == "cldas":
        return index_cldas_file(path, root_dir=root_dir)
    if kind == "ecmwf":
        return index_ecmwf_file(path, root_dir=root_dir)
    if kind == "town_forecast":
        return index_town_forecast_file(path, root_dir=root_dir)
    return None


def build_local_file_index(
    discovered: list[tuple[LocalDataKind, Path]], *, root_dir: Path
) -> LocalFileIndex:
    items: list[LocalFileIndexItem] = []
    for kind, path in discovered:
        try:
            item = index_discovered_file(kind=kind, path=path, root_dir=root_dir)
        except FileNotFoundError:
            continue
        if item is not None:
            items.append(item)

    items.sort(
        key=lambda it: (it.kind, it.variable or "", it.time or "", it.relative_path)
    )
    return LocalFileIndex(
        generated_at=_format_time_iso(datetime.now(timezone.utc)),
        root_dir=str(root_dir.resolve()),
        items=items,
    )


def build_local_file_index_from_config(
    paths: LocalDataPaths, *, discovered: list[tuple[LocalDataKind, Path]]
) -> LocalFileIndex:
    return build_local_file_index(discovered, root_dir=paths.root_dir)
