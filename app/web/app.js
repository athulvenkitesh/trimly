const API = "/api/v1";
const state = { token: localStorage.getItem("trimly_access_token"), shop: null, services: [], bookings: [], shopOpen: true, bufferMinutes: 0, slotAfter: null, view: "overview", slotServiceId: null, slotDuration: null, nextSlotAt: null };
const $ = (selector) => document.querySelector(selector);

function setMessage(selector, text = "", success = false) {
  const node = $(selector); node.textContent = text; node.classList.toggle("success", success);
}
function showToast(title, message = "", kind = "success") {
  const toast = document.createElement("div"); toast.className = `toast ${kind}`;
  toast.innerHTML = `<div class="toast-icon">${kind === "success" ? "✓" : "!"}</div><div class="toast-copy"><b></b><span></span></div><button class="toast-close" aria-label="Dismiss notification">×</button>`;
  toast.querySelector("b").textContent = title; toast.querySelector("span").textContent = message;
  const dismiss = () => { toast.classList.add("toast-hide"); setTimeout(() => toast.remove(), 220); };
  toast.querySelector("button").addEventListener("click", dismiss); $("#toast-region").append(toast); setTimeout(dismiss, 5000);
}
function errorText(error) {
  if (typeof error?.detail === "string") return error.detail;
  if (error?.detail?.error?.message) return error.detail.error.message;
  if (Array.isArray(error?.detail)) return error.detail.map((item) => `${item.loc?.slice(-1)[0] || "Input"}: ${item.msg}`).join(" ");
  if (typeof error?.message === "string") return error.message;
  if (error?.status) return `The request could not be completed (HTTP ${error.status}).`;
  return "The request could not be completed. Please try again.";
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
function saveSession(tokens) { state.token = tokens.access_token; localStorage.setItem("trimly_access_token", tokens.access_token); localStorage.setItem("trimly_refresh_token", tokens.refresh_token); }
function showAuth(mode = "register") {
  $("#auth-screen").hidden = false; $("#dashboard-screen").hidden = true;
  const register = mode === "register";
  $("#register-form").hidden = !register; $("#login-form").hidden = register;
  $("#register-copy").hidden = !register; $("#login-copy").hidden = register;
  $("#switch-register").hidden = !register; $("#switch-login").hidden = register; setMessage("#auth-message");
}
async function bootDashboard() {
  try {
    const me = await request("/auth/me");
    if (me.role !== "SHOP_OWNER") throw { detail: "This portal is for shop-owner accounts." };
    $("#owner-email").textContent = me.email;
    $("#auth-screen").hidden = true; $("#dashboard-screen").hidden = false;
    const shops = await request("/barber/shops");
    if (shops.length) await selectShop(shops[0]); else showShopSetup();
  } catch (error) { signOut(errorText(error)); }
}
function showShopSetup() { state.shop = null; $("#empty-state").hidden = false; $("#shop-workspace").hidden = true; $("#dashboard-title").textContent = "Welcome to Trimly"; $("#dashboard-subtitle").textContent = "Create your first shop to begin building your online presence."; }
async function selectShop(shop) {
  state.shop = shop; $("#empty-state").hidden = true; $("#shop-workspace").hidden = false;
  $("#dashboard-title").textContent = `Welcome back`;
  $("#dashboard-subtitle").textContent = "Your booking workspace is ready to manage.";
  $("#shop-name").textContent = shop.name; $("#shop-address").textContent = shop.address || "Address not added"; $("#shop-initial").textContent = shop.name.trim().charAt(0).toUpperCase();
  resetLocationForm(shop);
  renderShopStatus(shop.is_active !== false);
  showView("overview");
  await Promise.all([loadServices(), loadBookings(), loadHours()]);
  refreshNextSlot();
}

// ── Views ──────────────────────────────────────────────────────────
function showView(view) {
  state.view = view;
  $("#overview-view").hidden = view !== "overview";
  $("#appointments-section").hidden = view !== "appointments";
  $("#services-section").hidden = view !== "services";
  $("#settings-section").hidden = view !== "settings";
  $("#assistant-section").hidden = view !== "assistant";
  if (view === "assistant") openOwnerChat();
  document.querySelectorAll(".sidebar .nav-link").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  if (view === "settings") {
    // The map is built lazily: a hidden container has no size for Leaflet.
    const resize = () => maps.map?.invalidateSize();
    loadMaps().then(resize).catch(() => {});
    setTimeout(resize, 80);
  }
  if (view === "overview") renderOverview();
}

// ── Overview: today's collection, shop status, next slot, upcoming ─────
const rupees = (paise) => `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const addDays = (date, days) => { const next = new Date(date); next.setDate(next.getDate() + days); return next; };
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const dayLabel = (date) => {
  const today = new Date();
  if (sameDay(date, today)) return "Today";
  if (sameDay(date, addDays(today, 1))) return "Tomorrow";
  return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
};

function renderOverview() {
  if (!state.shop) return;
  const now = new Date();
  const confirmed = state.bookings.filter((booking) => booking.status === "CONFIRMED");
  const todays = confirmed.filter((booking) => sameDay(new Date(booking.starts_at), now));
  const collected = todays.reduce((sum, booking) => sum + (booking.service_price_paise || 0), 0);
  $("#today-collection").textContent = rupees(collected);
  $("#today-meta").textContent = todays.length
    ? `${todays.length} appointment${todays.length === 1 ? "" : "s"} today`
    : "No appointments today";

  const upcoming = confirmed
    .filter((booking) => new Date(booking.starts_at) > now)
    .sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at))
    .slice(0, 6);
  $("#upcoming-count").textContent = `${upcoming.length} upcoming`;
  $("#upcoming-empty").hidden = upcoming.length > 0;
  const list = $("#upcoming-list");
  list.innerHTML = "";
  upcoming.forEach((booking) => list.append(bookingCard(booking)));
}

function renderShopStatus(open) {
  state.shopOpen = open;
  renderBufferChips();
  const toggle = $("#shop-status-toggle");
  toggle.setAttribute("aria-checked", String(open));
  toggle.setAttribute("title", open ? "Close your shop for new bookings" : "Open your shop for bookings");
  $("#shop-status-label").textContent = open ? "Open" : "Closed";
  $("#shop-status-meta").textContent = open ? "Customers can book you today" : "New bookings are paused";
  const pill = document.querySelector(".live-pill");
  if (pill) { pill.textContent = open ? "● Live" : "● Closed"; pill.classList.toggle("closed", !open); }
}

const timeText = (date) => date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
const minutesUntil = (date) => Math.max(0, Math.round((date.getTime() - Date.now()) / 60000));

const BUFFERS = [0, 5, 10, 15, 20];
// The server snaps to 5-minute marks, so hand-picked times are rounded the same way.
const roundUpTo5 = (date) => { const snapped = new Date(date); snapped.setSeconds(0, 0); snapped.setMinutes(Math.ceil(snapped.getMinutes() / 5) * 5); return snapped; };
function renderBufferChips() {
  document.querySelectorAll(".buffer-chip").forEach((chip) => {
    // A hand-edited time outranks the chips until one is pressed again.
    const active = !state.slotAfter && Number(chip.dataset.buffer) === state.bufferMinutes;
    chip.classList.toggle("active", active);
    chip.setAttribute("aria-pressed", String(active));
    chip.disabled = !state.shopOpen;
  });
}

// Next free moment counted from the current time; `buffer` pushes it later in minutes.
async function refreshNextSlot(buffer = state.bufferMinutes || 0) {
  if (!state.shop) return;
  state.bufferMinutes = buffer;
  renderBufferChips();
  const value = $("#next-slot"), meta = $("#next-slot-meta"), walkIn = $("#walk-in-button"), edit = $("#slot-edit"), action = $("#next-slot-action"), chipsRow = $("#slot-buffer"), hint = $("#walk-in-hint");
  const hideAction = () => { action.hidden = true; chipsRow.hidden = false; hint.hidden = false; };
  state.nextSlotAt = null;
  const base = state.slotAfter || new Date(Date.now() + buffer * 60000);
  const params = new URLSearchParams({ after: base.toISOString() });
  if (state.slotServiceId) params.set("service_id", state.slotServiceId);
  meta.textContent = "Checking your calendar…";
  try {
    const data = await request(`/barber/shops/${state.shop.id}/next-slot?${params}`);
    state.slotServiceId = data.service_id ?? null;
    state.slotDuration = data.duration_minutes ?? null;
    if (!data.is_open) { value.textContent = "Closed"; meta.textContent = "Open your shop to accept bookings."; walkIn.disabled = true; edit.disabled = true; hideAction(); return; }
    if (!data.service_id) { value.textContent = "—"; meta.textContent = "Add a service to start taking bookings."; walkIn.disabled = true; edit.disabled = true; hideAction(); return; }
    if (!data.starts_at) {
      walkIn.disabled = true; edit.disabled = true;
      if (data.reason === "no_hours") {
        // The shop is open and has services, but no weekday is configured — slots exist nowhere.
        value.textContent = "No hours set";
        meta.textContent = "No business hours yet — no customer can book a slot until they exist.";
        action.hidden = false; chipsRow.hidden = true; hint.hidden = true;
      } else {
        value.textContent = "No free time";
        meta.textContent = "Nothing free in the next 7 days.";
        hideAction();
      }
      return;
    }
    const when = new Date(data.starts_at);
    state.nextSlotAt = when;
    const away = minutesUntil(when);
    value.textContent = timeText(when);
    const note = state.slotAfter
      ? (when.getTime() === state.slotAfter.getTime() ? ` · set to ${timeText(state.slotAfter)}` : ` · next free after ${timeText(state.slotAfter)}`)
      : (buffer ? ` · pushed +${buffer} min` : "");
    meta.textContent = `${away <= 1 ? "Now" : `in ${away} min`} · ${dayLabel(when)} · ${data.service_name} (${data.duration_minutes} min)${note}`;
    walkIn.disabled = false;
    edit.disabled = false;
    hideAction();
  } catch (error) {
    value.textContent = "—";
    meta.textContent = "Could not load availability.";
    walkIn.disabled = true;
    edit.disabled = true;
    hideAction();
  }
}

// ── Hand-edit the displayed slot (the chips nudge, this picks an exact time) ──
function openSlotEditor() {
  const base = state.nextSlotAt && state.nextSlotAt.getTime() > Date.now() ? state.nextSlotAt : new Date();
  const pad = (part) => String(part).padStart(2, "0");
  $("#slot-time-input").value = `${pad(base.getHours())}:${pad(base.getMinutes())}`;
  $("#slot-editor").hidden = false;
  $("#slot-edit").hidden = true;
  $("#slot-time-input").focus();
}
function closeSlotEditor() {
  $("#slot-editor").hidden = true;
  $("#slot-edit").hidden = false;
}
function applyEditedSlotTime() {
  const raw = $("#slot-time-input").value;
  const [hours, minutes] = raw.split(":").map(Number);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return;
  // Keep the day currently on display; fall back to today.
  const chosen = state.nextSlotAt && state.nextSlotAt.getTime() > Date.now() ? new Date(state.nextSlotAt) : new Date();
  chosen.setHours(hours, minutes, 0, 0);
  let rounded = roundUpTo5(chosen);
  // A time of day already behind us means "tomorrow" (23:47 → 00:10 is the next day).
  if (rounded.getTime() <= Date.now()) { rounded = new Date(rounded.getTime() + 24 * 3600 * 1000); }
  if (rounded.getTime() <= Date.now()) { showToast("That time has passed", "Pick a time later than now.", "error"); return; }
  state.slotAfter = rounded;
  closeSlotEditor();
  refreshNextSlot(0);
}
function bookingCard(b) {
  const when = new Date(b.starts_at);
  const upcoming = b.status === "CONFIRMED" && when.getTime() > Date.now();
  const card = document.createElement("article");
  card.className = "booking-card";
  const statusLabel = b.status === "CONFIRMED" ? (upcoming ? "Upcoming" : "Completed") : "Cancelled";
  const statusClass = b.status === "CANCELLED" ? "cancelled" : (upcoming ? "upcoming" : "done");
  card.innerHTML = `
    <div class="booking-when"><strong>${when.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</strong><span>${when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span></div>
    <div class="booking-info"><h3></h3><p>${b.service_duration_minutes} min · <b>${rupees(b.service_price_paise || 0)}</b> · code <b>${b.code}</b></p><p class="booking-customer"></p></div>
    <span class="booking-status ${statusClass}">${statusLabel}</span>`;
  card.querySelector("h3").textContent = b.service_name;
  card.querySelector(".booking-customer").textContent = b.is_walk_in ? `${b.walk_in_name || "Walk-in customer"} · walk-in` : b.customer_email;
  return card;
}
async function loadBookings() {
  if (!state.shop) return;
  try {
    const bookings = await request(`/barber/shops/${state.shop.id}/bookings`);
    state.bookings = bookings;
    $("#appointment-count").textContent = `${bookings.length} appointment${bookings.length === 1 ? "" : "s"}`;
    $("#no-bookings").hidden = bookings.length > 0;
    const list = $("#bookings-list"); list.innerHTML = "";
    bookings.forEach((booking) => list.append(bookingCard(booking)));
    renderOverview();
  } catch (error) { showToast("Could not load appointments", errorText(error), "error"); }
}

async function loadServices() {
  const services = await request(`/shops/${state.shop.id}/services`);
  state.services = services;
  $("#service-count").textContent = `${services.length} service${services.length === 1 ? "" : "s"}`;
  $("#no-services").hidden = services.length > 0; $("#services-list").innerHTML = "";
  services.forEach((service) => {
    const card = document.createElement("article"); card.className = "service-card";
    card.innerHTML = `<div class="service-icon">✂</div><div><h3></h3><p>${service.duration_minutes} min appointment</p></div><strong class="service-price">₹${(service.price_paise / 100).toFixed(0)}</strong><button class="delete-service" aria-label="Remove ${service.name}" title="Remove service">×</button>`;
    card.querySelector("h3").textContent = service.name;
    card.querySelector("button").addEventListener("click", () => deactivateService(service.id)); $("#services-list").append(card);
  });
}
async function deactivateService(id) {
  if (!confirm("Remove this service from your menu?")) return;
  try { await request(`/shops/${state.shop.id}/services/${id}`, { method: "DELETE" }); await loadServices(); showToast("Service removed", "It is no longer visible in your service menu."); } catch (error) { const message = errorText(error); setMessage("#service-message", message); showToast("Could not remove service", message, "error"); }
}
function signOut(message = "") { state.token = null; state.shop = null; state.hoursRows = null; localStorage.removeItem("trimly_access_token"); localStorage.removeItem("trimly_refresh_token"); showAuth("login"); if (message) setMessage("#auth-message", message); }

// ── Settings: business hours — the windows in which any booking at all can exist ──
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
// The API counts weekday as 0=Monday (Python convention); the browser counts 0=Sunday.
const dbWeekday = (jsDay) => (jsDay + 6) % 7;
async function loadHours() {
  if (!state.shop) return;
  const grid = $("#hours-grid");
  let rows = [];
  try { rows = await request(`/barber/shops/${state.shop.id}/business-hours`); } catch { rows = []; }
  const byDay = new Map(rows.map((row) => [row.weekday, row]));
  grid.innerHTML = "";
  state.hoursRows = WEEKDAYS.map((day, dbDay) => {
    const saved = byDay.get(dbDay);
    const row = document.createElement("div");
    row.className = "hours-row";
    row.innerHTML = `
      <strong class="hours-day">${day}</strong>
      <label class="hours-open"><input type="checkbox" aria-label="Open on ${day}"> open</label>
      <input type="time" class="hours-start" aria-label="${day} opens at">
      <span class="muted">→</span>
      <input type="time" class="hours-end" aria-label="${day} closes at">`;
    const open = row.querySelector("input"), start = row.querySelector(".hours-start"), end = row.querySelector(".hours-end");
    open.checked = saved ? !saved.is_closed : false;
    start.value = typeof saved?.opens_at === "string" ? saved.opens_at.slice(0, 5) : "09:00";
    end.value = typeof saved?.closes_at === "string" ? saved.closes_at.slice(0, 5) : "18:00";
    grid.append(row);
    return { weekday: dbDay, day, open, start, end };
  });
  const openCount = rows.filter((row) => !row.is_closed).length;
  if (!openCount) $("#hours-status").textContent = "Not set";
  else if (openCount === 1) $("#hours-status").textContent = "1 open day";
  else $("#hours-status").textContent = `${openCount} open days`;
}
async function saveHours(event) {
  event.preventDefault();
  if (!state.shop || !state.hoursRows) return;
  for (const row of state.hoursRows) {
    if (row.open.checked && !row.start.value) row.start.value = "09:00";
    if (row.open.checked && !row.end.value) row.end.value = "18:00";
    if (row.open.checked && row.start.value >= row.end.value) {
      showToast("Check your hours", `${row.day}: closing time must be after opening.`, "error"); return;
    }
  }
  try {
    for (const row of state.hoursRows) {
      await request(`/barber/shops/${state.shop.id}/business-hours`, { method: "PUT", body: JSON.stringify({
        weekday: row.weekday, opens_at: row.start.value || "09:00", closes_at: row.end.value || "18:00", is_closed: !row.open.checked,
      }) });
    }
    await loadHours();
    setMessage("#hours-message");
    showToast("Hours saved", "Bookable slots now exist inside those windows.");
    refreshNextSlot();
  } catch (error) { const message = errorText(error); setMessage("#hours-message", message); showToast("Could not save hours", message, "error"); }
}
function fillDefaultHours() {
  if (!state.hoursRows) return;
  // Mon–Sat, 9am–6pm; Sunday closed. Values are easy to edit afterwards.
  state.hoursRows.forEach((row, index) => {
    const open = index < 6;
    row.open.checked = open; row.start.value = "09:00"; row.end.value = "18:00";
  });
}

// ---- Shop location (Leaflet + OpenStreetMap — free, no API key) ----
const maps = { map: null, marker: null, searchTimer: null, searchControl: null };

const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIB = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';
const NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q=";

function resetLocationForm(shop = state.shop) {
  if (!shop) return;
  $("#location-lat").value = shop.latitude ?? "";
  $("#location-lng").value = shop.longitude ?? "";
  $("#location-address").value = shop.address || "";
  $("#location-place-id").value = shop.place_id || "";
  $("#location-postal").value = shop.postal_code || "";
  const search = $("#location-search"); if (search) search.value = "";
  setMessage("#location-message");
  updateLocationStatus();
}

function updateLocationStatus() {
  const set = $("#location-lat").value !== "" && $("#location-lng").value !== "";
  const pill = $("#location-status");
  pill.textContent = set ? "Pin set" : "Not set";
  pill.classList.toggle("location-set", set);
}

function initMap() {
  const shop = state.shop;
  const start = shop?.latitude != null && shop?.longitude != null
    ? { lat: shop.latitude, lng: shop.longitude }
    : { lat: 12.9716, lng: 77.5946 };
  const zoom = shop?.latitude != null ? 16 : 11;

  try {
    maps.map = L.map("map-canvas", { center: [start.lat, start.lng], zoom, scrollWheelZoom: false });
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIB, maxZoom: 19 }).addTo(maps.map);
    maps.marker = L.marker([start.lat, start.lng], { draggable: true, title: shop?.name || "Your shop" }).addTo(maps.map);
    maps.marker.on("dragend", () => syncFromMarker());
    maps.map.on("click", (event) => setMarker(event.latlng));
    maps.map.on("focus", () => maps.map.scrollWheelZoom.enable());
    maps.map.on("blur", () => maps.map.scrollWheelZoom.disable());
    initSearch();
    if (shop?.latitude != null) { $("#location-lat").value = shop.latitude; $("#location-lng").value = shop.longitude; }
    updateLocationStatus();
  } catch { $("#map-placeholder").hidden = false; }
}

function setMarker(latlng) {
  maps.marker.setLatLng(latlng);
  $("#location-lat").value = Number(latlng.lat.toFixed(6));
  $("#location-lng").value = Number(latlng.lng.toFixed(6));
  updateLocationStatus();
}

function focusMapOnShop() {
  const shop = state.shop;
  if (!maps.map || !maps.marker || shop?.latitude == null) return;
  maps.map.setView([shop.latitude, shop.longitude], 16);
  maps.marker.setLatLng([shop.latitude, shop.longitude]);
  $("#location-lat").value = shop.latitude; $("#location-lng").value = shop.longitude;
  updateLocationStatus();
}

async function initSearch() {
  const input = $("#location-search");
  if (!input) return;
  input.disabled = false;
  const results = document.createElement("div");
  results.className = "search-results";
  results.hidden = true;
  input.insertAdjacentElement("afterend", results);
  maps.searchBox = results;

  const closeResults = () => { results.hidden = true; results.innerHTML = ""; };
  let searchSerial = 0; // guards against out-of-order responses

  const renderResults = (places) => {
    results.innerHTML = "";
    if (!places.length) {
      results.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = "No matches found. Try a nearby landmark or the standard spelling.";
      results.append(empty);
      results.hidden = false;
      return;
    }
    for (const place of places) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "search-result";
      option.textContent = place.display_name;
      option.addEventListener("click", () => {
        closeResults();
        input.value = place.display_name;
        setMarker({ lat: Number(place.lat), lng: Number(place.lon) });
        maps.map.setView([place.lat, place.lon], 16);
        if (!$("#location-address").value) $("#location-address").value = place.display_name;
      });
      results.append(option);
    }
    results.hidden = false;
  };

  const runSearch = async (query) => {
    const serial = ++searchSerial;
    results.innerHTML = "";
    const pending = document.createElement("div");
    pending.className = "search-pending";
    pending.textContent = "Searching…";
    results.append(pending);
    results.hidden = false;
    try {
      const response = await fetch(`${NOMINATIM_SEARCH}${encodeURIComponent(query)}`, { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error("search failed");
      const places = await response.json();
      if (serial !== searchSerial) return; // a newer query already resolved
      renderResults(places);
    } catch {
      if (serial !== searchSerial) return;
      results.innerHTML = "";
      const failed = document.createElement("div");
      failed.className = "search-empty";
      failed.textContent = "Search is unavailable right now — you can still drag the pin or type coordinates.";
      results.append(failed);
      results.hidden = false;
    }
  };

  input.addEventListener("blur", () => setTimeout(closeResults, 180));

  input.addEventListener("input", () => {
    clearTimeout(maps.searchTimer);
    const query = input.value.trim();
    if (query.length < 3) { closeResults(); return; }
    maps.searchTimer = setTimeout(() => runSearch(query), 450);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    clearTimeout(maps.searchTimer);
    const query = input.value.trim();
    if (query.length >= 3) runSearch(query);
  });

  // Re-show the last results when the field regains focus.
  input.addEventListener("focus", () => {
    if (results.children.length) results.hidden = false;
  });
}
function syncFromMarker() {
  const position = maps.marker.getLatLng();
  $("#location-lat").value = Number(position.lat.toFixed(6));
  $("#location-lng").value = Number(position.lng.toFixed(6));
  updateLocationStatus();
}

// Search Nominatim for the pincode and center the map on the best hit.
async function jumpToPincode() {
  const input = $("#location-postal");
  const code = input.value.trim();
  if (!code || !maps.map) return false;
  setMessage("#location-message", "Finding that pincode…");
  try {
    const response = await fetch(`${NOMINATIM_SEARCH}${encodeURIComponent(code)}`, { headers: { "Accept": "application/json" } });
    if (!response.ok) throw new Error("pincode lookup failed");
    const places = await response.json();
    if (!places.length) {
      setMessage("#location-message", "That pincode wasn't found — drag the pin or search the address instead.");
      return false;
    }
    const hit = places[0];
    maps.map.setView([Number(hit.lat), Number(hit.lon)], 14);
    setMarker({ lat: Number(hit.lat), lng: Number(hit.lon) });
    const search = $("#location-search");
    if (search && !search.value) search.value = hit.display_name.split(",").slice(-2).join(", ").trim();
    setMessage("#location-message", "Map moved to your pincode — drag the pin to fine-tune, then save.", true);
    return true;
  } catch {
    setMessage("#location-message", "Pincode lookup failed — you can still drag the pin manually.");
    return false;
  }
}

async function loadMaps() {
  if (maps.map) return;
  try {
    await loadScript("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "link");
    await loadScript("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "script");
    initMap();
  } catch { $("#map-placeholder").hidden = false; }
}

function loadScript(url, tag) {
  return new Promise((resolve, reject) => {
    const element = document.createElement(tag);
    if (tag === "link") { element.rel = "stylesheet"; element.href = url; }
    else { element.src = url; }
    element.onload = resolve; element.onerror = () => reject(new Error(`Failed to load ${url}`));
    document.head.append(element);
  });
}

$("#location-lat").addEventListener("input", updateLocationStatus);
$("#location-lng").addEventListener("input", updateLocationStatus);
const postalInput = $("#location-postal");
let postalTimer = null;
if (postalInput) {
  postalInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); clearTimeout(postalTimer); jumpToPincode(); }
  });
  postalInput.addEventListener("input", () => {
    clearTimeout(postalTimer);
    const code = postalInput.value.trim();
    if (code.length >= 4) postalTimer = setTimeout(jumpToPincode, 700);
  });
}
$("#location-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const latitude = Number($("#location-lat").value), longitude = Number($("#location-lng").value);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return setMessage("#location-message", "Pick a spot on the map or enter latitude and longitude.");
  try {
    const updated = await request(`/barber/shops/${state.shop.id}/location`, { method: "PUT", body: JSON.stringify({ latitude, longitude, place_id: $("#location-place-id").value || null, postal_code: $("#location-postal").value.trim() || null, address: $("#location-address").value || null }) });
    state.shop = { ...state.shop, ...updated };
    $("#shop-address").textContent = updated.address || "Address not added";
    setMessage("#location-message", "Location saved. Customers can now find your shop.", true);
    showToast("Location saved", "Your shop pin is live for customers.");
  } catch (error) { const message = errorText(error); setMessage("#location-message", message); showToast("Could not save location", message, "error"); }
});
$("#clear-location").addEventListener("click", async () => {
  if (!confirm("Remove your shop pin from the map?")) return;
  try {
    await request(`/barber/shops/${state.shop.id}/location`, { method: "PUT", body: JSON.stringify({ place_id: null }) });
    resetLocationForm({ ...state.shop, latitude: null, longitude: null, place_id: null });
    showToast("Pin cleared", "Your shop location was removed.");
  } catch (error) { const message = errorText(error); setMessage("#location-message", message); showToast("Could not clear location", message, "error"); }
});

document.querySelectorAll("[data-show]").forEach((button) => button.addEventListener("click", () => showAuth(button.dataset.show)));
$("#register-form").addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); if (values.password !== values.confirmPassword) return setMessage("#auth-message", "Passwords do not match."); try { const tokens = await request("/auth/register", { method: "POST", body: JSON.stringify({ email: values.email, password: values.password, role: "SHOP_OWNER" }) }); saveSession(tokens); await bootDashboard(); showToast("Account created", "Welcome to your owner dashboard."); } catch (error) { const message = errorText(error); setMessage("#auth-message", message); showToast("Could not create account", message, "error"); } });
$("#login-form").addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); try { const tokens = await request("/auth/login", { method: "POST", body: JSON.stringify(values) }); saveSession(tokens); await bootDashboard(); showToast("Welcome back", "You are signed in to your owner dashboard."); } catch (error) { const message = errorText(error); setMessage("#auth-message", message); showToast("Could not sign in", message, "error"); } });
$("#shop-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const values = Object.fromEntries(new FormData(form)); try { const shop = await request("/shops", { method: "POST", body: JSON.stringify(values) }); form.reset(); await selectShop(shop); showToast("Shop created", `${shop.name} is ready for its service menu.`); } catch (error) { const message = errorText(error); setMessage("#shop-message", message); showToast("Could not create shop", message, "error"); } });
$("#service-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const values = Object.fromEntries(new FormData(form)); try { const service = await request(`/shops/${state.shop.id}/services`, { method: "POST", body: JSON.stringify({ name: values.name, duration_minutes: Number(values.duration_minutes), price_paise: Math.round(Number(values.price) * 100) }) }); form.reset(); form.duration_minutes.value = 30; form.price.value = 0; await loadServices(); refreshNextSlot(); setMessage("#service-message"); showToast("Service added", `${service.name} is now available in your service menu.`); } catch (error) { const message = errorText(error); setMessage("#service-message", message); showToast("Could not add service", message, "error"); } });
// ── Ask Trimly: owner assistant over the shop's own bookings/payments ──
const ownerChat = { seeded: false, busy: false, lastMessage: "" };

function ownerChatBubble(role, text) {
  const node = document.createElement("div");
  node.className = `chat-bubble ${role}`;
  const copy = document.createElement("p");
  copy.className = "chat-text";
  copy.textContent = text;
  node.append(copy);
  $("#oc-log").append(node);
  $("#oc-log").scrollTop = $("#oc-log").scrollHeight;
  return node;
}

function ownerChatChips(suggestions) {
  $("#oc-chips").replaceChildren(...(suggestions || []).slice(0, 4).map((label) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-chip";
    button.textContent = label;
    button.onclick = () => askOwnerAssistant(label);
    return button;
  }));
}

function renderOwnerReply(reply) {
  const node = ownerChatBubble("bot", reply.answer);
  if (reply.sources && reply.sources.length) {
    const labels = [...new Set(reply.sources.map((source) => source.label))].slice(0, 3);
    const note = document.createElement("p");
    note.className = "chat-sources";
    note.textContent = `From: ${labels.join(" · ")}`;
    node.append(note);
  }
  ownerChatChips(reply.suggestions);
}

async function askOwnerAssistant(text) {
  const message = (text || "").trim();
  if (!message || ownerChat.busy || !state.shop) return;
  ownerChat.busy = true;
  ownerChat.lastMessage = message;
  ownerChatBubble("user", message);
  const typing = ownerChatBubble("bot", "Checking your numbers…");
  typing.classList.add("typing");
  $("#assistant-status").textContent = "Thinking…";
  try {
    const reply = await request("/chat/owner", { method: "POST", body: JSON.stringify({ message, shop_id: state.shop.id }) });
    typing.remove();
    renderOwnerReply(reply);
    $("#assistant-status").textContent = "Ready";
  } catch (error) {
    typing.remove();
    ownerChatBubble("bot", errorText(error));
    $("#assistant-status").textContent = "Could not answer";
  } finally { ownerChat.busy = false; }
}

function openOwnerChat() {
  if (ownerChat.seeded) return;
  ownerChat.seeded = true;
  ownerChatBubble("bot", "Ask me anything about your shop — today's bookings, revenue, popular services, cancellations or reviews. I answer from your live data.");
  ownerChatChips(["How many bookings today?", "Today's revenue", "Who is next?", "Top services"]);
}

$("#oc-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#oc-input");
  const text = input.value.trim();
  input.value = "";
  askOwnerAssistant(text);
});

document.querySelectorAll(".sidebar .nav-link").forEach((link) => link.addEventListener("click", () => showView(link.dataset.view)));
document.querySelectorAll(".buffer-chip").forEach((chip) => chip.addEventListener("click", () => { state.slotAfter = null; refreshNextSlot(Number(chip.dataset.buffer) || 0); }));  $("#slot-edit").addEventListener("click", openSlotEditor);
  $("#next-slot-action").addEventListener("click", () => showView("settings"));
$("#slot-time-apply").addEventListener("click", applyEditedSlotTime);
$("#hours-form").addEventListener("submit", saveHours);
$("#hours-defaults").addEventListener("click", fillDefaultHours);
$("#slot-time-cancel").addEventListener("click", closeSlotEditor);
$("#slot-time-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); applyEditedSlotTime(); }
  if (event.key === "Escape") closeSlotEditor();
});
$("#walk-in-button").addEventListener("click", async () => {
  if (!state.shop) return;
  const button = $("#walk-in-button");
  const takenBy = state.nextSlotAt;
  button.disabled = true;
  try {
    const booking = await request(`/barber/shops/${state.shop.id}/walk-in`, { method: "POST", body: JSON.stringify({ service_id: state.slotServiceId || null, starts_at: takenBy ? takenBy.toISOString() : null }) });
    const when = new Date(booking.starts_at);
    showToast("Walk-in seated", `${timeText(when)} on ${when.toLocaleDateString(undefined, { day: "numeric", month: "short" })} is now taken.`);
    await loadBookings();
    state.slotAfter = null;
    await refreshNextSlot(0);
    if (takenBy && state.nextSlotAt) {
      $("#next-slot-meta").textContent += ` · moved on from ${timeText(takenBy)}`;
    }
  } catch (error) {
    showToast("Could not seat walk-in", errorText(error), "error");
  } finally { button.disabled = !state.shopOpen; }
});
$("#shop-status-toggle").addEventListener("click", async () => {
  if (!state.shop) return;
  const next = !state.shopOpen;
  const toggle = $("#shop-status-toggle");
  toggle.disabled = true;
  renderShopStatus(next); // optimistic; reverted below if the request fails
  try {
    const saved = await request(`/barber/shops/${state.shop.id}/status`, { method: "PUT", body: JSON.stringify({ is_open: next }) });
    state.shop = { ...state.shop, is_active: saved.is_open };
    renderShopStatus(saved.is_open);
    showToast(saved.is_open ? "Shop is open" : "Shop closed", saved.is_open ? "Customers can book you again." : "New bookings are paused until you reopen.");
    refreshNextSlot();
  } catch (error) {
    renderShopStatus(!next);
    showToast("Could not update shop status", errorText(error), "error");
  } finally { toggle.disabled = false; }
});
$("#sign-out").addEventListener("click", () => signOut());
$("#open-password").addEventListener("click", () => { setMessage("#password-message"); $("#password-form").reset(); $("#password-dialog").showModal(); });
$("#password-form").addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); if (values.new_password !== values.confirm_password) return setMessage("#password-message", "New passwords do not match."); try { await request("/auth/password", { method: "PUT", body: JSON.stringify({ current_password: values.current_password, new_password: values.new_password }) }); $("#password-dialog").close(); showToast("Password updated", "Your new password is ready to use."); } catch (error) { const message = errorText(error); setMessage("#password-message", message); showToast("Could not change password", message, "error"); } });
const THEME_KEY = "trimly_theme";
function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (error) { /* private mode */ }
  const icon = next === "dark" ? "☾" : "☀";
  const label = next === "dark" ? "Switch to light mode" : "Switch to dark mode";
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    const slot = button.querySelector(".theme-icon");
    if (slot) slot.textContent = icon;
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
  });
}
document.querySelectorAll(".theme-toggle").forEach((button) => button.addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark")));
applyTheme(document.documentElement.dataset.theme);

if (state.token) bootDashboard(); else showAuth();
