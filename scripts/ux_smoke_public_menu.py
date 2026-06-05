from __future__ import annotations

import argparse
import json
import uuid
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
BRANDED_TENANT = {
    "name": "Brand Smoke",
    "description": "Tenant branding smoke profile",
    "hero_image": "",
    "logo_url": "/uploads/demo/logo-smoke.svg",
    "primary_color": "#123456",
    "accent_color": "#f59e0b",
    "theme_mode": "dark",
    "plan": "standard",
    "features": {"plan": "standard"},
    "bot_username": None,
    "bot_enabled": False,
}
UNBRANDED_TENANT = {
    "name": "No Brand Smoke",
    "description": "Tenant without custom branding",
    "hero_image": "",
    "logo_url": None,
    "primary_color": None,
    "accent_color": None,
    "theme_mode": "default",
    "plan": "basic",
    "features": {"plan": "basic"},
    "bot_username": None,
    "bot_enabled": False,
}
BROKEN_LOGO_TENANT = {
    **BRANDED_TENANT,
    "logo_url": "/uploads/demo/missing-logo-smoke.svg",
}


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


def install_tenant_profile_route(page: Page, tenant_payload: dict) -> None:
    page.route("**/t/*/tenant", lambda route: route.fulfill(json=tenant_payload))
    page.route(
        "**/uploads/demo/logo-smoke.svg",
        lambda route: route.fulfill(
            status=200,
            content_type="image/svg+xml",
            body=(
                '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
                '<rect width="96" height="96" rx="22" fill="#123456"/>'
                '<circle cx="48" cy="48" r="24" fill="#f59e0b"/>'
                "</svg>"
            ),
        ),
    )
    page.route("**/uploads/demo/missing-logo-smoke.svg", lambda route: route.fulfill(status=404, body="missing"))


def install_menu_error_route(page: Page) -> None:
    page.route("**/t/*/menu", lambda route: route.fulfill(status=500, json={"detail": "menu unavailable"}))


def install_order_success_route(page: Page) -> None:
    page.route("**/t/*/orders", lambda route: route.fulfill(status=200, json={"order_id": 4242}))


def install_order_error_route(page: Page) -> None:
    page.route(
        "**/t/*/orders",
        lambda route: route.fulfill(status=503, json={"detail": "Kitchen offline"}),
    )


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


def run_branding_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        page = context.new_page()
        install_tenant_profile_route(page, BRANDED_TENANT)
        install_edge_routes(page, EDGE_MENU)
        page.goto(url, wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        page.screenshot(path=screenshot_dir / "phase5-branding-custom.png", full_page=True)

        profile = page.evaluate("() => fetch(`${window.location.pathname}/tenant`).then((res) => res.json())")
        assert_true(profile.get("logo_url") == BRANDED_TENANT["logo_url"], "public profile does not return logo_url", issues)
        assert_true(profile.get("primary_color") == BRANDED_TENANT["primary_color"], "public profile does not return primary_color", issues)
        assert_true(profile.get("accent_color") == BRANDED_TENANT["accent_color"], "public profile does not return accent_color", issues)
        assert_true(profile.get("theme_mode") == BRANDED_TENANT["theme_mode"], "public profile does not return theme_mode", issues)

        branding_state = page.evaluate(
            """() => ({
                logoVisible: Boolean(document.querySelector("#site-logo:not([hidden])")),
                logoSrc: document.querySelector("#site-logo")?.getAttribute("src") || "",
                primary: getComputedStyle(document.documentElement).getPropertyValue("--tenant-primary").trim(),
                accent: getComputedStyle(document.documentElement).getPropertyValue("--tenant-accent").trim(),
                dark: document.body.classList.contains("theme-dark"),
                loadingBusy: document.querySelectorAll("#menu[aria-busy='true']").length,
                errorState: document.querySelectorAll(".menu-error-state").length,
                cards: document.querySelectorAll(".menu-card").length
            })"""
        )
        assert_true(branding_state["logoVisible"], "logo is not visible after branding load", issues)
        assert_true(branding_state["logoSrc"] == BRANDED_TENANT["logo_url"], "logo src was not applied", issues)
        assert_true(branding_state["primary"] == "#123456", "primary CSS variable was not applied", issues)
        assert_true(branding_state["accent"] == "#f59e0b", "accent CSS variable was not applied", issues)
        assert_true(branding_state["dark"], "theme_mode dark class was not applied", issues)
        assert_true(branding_state["loadingBusy"] == 0, "menu remains aria-busy after branded load", issues)
        assert_true(branding_state["errorState"] == 0, "branded page unexpectedly shows menu error state", issues)
        assert_true(branding_state["cards"] == 3, "branded page did not render menu cards", issues)

        page.unroute("**/t/*/tenant")
        page.unroute("**/t/*/menu")
        install_tenant_profile_route(page, BROKEN_LOGO_TENANT)
        install_edge_routes(page, EDGE_MENU)
        page.goto(url, wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        broken_logo_state = page.evaluate(
            """() => ({
                logoVisible: Boolean(document.querySelector("#site-logo:not([hidden])")),
                logoSrc: document.querySelector("#site-logo")?.getAttribute("src") || "",
                primary: getComputedStyle(document.documentElement).getPropertyValue("--tenant-primary").trim(),
                accent: getComputedStyle(document.documentElement).getPropertyValue("--tenant-accent").trim()
            })"""
        )
        assert_true(not broken_logo_state["logoVisible"], "broken logo remains visible", issues)
        assert_true(broken_logo_state["logoSrc"] == "", "broken logo src was not cleared", issues)
        assert_true(broken_logo_state["primary"] == "#123456", "broken logo path should not block primary color", issues)
        assert_true(broken_logo_state["accent"] == "#f59e0b", "broken logo path should not block accent color", issues)

        page.unroute("**/t/*/tenant")
        page.unroute("**/t/*/menu")
        install_tenant_profile_route(page, UNBRANDED_TENANT)
        install_edge_routes(page, EDGE_MENU)
        page.goto(url, wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)
        page.screenshot(path=screenshot_dir / "phase5-branding-empty.png", full_page=True)
        unbranded_state = page.evaluate(
            """() => ({
                logoVisible: Boolean(document.querySelector("#site-logo:not([hidden])")),
                primary: getComputedStyle(document.documentElement).getPropertyValue("--tenant-primary").trim(),
                accent: getComputedStyle(document.documentElement).getPropertyValue("--tenant-accent").trim(),
                themeClass: document.body.classList.contains("theme-light") || document.body.classList.contains("theme-dark"),
                cards: document.querySelectorAll(".menu-card").length,
                errorState: document.querySelectorAll(".menu-error-state").length
            })"""
        )
        assert_true(not unbranded_state["logoVisible"], "logo remains visible without branding", issues)
        assert_true(unbranded_state["primary"] == "", "primary CSS variable should be unset without branding", issues)
        assert_true(unbranded_state["accent"] == "", "accent CSS variable should be unset without branding", issues)
        assert_true(not unbranded_state["themeClass"], "theme class remains set without branding", issues)
        assert_true(unbranded_state["cards"] == 3, "unbranded page did not render menu cards", issues)
        assert_true(unbranded_state["errorState"] == 0, "unbranded page unexpectedly shows menu error state", issues)

        admin_payloads: list[dict] = []
        page.route("**/t/*/api/admin/analytics**", lambda route: route.fulfill(json={"orders": 0, "revenue": 0, "average_check": 0, "top_items": []}))
        page.route("**/t/*/api/admin/promotions", lambda route: route.fulfill(json={"items": []}))

        def capture_branding_update(route) -> None:
            payload = route.request.post_data_json
            admin_payloads.append(payload() if callable(payload) else payload)
            response = dict(UNBRANDED_TENANT)
            response.update(admin_payloads[-1])
            route.fulfill(json=response)

        page.route("**/t/*/api/admin/tenant", capture_branding_update)
        admin_url = f"{url.rstrip('/')}/admin"
        page.goto(admin_url, wait_until="networkidle")
        page.locator("#branding-form").wait_for(timeout=8000)
        assert_true(page.locator("#brand-use-default-colors").is_checked(), "default colors checkbox should be checked without tenant colors", issues)
        assert_true(page.locator("#brand-primary").is_disabled(), "primary color input should be disabled with default colors", issues)
        assert_true(page.locator("#brand-accent").is_disabled(), "accent color input should be disabled with default colors", issues)
        page.locator("#branding-form button[type='submit']").click()
        page.wait_for_timeout(300)
        assert_true(bool(admin_payloads), "admin branding submit did not reach API", issues)
        assert_true(admin_payloads[-1].get("primary_color") is None, "default colors submit should send primary_color null", issues)
        assert_true(admin_payloads[-1].get("accent_color") is None, "default colors submit should send accent_color null", issues)

        page.locator("#brand-use-default-colors").uncheck()
        page.locator("#brand-primary").fill("#0f766e")
        page.locator("#brand-accent").fill("#f97316")
        page.locator("#branding-form button[type='submit']").click()
        page.wait_for_timeout(300)
        assert_true(admin_payloads[-1].get("primary_color") == "#0f766e", "custom colors submit did not send primary color", issues)
        assert_true(admin_payloads[-1].get("accent_color") == "#f97316", "custom colors submit did not send accent color", issues)

        print(
            json.dumps(
                {
                    "url": url,
                    "mode": "branding",
                    "screenshots": [str(p) for p in sorted(screenshot_dir.glob("phase5-branding-*.png"))],
                    "issues": issues,
                },
                indent=2,
            )
        )
        browser.close()

    return issues


def run_order_flow_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        page = context.new_page()
        install_tenant_profile_route(page, UNBRANDED_TENANT)
        install_edge_routes(page, EDGE_MENU)
        install_order_success_route(page)
        page.goto(url, wait_until="networkidle")
        clear_cart_storage(page)
        page.reload(wait_until="networkidle")
        page.locator(".menu-card").first.wait_for(timeout=8000)

        open_cart(page)
        assert_true(page.locator(".cart-form").is_hidden(), "empty cart checkout form should be hidden", issues)
        assert_true(page.locator("#submit-order").is_disabled(), "empty cart submit should be disabled", issues)
        assert_true(
            page.locator("#order-form").evaluate("(form) => form.noValidate"),
            "order form should disable native required validation",
            issues,
        )
        page.locator("#order-form").evaluate("(form) => form.requestSubmit()")
        page.locator("#cart-empty", has_text="Savat bo'sh. Avval taom qo'shing.").wait_for(timeout=3000)
        page.screenshot(path=screenshot_dir / "phase6-order-flow-empty-submit.png", full_page=True)
        assert_true(
            page.locator("#cart-empty").inner_text(timeout=3000).strip() == "Savat bo'sh. Avval taom qo'shing.",
            "empty cart submit did not show the app empty-cart message",
            issues,
        )

        page.locator("#mobile-cart-close").click()
        page.wait_for_timeout(300)
        page.locator(".add-btn").first.click()
        open_cart(page)
        assert_true(page.locator(".cart-form").is_visible(), "checkout form should be visible after adding an item", issues)
        page.locator(".cart-remove-btn").first.click()
        page.screenshot(path=screenshot_dir / "phase6-order-flow-remove-empty.png", full_page=True)
        assert_true(page.locator(".cart-item").count() == 0, "removing last item did not empty cart rows", issues)
        assert_true(page.locator(".cart-form").is_hidden(), "checkout form remains visible after removing last item", issues)
        assert_true(page.locator("#submit-order").is_disabled(), "submit remains enabled after removing last item", issues)
        assert_true(page.locator("#cart-empty").is_visible(), "empty state is not visible after removing last item", issues)

        page.locator("#mobile-cart-close").click()
        page.wait_for_timeout(300)
        page.locator(".add-btn").first.click()
        open_cart(page)
        page.locator('[name="name"]').fill("UX Smoke")
        page.locator('[name="phone"]').fill("+998901234567")
        page.locator('[name="address"]').fill("Smoke address")
        page.locator("#submit-order").click()
        page.locator("#cart-empty", has_text="Buyurtma qabul qilindi").wait_for(timeout=5000)
        page.screenshot(path=screenshot_dir / "phase6-order-flow-success.png", full_page=True)
        success_text = page.locator("#cart-empty").inner_text(timeout=3000)
        assert_true("Buyurtma qabul qilindi" in success_text, "success state is not visible after order submit", issues)
        assert_true("bog'lanamiz" in success_text, "success state does not explain follow-up contact", issues)
        assert_true(page.locator("body.cart-open").count() == 1, "cart should remain open after success", issues)
        assert_true(page.locator(".cart-item").count() == 0, "cart rows remain after successful order", issues)

        page.locator("#mobile-cart-close").click()
        page.wait_for_timeout(300)
        page.unroute("**/t/*/orders")
        install_order_error_route(page)
        page.locator(".add-btn").first.click()
        open_cart(page)
        page.locator('[name="name"]').fill("UX Smoke")
        page.locator('[name="phone"]').fill("+998901234567")
        page.locator('[name="address"]').fill("Smoke address")
        page.locator("#submit-order").click()
        page.locator("#order-status", has_text="Qayta urinib").wait_for(timeout=5000)
        page.screenshot(path=screenshot_dir / "phase6-order-flow-error.png", full_page=True)
        error_text = page.locator("#order-status").inner_text(timeout=3000)
        assert_true("Buyurtmani yuborib bo'lmadi" in error_text, "order error text is not user-friendly", issues)
        assert_true("Qayta urinib ko'ring" in error_text, "order error does not include retry guidance", issues)
        assert_true("Kitchen offline" in error_text, "safe backend detail is not shown in order error", issues)
        assert_true("Traceback" not in error_text and ".py:" not in error_text, "technical stack details leaked in order error", issues)

        print(
            json.dumps(
                {
                    "url": url,
                    "mode": "order-flow",
                    "screenshots": [str(p) for p in sorted(screenshot_dir.glob("phase6-order-flow-*.png"))],
                    "issues": issues,
                },
                indent=2,
            )
        )
        browser.close()

    return issues


def run_admin_flow_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    base_url = url.split("/t/")[0].rstrip("/")
    menu_url = f"{base_url}/admin/menu/demo?admin_token=smoke"
    admin_url = f"{base_url}/t/demo/admin?admin_token=smoke"
    guidance = "Access denied. Open the admin link from Telegram again or request a new admin login link."

    def install_login(page: Page) -> None:
      page.route("**/admin/auth/login", lambda route: route.fulfill(json={"ok": True, "tenant_slug": "demo"}))

    def empty_payload() -> dict:
        return {"tenant": {"name": "Admin Smoke", "slug": "demo"}, "categories": [], "items": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        failure_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        failure_page = failure_context.new_page()
        failure_page_errors: list[str] = []
        failure_page.on("pageerror", lambda exc: failure_page_errors.append(str(exc)))
        install_login(failure_page)
        menu_requests = {"count": 0}

        def flaky_menu(route) -> None:
            menu_requests["count"] += 1
            if menu_requests["count"] == 1:
                route.abort()
            else:
                route.fulfill(json=empty_payload())

        failure_page.route("**/admin/api/menu/demo", flaky_menu)
        failure_page.goto(menu_url, wait_until="networkidle")
        failure_page.locator("#empty-state", has_text="Menu data failed to load. Check connection and retry.").wait_for(timeout=5000)
        failure_page.screenshot(path=screenshot_dir / "phase62-admin-menu-load-error.png", full_page=True)
        assert_true(failure_page.locator("#save-btn").is_disabled(), "admin menu save remains enabled after initial load failure", issues)
        assert_true(failure_page.locator("#category-save-btn").is_disabled(), "category save remains enabled after initial load failure", issues)
        assert_true(failure_page.locator("#empty-state button", has_text="Retry").is_visible(), "admin menu load error retry button is missing", issues)
        failure_page.locator("#empty-state button", has_text="Retry").click()
        failure_page.locator("#empty-state", has_text="No dishes yet. Add a dish after creating a category.").wait_for(timeout=5000)
        assert_true(not failure_page_errors, f"initial load failure leaked page errors: {failure_page_errors}", issues)
        assert_true(
            failure_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"),
            "admin menu load failure has mobile horizontal overflow",
            issues,
        )
        failure_context.close()

        action_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        action_page = action_context.new_page()
        action_page_errors: list[str] = []
        action_page.on("pageerror", lambda exc: action_page_errors.append(str(exc)))
        install_login(action_page)
        action_payload = {
            "tenant": {"name": "Admin Smoke", "slug": "demo"},
            "categories": [{"id": 11, "title": "Smoke category", "sort_order": 0}],
            "items": [],
        }
        action_page.route("**/admin/api/menu/demo", lambda route: route.abort() if route.request.method == "POST" else route.fulfill(json=action_payload))
        action_page.goto(menu_url, wait_until="networkidle")
        action_page.locator("#item-name").fill("Smoke dish")
        action_page.locator("#item-price").fill("12000")
        action_page.locator("#save-btn").click()
        action_page.locator("#form-status", has_text="Create failed. Check connection and retry.").wait_for(timeout=5000)
        action_page.screenshot(path=screenshot_dir / "phase62-admin-action-network-error.png", full_page=True)
        assert_true(not action_page_errors, f"action failure leaked page errors: {action_page_errors}", issues)
        assert_true(
            action_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"),
            "admin action failure has mobile horizontal overflow",
            issues,
        )
        action_context.close()

        denied_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        denied_menu = denied_context.new_page()
        denied_menu.route("**/admin/api/menu/demo", lambda route: route.fulfill(status=401, json={"detail": "Unauthorized"}))
        denied_menu.goto(f"{base_url}/admin/menu/demo", wait_until="networkidle")
        denied_menu.locator("#global-status", has_text=guidance).wait_for(timeout=5000)
        denied_menu.screenshot(path=screenshot_dir / "phase62-admin-menu-no-session.png", full_page=True)
        assert_true(denied_menu.locator("#save-btn").is_disabled(), "admin menu no-session leaves save enabled", issues)

        denied_dashboard = denied_context.new_page()
        denied_dashboard.route("**/t/demo/tenant", lambda route: route.fulfill(json=UNBRANDED_TENANT))
        denied_dashboard.route("**/t/demo/api/admin/analytics**", lambda route: route.fulfill(status=401, json={"detail": "Unauthorized"}))
        denied_dashboard.route("**/t/demo/api/admin/promotions", lambda route: route.fulfill(status=401, json={"detail": "Unauthorized"}))
        denied_dashboard.goto(f"{base_url}/t/demo/admin", wait_until="networkidle")
        denied_dashboard.locator("#analytics-status", has_text=guidance).wait_for(timeout=5000)
        denied_dashboard.screenshot(path=screenshot_dir / "phase62-admin-dashboard-no-session.png", full_page=True)
        assert_true(denied_dashboard.locator("#branding-status").inner_text(timeout=3000) == guidance, "dashboard branding does not show access guidance after denied admin sections", issues)
        denied_context.close()

        branding_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        branding_page = branding_context.new_page()
        install_login(branding_page)
        branding_profile = dict(UNBRANDED_TENANT)
        branding_profile["plan"] = "standard"
        branding_profile["features"] = {"plan": "standard"}
        branding_page.route("**/t/demo/tenant", lambda route: route.fulfill(json=branding_profile))
        branding_page.route("**/t/demo/api/admin/analytics**", lambda route: route.fulfill(json={"orders": 0, "revenue": 0, "average_check": 0, "top_items": []}))
        branding_page.route("**/t/demo/api/admin/promotions", lambda route: route.fulfill(json={"items": []}))

        def save_branding(route) -> None:
            branding_profile.update(route.request.post_data_json)
            route.fulfill(json=branding_profile)

        branding_page.route("**/t/demo/api/admin/tenant", save_branding)
        branding_page.goto(admin_url, wait_until="networkidle")
        branding_page.locator("#brand-use-default-colors").uncheck()
        branding_page.locator("#brand-primary").fill("#0f766e")
        branding_page.locator("#brand-accent").fill("#f97316")
        branding_page.locator("#branding-form button[type='submit']").click()
        branding_page.locator("#branding-status", has_text="Branding saqlandi.").wait_for(timeout=5000)
        branding_page.wait_for_timeout(300)
        branding_page.screenshot(path=screenshot_dir / "phase62-admin-branding-success.png", full_page=True)
        assert_true(branding_page.locator("#branding-status").inner_text(timeout=3000) == "Branding saqlandi.", "branding success message was cleared after reload", issues)
        assert_true(
            branding_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"),
            "admin dashboard has mobile horizontal overflow",
            issues,
        )
        branding_context.close()

        stale_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        stale_page = stale_context.new_page()
        install_login(stale_page)
        state = {
            "categories": [],
            "items": [],
            "next_category_id": 31,
            "next_item_id": 41,
        }

        def state_payload() -> dict:
            return {"tenant": {"name": "Admin Smoke", "slug": "demo"}, "categories": state["categories"], "items": state["items"]}

        def category_route(route) -> None:
            data = route.request.post_data_json
            category = {"id": state["next_category_id"], "title": data.get("title", ""), "sort_order": len(state["categories"])}
            state["next_category_id"] += 1
            state["categories"].append(category)
            route.fulfill(json=category)

        def menu_collection_route(route) -> None:
            if route.request.method == "GET":
                route.fulfill(json=state_payload())
                return
            data = route.request.post_data_json
            item = {
                "id": state["next_item_id"],
                "name": data.get("name", ""),
                "price": data.get("price", 0),
                "category_id": data.get("category_id"),
                "description": data.get("description"),
                "image_path": data.get("image_path"),
                "image": data.get("image_path"),
            }
            state["next_item_id"] += 1
            state["items"].append(item)
            route.fulfill(json=item)

        def menu_item_route(route) -> None:
            item_id = int(route.request.url.rstrip("/").split("/")[-1])
            state["items"] = [item for item in state["items"] if int(item["id"]) != item_id]
            route.fulfill(json={"ok": True})

        stale_page.route("**/t/demo/categories", category_route)
        stale_page.route("**/admin/api/menu/demo", menu_collection_route)
        stale_page.route("**/admin/api/menu/demo/*", menu_item_route)
        stale_page.goto(menu_url, wait_until="networkidle")
        stale_page.locator("#category-name").fill("Smoke category")
        stale_page.locator("#category-save-btn").click()
        stale_page.locator("#category-status", has_text="Category created.").wait_for(timeout=5000)
        stale_page.locator("#item-name").fill("Smoke dish")
        stale_page.locator("#item-price").fill("19000")
        stale_page.locator("#save-btn").click()
        stale_page.locator("#global-status", has_text="Item created.").wait_for(timeout=5000)
        stale_page.once("dialog", lambda dialog: dialog.accept())
        stale_page.locator("button.danger-btn", has_text="Delete").last.click()
        stale_page.locator("#global-status", has_text="Item deleted.").wait_for(timeout=5000)
        stale_page.screenshot(path=screenshot_dir / "phase62-admin-stale-status-clear.png", full_page=True)
        assert_true(stale_page.locator("#category-status").inner_text(timeout=3000) == "", "stale category status remains after item delete", issues)
        assert_true(
            stale_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"),
            "admin stale-status flow has mobile horizontal overflow",
            issues,
        )
        stale_context.close()

        print(
            json.dumps(
                {
                    "url": url,
                    "mode": "admin-flow",
                    "screenshots": [str(p) for p in sorted(screenshot_dir.glob("phase62-admin-*.png"))],
                    "issues": issues,
                },
                indent=2,
            )
        )
        browser.close()

    return issues


def run_onboarding_smoke(url: str, screenshot_dir: Path) -> list[str]:
    issues: list[str] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    base_url = url.split("/t/")[0].rstrip("/")
    operator_token = "change_me"
    slug = f"smoke-onboarding-{uuid.uuid4().hex[:8]}"

    with sync_playwright() as p:
        denied_request = p.request.new_context(base_url=base_url)
        denied_slug = denied_request.get(f"/api/onboarding/slug-check?slug={slug}")
        denied_create = denied_request.post(
            "/api/onboarding/tenants",
            data=json.dumps({"slug": slug, "name": "Denied", "admin_chat_id": 1, "plan": "standard"}),
            headers={"Content-Type": "application/json"},
        )
        assert_true(denied_slug.status == 401, "slug check without operator auth should be denied", issues)
        assert_true(denied_create.status == 401, "tenant create without operator auth should be denied", issues)
        denied_request.dispose()

        request = p.request.new_context(base_url=base_url)
        login = request.post(
            "/api/onboarding/operator-login",
            data=json.dumps({"secret": operator_token}),
            headers={"Content-Type": "application/json"},
        )
        assert_true(login.ok, "operator login failed in onboarding smoke", issues)

        available = request.get(f"/api/onboarding/slug-check?slug={slug}")
        assert_true(available.ok, "slug check available request failed", issues)
        available_data = available.json()
        assert_true(available_data.get("normalized_slug") == slug, "slug check did not preserve normalized slug", issues)
        assert_true(available_data.get("available") is True, "fresh onboarding slug should be available", issues)

        reject = request.post(
            "/api/onboarding/tenants",
            data=json.dumps(
                {
                    "slug": f"{slug}-bot",
                    "name": "Smoke Bot Reject",
                    "admin_chat_id": 6997959356,
                    "plan": "standard",
                    "enable_bot": True,
                    "initial_categories": ["Main"],
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        assert_true(reject.status == 400, "onboarding should reject enable_bot without token", issues)
        assert_true("Bot token is required" in reject.text(), "enable_bot rejection is not user-friendly", issues)

        invalid_chat = request.post(
            "/api/onboarding/tenants",
            data=json.dumps(
                {
                    "slug": f"{slug}-chat",
                    "name": "Smoke Invalid Chat",
                    "admin_chat_id": 0,
                    "plan": "standard",
                    "initial_categories": ["Main"],
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        assert_true(invalid_chat.status == 400, "invalid admin_chat_id should be rejected", issues)
        assert_true("positive" in invalid_chat.text(), "invalid admin_chat_id rejection is not useful", issues)

        placeholder = request.post(
            "/api/onboarding/tenants",
            data=json.dumps(
                {
                    "slug": f"{slug}-placeholder",
                    "name": "Smoke Placeholder",
                    "admin_chat_id": 6997959356,
                    "plan": "standard",
                    "bot_token": "<PASTE_TOKEN_LOCALLY>",
                    "initial_categories": ["Main"],
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        assert_true(placeholder.status == 400, "placeholder bot token should be rejected", issues)
        assert_true("placeholder" in placeholder.text().lower(), "placeholder token rejection is not useful", issues)

        created = request.post(
            "/api/onboarding/tenants",
            data=json.dumps(
                {
                    "slug": slug,
                    "name": "Smoke Onboarding",
                    "admin_chat_id": 6997959356,
                    "plan": "standard",
                    "bot_username": "deliveringbotliqibot",
                    "enable_bot": False,
                    "initial_categories": ["Main", " Main ", "Drinks"],
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        assert_true(created.ok, f"onboarding create tenant failed: {created.text()}", issues)
        data = created.json()
        serialized = json.dumps(data)
        assert_true("bot_token" not in serialized.lower(), "onboarding response exposes bot_token", issues)
        assert_true(data.get("public_menu_url", "").endswith(f"/t/{slug}"), "public link should point to /t/{slug}", issues)
        assert_true("/menu" not in data.get("public_menu_url", ""), "public link should not point to raw /menu endpoint", issues)
        assert_true(data.get("admin_menu_url"), "admin menu one-time link missing", issues)
        assert_true(data.get("admin_dashboard_url"), "admin dashboard one-time link missing", issues)
        assert_true(data.get("bot_url") == "https://t.me/deliveringbotliqibot", "bot URL was not generated from username", issues)
        assert_true(data.get("tenant", {}).get("categories_created") == 2, "initial categories were not de-duped and created cleanly", issues)

        unavailable = request.get(f"/api/onboarding/slug-check?slug={slug}")
        assert_true(unavailable.ok, "slug check unavailable request failed", issues)
        assert_true(unavailable.json().get("available") is False, "created onboarding slug should be unavailable", issues)

        public_page = request.get(f"/t/{slug}")
        assert_true(public_page.ok, "generated public menu page does not load", issues)
        public_menu = request.get(f"/t/{slug}/menu")
        assert_true(public_menu.ok, "generated tenant menu API does not load", issues)
        category_titles = [item.get("title") for item in public_menu.json().get("categories", [])]
        assert_true(category_titles.count("Main") == 1 and "Drinks" in category_titles, "initial categories are missing or duplicated in public menu API", issues)
        request.dispose()

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        page = context.new_page()
        page.goto(f"{base_url}/admin/onboarding", wait_until="networkidle")
        page.locator("#operator-login-form").wait_for(timeout=5000)
        page.locator("#operator-secret").fill(operator_token)
        page.locator("#operator-login-btn").click()
        page.locator("#onboarding-form").wait_for(timeout=5000)
        page.screenshot(path=screenshot_dir / "phase71-onboarding-form.png", full_page=True)
        assert_true(page.locator("#bot-token").evaluate("(el) => el.type") == "password", "bot token input should be password", issues)

        admin_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        admin_page = admin_context.new_page()
        admin_page.goto(data["admin_menu_url"], wait_until="networkidle")
        admin_page.locator("#first-run-panel").wait_for(timeout=8000)
        admin_page.screenshot(path=screenshot_dir / "phase71-onboarding-admin-link.png", full_page=True)
        assert_true(admin_page.locator("#first-run-panel").is_visible(), "first-run checklist is not visible for new tenant", issues)
        assert_true(admin_page.locator("#category-meta").inner_text(timeout=3000) == "2 categories", "admin link did not load initial categories", issues)
        assert_true(
            admin_page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"),
            "onboarding admin page has mobile horizontal overflow",
            issues,
        )
        admin_context.close()

        dashboard_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True)
        dashboard_page = dashboard_context.new_page()
        dashboard_page.goto(data["admin_dashboard_url"], wait_until="networkidle")
        dashboard_page.locator("#branding-form").wait_for(timeout=8000)
        assert_true(dashboard_page.locator("#branding-status").inner_text(timeout=3000) == "", "admin dashboard link did not open cleanly", issues)
        dashboard_context.close()
        context.close()

        print(
            json.dumps(
                {
                    "url": url,
                    "mode": "onboarding",
                    "screenshots": [str(p) for p in sorted(screenshot_dir.glob("phase71-onboarding-*.png"))],
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
    parser.add_argument("--branding", action="store_true", help="Run tenant branding checks.")
    parser.add_argument("--order-flow", action="store_true", help="Run checkout order-flow UX checks.")
    parser.add_argument("--admin-flow", action="store_true", help="Run admin resilience UX checks.")
    parser.add_argument("--onboarding", action="store_true", help="Run assisted onboarding UX checks.")
    args = parser.parse_args()

    try:
        if args.branding:
            issues = run_branding_smoke(args.url, args.screenshots)
        elif args.onboarding:
            issues = run_onboarding_smoke(args.url, args.screenshots)
        elif args.admin_flow:
            issues = run_admin_flow_smoke(args.url, args.screenshots)
        elif args.order_flow:
            issues = run_order_flow_smoke(args.url, args.screenshots)
        elif args.loading_error:
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
