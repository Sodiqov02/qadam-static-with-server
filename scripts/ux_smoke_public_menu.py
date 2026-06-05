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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public menu UX smoke checks with Playwright Chromium.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--screenshots", type=Path, default=DEFAULT_SCREENSHOT_DIR)
    parser.add_argument("--edge", action="store_true", help="Run mocked edge-case menu data checks.")
    parser.add_argument("--loading-error", action="store_true", help="Run loading and error UX checks.")
    parser.add_argument("--branding", action="store_true", help="Run tenant branding checks.")
    parser.add_argument("--order-flow", action="store_true", help="Run checkout order-flow UX checks.")
    args = parser.parse_args()

    try:
        if args.branding:
            issues = run_branding_smoke(args.url, args.screenshots)
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
