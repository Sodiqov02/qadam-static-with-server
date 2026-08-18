import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


BASE_DIR = Path(__file__).resolve().parents[1]
DEV_ADMIN_SECRET = "dev_only_admin_secret"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _run_config_import(env_updates: dict[str, str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in ("ADMIN_SECRET", "APP_ENV", "ENVIRONMENT", "QADAM_ENV", "ENV", "RAILWAY_ENVIRONMENT"):
        env.pop(key, None)
    env.update(env_updates)
    env["PYTHONPATH"] = str(BASE_DIR)
    return subprocess.run(
        [sys.executable, "-c", "import src.config; print(src.config.ADMIN_SECRET)"],
        cwd=str(BASE_DIR),
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )


def main() -> None:
    issues: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sanity.db"
        common_env = {
            "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "API_BASE_URL": "http://127.0.0.1:8000",
        }

        unsafe_cases = {
            "missing": {**common_env, "RAILWAY_ENVIRONMENT": "production"},
            "empty": {**common_env, "RAILWAY_ENVIRONMENT": "production", "ADMIN_SECRET": ""},
            "change_me": {**common_env, "RAILWAY_ENVIRONMENT": "production", "ADMIN_SECRET": "change_me"},
            "dev_fallback": {
                **common_env,
                "RAILWAY_ENVIRONMENT": "production",
                "ADMIN_SECRET": DEV_ADMIN_SECRET,
            },
            "example_placeholder": {
                **common_env,
                "APP_ENV": "production",
                "ADMIN_SECRET": "replace_with_strong_random_secret",
            },
            "too_short": {
                **common_env,
                "APP_ENV": "production",
                "ADMIN_SECRET": "short",
            },
        }
        for label, env_updates in unsafe_cases.items():
            rejected = _run_config_import(env_updates)
            if rejected.returncode == 0:
                issues.append(f"production config accepted unsafe ADMIN_SECRET case: {label}")

        local = _run_config_import({**common_env, "ADMIN_SECRET": ""})
        if local.returncode != 0 or local.stdout.strip() != DEV_ADMIN_SECRET:
            issues.append("local config did not use the explicit dev fallback")

        production = _run_config_import(
            {
                **common_env,
                "APP_ENV": "production",
                "ADMIN_SECRET": "production_sanity_secret_value",
            }
        )
        if production.returncode != 0:
            issues.append("production config rejected a non-placeholder strong ADMIN_SECRET")

        os.environ.update({**common_env, "ADMIN_SECRET": DEV_ADMIN_SECRET})
        from src.api_app import app
        from src.db import engine

        try:
            with TestClient(app) as client:
                response = client.get("/healthz")
                if response.status_code != 200:
                    issues.append(f"/healthz returned {response.status_code}")
                elif response.json() != {"status": "ok"}:
                    issues.append(f"/healthz returned unexpected body: {response.text}")
                if logging.getLogger("src.notifier").disabled:
                    issues.append("startup migrations disabled the notifier logger")
        finally:
            engine.dispose()

    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
