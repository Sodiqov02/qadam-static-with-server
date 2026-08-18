from __future__ import annotations

import json
import base64
import os
from pathlib import Path
import sys
import tempfile


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def main() -> None:
    finding = "atomic upload behavior"
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'atomic.db').as_posix()}"
            os.environ["ADMIN_SECRET"] = "atomic_upload_regression_secret"
            os.environ["UPLOADS_DIR"] = str(root / "uploads")
            os.environ["MENU_IMAGES_DIR"] = str(root / "menu_images")

            import src.api_app as api_app

            destination = root / "destination.bin"
            destination.write_bytes(b"old")
            events: list[object] = []
            original_named_temporary_file = api_app.tempfile.NamedTemporaryFile
            original_fsync = api_app.os.fsync
            original_replace = api_app.os.replace

            def tracked_temp(*args, **kwargs):
                events.append(("temp_dir", Path(kwargs["dir"])))
                return original_named_temporary_file(*args, **kwargs)

            def tracked_fsync(fd):
                events.append("fsync")
                return original_fsync(fd)

            def tracked_replace(source, target):
                events.append(("replace", Path(source).read_bytes(), Path(target), Path(target).read_bytes()))
                return original_replace(source, target)

            api_app.tempfile.NamedTemporaryFile = tracked_temp
            api_app.os.fsync = tracked_fsync
            api_app.os.replace = tracked_replace
            try:
                api_app._atomic_write(destination, b"complete")
            finally:
                api_app.tempfile.NamedTemporaryFile = original_named_temporary_file
                api_app.os.fsync = original_fsync
                api_app.os.replace = original_replace

            require("successful atomic write", destination.read_bytes() == b"complete")
            require("temp created beside destination", events[0] == ("temp_dir", destination.parent), events)
            fsync_index = events.index("fsync")
            replace_index = next(index for index, event in enumerate(events) if isinstance(event, tuple) and event[0] == "replace")
            require("fsync happens before replace", fsync_index < replace_index, events)
            require("replace receives complete data", events[replace_index][1] == b"complete", events)
            require("destination remains old until replace", events[replace_index][3] == b"old", events)
            require("successful write leaves no temp", not list(root.glob(".upload-*.tmp")))

            destination.write_bytes(b"stable")
            failure_events: list[str] = []

            def failing_replace(source, target):
                failure_events.append("replace")
                raise OSError("forced replace failure")

            api_app.os.replace = failing_replace
            try:
                try:
                    api_app._atomic_write(destination, b"new-data")
                except OSError:
                    pass
                else:
                    raise AssertionError("replace failure was not propagated")
            finally:
                api_app.os.replace = original_replace
            require("old destination survives replace failure", destination.read_bytes() == b"stable")
            require("replace attempted after full write", failure_events == ["replace"], failure_events)
            require("replace failure temp removed", not list(root.glob(".upload-*.tmp")))

            destination.write_bytes(b"stable-again")

            class PartialWrite:
                def __init__(self, handle):
                    self._handle = handle
                    self.name = handle.name

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    self._handle.close()

                def write(self, data):
                    self._handle.write(data[:2])
                    raise OSError("forced partial write")

                def flush(self):
                    return self._handle.flush()

                def fileno(self):
                    return self._handle.fileno()

            def partial_temp(*args, **kwargs):
                return PartialWrite(original_named_temporary_file(*args, **kwargs))

            api_app.tempfile.NamedTemporaryFile = partial_temp
            try:
                try:
                    api_app._atomic_write(destination, b"partial-data")
                except OSError:
                    pass
                else:
                    raise AssertionError("partial write failure was not propagated")
            finally:
                api_app.tempfile.NamedTemporaryFile = original_named_temporary_file
            require("partial write does not alter destination", destination.read_bytes() == b"stable-again")
            require("partial write temp removed", not list(root.glob(".upload-*.tmp")))
            require(
                "managed upload traversal remains rejected",
                api_app._managed_upload_file("/uploads/demo/hero/%2e%2e/private", "demo", "hero") is None,
            )

            from fastapi.testclient import TestClient
            from src.db import engine
            from src.store import bootstrap_tenant, get_tenant_by_slug

            with TestClient(api_app.app, raise_server_exceptions=False) as client:
                bootstrap_tenant(
                    slug="atomic",
                    name="Atomic",
                    admin_chat_id=1,
                    bot_token=None,
                    bot_username=None,
                    bot_enabled=False,
                    features={"plan": "vip", "hero_image": "/uploads/atomic/hero/original.png"},
                    category_titles=["Main"],
                )
                original_atomic_write = api_app._atomic_write

                def fail_upload(_destination, _data):
                    raise OSError("forced upload write failure")

                api_app._atomic_write = fail_upload
                try:
                    valid_png = base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                    )
                    response = client.post(
                        "/t/atomic/api/admin/upload",
                        headers={"x-admin-token": "atomic_upload_regression_secret"},
                        data={"type": "hero"},
                        files={"file": ("hero.png", valid_png, "image/png")},
                    )
                finally:
                    api_app._atomic_write = original_atomic_write
                require("write failure returns server error", response.status_code == 500, response.text)
                tenant = get_tenant_by_slug("atomic")
                require(
                    "write failure does not update DB image URL",
                    tenant.features.get("hero_image") == "/uploads/atomic/hero/original.png",
                    tenant.features,
                )
            engine.dispose()
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": finding, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "finding": finding, "issues": []}, indent=2))


if __name__ == "__main__":
    main()
