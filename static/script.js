(function () {
  const menuEl = document.getElementById("menu");
  const cartList = document.getElementById("cart-list");
  const cartEmpty = document.getElementById("cart-empty");
  const cartTotal = document.getElementById("cart-total");
  const clearBtn = document.getElementById("clear-cart");
  const orderForm = document.getElementById("order-form");
  const submitBtn = document.getElementById("submit-order");
  const statusEl = document.getElementById("order-status");
  const heroTitle = document.getElementById("hero-title");
  const heroDesc = document.getElementById("hero-desc");
  const heroMedia = document.getElementById("hero-media");
  const heroCta = document.getElementById("hero-cta");
  const ordersLink = document.getElementById("orders-link");
  const adminLink = document.getElementById("admin-link");
  const botLink = document.getElementById("bot-link");
  const botQr = document.getElementById("bot-qr");

  if (!menuEl || !orderForm || !statusEl) {
    return;
  }

  const tenantRequiredError = "Tenant slug required. Open page as /t/<slug>";
  const cart = new Map();

  let activeSlug = "";
  let promotions = [];
  let discountPercent = 0;
  let tenantPlan = "basic";

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

  function clearTenantState() {
    promotions = [];
    discountPercent = 0;
    tenantPlan = "basic";
    cart.clear();
    cartList.innerHTML = "";
    cartEmpty.style.display = "block";
    cartTotal.textContent = "";
    menuEl.innerHTML = "";
    statusEl.textContent = "";
    if (orderForm) {
      orderForm.reset();
    }
  }

  function enforceSlugChangeReload() {
    const currentSlug = extractSlug();
    if (activeSlug && currentSlug && currentSlug !== activeSlug) {
      clearTenantState();
      window.location.reload();
    }
  }

  function addToCart(item) {
    const current = cart.get(item.id) || { item, qty: 0 };
    current.qty += 1;
    cart.set(item.id, current);
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

  function renderCart() {
    cartList.innerHTML = "";
    const items = Array.from(cart.values());
    if (!items.length) {
      cartEmpty.style.display = "block";
      cartTotal.textContent = "";
      return;
    }
    cartEmpty.style.display = "none";
    let total = 0;
    items.forEach(({ item, qty }) => {
      const li = document.createElement("li");
      li.className = "cart-item";
      const lineTotal = effectivePrice(item.price) * qty;
      total += lineTotal;
      const left = document.createElement("span");
      safeText(left, `${item.name} x${qty}`);
      const right = document.createElement("span");
      safeText(right, formatPrice(lineTotal));
      li.appendChild(left);
      li.appendChild(right);
      li.addEventListener("click", function () {
        updateQty(item.id, -1);
      });
      cartList.appendChild(li);
    });
    cartTotal.textContent = "Jami: " + formatPrice(total);
  }

  function renderMenu(categories) {
    menuEl.innerHTML = "";
    categories.forEach((cat) => {
      (cat.items || []).forEach((item) => {
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
          safeText(badge, "Item of the day");
          card.appendChild(badge);
        }

        if (discountPercent) {
          const badge = document.createElement("div");
          badge.className = "badge-promo-alt";
          safeText(badge, `Happy hours -${discountPercent}%`);
          card.appendChild(badge);
        }

        const imageWrap = document.createElement("div");
        imageWrap.className = "menu-item-image";
        if (isRenderableImageUrl(item.image_url)) {
          const img = document.createElement("img");
          img.src = item.image_url;
          img.alt = item.name || "";
          img.loading = "lazy";
          imageWrap.appendChild(img);
        } else {
          const img = document.createElement("div");
          img.className = "img-placeholder";
          safeText(img, item.name || "");
          imageWrap.appendChild(img);
        }
        card.appendChild(imageWrap);

        const title = document.createElement("h4");
        safeText(title, item.name);
        card.appendChild(title);

        const desc = document.createElement("p");
        safeText(desc, item.description || "");
        card.appendChild(desc);

        const priceRow = document.createElement("div");
        priceRow.className = "price-row";
        const price = document.createElement("div");
        price.className = "price";
        safeText(price, formatPrice(effectivePrice(item.price)));
        if (discountPercent) {
          const note = document.createElement("div");
          note.className = "promo-note";
          safeText(note, `Old: ${formatPrice(item.price)}`);
          price.appendChild(note);
        }
        const btn = document.createElement("button");
        btn.className = "add-btn";
        btn.type = "button";
        safeText(btn, "+");
        btn.addEventListener("click", function () {
          addToCart(item);
        });
        priceRow.appendChild(price);
        priceRow.appendChild(btn);
        card.appendChild(priceRow);
        menuEl.appendChild(card);
      });
    });
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
    }
    if (data.description) {
      heroDesc.textContent = data.description;
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
      if (botLink) {
        botLink.textContent = `@${botUsername}`;
        botLink.href = link;
      }
      if (botQr) {
        botQr.src = `https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=${encodeURIComponent(link)}`;
      }
    } else {
      if (botLink) {
        botLink.textContent = "Bot mavjud emas";
      }
      if (botQr) {
        botQr.removeAttribute("src");
      }
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
    const res = await fetch(tenantPath("/menu"), { credentials: "same-origin" });
    if (!res.ok) {
      throw new Error("Menu yuklab bo'lmadi");
    }
    const data = await res.json();
    renderMenu(data.categories || []);
  }

  async function submitOrder(evt) {
    evt.preventDefault();
    statusEl.textContent = "";
    if (!cart.size) {
      statusEl.textContent = "Savat bo'sh. Avval menyudan qo'shing.";
      return;
    }
    submitBtn.disabled = true;
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
      statusEl.textContent = `Buyurtma qabul qilindi: #${data.order_id}`;
      clearCart();
      orderForm.reset();
    } catch (err) {
      statusEl.textContent = (err && err.message) || "Xatolik";
    } finally {
      submitBtn.disabled = false;
    }
  }

  async function boot() {
    clearTenantState();
    activeSlug = extractSlug();
    if (!activeSlug) {
      statusEl.textContent = tenantRequiredError;
      menuEl.innerHTML = `<p class="muted">${tenantRequiredError}</p>`;
      return;
    }
    try {
      await loadTenant();
      await loadPromotions();
      await loadMenu();
    } catch (err) {
      const message = (err && err.message) || "Xatolik";
      statusEl.textContent = message;
      menuEl.innerHTML = `<p class="muted">${message}</p>`;
    }
  }

  clearBtn.addEventListener("click", clearCart);
  orderForm.addEventListener("submit", submitOrder);
  heroCta.addEventListener("click", function () {
    document.getElementById("menu").scrollIntoView({ behavior: "auto" });
  });
  window.addEventListener("popstate", enforceSlugChangeReload);
  window.setInterval(enforceSlugChangeReload, 1000);

  boot();
})();
