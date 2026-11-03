from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Review, Service, Shop
from app.services.whatsapp_flow import haversine_km


class DiscoveryService:
    """Customer-facing shop discovery: nearby filtering and text search."""

    def __init__(self, db: Session):
        self.db = db

    def nearby(self, latitude: float, longitude: float, limit: int = 10) -> list[dict]:
        shops = self.db.scalars(select(Shop).where(Shop.is_active)).all()
        scored = []
        for shop in shops:
            if shop.latitude is None or shop.longitude is None:
                continue  # unplaced shops cannot be shown as "nearby"
            km = haversine_km(latitude, longitude, shop.latitude, shop.longitude)
            if km <= 25.0:
                scored.append((km, shop))
        scored.sort(key=lambda pair: (pair[0], pair[1].name))
        return [{"shop": shop, "distance_km": round(km, 2)} for km, shop in scored[:limit]]

    def search(self, query: str, latitude: float | None, longitude: float | None, limit: int = 10) -> list[dict]:
        """Rank shops by name match, then by services matching the query."""
        needle = query.strip().lower()
        if not needle:
            return self._ordered(latitude, longitude, self.db.scalars(select(Shop).where(Shop.is_active)).all())
        shops = self.db.scalars(select(Shop).where(Shop.is_active)).all()
        name_hits = [s for s in shops if needle in s.name.lower()]
        service_hits = {
            service.shop_id
            for service in self.db.scalars(select(Service).where(Service.is_active)).all()
            if needle in service.name.lower()
        }
        service_shops = [s for s in shops if s.id in service_hits and s not in name_hits]
        rest = [s for s in shops if s not in name_hits and s not in service_shops]
        return self._ordered(latitude, longitude, name_hits + service_shops + rest)[:limit]

    def _ordered(self, latitude: float | None, longitude: float | None, shops: list[Shop]) -> list[dict]:
        results = []
        for shop in shops:
            distance = None
            if latitude is not None and longitude is not None and shop.latitude is not None and shop.longitude is not None:
                distance = round(haversine_km(latitude, longitude, shop.latitude, shop.longitude), 2)
            results.append({"shop": shop, "distance_km": distance})
        if latitude is not None and longitude is not None:
            results.sort(key=lambda pair: (pair["distance_km"] is None, pair["distance_km"] or 0))
        return results

    def rating_summaries(self, shop_ids: list[int]) -> dict[int, tuple[float | None, int]]:
        """Batch (avg, count) per shop so result lists need one extra query."""
        if not shop_ids:
            return {}
        rows = self.db.execute(
            select(Review.shop_id, func.avg(Review.rating), func.count(Review.id))
            .where(Review.shop_id.in_(shop_ids)).group_by(Review.shop_id)
        ).all()
        return {shop_id: (round(float(avg), 1) if avg is not None else None, count)
                for shop_id, avg, count in rows}

    def to_payload(self, entry: dict, ratings: dict[int, tuple[float | None, int]] | None = None) -> dict:
        shop = entry["shop"]
        rating_avg, rating_count = (ratings or {}).get(shop.id, (None, 0))
        return {
            "id": shop.id, "name": shop.name, "address": shop.address,
            "latitude": shop.latitude, "longitude": shop.longitude,
            "postal_code": shop.postal_code, "is_active": shop.is_active,
            "created_at": shop.created_at, "owner_id": shop.owner_id,
            "convenience_fee_paise": shop.convenience_fee_paise,
            "logo_url": shop.logo_url,
            "distance_km": entry["distance_km"],
            "rating_avg": rating_avg, "rating_count": rating_count,
        }
