const API = "/api/v1";
const state = { token: localStorage.getItem("trimly_admin_access_token"), shops: [], services: [], view: "shops" };
const $ = (selector) => document.querySelector(selector);

function errorText(error) { if (typeof error?.detail === "string") return error.detail; if (Array.isArray(error?.detail)) return error.detail.map((x) => x.msg).join(" "); return error?.message || `Request failed${error?.status ? ` (HTTP ${error.status})` : ""}.`; }
function toast(title, text = "", kind = "success") { const node = document.createElement("div"); node.className = `toast ${kind}`; node.innerHTML = `<div><b></b><span></span></div><button aria-label="Dismiss">×</button>`; node.querySelector("b").textContent = title; node.querySelector("span").textContent = text; const close = () => node.remove(); node.querySelector("button").onclick = close; $("#toast-region").append(node); setTimeout(close, 5000); }
async function request(path, options = {}) { const response = await fetch(`${API}${path}`, { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}`, ...(options.headers || {}) } }); const body = response.status === 204 ? null : await response.json().catch(() => ({})); if (!response.ok) throw { ...body, status: response.status }; return body; }
function signOut(message = "") { state.token = null; localStorage.removeItem("trimly_admin_access_token"); $("#admin-screen").hidden = true; $("#login-screen").hidden = false; if (message) $("#login-message").textContent = message; }
async function boot() { try { const me = await request("/auth/me"); if (me.role !== "ADMIN") throw { detail: "This account does not have administrator access." }; $("#admin-email").textContent = me.email; $("#login-screen").hidden = true; $("#admin-screen").hidden = false; await refresh(); } catch (error) { signOut(errorText(error)); } }
async function refresh() { try { [state.shops, state.services] = await Promise.all([request("/admin/shops"), request("/admin/services")]); render(); } catch (error) { toast("Could not load dashboard", errorText(error), "error"); if (error.status === 401 || error.status === 403) signOut(errorText(error)); } }
function setMetrics() { $("#shop-total").textContent = state.shops.length; $("#shop-active").textContent = state.shops.filter((shop) => shop.is_active).length; $("#service-total").textContent = state.services.filter((service) => service.is_active).length; }
function status(active) { const node = document.createElement("span"); node.className = `status ${active ? "active" : "inactive"}`; node.textContent = active ? "Active" : "Disabled"; return node; }
function cell(text, className = "") { const node = document.createElement("td"); if (className) node.className = className; node.textContent = text; return node; }
function actionButton(text, className, onClick) { const button = document.createElement("button"); button.className = className; button.textContent = text; button.onclick = onClick; return button; }
function renderShops() {
  const needle = $("#shop-search").value.toLowerCase().trim();
  const shops = state.shops.filter((shop) => `${shop.name} ${shop.owner_email}`.toLowerCase().includes(needle));
  const table = $("#shops-table"); table.innerHTML = ""; $("#shops-empty").hidden = shops.length > 0;
  $("#shop-caption").textContent = `${shops.length} of ${state.shops.length} shops`;
  shops.forEach((shop) => {
    const row = document.createElement("tr"); const name = cell("", "shop-name"); name.textContent = shop.name;
    row.append(name, cell(shop.owner_email), cell(`${shop.service_count} service${shop.service_count === 1 ? "" : "s"}`));
    const statusCell = document.createElement("td"); statusCell.append(status(shop.is_active)); row.append(statusCell, cell(new Date(shop.created_at).toLocaleDateString()));
    const actionCell = document.createElement("td");
    actionCell.append(actionButton(shop.is_active ? "Disable" : "Enable", "action", () => setShopStatus(shop)), actionButton("Delete", "action danger", () => deleteShop(shop)));
    row.append(actionCell); table.append(row);
  });
}
function renderServices() {
  const needle = $("#service-search").value.toLowerCase().trim();
  const services = state.services.filter((service) => `${service.name} ${service.shop_name}`.toLowerCase().includes(needle));
  const table = $("#services-table"); table.innerHTML = ""; $("#services-empty").hidden = services.length > 0;
  $("#service-caption").textContent = `${services.length} of ${state.services.length} services`;
  services.forEach((service) => {
    const row = document.createElement("tr"); row.append(cell(service.name, "service-name"), cell(service.shop_name), cell(`${service.duration_minutes} min`), cell(`₹${(service.price_paise / 100).toFixed(0)}`));
    const statusCell = document.createElement("td"); statusCell.append(status(service.is_active)); row.append(statusCell);
    const actionCell = document.createElement("td");
    if (service.is_active) actionCell.append(actionButton("Deactivate", "action", () => deactivateService(service)));
    actionCell.append(actionButton("Delete", "action danger", () => deleteService(service)));
    row.append(actionCell); table.append(row);
  });
}
function render() { setMetrics(); renderShops(); renderServices(); }
async function setShopStatus(shop) { const target = !shop.is_active; const verb = target ? "enable" : "disable"; if (!confirm(`Are you sure you want to ${verb} ${shop.name}?`)) return; try { await request(`/admin/shops/${shop.id}`, { method: "PATCH", body: JSON.stringify({ is_active: target }) }); toast(target ? "Shop enabled" : "Shop disabled", `${shop.name} was updated.`); await refresh(); } catch (error) { toast("Could not update shop", errorText(error), "error"); } }
async function deactivateService(service) { if (!confirm(`Deactivate ${service.name}? Customers will no longer be able to book it.`)) return; try { await request(`/admin/services/${service.id}/deactivate`, { method: "PATCH" }); toast("Service deactivated", `${service.name} is no longer bookable.`); await refresh(); } catch (error) { toast("Could not deactivate service", errorText(error), "error"); } }
async function deleteShop(shop) { if (!confirm(`Permanently delete ${shop.name}? This cannot be undone.`)) return; try { await request(`/admin/shops/${shop.id}`, { method: "DELETE" }); toast("Shop deleted", `${shop.name} was permanently removed.`); await refresh(); } catch (error) { toast("Could not delete shop", errorText(error), "error"); } }
async function deleteService(service) { if (!confirm(`Permanently delete ${service.name}? This cannot be undone.`)) return; try { await request(`/admin/services/${service.id}`, { method: "DELETE" }); toast("Service deleted", `${service.name} was permanently removed.`); await refresh(); } catch (error) { toast("Could not delete service", errorText(error), "error"); } }
$("#login-form").addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); try { const tokens = await request("/auth/login", { method: "POST", body: JSON.stringify(values), headers: { Authorization: "" } }); state.token = tokens.access_token; localStorage.setItem("trimly_admin_access_token", tokens.access_token); await boot(); } catch (error) { const message = errorText(error); $("#login-message").textContent = message; toast("Sign in failed", message, "error"); } });
document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => { state.view = button.dataset.view; document.querySelectorAll(".nav").forEach((item) => item.classList.toggle("active", item === button)); $("#shops-view").hidden = state.view !== "shops"; $("#services-view").hidden = state.view !== "services"; $("#page-title").textContent = state.view === "shops" ? "Shops" : "Services"; $("#page-subtitle").textContent = state.view === "shops" ? "Review and manage every barbershop on Trimly." : "Review every bookable service across the marketplace."; }));
$("#shop-search").addEventListener("input", renderShops); $("#service-search").addEventListener("input", renderServices); $("#refresh").onclick = refresh; $("#sign-out").onclick = () => signOut();
$("#open-password").onclick = () => { $("#password-form").reset(); $("#password-message").textContent = ""; $("#password-dialog").showModal(); };
$("#password-form").addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget)); if (values.new_password !== values.confirm_password) { $("#password-message").textContent = "New passwords do not match."; return; } try { await request("/auth/password", { method: "PUT", body: JSON.stringify({ current_password: values.current_password, new_password: values.new_password }) }); $("#password-dialog").close(); toast("Password updated", "Your new password is ready to use."); } catch (error) { const message = errorText(error); $("#password-message").textContent = message; toast("Could not change password", message, "error"); } });
if (state.token) boot();
