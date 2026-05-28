from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


DEFAULT_URL = "http://127.0.0.1:8000/t/demo"
DEFAULT_SCREENSHOT_DIR = Path("screenshots/ux-stabilization")


def assert_true(condition: bool, message: str, issues: list[str]) -> None:
    if not condition:
        issues.append(message)


def visible_box(page: Page, selector: str) -> dict:
    return page.locator(selector).first.evaluate(
        """(el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height,
                visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none"
            };
        }"""
    )


def hidden_box(page: Page, selector: str) -> dict:
    return page.locator(selector).first.evaluate(
        """(el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height,
                opacity: Number(style.opacity),
                visibility: style.visibility,
                pointerEvents: style.pointerEvents
            };
        }"""
    )


def open_cart(page: Page) -> None:
    page.locator("#mobile-cart-toggle").click()
    page.locator("body.cart-open").wait_for(timeout=3000)


def cart_quantity(page: Page) -> str:
    return page.locator(".cart-qty-value").first.inner_text(timeout=3000).strip()


def run_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        page.evaluate(
            """() => {
                const slug = window.location.pathname.split("/")[2] || "";
                if (slug) {
                    window.localStorage.removeItem(`qadam.cart.${decodeURIComponent(slug)}`);
                }
            }"""
        )
        page.reload(wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        page.screenshot(path=screenshot_dir / "phase4-mobile-initial.png", full_page=True)

        metrics = page.evaluate(
            """() => ({
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                filters: document.querySelectorAll(".menu-filter-pill").length,
                cards: document.querySelectorAll(".menu-card").length,
                addButtons: document.querySelectorAll(".add-btn").length
            })"""
        )
        assert_true(metrics["scrollWidth"] <= metrics["clientWidth"], "mobile has horizontal overflow", issues)
        assert_true(metrics["filters"] >= 2, "category tabs are missing or under-rendered", issues)
        assert_true(metrics["cards"] >= 1, "menu cards did not render", issues)
        assert_true(metrics["addButtons"] >= 1, "add buttons did not render", issues)

        page.locator(".add-btn").first.click()
        open_cart(page)
        page.screenshot(path=screenshot_dir / "phase4-mobile-cart-open.png", full_page=True)
        assert_true(page.locator(".cart-item").count() == 1, "add item did not create a cart row", issues)
        assert_true(cart_quantity(page) == "1", "initial cart quantity is not 1", issues)

        page.locator(".cart-qty-btn", has_text="+").first.click()
        assert_true(cart_quantity(page) == "2", "increment did not update quantity to 2", issues)

        page.locator(".cart-qty-btn", has_text="-").first.click()
        assert_true(cart_quantity(page) == "1", "decrement did not update quantity back to 1", issues)

        page.reload(wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        open_cart(page)
        assert_true(page.locator(".cart-item").count() == 1, "cart did not persist after refresh", issues)
        assert_true(cart_quantity(page) == "1", "persisted cart quantity is not 1", issues)

        page.locator(".cart-remove-btn").first.click()
        assert_true(page.locator(".cart-item").count() == 0, "remove item did not empty the cart row", issues)
        assert_true(page.locator("#cart-empty").is_visible(), "empty cart state is not visible after remove", issues)

        page.locator("#mobile-cart-close").click()
        page.wait_for_timeout(300)
        page.locator(".add-btn").first.click()
        open_cart(page)
        page.locator("#clear-cart").click()
        assert_true(page.locator(".cart-item").count() == 0, "clear cart did not remove items", issues)

        page.locator("#mobile-cart-close").click()
        page.wait_for_timeout(300)
        page.locator(".add-btn").first.click()
        open_cart(page)
        page.locator(".cart-form").scroll_into_view_if_needed()
        page.locator('[name="name"]').fill("UX Smoke")
        page.locator('[name="phone"]').fill("+998901234567")
        page.locator('[name="address"]').fill("Mobile viewport address")
        page.locator('[name="comment"]').fill("Smoke check")
        page.screenshot(path=screenshot_dir / "phase4-mobile-form-focused.png", full_page=True)

        form_box = visible_box(page, ".cart-form")
        submit_box = visible_box(page, "#submit-order")
        pane_box = visible_box(page, ".cart-pane")
        assert_true(form_box["visible"], "order form is not visible/reachable in cart", issues)
        assert_true(submit_box["visible"], "submit button is not visible/reachable in cart", issues)
        assert_true(
            submit_box["y"] + submit_box["height"] <= pane_box["y"] + pane_box["height"] + 2,
            "submit button overflows below mobile cart pane",
            issues,
        )

        page.locator("#mobile-cart-close").click()
        page.wait_for_timeout(300)
        page.locator("#menu-filters").scroll_into_view_if_needed()
        page.locator(".menu-filter-pill").nth(1).click()
        active_text = page.locator(".menu-filter-pill.is-active").inner_text(timeout=3000).strip()
        page.screenshot(path=screenshot_dir / "phase4-mobile-category-active.png", full_page=True)
        assert_true(bool(active_text), "active category highlight is missing after tab click", issues)
        closed_cart = hidden_box(page, ".cart-pane")
        assert_true(
            closed_cart["visibility"] == "hidden" and closed_cart["opacity"] == 0,
            "closed mobile cart remains visually exposed",
            issues,
        )

        image_stats = page.evaluate(
            """() => Array.from(document.querySelectorAll(".menu-item-image")).map((el) => {
                const rect = el.getBoundingClientRect();
                return { width: rect.width, height: rect.height };
            })"""
        )
        assert_true(
            all(item["width"] > 0 and item["height"] > 0 for item in image_stats),
            "one or more menu image frames collapsed",
            issues,
        )

        print(json.dumps({"url": url, "screenshots": [str(p) for p in sorted(screenshot_dir.glob("*.png"))], "issues": issues}, indent=2))
        browser.close()

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public menu UX smoke checks with Playwright Chromium.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--screenshots", type=Path, default=DEFAULT_SCREENSHOT_DIR)
    args = parser.parse_args()

    try:
        issues = run_smoke(args.url, args.screenshots)
    except PlaywrightTimeoutError as exc:
        print(json.dumps({"url": args.url, "issues": [f"timeout: {exc}"]}, indent=2))
        return 1

    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
