from __future__ import annotations

import argparse
import asyncio
from typing import Optional

from retention import AuditLogger, get_retention_config, run_retention_cleanup
from retention.cleanup import RetentionCleanupResult


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="retention")
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to retention.yaml (defaults to DIGITAL_EARTH_RETENTION_CONFIG / config/retention.yaml).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("cleanup", help="Run a single cleanup pass and exit.")

    run = sub.add_parser("run", help="Run cleanup on a cron schedule (UTC).")
    run.add_argument(
        "--cron",
        default=None,
        help="Override scheduler cron expression (defaults to retention.yaml scheduler.cron).",
    )
    run.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Retry failed cleanup up to N times (defaults to 0).",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    cfg = get_retention_config(args.config_path)
    audit = AuditLogger(log_path=cfg.audit.log_path)

    if args.command == "cleanup":
        run_retention_cleanup(cfg, audit=audit)
        return 0

    if args.command == "run":
        from retention.scheduler import RetentionCleanupScheduler

        cron = (args.cron or cfg.scheduler.cron).strip()
        max_retries = 0 if args.max_retries is None else args.max_retries

        def cleanup() -> RetentionCleanupResult:
            latest_cfg = get_retention_config(args.config_path)
            latest_audit = AuditLogger(log_path=latest_cfg.audit.log_path)
            return run_retention_cleanup(latest_cfg, audit=latest_audit)

        scheduler = RetentionCleanupScheduler(
            cron=cron,
            cleanup=cleanup,
            max_retries=max_retries,
        )
        asyncio.run(scheduler.run_forever())
        return 0

    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
