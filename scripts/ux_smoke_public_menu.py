from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


DEFAULT_URL = "http://127.0.0.1:8000/t/demo"
DEFAULT_SCREENSHOT_DIR = Path("screenshots/ux-stabilization")


EDGE_MENU = {
    "categories": [
        {
            "id": 9001,
            "title": "Juda juda uzun kategoriya nomi delivery brunch setlari va oilaviy combo taomlar",
            "items": [
                {
                    "id": 9101,
                    "name": "Super uzun nomli maxsus burger lavash set combo oilaviy bayram uchun ekstra pishloq va sous bilan",
                    "description": (
                        "Bu taom tavsifi ataylab uzun yozilgan: tarkibida yangi sabzavotlar, maxsus sous, "
                        "qo'shimcha garnir, bolalar uchun yengil variant va yetkazib berishda alohida qadoqlash bor."
                    ),
                    "price": 1234567890,
                    "image_url": "/uploads/huge-edge-image.svg",
                },
                {
                    "id": 9102,
                    "name": "Broken image placeholder tekshiruvi uchun taom",
                    "description": "Rasm yuklanmasa ham karta sinmasligi kerak.",
                    "price": 0,
                    "image_url": "/uploads/missing-edge-image.jpg",
                },
            ],
        },
        {
            "id": 9002,
            "title": "Bo'sh kategoriya nomi juda uzun lekin ichida mahsulot yo'q",
            "items": [],
        },
        {
            "id": 9003,
            "title": "LongUnbrokenCategoryNameWithoutSpacesAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "items": [
                {
                    "id": 9103,
                    "name": "LongUnbrokenMenuItemTitleWithoutSpacesBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                    "description": (
                        "LongUnbrokenDescriptionWithoutSpacesCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
                    ),
                    "price": 15000,
                    "image": "",
                    "image_url": "",
                }
            ],
        },
    ]
}

EMPTY_MENU = {"categories": []}


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


def clear_cart_storage(page: Page) -> None:
    page.evaluate(
        """() => {
            const slug = window.location.pathname.split("/")[2] || "";
            if (slug) {
                window.localStorage.removeItem(`qadam.cart.${decodeURIComponent(slug)}`);
            }
        }"""
    )


def page_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            filters: document.querySelectorAll(".menu-filter-pill").length,
            cards: document.querySelectorAll(".menu-card").length,
            addButtons: document.querySelectorAll(".add-btn").length
        })"""
    )


def overflowing_elements(page: Page) -> list[dict]:
    return page.evaluate(
        """() => {
            const width = document.documentElement.clientWidth;
            const isInsideHorizontalScroller = (el) => {
                let current = el.parentElement;
                while (current && current !== document.body) {
                    const style = window.getComputedStyle(current);
                    if ((style.overflowX === "auto" || style.overflowX === "scroll") && current.scrollWidth > current.clientWidth) {
                        return true;
                    }
                    current = current.parentElement;
                }
                return false;
            };
            return Array.from(document.querySelectorAll("body *"))
                .filter((el) => !isInsideHorizontalScroller(el))
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || "",
                        className: String(el.className || ""),
                        left: rect.left,
                        right: rect.right,
                        width: rect.width,
                        text: (el.textContent || "").trim().slice(0, 80)
                    };
                })
                .filter((item) => item.width > 0 && (item.left < -1 || item.right > width + 1));
        }"""
    )


def install_edge_routes(page: Page, menu_payload: dict) -> None:
    page.route("**/t/*/menu", lambda route: route.fulfill(json=menu_payload))
    page.route(
        "**/uploads/huge-edge-image.svg",
        lambda route: route.fulfill(
            status=200,
            content_type="image/svg+xml",
            body=(
                '<svg xmlns="http://www.w3.org/2000/svg" width="5000" height="3200" viewBox="0 0 5000 3200">'
                '<defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#f6e7c8"/>'
                '<stop offset="1" stop-color="#172033"/></linearGradient></defs>'
                '<rect width="5000" height="3200" fill="url(#g)"/>'
                '<circle cx="3500" cy="1450" r="820" fill="#d6ad68" opacity=".55"/>'
                '<text x="260" y="420" font-size="180" fill="#172033" font-family="Arial">Large image</text>'
                "</svg>"
            ),
        ),
    )
    page.route("**/uploads/missing-edge-image.jpg", lambda route: route.fulfill(status=404, body="missing"))


def install_menu_error_route(page: Page) -> None:
    page.route("**/t/*/menu", lambda route: route.fulfill(status=500, json={"detail": "menu unavailable"}))


def run_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        clear_cart_storage(page)
        page.reload(wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        page.screenshot(path=screenshot_dir / "phase4-mobile-initial.png", full_page=True)

        metrics = page_metrics(page)
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


def run_edge_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        page = context.new_page()
        install_edge_routes(page, EDGE_MENU)
        page.goto(url, wait_until="networkidle")
        clear_cart_storage(page)
        page.reload(wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        page.screenshot(path=screenshot_dir / "phase4-edge-menu.png", full_page=True)

        metrics = page_metrics(page)
        assert_true(metrics["scrollWidth"] <= metrics["clientWidth"], "edge menu has horizontal overflow", issues)
        assert_true(metrics["filters"] == 4, "edge menu category tabs did not render expected count", issues)
        assert_true(metrics["cards"] == 3, "edge menu should render only categories with items", issues)
        assert_true(metrics["addButtons"] == 3, "edge menu add buttons count is wrong", issues)

        overflow = overflowing_elements(page)
        assert_true(not overflow, f"edge menu has overflowing elements: {overflow[:3]}", issues)

        long_title_height = page.locator(".menu-item-title").first.evaluate("(el) => el.getBoundingClientRect().height")
        assert_true(long_title_height <= 96, "long item title makes card title area too tall", issues)

        desc_heights = page.evaluate(
            """() => Array.from(document.querySelectorAll(".menu-card-desc")).map((el) => el.getBoundingClientRect().height)"""
        )
        assert_true(all(height <= 88 for height in desc_heights), "long item descriptions are not constrained", issues)

        image_stats = page.evaluate(
            """() => Array.from(document.querySelectorAll(".menu-item-image")).map((el) => {
                const rect = el.getBoundingClientRect();
                const img = el.querySelector("img");
                return {
                    width: rect.width,
                    height: rect.height,
                    hasFallback: Boolean(el.querySelector(".img-placeholder")),
                    objectFit: img ? window.getComputedStyle(img).objectFit : ""
                };
            })"""
        )
        assert_true(all(item["width"] > 0 and item["height"] > 0 for item in image_stats), "edge image frame collapsed", issues)
        assert_true(any(item["hasFallback"] for item in image_stats), "broken image did not render fallback placeholder", issues)
        assert_true(any(item["objectFit"] == "cover" for item in image_stats), "large image does not use object-fit cover", issues)

        price_texts = page.evaluate(
            """() => Array.from(document.querySelectorAll(".menu-item-price")).map((el) => el.textContent.trim())"""
        )
        assert_true("0 so'm" in price_texts, "zero price is not formatted consistently", issues)
        assert_true(any(text == "1 234 567 890 so'm" for text in price_texts), "large price is not grouped consistently", issues)

        page.locator(".add-btn").first.click()
        open_cart(page)
        page.locator(".cart-form").scroll_into_view_if_needed()
        page.locator('[name="address"]').fill("Keyboard focus address field")
        page.screenshot(path=screenshot_dir / "phase4-edge-form-focused.png", full_page=True)
        form_box = visible_box(page, ".cart-form")
        submit_box = visible_box(page, "#submit-order")
        pane_box = visible_box(page, ".cart-pane")
        assert_true(form_box["visible"], "edge form is not reachable in mobile cart", issues)
        assert_true(submit_box["visible"], "edge submit button is not reachable in mobile cart", issues)
        assert_true(
            submit_box["y"] + submit_box["height"] <= pane_box["y"] + pane_box["height"] + 2,
            "edge submit button overflows below mobile cart pane",
            issues,
        )

        page.unroute("**/t/*/menu")
        install_edge_routes(page, EMPTY_MENU)
        page.goto(url, wait_until="networkidle")
        page.locator(".empty-state").wait_for(timeout=8000)
        page.screenshot(path=screenshot_dir / "phase4-edge-empty-menu.png", full_page=True)
        empty_metrics = page_metrics(page)
        assert_true(empty_metrics["scrollWidth"] <= empty_metrics["clientWidth"], "empty menu has horizontal overflow", issues)
        assert_true(empty_metrics["cards"] == 0, "empty menu should not render cards", issues)
        assert_true(page.locator(".empty-state").is_visible(), "empty menu state is not visible", issues)

        print(
            json.dumps(
                {
                    "url": url,
                    "mode": "edge",
                    "screenshots": [str(p) for p in sorted(screenshot_dir.glob("*.png"))],
                    "issues": issues,
                },
                indent=2,
            )
        )
        browser.close()

    return issues


def run_loading_error_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        loading_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        loading_page = loading_context.new_page()
        pending_routes = []
        loading_page.route("**/t/*/menu", lambda route: pending_routes.append(route))
        loading_page.goto(url, wait_until="domcontentloaded")
        loading_page.locator(".menu-card-skeleton").first.wait_for(timeout=5000)
        loading_page.locator(".menu-filter-skeleton").first.wait_for(timeout=5000)
        loading_page.screenshot(path=screenshot_dir / "phase5-loading-menu.png", full_page=True)
        assert_true(loading_page.locator(".menu-card-skeleton").count() >= 3, "menu skeleton cards are missing", issues)
        assert_true(loading_page.locator(".menu-filter-skeleton").count() >= 2, "category skeleton tabs are missing", issues)
        assert_true(loading_page.locator("#menu[aria-busy='true']").count() == 1, "menu is not marked aria-busy while loading", issues)
        for route in pending_routes:
            route.abort()
        loading_context.close()

        error_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        error_page = error_context.new_page()
        install_menu_error_route(error_page)
        error_page.goto(url, wait_until="networkidle")
        error_page.locator(".menu-error-state").wait_for(timeout=8000)
        error_page.screenshot(path=screenshot_dir / "phase5-error-menu.png", full_page=True)
        assert_true(error_page.locator(".menu-error-state").is_visible(), "friendly menu error state is not visible", issues)
        assert_true(error_page.locator(".menu-retry-btn").is_visible(), "menu retry button is not visible", issues)
        assert_true(error_page.locator("#menu[aria-busy='true']").count() == 0, "menu remains aria-busy after error", issues)

        error_page.unroute("**/t/*/menu")
        install_edge_routes(error_page, EDGE_MENU)
        error_page.locator(".menu-retry-btn").click()
        error_page.locator(".menu-card").first.wait_for(timeout=8000)
        error_page.screenshot(path=screenshot_dir / "phase5-retry-menu.png", full_page=True)
        retry_metrics = page_metrics(error_page)
        assert_true(retry_metrics["cards"] == 3, "retry did not render menu cards after recovery", issues)
        assert_true(retry_metrics["scrollWidth"] <= retry_metrics["clientWidth"], "retry recovery has horizontal overflow", issues)
        error_context.close()

        print(
            json.dumps(
                {
                    "url": url,
                    "mode": "loading-error",
                    "screenshots": [str(p) for p in sorted(screenshot_dir.glob("phase5-*.png"))],
                    "issues": issues,
                },
                indent=2,
            )
        )
        browser.close()

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public menu UX smoke checks with Playwright Chromium.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--screenshots", type=Path, default=DEFAULT_SCREENSHOT_DIR)
    parser.add_argument("--edge", action="store_true", help="Run mocked edge-case menu data checks.")
    parser.add_argument("--loading-error", action="store_true", help="Run loading and error UX checks.")
    args = parser.parse_args()

    try:
        if args.loading_error:
            issues = run_loading_error_smoke(args.url, args.screenshots)
        elif args.edge:
            issues = run_edge_smoke(args.url, args.screenshots)
        else:
            issues = run_smoke(args.url, args.screenshots)
    except PlaywrightTimeoutError as exc:
        print(json.dumps({"url": args.url, "issues": [f"timeout: {exc}"]}, indent=2))
        return 1

    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
