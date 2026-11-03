from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.routes import admin, auth, availability, barber, bookings, chat, customer, discovery, payments, reviews, services, shops, whatsapp
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="1.0.0", description="Transactional appointment booking API")

@app.get("/health", tags=["health"], summary="Health check")
def health():
    return {"status": "ok"}

app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(shops.router, prefix=settings.api_v1_prefix)
app.include_router(services.router, prefix=settings.api_v1_prefix)
app.include_router(availability.router, prefix=settings.api_v1_prefix)
app.include_router(bookings.router, prefix=settings.api_v1_prefix)
app.include_router(discovery.router, prefix=settings.api_v1_prefix)
app.include_router(reviews.router, prefix=settings.api_v1_prefix)
app.include_router(customer.router, prefix=settings.api_v1_prefix)
app.include_router(barber.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(whatsapp.router, prefix=settings.api_v1_prefix)
app.include_router(payments.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)

class RevalidatingStaticFiles(StaticFiles):
    """Static files that always revalidate in the browser.

    StaticFiles sends no Cache-Control header, so browsers heuristically cache
    pages and keep serving stale HTML/JS/CSS after edits. `no-cache` forces a
    cheap If-Modified-Since revalidation (files unchanged -> 304) instead.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Uploaded shop logos (owner-uploaded, served read-only).
uploads_dir = Path(__file__).parent.parent / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# The owner portal is intentionally a separate presentation layer; it uses the
# same versioned API as any future mobile or WhatsApp client.
# Mounted before the customer portal: the catch-all "/" mount would otherwise
# swallow every path, making /dashboard and /admin unreachable.
app.mount("/dashboard", RevalidatingStaticFiles(directory=Path(__file__).parent / "web", html=True), name="owner-portal")
app.mount("/admin", RevalidatingStaticFiles(directory=Path(__file__).parent / "admin_web", html=True), name="admin-portal")

# The customer booking portal is the public-facing webapp (mounted last so its
# catch-all "/" prefix does not shadow the portals above).
app.mount("/", RevalidatingStaticFiles(directory=Path(__file__).parent / "customer_web", html=True), name="customer-portal")
