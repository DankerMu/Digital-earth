from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from scheduler.runs import IngestRun, get_ingest_run_store

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str = Field(default_factory=_utc_now_iso)
    items: list[IngestRun] = Field(default_factory=list)


@router.get("/runs", response_model=IngestRunsResponse)
def list_ingest_runs(
    limit: int = Query(default=20, ge=1, le=200),
) -> IngestRunsResponse:
    store = get_ingest_run_store()
    return IngestRunsResponse(items=store.list_runs(limit=limit))
