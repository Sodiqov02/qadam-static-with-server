(function () {
  const menuEl = document.getElementById("menu");
  const menuFilters = document.getElementById("menu-filters");
  const cartList = document.getElementById("cart-list");
  const cartEmpty = document.getElementById("cart-empty");
  const cartCount = document.getElementById("cart-count");
  const cartTotal = document.getElementById("cart-total");
  const cartToast = document.getElementById("cart-toast");
  const cartPane = document.querySelector(".cart-pane");
  const clearBtn = document.getElementById("clear-cart");
  const mobileCartToggle = document.getElementById("mobile-cart-toggle");
  const headerCartToggle = document.getElementById("header-cart-toggle");
  const mobileCartBadge = document.getElementById("mobile-cart-badge");
  const headerCartBadge = document.getElementById("header-cart-badge");
  const mobileCartClose = document.getElementById("mobile-cart-close");
  const mobileCartBackdrop = document.getElementById("mobile-cart-backdrop");
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
  const botLink = document.getElementById("bot-link");
  const botQr = document.getElementById("bot-qr");
  const botMeta = document.getElementById("bot-meta");
  const siteTitle = document.getElementById("site-title");
  const footerTitle = document.getElementById("footer-title");
  const footerDescription = document.getElementById("footer-description");
  const footerTelegramLink = document.getElementById("footer-telegram-link");
  const footerPhone = document.getElementById("footer-phone");
  const footerAddress = document.getElementById("footer-address");
  const footerHours = document.getElementById("footer-hours");
  const cartTriggers = document.querySelectorAll(".cart-trigger");

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
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (_) {
      return false;
    }
  }

  function safeText(el, text) {
    el.textContent = text ?? "";
    return el;
  }

  function formatPrice(n) {
    return `${Number(n || 0).toLocaleString("ru-RU")} so'm`;
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

  function renderMenuFilters(categories) {
    if (!menuFilters) {
      return;
    }
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
  }

  function setStatus(message, type) {
    statusEl.textContent = message || "";
    statusEl.classList.remove("is-success", "is-error");
    if (type) {
      statusEl.classList.add(type);
    }
  }

  function setSubmitState(isLoading) {
    submitBtn.disabled = isLoading;
    submitBtn.classList.toggle("is-loading", isLoading);
    submitBtn.textContent = isLoading ? "Yuborilmoqda..." : "Yuborish";
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
    button.classList.add("is-added");
    window.setTimeout(function () {
      button.classList.remove("is-added");
    }, 320);
  }

  function renderMenuSkeleton(count) {
    menuEl.innerHTML = "";
    const grid = document.createElement("div");
    grid.className = "menu-section-grid is-skeleton-grid";
    for (let i = 0; i < count; i += 1) {
      const card = document.createElement("div");
      card.className = "menu-card menu-card-skeleton";

      const image = document.createElement("div");
      image.className = "menu-item-image";
      card.appendChild(image);

      const body = document.createElement("div");
      body.className = "menu-card-body";

      const chip = document.createElement("div");
      chip.className = "skeleton-chip";
      body.appendChild(chip);

      const title = document.createElement("div");
      title.className = "skeleton-line title";
      body.appendChild(title);

      const line = document.createElement("div");
      line.className = "skeleton-line body";
      body.appendChild(line);

      const shortLine = document.createElement("div");
      shortLine.className = "skeleton-line body short";
      body.appendChild(shortLine);

      card.appendChild(body);
      grid.appendChild(card);
    }
    menuEl.appendChild(grid);
  }

  function clearTenantState() {
    promotions = [];
    discountPercent = 0;
    tenantPlan = "basic";
    menuCategories = [];
    activeCategoryId = "all";
    cart.clear();
    menuEl.innerHTML = "";
    if (menuFilters) {
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
    if (botLink) {
      botLink.textContent = "@bot";
      botLink.href = "#";
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
    renderCart();
  }

  function clearCart() {
    cart.clear();
    renderCart();
  }

  function removeFromCart(id) {
    cart.delete(id);
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
      cartTotal.textContent = formatPrice(0);
      return;
    }
    cartEmpty.style.display = "none";
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
      safeText(sub, `${formatPrice(effectivePrice(item.price))} x ${qty}`);
      info.appendChild(sub);

      const price = document.createElement("span");
      price.className = "cart-item-price";
      safeText(price, formatPrice(lineTotal));

      main.appendChild(info);
      main.appendChild(price);
      li.appendChild(main);

      const actions = document.createElement("div");
      actions.className = "cart-item-actions";

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
      safeText(removeBtn, "Olib tashlash");
      removeBtn.addEventListener("click", function () {
        removeFromCart(item.id);
      });

      actions.appendChild(qtyControl);
      actions.appendChild(removeBtn);
      li.appendChild(actions);
      cartList.appendChild(li);
    });
    cartTotal.textContent = formatPrice(total);
  }

  function renderMenu(categories) {
    menuEl.innerHTML = "";
    let renderedSections = 0;
    const visibleCategories = categories.filter((cat) => {
      if (activeCategoryId === "all") {
        return true;
      }
      return String(cat.id) === activeCategoryId;
    });

    visibleCategories.forEach((cat) => {
      const items = Array.isArray(cat.items) ? cat.items : [];
      if (!items.length && activeCategoryId === "all") {
        return;
      }

      const section = document.createElement("section");
      section.className = "menu-section";

      if (cat.title || cat.description) {
        const head = document.createElement("div");
        head.className = "menu-section-head";

        if (cat.title) {
          const title = document.createElement("h3");
          title.className = "menu-section-title";
          safeText(title, cat.title);
          head.appendChild(title);
        }

        if (cat.description) {
          const subtitle = document.createElement("p");
          subtitle.className = "menu-section-subtitle";
          safeText(subtitle, cat.description);
          head.appendChild(subtitle);
        }

        section.appendChild(head);
      }

      const sectionGrid = document.createElement("div");
      sectionGrid.className = "menu-section-grid";

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
            img.classList.remove("menu-image-loading");
          });
          img.addEventListener("error", function () {
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
        price.className = "price";
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
        sectionGrid.appendChild(card);
      });

      if (items.length) {
        section.appendChild(sectionGrid);
      } else {
        const empty = document.createElement("p");
        empty.className = "muted";
        safeText(empty, "Bu bo'limda hozircha taom yo'q.");
        section.appendChild(empty);
      }

      menuEl.appendChild(section);
      renderedSections += 1;
    });

    if (!renderedSections) {
      menuEl.innerHTML = `<div class="empty-state compact">Bu bo'limda hozircha taom yo'q.</div>`;
    }
  }

  async function loadTenant() {
    const res = await fetch(tenantPath("/tenant"), { credentials: "same-origin" });
    if (!res.ok) {
      throw new Error("Tenant not found");
    }
    const data = await res.json();
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

    const botUsername = (data.bot_username || "").replace("@", "");
    if (data.bot_enabled && botUsername) {
      const link = `https://t.me/${botUsername}`;
      if (headerTelegramLink) {
        headerTelegramLink.href = link;
        headerTelegramLink.textContent = "Telegram";
        headerTelegramLink.style.display = "";
      }
      if (botLink) {
        botLink.textContent = `@${botUsername}`;
        botLink.href = link;
      }
      if (footerTelegramLink) {
        footerTelegramLink.textContent = `@${botUsername}`;
        footerTelegramLink.href = link;
      }
      if (botQr) {
        botQr.src = `https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=${encodeURIComponent(link)}`;
      }
      if (botMeta) {
        botMeta.textContent = "Tezkor buyurtma va aloqa uchun Telegram botga o'ting";
      }
      if (footerPhone) {
        footerPhone.textContent = "Aloqa Telegram orqali";
      }
    } else {
      if (headerTelegramLink) {
        headerTelegramLink.style.display = "none";
      }
      if (botLink) {
        botLink.textContent = "Bot mavjud emas";
        botLink.removeAttribute("href");
      }
      if (footerTelegramLink) {
        footerTelegramLink.textContent = "Mavjud emas";
        footerTelegramLink.removeAttribute("href");
      }
      if (botQr) {
        botQr.removeAttribute("src");
      }
      if (botMeta) {
        botMeta.textContent = "Telegram bot ulanmagan";
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
    renderMenuSkeleton(6);
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
  }

  async function submitOrder(evt) {
    evt.preventDefault();
    setStatus("");
    if (!cart.size) {
      setStatus("Savat bo'sh. Avval menyudan qo'shing.", "is-error");
      return;
    }
    setSubmitState(true);
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
      const res = await fetch(tenantPath("/orders"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "same-origin",
      });
      if (!res.ok) {
        throw new Error("Yuborishda xatolik");
      }
      const data = await res.json();
      setStatus(`Buyurtma qabul qilindi: #${data.order_id}`, "is-success");
      showCartToast("Buyurtmangiz muvaffaqiyatli yuborildi");
      setCartOpen(false);
      clearCart();
      orderForm.reset();
    } catch (err) {
      setStatus((err && err.message) || "Xatolik", "is-error");
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
    renderMenuSkeleton(6);
    try {
      await loadTenant();
      await loadPromotions();
      await loadMenu();
    } catch (err) {
      const message = (err && err.message) || "Xatolik";
      setStatus(message, "is-error");
      menuEl.innerHTML = `<p class="muted">${message}</p>`;
    }
  }

  clearBtn.addEventListener("click", clearCart);
  orderForm.addEventListener("submit", submitOrder);
  cartTriggers.forEach((trigger) => {
    trigger.addEventListener("click", function () {
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

  boot();
})();
