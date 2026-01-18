from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from models import Base, RiskPOI
from risk_poi_import import import_risk_pois, main


def _count_risk_pois(engine) -> int:
    with Session(engine) as session:
        return int(
            session.execute(select(func.count()).select_from(RiskPOI)).scalar_one()
        )


def test_import_csv_inserts_rows_and_reports_duplicates_and_errors(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    csv_path = tmp_path / "risk_pois.csv"
    csv_path.write_text(
        "\n".join(
            [
                "name,type,lon,lat,alt,weight,tags",
                'poi-a,fire,110,35,,1.0,"hot,smoke"',
                'poi-a,fire,110,35,,1.0,"hot,smoke"',
                "poi-b,fire,200,35,,1.0,[]",
                'poi-c,flood,111,35,12.0,,["river"]',
            ]
        ),
        encoding="utf-8",
    )

    report = import_risk_pois(engine=engine, source=csv_path)

    assert report.total_rows == 4
    assert report.inserted_rows == 2
    assert report.duplicate_count == 1
    assert report.error_count == 1

    duplicate = report.duplicate_rows[0]
    assert duplicate.reason == "duplicate_in_file"
    assert duplicate.row == 3

    error = report.error_rows[0]
    assert error.row == 4
    assert "lon out of range" in error.message

    with Session(engine) as session:
        names = session.scalars(select(RiskPOI.name).order_by(RiskPOI.id)).all()
    assert names == ["poi-a", "poi-c"]


def test_import_geojson_skips_existing_duplicates(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            RiskPOI(name="poi-a", poi_type="fire", lon=110.0, lat=35.0, weight=1.0)
        )
        session.commit()

    geojson_path = tmp_path / "risk_pois.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [110.0, 35.0]},
                        "properties": {"name": "poi-a", "type": "fire"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [111.0, 35.0, 12.0],
                        },
                        "properties": {
                            "name": "poi-b",
                            "type": "flood",
                            "tags": ["river"],
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0, 0], [1, 1]],
                        },
                        "properties": {"name": "bad", "type": "fire"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = import_risk_pois(engine=engine, source=geojson_path)

    assert report.total_rows == 3
    assert report.inserted_rows == 1
    assert report.duplicate_count == 1
    assert report.error_count == 1

    assert report.duplicate_rows[0].reason == "duplicate_in_db"
    assert report.duplicate_rows[0].row == 1
    assert report.error_rows[0].row == 3

    assert _count_risk_pois(engine) == 2


def test_import_supports_at_least_1000_points(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    csv_path = tmp_path / "bulk.csv"
    rows = ["name,type,lon,lat,weight"]
    for idx in range(1000):
        rows.append(f"poi-{idx},fire,{110.0 + idx * 0.0001},{35.0 + idx * 0.0001},1.0")
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    report = import_risk_pois(engine=engine, source=csv_path)
    assert report.inserted_rows == 1000
    assert report.error_count == 0
    assert report.duplicate_count == 0
    assert _count_risk_pois(engine) == 1000


def test_main_emits_json_report_without_touching_db(tmp_path: Path, capsys) -> None:
    csv_path = tmp_path / "dry_run.csv"
    csv_path.write_text(
        "\n".join(
            [
                "name,type,lon,lat",
                "poi-a,fire,110,35",
                "poi-a,fire,110,35",
                "bad,fire,0,91",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            str(csv_path),
            "--database-url",
            "sqlite+pysqlite:///:memory:",
            "--dry-run",
            "--no-dedupe-existing",
        ]
    )
    assert exit_code == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["summary"]["total_rows"] == 3
    assert payload["summary"]["duplicate_rows"] == 1
    assert payload["summary"]["error_rows"] == 1


def test_strict_mode_prevents_inserts(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    csv_path = tmp_path / "strict.csv"
    csv_path.write_text(
        "\n".join(["name,type,lon,lat", "bad,fire,0,91", "poi-a,fire,110,35"]),
        encoding="utf-8",
    )

    report = import_risk_pois(engine=engine, source=csv_path, strict=True)
    assert report.error_count == 1
    assert report.inserted_rows == 0
    assert _count_risk_pois(engine) == 0
