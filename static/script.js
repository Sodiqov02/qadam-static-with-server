(function () {
  const menuEl = document.getElementById("menu");
  const menuFilters = document.getElementById("menu-filters");
  const cartList = document.getElementById("cart-list");
  const cartEmpty = document.getElementById("cart-empty");
  const cartCount = document.getElementById("cart-count");
  const cartTotal = document.getElementById("cart-total");
  const cartToast = document.getElementById("cart-toast");
  const cartPane = document.querySelector(".cart-pane");
  const cartScroll = document.querySelector(".cart-scroll");
  const cartForm = document.querySelector(".cart-form");
  const clearBtn = document.getElementById("clear-cart");
  const mobileCartToggle = document.getElementById("mobile-cart-toggle");
  const headerCartToggle = document.getElementById("header-cart-toggle");
  const mobileCartBadge = document.getElementById("mobile-cart-badge");
  const headerCartBadge = document.getElementById("header-cart-badge");
  const mobileCartClose = document.getElementById("mobile-cart-close");
  const mobileCartBackdrop = document.getElementById("mobile-cart-backdrop");
  const scrollToFormFab = document.getElementById("scroll-to-form-fab");
  const orderForm = document.getElementById("order-form");
  const submitBtn = document.getElementById("submit-order");
  const statusEl = document.getElementById("order-status");
  const heroTitle = document.getElementById("hero-title");
  const heroDesc = document.getElementById("hero-desc");
  const heroMedia = document.getElementById("hero-media");
  const heroCta = document.getElementById("hero-cta");
  const ordersLink = document.getElementById("orders-link");
  const adminLink = document.getElementById("admin-link");
  const headerTelegramLink = document.getElementById("header-telegram-link");
  const siteLogo = document.getElementById("site-logo");
  const siteTitle = document.getElementById("site-title");
  const footerTitle = document.getElementById("footer-title");
  const footerDescription = document.getElementById("footer-description");
  const footerTelegramLink = document.getElementById("footer-telegram-link");
  const footerPhone = document.getElementById("footer-phone");
  const footerAddress = document.getElementById("footer-address");
  const footerHours = document.getElementById("footer-hours");
  const cartTriggers = document.querySelectorAll(".cart-trigger");
  let lastCartTrigger = null;

  if (!menuEl || !orderForm || !statusEl) {
    return;
  }

  const tenantRequiredError = "Tenant slug required. Open page as /t/<slug>";
  const cart = new Map();

  let activeSlug = "";
  let promotions = [];
  let discountPercent = 0;
  let tenantPlan = "basic";
  let menuCategories = [];
  let activeCategoryId = "all";
  let toastTimer = 0;
  let isCartLoading = false;
  let cartNotice = null;
  let isOrderSubmitting = false;

  function extractSlug() {
    const slug = window.location.pathname.split("/")[2] || "";
    return slug ? decodeURIComponent(slug) : "";
  }

  function tenantPath(path) {
    const slug = extractSlug();
    if (!slug) {
      throw new Error(tenantRequiredError);
    }
    return `/t/${encodeURIComponent(slug)}${path}`;
  }

  function cartStorageKey() {
    const slug = activeSlug || extractSlug();
    return slug ? `qadam.cart.${slug}` : "";
  }

  function saveCartState() {
    const key = cartStorageKey();
    if (!key) {
      return;
    }
    try {
      const payload = Array.from(cart.values()).map(({ item, qty }) => ({
        id: item.id,
        qty,
      }));
      window.localStorage.setItem(key, JSON.stringify(payload));
    } catch (_) {
      // Cart persistence is a UX enhancement; storage failures should not block ordering.
    }
  }

  function restoreCartState(categories) {
    const key = cartStorageKey();
    if (!key) {
      return;
    }
    let payload = [];
    try {
      payload = JSON.parse(window.localStorage.getItem(key) || "[]");
    } catch (_) {
      payload = [];
    }
    if (!Array.isArray(payload) || !payload.length) {
      return;
    }

    const itemMap = new Map();
    (categories || []).forEach((category) => {
      (category.items || []).forEach((item) => {
        itemMap.set(String(item.id), item);
      });
    });

    cart.clear();
    payload.forEach((entry) => {
      const item = itemMap.get(String(entry && entry.id));
      const qty = Number(entry && entry.qty);
      if (item && Number.isFinite(qty) && qty > 0) {
        cart.set(item.id, { item, qty: Math.floor(qty) });
      }
    });
    saveCartState();
  }

  function isRenderableImageUrl(value) {
    if (!value || typeof value !== "string") {
      return false;
    }
    if (value.startsWith("/uploads/")) {
      return true;
    }
    if (value.startsWith("/menu-images/")) {
      return true;
    }
    if (value.startsWith("/static/demo/")) {
      return true;
    }
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (_) {
      return false;
    }
  }

  function isHexColor(value) {
    return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
  }

  function resetBranding() {
    document.body.classList.remove("theme-light", "theme-dark");
    document.documentElement.style.removeProperty("--tenant-primary");
    document.documentElement.style.removeProperty("--tenant-accent");
    if (siteLogo) {
      siteLogo.hidden = true;
      siteLogo.onload = null;
      siteLogo.onerror = null;
      siteLogo.removeAttribute("src");
    }
  }

  function applyTenantBranding(data) {
    resetBranding();
    if (!data || typeof data !== "object") {
      return;
    }

    if (isRenderableImageUrl(data.logo_url) && siteLogo) {
      siteLogo.alt = data.name ? `${data.name} logo` : "Restaurant logo";
      siteLogo.hidden = true;
      siteLogo.onload = function () {
        siteLogo.hidden = false;
      };
      siteLogo.onerror = function () {
        siteLogo.hidden = true;
        siteLogo.removeAttribute("src");
      };
      siteLogo.src = data.logo_url;
    }
    if (isHexColor(data.primary_color)) {
      document.documentElement.style.setProperty("--tenant-primary", data.primary_color.toLowerCase());
    }
    if (isHexColor(data.accent_color)) {
      document.documentElement.style.setProperty("--tenant-accent", data.accent_color.toLowerCase());
    }

    const themeMode = String(data.theme_mode || "default").toLowerCase();
    if (themeMode === "light" || themeMode === "dark") {
      document.body.classList.add(`theme-${themeMode}`);
    }
  }

  function safeText(el, text) {
    el.textContent = text ?? "";
    return el;
  }

  function formatPrice(n) {
    const amount = Number(n || 0).toLocaleString("ru-RU").replace(/\s/g, " ");
    return `${amount} so'm`;
  }

  function effectivePrice(price) {
    if (!discountPercent) {
      return Number(price || 0);
    }
    return Math.round((Number(price || 0) * (100 - discountPercent)) / 100);
  }

  function setCartOpen(isOpen) {
    const open = Boolean(isOpen);
    document.body.classList.toggle("cart-open", open);
    if (cartPane) {
      cartPane.setAttribute("aria-hidden", open ? "false" : "true");
      if (open) {
        cartPane.removeAttribute("inert");
      } else {
        cartPane.setAttribute("inert", "");
      }
    }
    if (open) {
      window.requestAnimationFrame(function () {
        if (cartScroll) {
          cartScroll.scrollTop = 0;
        }
        updateScrollFab();
        if (mobileCartClose) {
          mobileCartClose.focus({ preventScroll: true });
        }
      });
    } else if (lastCartTrigger && typeof lastCartTrigger.focus === "function") {
      if (scrollToFormFab) {
        scrollToFormFab.classList.remove("visible");
      }
      lastCartTrigger.focus({ preventScroll: true });
    }
  }

  function updateScrollFab() {
    if (!scrollToFormFab || !cartScroll || !cartForm) {
      return;
    }
    if (!document.body.classList.contains("cart-open") || cart.size === 0) {
      scrollToFormFab.classList.remove("visible");
      return;
    }

    const formRect = cartForm.getBoundingClientRect();
    const containerRect = cartScroll.getBoundingClientRect();

    const formVisible =
      formRect.top < containerRect.bottom - 40 &&
      formRect.bottom > containerRect.top;

    if (formVisible) {
      scrollToFormFab.classList.remove("visible");
    } else {
      scrollToFormFab.classList.add("visible");
    }
  }

  function updateCartToggles(totalQty) {
    const countLabel = totalQty ? `${totalQty} ta mahsulot` : "Savat";
    if (mobileCartToggle) {
      mobileCartToggle.setAttribute("aria-label", countLabel);
    }
    if (headerCartToggle) {
      headerCartToggle.setAttribute("aria-label", countLabel);
    }
    if (mobileCartBadge) {
      mobileCartBadge.hidden = totalQty <= 0;
      mobileCartBadge.textContent = String(totalQty);
    }
    if (headerCartBadge) {
      headerCartBadge.hidden = totalQty <= 0;
      headerCartBadge.textContent = String(totalQty);
    }
  }

  function scrollActiveCategoryIntoView() {
    const active = document.querySelector(".menu-filter-pill.is-active");
    if (active) {
      active.scrollIntoView({
        behavior: "smooth",
        inline: "center",
        block: "nearest",
      });
    }
  }

  function renderMenuFilters(categories) {
    if (!menuFilters) {
      return;
    }
    menuFilters.hidden = false;
    menuFilters.innerHTML = "";

    const allButton = document.createElement("button");
    allButton.type = "button";
    allButton.className = `menu-filter-pill${activeCategoryId === "all" ? " is-active" : ""}`;
    safeText(allButton, "Barcha");
    allButton.addEventListener("click", function () {
      activeCategoryId = "all";
      renderMenuFilters(menuCategories);
      renderMenu(menuCategories);
    });
    menuFilters.appendChild(allButton);

    categories.forEach((category) => {
      const filterBtn = document.createElement("button");
      filterBtn.type = "button";
      filterBtn.className = `menu-filter-pill${activeCategoryId === String(category.id) ? " is-active" : ""}`;
      safeText(filterBtn, category.title || "");
      filterBtn.addEventListener("click", function () {
        activeCategoryId = String(category.id);
        renderMenuFilters(menuCategories);
        renderMenu(menuCategories);
      });
      menuFilters.appendChild(filterBtn);
    });

    window.requestAnimationFrame(scrollActiveCategoryIntoView);
  }

  function setStatus(message, type) {
    statusEl.textContent = message || "";
    statusEl.classList.remove("is-success", "is-error");
    if (type) {
      statusEl.classList.add(type);
    }
  }

  function setSubmitState(isLoading) {
    isOrderSubmitting = Boolean(isLoading);
    submitBtn.disabled = isOrderSubmitting || cart.size === 0;
    submitBtn.classList.toggle("is-loading", isOrderSubmitting);
    submitBtn.textContent = isOrderSubmitting ? "Yuborilmoqda..." : "Yuborish";
  }

  function setCheckoutAvailability(hasItems) {
    const available = Boolean(hasItems);
    if (cartForm) {
      cartForm.hidden = !available;
      cartForm.setAttribute("aria-hidden", available ? "false" : "true");
    }
    Array.from(orderForm.elements).forEach((control) => {
      if (control !== submitBtn) {
        control.disabled = !available;
      }
    });
    setSubmitState(isOrderSubmitting);
  }

  function setCartNotice(message, type) {
    cartNotice = message ? { message, type: type || "" } : null;
    renderCart();
  }

  function setCartLoading(isLoading) {
    isCartLoading = Boolean(isLoading);
    renderCart();
  }

  function renderFilterSkeleton(count) {
    if (!menuFilters) {
      return;
    }
    menuFilters.hidden = false;
    menuFilters.innerHTML = "";
    for (let i = 0; i < count; i += 1) {
      const pill = document.createElement("span");
      pill.className = "menu-filter-pill menu-filter-skeleton skeleton";
      pill.setAttribute("aria-hidden", "true");
      menuFilters.appendChild(pill);
    }
  }

  function renderMenuError(message) {
    menuEl.innerHTML = "";
    menuEl.removeAttribute("aria-busy");
    if (menuFilters) {
      menuFilters.hidden = true;
      menuFilters.innerHTML = "";
    }

    const block = document.createElement("div");
    block.className = "menu-error-state";
    block.setAttribute("role", "status");

    const title = document.createElement("h3");
    safeText(title, "Menyuni yuklab bo'lmadi");
    block.appendChild(title);

    const copy = document.createElement("p");
    safeText(copy, message || "Internet aloqasi yoki server javobida muammo bor. Qayta urinib ko'ring.");
    block.appendChild(copy);

    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "ghost-btn menu-retry-btn";
    safeText(retry, "Qayta urinish");
    retry.addEventListener("click", function () {
      boot();
    });
    block.appendChild(retry);
    menuEl.appendChild(block);
  }

  function showCartToast(message) {
    if (!cartToast) {
      return;
    }
    cartToast.textContent = message;
    cartToast.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      cartToast.classList.remove("is-visible");
    }, 1800);
  }

  function animateAddButton(button) {
    if (!button) {
      return;
    }
    const original = button.dataset.originalLabel || button.textContent;
    button.dataset.originalLabel = original;
    const lockedWidth = button.offsetWidth;
    if (lockedWidth) {
      button.style.width = `${lockedWidth}px`;
    }
    button.textContent = "Qo'shildi";
    button.disabled = true;
    button.classList.add("is-added");
    window.setTimeout(function () {
      button.textContent = original;
      button.disabled = false;
      button.classList.remove("is-added");
      button.style.width = "";
    }, 480);
  }

  function renderMenuSkeleton(count) {
    menuEl.innerHTML = "";
    menuEl.setAttribute("aria-busy", "true");
    const grid = document.createElement("div");
    grid.className = "menu-section-grid is-skeleton-grid";
    for (let i = 0; i < count; i += 1) {
      const card = document.createElement("div");
      card.className = "menu-card menu-card-skeleton";

      const image = document.createElement("div");
      image.className = "menu-item-image skeleton";
      card.appendChild(image);

      const body = document.createElement("div");
      body.className = "menu-card-body";

      const chip = document.createElement("div");
      chip.className = "skeleton-chip skeleton";
      body.appendChild(chip);

      const title = document.createElement("div");
      title.className = "skeleton-line title skeleton";
      body.appendChild(title);

      const line = document.createElement("div");
      line.className = "skeleton-line body skeleton";
      body.appendChild(line);

      const shortLine = document.createElement("div");
      shortLine.className = "skeleton-line body short skeleton";
      body.appendChild(shortLine);

      card.appendChild(body);
      grid.appendChild(card);
    }
    menuEl.appendChild(grid);
  }

  function clearTenantState() {
    resetBranding();
    promotions = [];
    discountPercent = 0;
    tenantPlan = "basic";
    menuCategories = [];
    activeCategoryId = "all";
    isCartLoading = false;
    cartNotice = null;
    cart.clear();
    menuEl.innerHTML = "";
    if (menuFilters) {
      menuFilters.hidden = false;
      menuFilters.innerHTML = "";
    }
    setStatus("");
    setSubmitState(false);
    setCartOpen(false);
    if (orderForm) {
      orderForm.reset();
    }
    if (siteTitle) {
      siteTitle.textContent = "Qadam menyusi";
    }
    if (footerTitle) {
      footerTitle.textContent = "Qadam";
    }
    if (footerDescription) {
      footerDescription.textContent = "Menyu, buyurtma va yetkazib berish bitta sahifada.";
    }
    if (headerTelegramLink) {
      headerTelegramLink.style.display = "";
      headerTelegramLink.href = "#";
    }
    if (footerTelegramLink) {
      footerTelegramLink.textContent = "Mavjud emas";
      footerTelegramLink.href = "#";
    }
    renderCart();
  }

  function enforceSlugChangeReload() {
    const currentSlug = extractSlug();
    if (activeSlug && currentSlug && currentSlug !== activeSlug) {
      clearTenantState();
      window.location.reload();
    }
  }

  function addToCart(item, triggerButton) {
    const current = cart.get(item.id) || { item, qty: 0 };
    current.qty += 1;
    cart.set(item.id, current);
    cartNotice = null;
    setStatus("");
    saveCartState();
    animateAddButton(triggerButton);
    showCartToast(`${item.name || "Taom"} savatga qo'shildi`);
    renderCart();
  }

  function updateQty(id, delta) {
    const current = cart.get(id);
    if (!current) {
      return;
    }
    current.qty += delta;
    if (current.qty <= 0) {
      cart.delete(id);
    } else {
      cart.set(id, current);
    }
    saveCartState();
    renderCart();
  }

  function clearCart() {
    cart.clear();
    cartNotice = null;
    saveCartState();
    renderCart();
  }

  function removeFromCart(id) {
    cart.delete(id);
    saveCartState();
    renderCart();
  }

  function renderCart() {
    cartList.innerHTML = "";
    const items = Array.from(cart.values());
    const totalQty = items.reduce((sum, entry) => sum + entry.qty, 0);
    if (cartCount) {
      cartCount.textContent = `${totalQty} ta mahsulot`;
    }
    updateCartToggles(totalQty);
    clearBtn.disabled = !items.length;
    if (!items.length) {
      cartEmpty.style.display = "block";
      cartEmpty.classList.toggle("is-success", Boolean(cartNotice && cartNotice.type === "is-success"));
      cartEmpty.classList.toggle("is-error", Boolean(cartNotice && cartNotice.type === "is-error"));
      cartEmpty.textContent = cartNotice
        ? cartNotice.message
        : isCartLoading
        ? "Savat tiklanmoqda..."
        : "Savat hozircha bo'sh. Yoqtirgan taomingizni qo'shing.";
      cartTotal.textContent = formatPrice(0);
      setCheckoutAvailability(false);
      if (scrollToFormFab) {
        scrollToFormFab.classList.remove("visible");
      }
      return;
    }
    cartEmpty.style.display = "none";
    cartEmpty.classList.remove("is-success", "is-error");
    setCheckoutAvailability(true);
    let total = 0;
    items.forEach(({ item, qty }) => {
      const li = document.createElement("li");
      li.className = "cart-item";
      const lineTotal = effectivePrice(item.price) * qty;
      total += lineTotal;

      const main = document.createElement("div");
      main.className = "cart-item-main";

      const info = document.createElement("div");
      const name = document.createElement("p");
      name.className = "cart-item-name";
      safeText(name, item.name);
      info.appendChild(name);

      const sub = document.createElement("p");
      sub.className = "cart-item-sub";
      safeText(sub, `${formatPrice(effectivePrice(item.price))} / dona`);
      info.appendChild(sub);

      main.appendChild(info);
      li.appendChild(main);

      const qtyControl = document.createElement("div");
      qtyControl.className = "cart-qty";

      const minusBtn = document.createElement("button");
      minusBtn.type = "button";
      minusBtn.className = "cart-qty-btn";
      minusBtn.setAttribute("aria-label", `${item.name} sonini kamaytirish`);
      safeText(minusBtn, "-");
      minusBtn.addEventListener("click", function () {
        updateQty(item.id, -1);
      });

      const qtyValue = document.createElement("span");
      qtyValue.className = "cart-qty-value";
      safeText(qtyValue, String(qty));

      const plusBtn = document.createElement("button");
      plusBtn.type = "button";
      plusBtn.className = "cart-qty-btn";
      plusBtn.setAttribute("aria-label", `${item.name} sonini oshirish`);
      safeText(plusBtn, "+");
      plusBtn.addEventListener("click", function () {
        updateQty(item.id, 1);
      });

      qtyControl.appendChild(minusBtn);
      qtyControl.appendChild(qtyValue);
      qtyControl.appendChild(plusBtn);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "cart-remove-btn";
      removeBtn.setAttribute("aria-label", `${item.name} ni olib tashlash`);
      removeBtn.textContent = "x";
      removeBtn.addEventListener("click", function () {
        removeFromCart(item.id);
      });

      const side = document.createElement("div");
      side.className = "cart-item-side";

      const topLine = document.createElement("div");
      topLine.className = "cart-item-topline";

      const price = document.createElement("span");
      price.className = "cart-item-price";
      safeText(price, formatPrice(lineTotal));

      topLine.appendChild(price);
      topLine.appendChild(removeBtn);

      const actions = document.createElement("div");
      actions.className = "cart-item-actions";
      actions.appendChild(qtyControl);
      side.appendChild(topLine);
      side.appendChild(actions);
      li.appendChild(side);
      cartList.appendChild(li);
    });
    cartTotal.textContent = formatPrice(total);
    window.requestAnimationFrame(updateScrollFab);
  }

  function publicErrorDetail(value) {
    let detail = "";
    if (typeof value === "string") {
      detail = value;
    } else if (value && typeof value === "object") {
      detail = value.detail || value.message || value.error || "";
    }
    detail = String(detail || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    if (!detail || /traceback|stack trace|exception|sqlalchemy|sqlite|\.py:\d+/i.test(detail)) {
      return "";
    }
    return detail.slice(0, 120);
  }

  async function orderErrorMessage(res) {
    let detail = "";
    try {
      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        detail = publicErrorDetail(await res.json());
      } else {
        detail = publicErrorDetail(await res.text());
      }
    } catch (_) {
      detail = "";
    }
    const base = "Buyurtmani yuborib bo'lmadi. Qayta urinib ko'ring.";
    return detail ? `${base} Server xabari: ${detail}` : base;
  }

  function renderMenu(categories) {
    menuEl.innerHTML = "";
    menuEl.removeAttribute("aria-busy");
    const grid = document.createElement("div");
    grid.className = "menu-section-grid";
    let renderedSections = 0;
    const visibleCategories = categories.filter((cat) => {
      if (activeCategoryId === "all") {
        return true;
      }
      return String(cat.id) === activeCategoryId;
    });

    visibleCategories.forEach((cat) => {
      const items = Array.isArray(cat.items) ? cat.items : [];
      if (!items.length) {
        return;
      }

      items.forEach((item) => {
        const card = document.createElement("div");
        card.className = "menu-card";

        if (cat.title && cat.title.toLowerCase().includes("maxs")) {
          const badge = document.createElement("div");
          badge.className = "badge-green";
          safeText(badge, "100% tabiy");
          card.appendChild(badge);
        }

        const itemPromo = promotions.find(
          (p) => p.type === "item_of_the_day" && String(p.product_id) === String(item.id)
        );
        if (itemPromo) {
          const badge = document.createElement("div");
          badge.className = "badge-promo";
          safeText(badge, "Kun tavsiyasi");
          card.appendChild(badge);
        }

        if (discountPercent) {
          const badge = document.createElement("div");
          badge.className = "badge-promo-alt";
          safeText(badge, `Aksiya -${discountPercent}%`);
          card.appendChild(badge);
        }

        const imageWrap = document.createElement("div");
        imageWrap.className = "menu-item-image";
        const imageUrl = item.image || item.image_url;
        if (isRenderableImageUrl(imageUrl)) {
          const img = document.createElement("img");
          img.src = imageUrl;
          img.alt = item.name || "";
          img.loading = "lazy";
          img.className = "menu-image-loading";
          img.addEventListener("load", function () {
            img.classList.add("is-loaded");
            img.classList.remove("menu-image-loading");
          });
          img.addEventListener("error", function () {
            img.classList.remove("menu-image-loading");
            imageWrap.innerHTML = "";
            const fallback = document.createElement("div");
            fallback.className = "img-placeholder";
            safeText(fallback, item.name || "");
            imageWrap.appendChild(fallback);
          });
          imageWrap.appendChild(img);
        } else {
          const img = document.createElement("div");
          img.className = "img-placeholder";
          safeText(img, item.name || "");
          imageWrap.appendChild(img);
        }
        card.appendChild(imageWrap);

        const body = document.createElement("div");
        body.className = "menu-card-body";

        const title = document.createElement("h4");
        title.className = "menu-item-title";
        safeText(title, item.name);
        body.appendChild(title);

        if (item.description) {
          const desc = document.createElement("p");
          desc.className = "menu-card-desc";
          safeText(desc, item.description || "");
          body.appendChild(desc);
        }

        card.appendChild(body);

        const priceRow = document.createElement("div");
        priceRow.className = "price-row";
        const price = document.createElement("div");
        price.className = "price menu-item-price";
        safeText(price, formatPrice(effectivePrice(item.price)));
        if (discountPercent) {
          const note = document.createElement("div");
          note.className = "promo-note";
          safeText(note, `Avval: ${formatPrice(item.price)}`);
          price.appendChild(note);
        }
        const btn = document.createElement("button");
        btn.className = "add-btn";
        btn.type = "button";
        safeText(btn, "Qo'shish");
        btn.addEventListener("click", function () {
          addToCart(item, btn);
        });
        priceRow.appendChild(price);
        priceRow.appendChild(btn);
        card.appendChild(priceRow);
        grid.appendChild(card);
      });
      renderedSections += 1;
    });

    if (!renderedSections) {
      menuEl.removeAttribute("aria-busy");
      menuEl.innerHTML = `<div class="empty-state compact">Bu bo'limda hozircha taom yo'q.</div>`;
      return;
    }
    menuEl.appendChild(grid);
  }

  async function loadTenant() {
    const res = await fetch(tenantPath("/tenant"), { credentials: "same-origin" });
    if (!res.ok) {
      throw new Error("Tenant not found");
    }
    const data = await res.json();
    applyTenantBranding(data);
    tenantPlan = data.plan || "basic";
    if (data.name) {
      heroTitle.textContent = data.name;
      if (siteTitle) {
        siteTitle.textContent = data.name;
      }
      if (footerTitle) {
        footerTitle.textContent = data.name;
      }
    }
    if (data.description) {
      heroDesc.textContent = data.description;
      if (footerDescription) {
        footerDescription.textContent = data.description;
      }
    }
    if (isRenderableImageUrl(data.hero_image)) {
      heroMedia.style.backgroundImage = `url("${data.hero_image}")`;
      heroMedia.classList.remove("hero-fallback");
    } else {
      heroMedia.classList.add("hero-fallback");
      heroMedia.style.backgroundImage = "";
    }

    if (ordersLink) {
      ordersLink.href = `/t/${encodeURIComponent(activeSlug)}/my-orders`;
    }
    if (adminLink) {
      adminLink.href = `/t/${encodeURIComponent(activeSlug)}/admin`;
    }
    if (tenantPlan === "basic") {
      if (ordersLink) {
        ordersLink.style.display = "none";
      }
      if (adminLink) {
        adminLink.style.display = "none";
      }
    } else {
      if (ordersLink) {
        ordersLink.style.display = "";
      }
      if (adminLink) {
        adminLink.style.display = "";
      }
    }

    const botUsername = (data.bot_username || "").replace(/^@+/, "");
    const botUsernameValid = /^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(botUsername);
    if (data.bot_enabled && botUsernameValid) {
      const link = `https://t.me/${botUsername}`;
      if (headerTelegramLink) {
        headerTelegramLink.href = link;
        headerTelegramLink.textContent = "Telegram";
        headerTelegramLink.style.display = "";
      }
      if (footerTelegramLink) {
        footerTelegramLink.textContent = `@${botUsername}`;
        footerTelegramLink.href = link;
      }
      if (footerPhone) {
        footerPhone.textContent = "Aloqa Telegram orqali";
      }
    } else {
      if (headerTelegramLink) {
        headerTelegramLink.style.display = "none";
      }
      if (footerTelegramLink) {
        footerTelegramLink.textContent = "Mavjud emas";
        footerTelegramLink.removeAttribute("href");
      }
      if (footerPhone) {
        footerPhone.textContent = "Telefon raqami mavjud emas";
      }
    }

    if (footerAddress) {
      footerAddress.textContent = "Yetkazib berish manzili buyurtma vaqtida aniqlanadi";
    }
    if (footerHours) {
      footerHours.textContent = "Har kuni 10:00 - 22:00";
    }
  }

  async function loadPromotions() {
    if (tenantPlan === "basic") {
      promotions = [];
      discountPercent = 0;
      return;
    }
    const res = await fetch(tenantPath("/api/promotions"), { credentials: "same-origin" });
    if (!res.ok) {
      promotions = [];
      discountPercent = 0;
      return;
    }
    const data = await res.json();
    promotions = data.items || [];
    discountPercent = promotions
      .filter((p) => p.type === "happy_hours" && p.discount_percent)
      .reduce((acc, p) => Math.max(acc, p.discount_percent), 0);
  }

  async function loadMenu() {
    renderFilterSkeleton(4);
    renderMenuSkeleton(9);
    const res = await fetch(tenantPath("/menu"), { credentials: "same-origin" });
    if (!res.ok) {
      throw new Error("Menu yuklab bo'lmadi");
    }
    const data = await res.json();
    menuCategories = data.categories || [];
    if (activeCategoryId !== "all" && !menuCategories.some((cat) => String(cat.id) === activeCategoryId)) {
      activeCategoryId = "all";
    }
    renderMenuFilters(menuCategories);
    renderMenu(menuCategories);
    restoreCartState(menuCategories);
    isCartLoading = false;
    renderCart();
  }

  async function submitOrder(evt) {
    evt.preventDefault();
    setStatus("");
    if (!cart.size) {
      setCartNotice("Savat bo'sh. Avval taom qo'shing.", "is-error");
      setCartOpen(true);
      return;
    }
    cartNotice = null;
    renderCart();
    try {
      const form = new FormData(orderForm);
      const payload = {
        items: Array.from(cart.values()).map(({ item, qty }) => ({ item_id: item.id, qty })),
        customer: {
          name: (form.get("name") || "").trim(),
          phone: (form.get("phone") || "").trim(),
          address: (form.get("address") || "").trim(),
          comment: (form.get("comment") || "-").trim() || "-",
        },
        source: "site",
      };
      if (!payload.customer.name || !payload.customer.phone || !payload.customer.address) {
        setStatus("Ism, telefon va manzilni to'ldiring.", "is-error");
        setCartOpen(true);
        return;
      }
      setSubmitState(true);
      const res = await fetch(tenantPath("/orders"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "same-origin",
      });
      if (!res.ok) {
        throw new Error(await orderErrorMessage(res));
      }
      const data = await res.json();
      cart.clear();
      saveCartState();
      orderForm.reset();
      setCartNotice(
        `Buyurtma qabul qilindi: #${data.order_id}. Tez orada siz bilan bog'lanamiz. Rahmat!`,
        "is-success"
      );
      showCartToast("Buyurtmangiz qabul qilindi");
      setCartOpen(true);
    } catch (err) {
      setStatus((err && err.message) || "Buyurtmani yuborib bo'lmadi. Qayta urinib ko'ring.", "is-error");
      setCartOpen(true);
    } finally {
      setSubmitState(false);
    }
  }

  async function boot() {
    clearTenantState();
    activeSlug = extractSlug();
    if (!activeSlug) {
      setStatus(tenantRequiredError, "is-error");
      menuEl.innerHTML = `<p class="muted">${tenantRequiredError}</p>`;
      return;
    }
    renderMenuSkeleton(9);
    renderFilterSkeleton(4);
    setCartLoading(true);
    try {
      await loadTenant();
      await loadPromotions();
      await loadMenu();
    } catch (err) {
      const message = (err && err.message) || "Xatolik";
      setCartLoading(false);
      setStatus(message, "is-error");
      renderMenuError(message);
    }
  }

  orderForm.setAttribute("novalidate", "");
  clearBtn.addEventListener("click", clearCart);
  orderForm.addEventListener("submit", submitOrder);
  cartTriggers.forEach((trigger) => {
    trigger.addEventListener("click", function () {
      lastCartTrigger = trigger;
      setCartOpen(true);
    });
  });
  if (mobileCartClose) {
    mobileCartClose.addEventListener("click", function () {
      setCartOpen(false);
    });
  }
  if (mobileCartBackdrop) {
    mobileCartBackdrop.addEventListener("click", function () {
      setCartOpen(false);
    });
  }
  if (scrollToFormFab) {
    scrollToFormFab.addEventListener("click", function () {
      if (!cartForm) {
        return;
      }
      cartForm.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    });
  }
  if (cartScroll) {
    cartScroll.addEventListener("scroll", updateScrollFab);
  }
  window.addEventListener("resize", updateScrollFab);
  heroCta.addEventListener("click", function () {
    const discovery = document.querySelector(".menu-discovery");
    if (discovery) {
      discovery.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  window.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      setCartOpen(false);
    }
  });

  window.addEventListener("popstate", enforceSlugChangeReload);
  window.setInterval(enforceSlugChangeReload, 1000);

  if (cartPane) {
    cartPane.setAttribute("inert", "");
  }

  boot();
})();
