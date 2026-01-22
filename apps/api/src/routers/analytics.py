from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import db
from digital_earth_config.settings import _resolve_config_dir
from models import BiasTileSet, HistoricalStatisticArtifact

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(dt: datetime) -> str:
    parsed = dt
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TileTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str
    legend: str


class HistoricalStatisticItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    variable: str
    window_kind: str
    window_key: str
    version: str
    window_start: str
    window_end: str
    samples: int
    dataset_path: str
    metadata_path: str
    tiles: dict[str, TileTemplate] = Field(default_factory=dict)


class HistoricalStatisticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str = Field(default_factory=_utc_now_iso)
    items: list[HistoricalStatisticItem] = Field(default_factory=list)


def _stats_tile_prefix(
    *, source: str, variable: str, stat: str, version: str, window_key: str
) -> str:
    src = (source or "").strip()
    var = (variable or "").strip().lower()
    stat_key = (stat or "").strip().lower()
    ver = (version or "").strip()
    key = (window_key or "").strip()
    return f"statistics/{src}/{var}/{stat_key}/{ver}/{key}"


def _stats_tile_templates(
    *, source: str, variable: str, version: str, window_key: str, fmt: str
) -> dict[str, TileTemplate]:
    fmt_norm = (fmt or "").strip().lower() or "png"
    if fmt_norm not in {"png", "webp"}:
        raise HTTPException(status_code=400, detail="Unsupported format")

    tiles: dict[str, TileTemplate] = {}
    for stat in ("sum", "mean"):
        prefix = _stats_tile_prefix(
            source=source,
            variable=variable,
            stat=stat,
            version=version,
            window_key=window_key,
        )
        layer = "/".join(prefix.split("/")[:4])
        tiles[stat] = TileTemplate(
            template=f"/api/v1/tiles/{prefix}/{{z}}/{{x}}/{{y}}.{fmt_norm}",
            legend=f"/api/v1/tiles/{layer}/legend.json",
        )
    return tiles


@router.get("/historical/statistics", response_model=HistoricalStatisticsResponse)
def list_historical_statistics(
    source: Optional[str] = Query(default=None),
    variable: Optional[str] = Query(default=None),
    window_kind: Optional[str] = Query(default=None),
    version: Optional[str] = Query(default=None),
    fmt: str = Query(default="png"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> HistoricalStatisticsResponse:
    stmt = select(HistoricalStatisticArtifact).order_by(
        desc(HistoricalStatisticArtifact.window_end)
    )
    if source:
        stmt = stmt.where(HistoricalStatisticArtifact.source == source.strip())
    if variable:
        stmt = stmt.where(HistoricalStatisticArtifact.variable == variable.strip())
    if window_kind:
        stmt = stmt.where(
            HistoricalStatisticArtifact.window_kind == window_kind.strip()
        )
    if version:
        stmt = stmt.where(HistoricalStatisticArtifact.version == version.strip())
    stmt = stmt.limit(limit).offset(offset)

    try:
        with Session(db.get_engine()) as session:
            rows = session.execute(stmt).scalars().all()
    except SQLAlchemyError as exc:
        logger.error("historical_statistics_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    items: list[HistoricalStatisticItem] = []
    for row in rows:
        items.append(
            HistoricalStatisticItem(
                source=row.source,
                variable=row.variable,
                window_kind=row.window_kind,
                window_key=row.window_key,
                version=row.version,
                window_start=_iso(row.window_start),
                window_end=_iso(row.window_end),
                samples=int(row.samples),
                dataset_path=row.dataset_path,
                metadata_path=row.metadata_path,
                tiles=_stats_tile_templates(
                    source=row.source,
                    variable=row.variable,
                    version=row.version,
                    window_key=row.window_key,
                    fmt=fmt,
                ),
            )
        )

    return HistoricalStatisticsResponse(items=items)


class BiasTileSetItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: str
    time_key: str
    level_key: str
    min_zoom: int
    max_zoom: int
    formats: list[str] = Field(default_factory=list)
    tile: TileTemplate


class BiasTileSetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str = Field(default_factory=_utc_now_iso)
    items: list[BiasTileSetItem] = Field(default_factory=list)


def _bias_tile_template(
    *, layer: str, time_key: str, level_key: str, fmt: str
) -> TileTemplate:
    fmt_norm = (fmt or "").strip().lower() or "png"
    if fmt_norm not in {"png", "webp"}:
        raise HTTPException(status_code=400, detail="Unsupported format")
    return TileTemplate(
        template=f"/api/v1/tiles/{layer}/{time_key}/{level_key}/{{z}}/{{x}}/{{y}}.{fmt_norm}",
        legend=f"/api/v1/tiles/{layer}/legend.json",
    )


@router.get("/bias/tile-sets", response_model=BiasTileSetsResponse)
def list_bias_tile_sets(
    layer: Optional[str] = Query(default=None),
    fmt: str = Query(default="png"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BiasTileSetsResponse:
    stmt = select(BiasTileSet).order_by(desc(BiasTileSet.time_key))
    if layer:
        stmt = stmt.where(BiasTileSet.layer == layer.strip())
    stmt = stmt.limit(limit).offset(offset)

    try:
        with Session(db.get_engine()) as session:
            rows = session.execute(stmt).scalars().all()
    except SQLAlchemyError as exc:
        logger.error("bias_tile_sets_db_error", extra={"error": str(exc)})
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    items: list[BiasTileSetItem] = []
    for row in rows:
        items.append(
            BiasTileSetItem(
                layer=row.layer,
                time_key=row.time_key,
                level_key=row.level_key,
                min_zoom=int(row.min_zoom),
                max_zoom=int(row.max_zoom),
                formats=list(row.formats or []),
                tile=_bias_tile_template(
                    layer=row.layer,
                    time_key=row.time_key,
                    level_key=row.level_key,
                    fmt=fmt,
                ),
            )
        )
    return BiasTileSetsResponse(items=items)


class SnowStatisticsDefinitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str = Field(default_factory=_utc_now_iso)
    definition: dict[str, Any] = Field(default_factory=dict)


@router.get("/snow/definition", response_model=SnowStatisticsDefinitionResponse)
def get_snow_statistics_definition() -> SnowStatisticsDefinitionResponse:
    config_dir = _resolve_config_dir()
    path = Path(config_dir) / "snow-statistics.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="snow-statistics.yaml not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail="Failed to load snow statistics"
        ) from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Invalid snow statistics config")
    payload = json.loads(json.dumps(data, ensure_ascii=False, default=str))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Invalid snow statistics config")
    return SnowStatisticsDefinitionResponse(definition=payload)
