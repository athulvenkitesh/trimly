const API = "/api/v1";
const $ = (selector) => document.querySelector(selector);
const state = { token: localStorage.getItem("trimly_access_token"), email: null, results: [], currentShop: null, booking: null, method: "upi", map: null, mapMarkers: [], reviewRating: 0, registerRole: "CUSTOMER", origin: null };

const stars = (avg) => { const full = Math.round(avg); return "★".repeat(full) + "☆".repeat(5 - full); };

const money = (paise) => `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const fmtSlot = (iso) => new Date(iso).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: true });

function toast(title, message = "", kind = "success") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.innerHTML = `<div class="toast-icon">${kind === "success" ? "✓" : "!"}</div><div class="toast-copy"><b></b><span></span></div><button class="toast-close" aria-label="Dismiss">×</button>`;
  node.querySelector("b").textContent = title;
  node.querySelector("span").textContent = message;
  node.querySelector("button").onclick = () => { node.classList.add("toast-hide"); setTimeout(() => node.remove(), 200); };
  $("#toast-region").append(node);
  setTimeout(() => node.remove(), 5200);
}

function setMessage(selector, text = "", success = false) {
  const node = $(selector); node.textContent = text; node.classList.toggle("success", success);
}
function errorText(error) {
  if (typeof error?.detail === "string") return error.detail;
  if (Array.isArray(error?.detail)) return error.detail.map((item) => `${item.loc?.slice(-1)[0] || "Input"}: ${item.msg}`).join(" ");
  if (error?.detail?.message) return error.detail.message;
  return error?.message || "Something went wrong. Please try again.";
}

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API}${path}`, { ...options, headers });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) { if (response.status === 401) signOut(); throw { ...body, status: response.status }; }
  return body;
}

// ── Auth ────────────────────────────────────────────────────────────────
function showAuth(mode = "register") {
  $("#auth-screen").hidden = false; $("#app-screen").hidden = true;
  const register = mode === "register";
  $("#register-form").hidden = !register; $("#login-form").hidden = register;
  $("#register-copy").hidden = !register; $("#login-copy").hidden = register;
  $("#switch-register").hidden = !register; $("#switch-login").hidden = register;
  setMessage("#auth-message");
  if (register) applyRole(state.registerRole || "CUSTOMER");
}
function applyRole(role) {
  const customer = role !== "SHOP_OWNER";
  state.registerRole = customer ? "CUSTOMER" : "SHOP_OWNER";
  $("#register-form").role.value = state.registerRole;
  $("#register-role-headline").textContent = customer ? "Find a barber and book a slot." : "List your shop and manage appointments.";
  $("#register-role-headline").hidden = false;
  $("#register-submit-label").textContent = customer ? "Create account" : "Create vendor account";
  $("#vendor-copy").firstChild.textContent = customer ? "Want to list your shop? " : "Booking haircuts instead? ";
  $("#vendor-create").textContent = customer ? "Create a vendor account" : "Create a customer account";
}
const OWNER_PORTAL = "/dashboard/";
function goToOwnerPortal() {
  toast("Owner account", "Taking you to the owner dashboard…");
  setTimeout(() => { window.location.href = OWNER_PORTAL; }, 600);
}
async function bootApp(me = null) {
  try {
    me = me || await request("/auth/me");
    if (me.role !== "CUSTOMER") { goToOwnerPortal(); return; }
    state.email = me.email;
    $("#user-email").textContent = me.email;
    $("#auth-screen").hidden = true; $("#app-screen").hidden = false;
    showView("discover");
  } catch (error) { signOut(errorText(error)); }
}
function signOut(message = "") {
  state.token = null; state.email = null;
  localStorage.removeItem("trimly_access_token"); localStorage.removeItem("trimly_refresh_token");
  showAuth("login");
  if (message) setMessage("#auth-message", message);
}

function showView(view) {
  $("#discover-view").hidden = view !== "discover";
  $("#shop-view").hidden = view !== "shop";
  $("#bookings-view").hidden = view !== "bookings";
  if (view === "bookings") loadMyBookings();
}

// ── Discovery ───────────────────────────────────────────────────────────
function renderResults(shops, heading) {
  state.results = shops;
  $("#results-meta").textContent = heading;
  $("#results-empty").hidden = shops.length > 0;
  $("#results").replaceChildren(...shops.map((shop) => {
    const card = document.createElement("article");
    card.className = "result-card";
    card.innerHTML = `<h3></h3><div class="meta"></div><div class="rating-line"></div><div class="meta fee"></div><span class="distance"></span>`;
    card.querySelector("h3").textContent = shop.name;
    card.querySelector(".meta").textContent = shop.address || "Address not set";
    const ratingLine = card.querySelector(".rating-line");
    if (shop.rating_count > 0) {
      ratingLine.innerHTML = `<span class="stars"></span> <b></b> <small></small>`;
      ratingLine.querySelector(".stars").textContent = stars(shop.rating_avg);
      ratingLine.querySelector("b").textContent = shop.rating_avg;
      ratingLine.querySelector("small").textContent = `(${shop.rating_count} review${shop.rating_count === 1 ? "" : "s"})`;
    } else {
      ratingLine.innerHTML = `<span class="no-ratings">No ratings yet</span>`;
    }
    card.querySelector(".fee").innerHTML = `Convenience fee <b>${money(shop.convenience_fee_paise)}</b>`;
    card.querySelector(".distance").textContent = shop.distance_km != null ? `${shop.distance_km} km away` : "";
    card.onclick = () => openShop(shop.id);
    return card;
  }));
  if (!$("#map-panel").hidden) drawMapPins();
}

async function searchText(event) {
  event.preventDefault();
  const query = $("#search-input").value.trim();
  if (!query) return;
  try {
    const shops = await request(`/discover/search?q=${encodeURIComponent(query)}`);
    renderResults(shops, `${shops.length} result${shops.length === 1 ? "" : "s"} for “${query}”`);
  } catch (error) { toast("Search failed", errorText(error), "error"); }
}

async function searchNearby() {
  if (!navigator.geolocation) return toast("Location unavailable", "Your browser blocked geolocation.", "error");
  $("#nearby-button").disabled = true;
  navigator.geolocation.getCurrentPosition(async (position) => {
    try {
      state.origin = [position.coords.latitude, position.coords.longitude];
      const shops = await request(`/discover/nearby?latitude=${position.coords.latitude}&longitude=${position.coords.longitude}`);
      renderResults(shops, `${shops.length} shop${shops.length === 1 ? "" : "s"} within 25 km`);
    } catch (error) { toast("Could not find shops", errorText(error), "error"); }
    finally { $("#nearby-button").disabled = false; }
  }, () => { $("#nearby-button").disabled = false; toast("Location denied", "Allow location access, or search by name.", "error"); });
}

// ── Map view (Leaflet + OpenStreetMap — free, no API key) ─────────────
// No {s} subdomains: a/b/c.tile.openstreetmap.org can be unreachable/blocked on
// some networks while tile.openstreetmap.org works (the vendor map proves it).
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIB = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
let leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.append(css);
      // Leaflet's sheet loads after ours and would win the popup styles —
      // re-assert the themed popup once its stylesheet is in place.
      const theme = document.createElement("style");
      theme.textContent = `.leaflet-popup-content-wrapper { background: var(--surface); color: var(--ink); border: 1px solid var(--line); border-radius: 10px; box-shadow: var(--shadow-dialog); }
.leaflet-popup-tip { background: var(--surface); border: 1px solid var(--line); }`;
      document.head.append(theme);
      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.onload = resolve; script.onerror = reject;
      document.head.append(script);
    });
  }
  return leafletPromise;
}

async function toggleMapView() {
  const panel = $("#map-panel");
  const showing = panel.hidden;
  panel.hidden = !showing;
  $("#map-toggle").textContent = showing ? "🗺 Hide map" : "🗺 Map view";
  if (!showing) { state.map?.remove(); state.map = null; state.mapMarkers = []; return; }
  try { await loadLeaflet(); } catch { toast("Map unavailable", "Could not load map tiles — check your connection.", "error"); panel.hidden = true; return; }
  if (!state.map) {
    state.map = L.map("shops-map", { scrollWheelZoom: false });
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIB, maxZoom: 19 }).addTo(state.map);
    // A map without a center requests no tiles at all — a grey canvas even when
    // it is “working”. Always start somewhere: “near me” if searched, else a
    // wide view over India.
    state.map.setView(state.origin || [12.9716, 77.5946], state.origin ? 13 : 5);
  }
  drawMapPins();
}

function drawMapPins() {
  if (!state.map) return;
  state.mapMarkers.forEach((marker) => marker.remove());
  state.mapMarkers = [];
  const placed = state.results.filter((shop) => shop.latitude != null && shop.longitude != null);
  if (!placed.length) {
    // Keep the map itself alive even with nothing to pin: show the searched area.
    state.map.setView(state.origin || [12.9716, 77.5946], state.origin ? 13 : 5);
    if (state.results.length) toast("No mappable shops", "None of these results have a set location yet.", "error");
    return;
  }
  const bounds = [];
  placed.forEach((shop) => {
    const logo = shop.logo_url || null;
    const initials = shop.name.trim().slice(0, 2).toUpperCase();
    const avatarHtml = logo
      ? `<img class="pin-avatar" src="${logo}" alt="${shop.name}" onerror="this.classList.add('no-logo');this.alt='';">`
      : `<span class="pin-avatar no-logo">${initials || shop.name[0]?.toUpperCase() || '?'}</span>`;
    const icon = L.divIcon({
      className: "shop-pin",
      html: `<div class="pin-body">${avatarHtml}<small>${shop.distance_km != null ? `${shop.distance_km} km` : shop.name}</small></div>`,
      iconSize: [0, 0],
    });
    const marker = L.marker([shop.latitude, shop.longitude], { icon }).addTo(state.map);
    const popup = document.createElement("div");
    popup.className = "pin-popup";
    const title = document.createElement("b"); title.textContent = shop.name;
    const meta = document.createElement("span"); meta.className = "pin-meta";
    meta.textContent = [shop.rating_count > 0 ? `★ ${shop.rating_avg} (${shop.rating_count})` : "No ratings yet",
                        shop.distance_km != null ? `${shop.distance_km} km away` : null,
                        `Fee ${money(shop.convenience_fee_paise ?? 0)}`].filter(Boolean).join(" · ");
    const open = document.createElement("button"); open.type = "button"; open.textContent = "View shop →";
    open.onclick = () => openShop(shop.id);
    const avatar = document.createElement("div");
    avatar.className = "pin-popup-avatar";
    avatar.innerHTML = logo
      ? `<img src="${logo}" alt="${shop.name}" onerror="this.parentElement.classList.add('no-logo');this.alt='';">`
      : initials || shop.name[0]?.toUpperCase() || '?';
    const body = document.createElement("div");
    body.className = "pin-popup-body";
    body.append(title, meta, open);
    popup.append(avatar, body);
    marker.bindPopup(popup);
    state.mapMarkers.push(marker);
    bounds.push([shop.latitude, shop.longitude]);
  });
  if (bounds.length === 1) state.map.setView(bounds[0], 14);
  else state.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
}

// ── Shop detail + booking ───────────────────────────────────────────────
async function openShop(shopId) {
  try {
    const [shop, services, reviews] = await Promise.all([
      request(`/shops/${shopId}`), request(`/shops/${shopId}/services`), request(`/shops/${shopId}/reviews`),
    ]);
    state.currentShop = { ...shop, services, reviews };
    $("#shop-name").textContent = shop.name;
    $("#shop-address").textContent = shop.address || "Address not set";
    $("#shop-postal").textContent = shop.postal_code ? `PIN ${shop.postal_code}` : "BARBERSHOP";
    $("#shop-distance").textContent = "";
    $("#shop-fee").innerHTML = `Convenience fee<br><b>${money(shop.convenience_fee_paise)}</b>`;
    const existing = state.results.find((s) => s.id === shopId);
    if (existing?.distance_km != null) $("#shop-distance").textContent = `${existing.distance_km} km away`;
    $("#shop-services").replaceChildren(...services.map((service) => {
      const tile = document.createElement("article");
      tile.className = "service-tile";
      tile.innerHTML = `<h3></h3><div class="meta"></div><button class="button primary book" type="button">Book this <span>→</span></button>`;
      tile.querySelector("h3").textContent = service.name;
      tile.querySelector(".meta").textContent = `${service.duration_minutes} min · ${money(service.price_paise)}`;
      tile.querySelector("button").onclick = () => openBookingDialog(shop, service);
      return tile;
    }));
    renderReviews(reviews);
    showView("shop");
  } catch (error) { toast("Could not open shop", errorText(error), "error"); }
}

// ── Reviews ───────────────────────────────────────────────────────────
function renderReviews(data) {
  const chip = $("#shop-rating");
  if (data.rating_count > 0) {
    chip.hidden = false;
    chip.innerHTML = `<span class="stars"></span><b></b><span class="count"></span>`;
    chip.querySelector(".stars").textContent = stars(data.rating_avg);
    chip.querySelector("b").textContent = `${data.rating_avg} / 5`;
    chip.querySelector(".count").textContent = `${data.rating_count} review${data.rating_count === 1 ? "" : "s"}`;
  } else {
    chip.hidden = true;
  }
  $("#reviews-summary").textContent = data.rating_count > 0
    ? `Rated ${data.rating_avg} out of 5 from ${data.rating_count} customer${data.rating_count === 1 ? "" : "s"}.`
    : "No ratings yet.";
  $("#reviews-empty").hidden = data.reviews.length > 0;
  $("#reviews-list").replaceChildren(...data.reviews.map((review) => {
    const card = document.createElement("article");
    card.className = "review-card";
    card.innerHTML = `<div class="review-head"><span class="stars"></span><span class="who"></span><span class="when"></span></div><p></p>`;
    card.querySelector(".stars").textContent = stars(review.rating);
    card.querySelector(".who").textContent = review.customer_name || "Guest";
    card.querySelector(".when").textContent = new Date(review.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    const body = card.querySelector("p");
    body.textContent = review.comment || "(no comment)";
    if (!review.comment) body.style.opacity = ".55";
    return card;
  }));
  // Reset the form for a fresh rating.
  state.reviewRating = 0;
  $("#star-picker").querySelectorAll("button").forEach((b) => b.classList.remove("on"));
  $("#review-comment").value = "";
  setMessage("#review-message");
}

function setReviewRating(value) {
  state.reviewRating = value;
  $("#star-picker").querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number(b.dataset.star) <= value));
}

async function submitReview(event) {
  event.preventDefault();
  if (!state.reviewRating) return setMessage("#review-message", "Pick a star rating first.");
  if (!state.currentShop) return;
  try {
    await request(`/shops/${state.currentShop.id}/reviews`, {
      method: "POST",
      body: JSON.stringify({ rating: state.reviewRating, comment: $("#review-comment").value.trim() || null }),
    });
    toast("Review posted", `Thanks for rating ${state.currentShop.name}!`);
    const reviews = await request(`/shops/${state.currentShop.id}/reviews`);
    state.currentShop.reviews = reviews;
    renderReviews(reviews);
  } catch (error) { setMessage("#review-message", errorText(error)); }
}

function openBookingDialog(shop, service) {
  state.booking = { shopId: shop.id, serviceId: service.id, service, shop, slot: null };
  $("#bd-shop-name").textContent = shop.name;
  $("#bd-service").textContent = `${service.name} · ${service.duration_minutes} min · ${money(service.price_paise)}`;
  $("#bd-slots").replaceChildren();
  $("#bd-summary").hidden = true;
  $("#bd-message").textContent = "";
  $("#bd-no-slots").hidden = true;
  $("#bd-method").hidden = true;
  document.querySelectorAll(".method-option").forEach((b) => b.classList.toggle("active", b.dataset.method === "upi"));
  state.method = "upi";
  const days = $("#bd-days");
  days.replaceChildren();
  const today = new Date();
  for (let offset = 0; offset < 3; offset++) {
    const day = new Date(today); day.setDate(today.getDate() + offset);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = offset === 0 ? "Today" : day.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
    button.onclick = () => { days.querySelectorAll("button").forEach((b) => b.classList.remove("active")); button.classList.add("active"); loadSlots(day); };
    days.append(button);
  }
  $("#booking-dialog").showModal();
  // Nothing fetched slots until a day chip was clicked — the dialog opened empty.
  const first = days.querySelector("button");
  if (first) { first.classList.add("active"); loadSlots(today); }
}

async function loadSlots(day) {
  const { shopId, serviceId } = state.booking;
  const dateStr = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
  const host = $("#bd-slots");
  host.replaceChildren();
  $("#bd-summary").hidden = true;
  try {
    const availability = await request(`/shops/${shopId}/availability?service_id=${serviceId}&date=${dateStr}`);
    if (!availability.slots.length) {
      const notice = $("#bd-no-slots");
      notice.textContent = availability.reason === "no_hours"
        ? "This shop hasn't set its opening hours yet, so no slots exist."
        : availability.reason === "closed_day"
          ? "The shop is closed on this day."
          : "All slots for this service are taken on this day.";
      notice.hidden = false;
      return;
    }
    $("#bd-no-slots").hidden = true;
    host.replaceChildren(...availability.slots.map((iso) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
      button.onclick = () => {
        host.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
        button.classList.add("active");
        state.booking.slot = iso;
        $("#bd-method").hidden = false;
        showSummary();
      };
      return button;
    }));
  } catch (error) { toast("Could not load slots", errorText(error), "error"); }
}

function showSummary() {
  const { service, shop } = state.booking;
  const fee = shop.convenience_fee_paise;
  $("#bd-price").textContent = `Service price: ${money(service.price_paise)}`;
  $("#bd-fee").textContent = `Convenience fee: ${money(fee)}`;
  $("#bd-method-line").textContent = `Paying with: ${state.method === "upi" ? "UPI" : "Card"}`;
  $("#bd-total").textContent = `Total: ${money(service.price_paise + fee)}`;
  $("#bd-confirm").textContent = state.method === "upi" ? "Confirm & get UPI link →" : "Confirm & pay by card →";
  $("#bd-summary").hidden = false;
  $("#bd-confirm").disabled = false;
}

async function confirmBooking() {
  const { shopId, serviceId, slot } = state.booking;
  const button = $("#bd-confirm");
  button.disabled = true;
  $("#bd-message").textContent = "";
  try {
    const booking = await request("/bookings", { method: "POST", body: JSON.stringify({ shop_id: shopId, service_id: serviceId, starts_at: slot }) });
    const pay = await request(`/customer/bookings/${booking.id}/pay?method=${state.method}`, { method: "POST" });
    $("#booking-dialog").close();
    if (pay.payment_status === "COMPLETED") {
      if ((pay.provider || "").startsWith("Mock")) {
        // No gateway is configured in this environment; don't imply real money moved.
        toast("Booked! (payment on hold)", `No payment gateway is configured, so this is marked unpaid-pending — code ${booking.code}. Configure UPI_VPA or Razorpay to charge customers.`, "error");
      } else {
        toast("Booked & paid!", `Confirmation code ${booking.code} — ${money(pay.amount_paise)} including the ${money(pay.convenience_fee_paise)} fee.`);
      }
    } else if (state.method === "upi") {
      toast("Booking reserved!", `Pay ${money(pay.amount_paise)} via UPI link sent to your payments page — code ${booking.code}.`);
      if (pay.checkout_url) window.open(pay.checkout_url, "_blank");
    } else {
      toast("Booking reserved!", `Complete your card payment — code ${booking.code}.`);
      if (pay.checkout_url) window.open(pay.checkout_url, "_blank");
    }
    showView("bookings");
  } catch (error) {
    $("#bd-message").textContent = errorText(error);
    button.disabled = false;
  }
}

// ── My bookings ─────────────────────────────────────────────────────────
async function loadMyBookings() {
  const list = $("#my-bookings");
  try {
    const bookings = await request("/customer/bookings");
    $("#bookings-empty").hidden = bookings.length > 0;
    list.replaceChildren(...bookings.map((booking) => {
      const card = document.createElement("article");
      card.className = "booking-card";
      card.innerHTML = `<div class="when"><strong></strong><span></span></div><div class="what"><h3></h3><p class="where"></p><p class="paid"></p></div><span class="status-tag"></span>`;
      const starts = new Date(booking.starts_at);
      card.querySelector(".when strong").textContent = starts.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
      card.querySelector(".when span").textContent = starts.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
      card.querySelector("h3").textContent = booking.service_name;
      card.querySelector(".where").innerHTML = `<b>${booking.shop_name}</b> · code ${booking.code}`;
      const paid = booking.payment_status === "COMPLETED"
        ? `Paid ${money(booking.amount_paise)} (incl. ${money(booking.convenience_fee_paise)} fee)`
        : booking.payment_status === "PENDING" ? "Payment pending" : "No payment yet";
      card.querySelector(".paid").textContent = paid;
      const upcoming = booking.status === "CONFIRMED" && starts > new Date();
      const tag = card.querySelector(".status-tag");
      tag.textContent = booking.status === "CANCELLED" ? "Cancelled" : upcoming ? "Upcoming" : "Completed";
      tag.classList.add(booking.status === "CANCELLED" ? "cancelled" : upcoming ? "upcoming" : "done");
      return card;
    }));
  } catch (error) { toast("Could not load bookings", errorText(error), "error"); }
}

// ── Assistant (retrieval-grounded chat: shops, prices, slots) ───────────
const chatState = { open: false, seeded: false, shopId: null, serviceId: null, lastMessage: "", booking: null, busy: false };

function chatOpen(open) {
  chatState.open = open;
  $("#chat-panel").hidden = !open;
  $("#chat-launcher").hidden = open;
  $("#chat-launcher").setAttribute("aria-expanded", String(open));
  if (!open) return;
  if (!chatState.seeded) {
    chatState.seeded = true;
    const hello = chatBubble("bot", "Hi! I can find barbershops near you, compare prices, check hours and reviews, and book a slot for you. Try “haircut near me” or “book a haircut tomorrow at 5pm”.");
    chatChips(["Haircut near me", "Show shops", "My bookings"]);
    if (hello) hello.dataset.greeting = "1";
  }
  $("#chat-input").focus();
}

function chatBubble(role, text) {
  const node = document.createElement("div");
  node.className = `chat-bubble ${role}`;
  const copy = document.createElement("p");
  copy.className = "chat-text";
  copy.textContent = text;
  node.append(copy);
  $("#chat-log").append(node);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return node;
}

function chatCards(node, cards) {
  const wrap = document.createElement("div");
  wrap.className = "chat-cards";
  cards.forEach((card) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-card";
    button.innerHTML = "<b></b><span></span>";
    button.querySelector("b").textContent = card.title;
    button.querySelector("span").textContent = card.meta || "";
    button.onclick = () => {
      if (card.kind === "booking") { chatOpen(false); showView("bookings"); return; }
      if (card.shop_id) { chatOpen(false); openShop(card.shop_id); }
    };
    wrap.append(button);
  });
  node.append(wrap);
}

function chatSources(node, sources) {
  if (!sources || !sources.length) return;
  const note = document.createElement("p");
  note.className = "chat-sources";
  const labels = [...new Set(sources.map((source) => source.label))].slice(0, 3);
  note.textContent = `From: ${labels.join(" · ")}`;
  node.append(note);
}

function chatChips(suggestions) {
  const host = $("#chat-chips");
  host.replaceChildren(...(suggestions || []).slice(0, 4).map((label) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-chip";
    button.textContent = label;
    button.onclick = () => handleChatChip(label);
    return button;
  }));
}

function renderChatReply(reply) {
  const node = chatBubble("bot", reply.answer);
  if (reply.shop_id != null) chatState.shopId = reply.shop_id;
  if (reply.service_id != null) chatState.serviceId = reply.service_id;
  if (reply.cards && reply.cards.length) chatCards(node, reply.cards);
  if (reply.booking) {
    chatState.booking = reply.booking;
    const pay = document.createElement("button");
    pay.type = "button";
    pay.className = "chat-action";
    pay.textContent = `Pay ${money(reply.booking.total_paise)} with UPI`;
    pay.onclick = () => payFromChat(reply.booking, pay);
    node.append(pay);
  }
  chatSources(node, reply.sources);
  chatChips(reply.suggestions);
}

async function sendChat(text) {
  const message = (text || "").trim();
  if (!message || chatState.busy) return;
  chatState.busy = true;
  chatState.lastMessage = message;
  chatBubble("user", message);
  const typing = chatBubble("bot", "Looking that up…");
  typing.classList.add("typing");
  try {
    const payload = { message, shop_id: chatState.shopId, service_id: chatState.serviceId };
    if (Array.isArray(state.origin)) { payload.latitude = state.origin[0]; payload.longitude = state.origin[1]; }
    const reply = await request("/chat/customer", { method: "POST", body: JSON.stringify(payload) });
    typing.remove();
    renderChatReply(reply);
  } catch (error) {
    typing.remove();
    chatBubble("bot", errorText(error));
  } finally { chatState.busy = false; }
}

function chatUseLocation() {
  if (!navigator.geolocation) return chatBubble("bot", "Your browser blocked geolocation — name a shop or service instead.");
  const typing = chatBubble("bot", "Getting your location…");
  typing.classList.add("typing");
  navigator.geolocation.getCurrentPosition((position) => {
    typing.remove();
    state.origin = [position.coords.latitude, position.coords.longitude];
    sendChat(chatState.lastMessage ? `${chatState.lastMessage} near me` : "shops near me");
  }, () => {
    typing.remove();
    chatBubble("bot", "Location denied. Name a shop or service instead.");
  });
}

async function payFromChat(booking, button) {
  // The button is the only record of what happened after the toast fades, so
  // settle it into the outcome instead of leaving a re-clickable "Pay".
  const settle = (label, enabled = false) => {
    if (!button) return;
    button.textContent = label;
    button.disabled = !enabled;
  };
  try {
    const pay = await request(`/customer/bookings/${booking.id}/pay?method=upi`, { method: "POST" });
    if (pay.payment_status === "COMPLETED") {
      if ((pay.provider || "").startsWith("Mock")) {
        settle("Payment on hold — no gateway");
        toast("Booked! (payment on hold)", `No payment gateway is configured yet — code ${booking.code}. Configure UPI_VPA or Razorpay to charge customers.`, "error");
      } else {
        settle(`Paid ${money(pay.amount_paise)} ✓`);
        toast("Paid!", `${money(pay.amount_paise)} received — code ${booking.code}.`);
      }
    } else {
      settle("Payment link opened");
      toast("Payment link ready", `Pay ${money(pay.amount_paise)} to settle code ${booking.code}.`);
      if (pay.checkout_url) window.open(pay.checkout_url, "_blank");
    }
  } catch (error) {
    const message = errorText(error);
    if (/already paid/i.test(message)) settle("Already paid ✓");
    else settle("Retry payment", true);
    toast("Payment could not start", message, "error");
  }
}

function handleChatChip(label) {
  if (/use my location/i.test(label)) return chatUseLocation();
  if (/^pay with upi$/i.test(label) && chatState.booking) return payFromChat(chatState.booking);
  if (/^sign in$/i.test(label)) return;
  return sendChat(label);
}

// ── Wiring ──────────────────────────────────────────────────────────────
document.querySelectorAll("[data-show]").forEach((button) => button.addEventListener("click", () => showAuth(button.dataset.show)));
$("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const role = state.registerRole || "CUSTOMER";
    const tokens = await request("/auth/register", { method: "POST", body: JSON.stringify({ email: values.email, password: values.password, role }) });
    state.token = tokens.access_token;
    localStorage.setItem("trimly_access_token", tokens.access_token);
    localStorage.setItem("trimly_refresh_token", tokens.refresh_token);
    if (role === "SHOP_OWNER") { goToOwnerPortal(); return; }
    await bootApp();
  } catch (error) { setMessage("#auth-message", errorText(error)); }
});
$("#vendor-create").addEventListener("click", () => applyRole(state.registerRole === "SHOP_OWNER" ? "CUSTOMER" : "SHOP_OWNER"));
$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const tokens = await request("/auth/login", { method: "POST", body: JSON.stringify(values) });
    state.token = tokens.access_token;
    localStorage.setItem("trimly_access_token", tokens.access_token);
    localStorage.setItem("trimly_refresh_token", tokens.refresh_token);
    const me = await request("/auth/me");
    if (me.role !== "CUSTOMER") { goToOwnerPortal(); return; }
    await bootApp(me);
  } catch (error) { setMessage("#auth-message", errorText(error)); }
});
$("#search-form").addEventListener("submit", searchText);
$("#nearby-button").addEventListener("click", searchNearby);
$("#map-toggle").addEventListener("click", toggleMapView);
$("#star-picker").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-star]");
  if (button) setReviewRating(Number(button.dataset.star));
});
$("#review-form").addEventListener("submit", submitReview);
$("#back-to-results").addEventListener("click", () => showView("discover"));
$("#nav-bookings").addEventListener("click", () => showView("bookings"));
$("#sign-out").addEventListener("click", () => signOut());
$("#chat-launcher").addEventListener("click", () => chatOpen(true));
$("#chat-close").addEventListener("click", () => chatOpen(false));
$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#chat-input");
  const text = input.value.trim();
  input.value = "";
  sendChat(text);
});
$("#bd-confirm").addEventListener("click", confirmBooking);
document.querySelectorAll(".method-option").forEach((button) => button.addEventListener("click", () => {
  state.method = button.dataset.method;
  document.querySelectorAll(".method-option").forEach((b) => b.classList.toggle("active", b === button));
  if (state.booking?.slot) showSummary();
}));

// ── Theme (single switch in the top-right corner) ───────────────────────
const THEME_KEY = "trimly_theme";
function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (error) { /* private mode */ }
  const dark = next === "dark";
  const icon = dark ? "☾" : "☀";
  const label = dark ? "Switch to light mode" : "Switch to dark mode";
  const button = $("#theme-switch");
  button.setAttribute("aria-checked", String(dark));
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
  const slot = button.querySelector(".switch-icon");
  if (slot) slot.textContent = icon;
}
$("#theme-switch").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
applyTheme(document.documentElement.dataset.theme || "dark");

if (state.token) bootApp(); else showAuth();
