from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.discovery_service import DiscoveryService

router = APIRouter(prefix="/discover", tags=["discovery"])


@router.get("/nearby", summary="Shops ranked by distance from a coordinate")
def nearby(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
):
    service = DiscoveryService(db)
    entries = service.nearby(latitude, longitude, limit)
    ratings = service.rating_summaries([entry["shop"].id for entry in entries])
    return [service.to_payload(entry, ratings) for entry in entries]


@router.get("/search", summary="Search shops by shop name or service name")
def search(
    q: str = Query(min_length=1, max_length=120),
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
):
    service = DiscoveryService(db)
    entries = service.search(q, latitude, longitude, limit)
    ratings = service.rating_summaries([entry["shop"].id for entry in entries])
    return [service.to_payload(entry, ratings) for entry in entries]
