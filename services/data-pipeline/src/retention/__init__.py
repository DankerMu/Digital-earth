from typing import TYPE_CHECKING, Any

from retention.audit import AuditLogger
from retention.cleanup import RetentionCleanupResult, run_retention_cleanup
from retention.config import (
    RetentionConfig,
    get_retention_config,
    load_retention_config,
)

if TYPE_CHECKING:
    from retention.scheduler import RetentionCleanupScheduler

__all__ = [
    "AuditLogger",
    "RetentionCleanupResult",
    "RetentionCleanupScheduler",
    "RetentionConfig",
    "get_retention_config",
    "load_retention_config",
    "run_retention_cleanup",
]


def __getattr__(name: str) -> Any:
    if name == "RetentionCleanupScheduler":
        from retention.scheduler import RetentionCleanupScheduler

        return RetentionCleanupScheduler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
