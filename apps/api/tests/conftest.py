import sys
from pathlib import Path
import inspect
from typing import Any

API_SRC = Path(__file__).resolve().parents[1] / "src"
TESTS_SRC = Path(__file__).resolve().parent
CONFIG_SRC = Path(__file__).resolve().parents[3] / "packages" / "config" / "src"
SHARED_SRC = Path(__file__).resolve().parents[3] / "packages" / "shared" / "src"
PIPELINE_SRC = (
    Path(__file__).resolve().parents[3] / "services" / "data-pipeline" / "src"
)

sys.path.insert(0, str(SHARED_SRC))
sys.path.insert(0, str(CONFIG_SRC))
sys.path.insert(0, str(PIPELINE_SRC))
sys.path.insert(0, str(API_SRC))
sys.path.insert(0, str(TESTS_SRC))


def _patch_testclient_client_kw() -> None:
    try:
        from starlette.testclient import TestClient as StarletteTestClient
    except Exception:
        return

    try:
        sig = inspect.signature(StarletteTestClient.__init__)
    except (TypeError, ValueError):
        return

    if "client" in sig.parameters:
        return

    original_init = StarletteTestClient.__init__

    def patched_init(self: Any, *args: Any, client: Any = None, **kwargs: Any) -> None:
        if "client" in kwargs:
            client = kwargs.pop("client")

        original_init(self, *args, **kwargs)

        if client is None:
            return

        try:
            host, port = client
            client_value = [str(host), int(port)]
        except Exception:
            return

        transport = getattr(self, "_transport", None)
        original_app = getattr(transport, "app", None) if transport is not None else None
        if original_app is None:
            return

        async def app_with_client(scope: Any, receive: Any, send: Any) -> None:
            if isinstance(scope, dict):
                scope["client"] = client_value
            await original_app(scope, receive, send)

        transport.app = app_with_client

    StarletteTestClient.__init__ = patched_init  # type: ignore[assignment]


_patch_testclient_client_kw()
