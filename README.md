# Transactional Booking API

FastAPI + SQLAlchemy 2.x backend for shop appointment bookings. PostgreSQL is the production datastore; Redis is provisioned for deferred work such as notifications and reminders.

## Start locally

```bash
cp .env.example .env
docker compose up --build
docker compose exec api alembic upgrade head
```

The API is served at `http://localhost:8000`, Swagger at `/docs`, and ReDoc at `/redoc`.

## Deploy

[`DEPLOY.md`](DEPLOY.md) covers production: a Render Blueprint
([`render.yaml`](render.yaml)) that builds the [Dockerfile](Dockerfile), runs
`alembic upgrade head` before each release, and connects a managed Postgres.
Shop logos go to Cloudflare R2 (`STORAGE_BACKEND=s3`) because a container host
replaces its filesystem on every deploy. Set `PORT`/`DATABASE_URL` from the
environment — `postgresql://` URLs are rewritten to the psycopg 3 driver
automatically.

## Design highlights

- `BookingService` owns synchronous reservation transactions; background work is deliberately kept out of the commit path.
- `AvailabilityService` is the one source of truth for slots.
- PostgreSQL locks the shop during availability verification and a partial unique index on active `(shop_id, starts_at)` bookings is the definitive cross-worker concurrency guard.
- Owner routes validate shop ownership before a mutation. JWT access and refresh tokens use distinct token types.
- WhatsApp and payment providers are reserved behind `app/integrations/` boundaries so neither contains booking-domain logic.
- Shop locations are stored as `latitude`/`longitude`/`place_id` on `shops`. Owners set the pin from the dashboard's map picker (Leaflet + OpenStreetMap — free, no API key or billing required; address search uses Nominatim).

## Migrations

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```
