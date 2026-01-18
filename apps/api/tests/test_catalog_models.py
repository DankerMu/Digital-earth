from __future__ import annotations

from sqlalchemy import create_engine, inspect

from models import Base


def test_catalog_models_define_expected_tables() -> None:
    tables = Base.metadata.tables
    assert set(tables) >= {"ecmwf_runs", "ecmwf_times", "ecmwf_assets"}

    assert set(tables["ecmwf_runs"].columns.keys()) >= {
        "id",
        "run_time",
        "status",
        "created_at",
    }
    assert set(tables["ecmwf_times"].columns.keys()) >= {
        "id",
        "run_id",
        "valid_time",
        "created_at",
    }
    assert set(tables["ecmwf_assets"].columns.keys()) >= {
        "id",
        "run_id",
        "time_id",
        "variable",
        "level",
        "status",
        "version",
        "path",
    }


def test_catalog_models_create_indexes_and_constraints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)

    run_indexes = {idx["name"]: idx for idx in inspector.get_indexes("ecmwf_runs")}
    assert "ix_ecmwf_runs_run_time" in run_indexes
    assert run_indexes["ix_ecmwf_runs_run_time"]["column_names"] == ["run_time"]
    assert bool(run_indexes["ix_ecmwf_runs_run_time"]["unique"]) is True

    time_indexes = {idx["name"]: idx for idx in inspector.get_indexes("ecmwf_times")}
    assert "ix_ecmwf_times_valid_time" in time_indexes
    assert time_indexes["ix_ecmwf_times_valid_time"]["column_names"] == ["valid_time"]

    time_unique = {uc["name"]: uc for uc in inspector.get_unique_constraints("ecmwf_times")}
    assert "uq_ecmwf_times_run_valid" in time_unique
    assert time_unique["uq_ecmwf_times_run_valid"]["column_names"] == [
        "run_id",
        "valid_time",
    ]

    asset_unique = {
        uc["name"]: uc for uc in inspector.get_unique_constraints("ecmwf_assets")
    }
    assert "uq_ecmwf_assets_identity" in asset_unique
