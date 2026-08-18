from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import scripts.ux_smoke_public_menu as smoke


def main() -> None:
    issues: list[str] = []
    calls: list[str] = []
    original_argv = sys.argv
    originals = {
        "run_smoke": smoke.run_smoke,
        "run_branding_smoke": smoke.run_branding_smoke,
        "run_order_flow_smoke": smoke.run_order_flow_smoke,
    }

    def expect(label: str, condition: bool) -> None:
        if not condition:
            issues.append(label)

    def runner(name: str, result: list[str] | None = None):
        def run(_url, _screenshots):
            calls.append(name)
            return list(result or [])

        return run

    try:
        smoke.run_smoke = runner("default")
        smoke.run_branding_smoke = runner("branding")
        smoke.run_order_flow_smoke = runner("order-flow")

        sys.argv = ["ux_smoke_public_menu.py", "--branding"]
        calls.clear()
        expect("one flag runs one suite", smoke.main() == 0 and calls == ["branding"])

        sys.argv = ["ux_smoke_public_menu.py", "--branding", "--order-flow"]
        calls.clear()
        expect(
            "multiple flags run all selected suites",
            smoke.main() == 0 and calls == ["branding", "order-flow"],
        )

        smoke.run_order_flow_smoke = runner("order-flow", ["forced failure"])
        calls.clear()
        expect(
            "any selected suite failure controls exit code",
            smoke.main() == 1 and calls == ["branding", "order-flow"],
        )

        sys.argv = ["ux_smoke_public_menu.py"]
        calls.clear()
        expect("no flags preserves default suite", smoke.main() == 0 and calls == ["default"])
    finally:
        sys.argv = original_argv
        for name, value in originals.items():
            setattr(smoke, name, value)

    if issues:
        print({"status": "failed", "issues": issues})
        raise SystemExit(1)
    print({"status": "ok", "issues": []})


if __name__ == "__main__":
    main()
