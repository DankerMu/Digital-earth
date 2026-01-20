from __future__ import annotations

import runpy
import sys

import pytest


def test_statistics_main_module_executes_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "python -m statistics",
            "--variable",
            "TMP",
            "--start",
            "2020-01-01T00:00:00Z",
            "--end",
            "2020-02-01T00:00:00Z",
            "--window-kind",
            "monthly",
            "--dry-run",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("statistics.__main__", run_name="__main__")
    assert exc.value.code == 0
