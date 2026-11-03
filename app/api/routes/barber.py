from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import require_shop_owner
from app.api.routes.shops import owned_shop
from app.core.database import get_db
from app.integrations.storage.provider import get_logo_storage
from app.models import Booking, BusinessHours, Service, Shop, SlotSettings, User
from app.schemas.booking import NextSlotOut, OwnerBookingOut, WalkInCreate
from app.services.booking_service import BookingService
from app.schemas.business_hours import BusinessHoursOut, BusinessHoursUpsert, SlotSettingsOut, SlotSettingsUpdate
from app.schemas.shop import ConvenienceFeeOut, ConvenienceFeeUpdate, ShopLocationOut, ShopLocationUpdate, ShopStatusOut, ShopStatusUpdate

router = APIRouter(prefix="/barber", tags=["shop-owner"])

@router.get("/shops", summary="List my shops")
def my_shops(user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    return db.scalars(select(Shop).where(Shop.owner_id == user.id).order_by(Shop.created_at.desc())).all()

@router.get("/shops/{shop_id}/bookings", response_model=list[OwnerBookingOut], summary="List my shop's appointments")
def shop_bookings(shop_id: int, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    rows = db.execute(
        select(Booking, Service.name, Service.duration_minutes, Service.price_paise, User.email)
        .join(Service, Service.id == Booking.service_id)
        # Walk-ins have no customer account, so this must not be an inner join.
        .outerjoin(User, User.id == Booking.customer_id)
        .where(Booking.shop_id == shop_id)
        .order_by(Booking.starts_at.desc())
    ).all()
    return [owner_booking(b, sname, dur, price, email) for b, sname, dur, price, email in rows]

def as_utc(value: datetime) -> datetime:
    """Timestamps read back from SQLite lose their offset; always answer in UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

def owner_booking(booking: Booking, service_name: str, duration_minutes: int, price_paise: int, customer_email: str | None) -> OwnerBookingOut:
    return OwnerBookingOut(
        id=booking.id, starts_at=as_utc(booking.starts_at), ends_at=as_utc(booking.ends_at), status=booking.status, code=booking.code,
        service_id=booking.service_id, service_name=service_name, service_duration_minutes=duration_minutes,
        service_price_paise=price_paise, customer_id=booking.customer_id, customer_email=customer_email,
        walk_in_name=booking.walk_in_name, is_walk_in=booking.customer_id is None,
    )

@router.get("/shops/{shop_id}/next-slot", response_model=NextSlotOut, summary="Next time a walk-in can be seated, from now")
def next_slot(shop_id: int, service_id: int | None = None, after: datetime | None = None, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = owned_shop(shop_id, user, db)
    service = db.get(Service, service_id) if service_id else db.scalar(
        select(Service).where(Service.shop_id == shop_id, Service.is_active.is_(True)).order_by(Service.duration_minutes))
    if service and service.shop_id != shop_id:
        service = None
    if not shop.is_active or not service or not service.is_active:
        return NextSlotOut(shop_id=shop.id, is_open=shop.is_active,
                           service_id=service.id if service else None, service_name=service.name if service else None,
                           duration_minutes=service.duration_minutes if service else None)
    service_locked = BookingService(db)
    starts_at = service_locked.next_free_start(shop_id, service.id, after)
    # An empty-but-unconfigured shop reads like a bug to the owner: say why no slot exists.
    reason = None
    if starts_at is None:
        reason = "no_hours" if not service_locked.has_open_hours(shop_id) else "fully_booked"
    return NextSlotOut(shop_id=shop.id, is_open=True, service_id=service.id, service_name=service.name,
                       duration_minutes=service.duration_minutes, starts_at=starts_at, reason=reason)

@router.post("/shops/{shop_id}/walk-in", response_model=OwnerBookingOut, status_code=201, summary="Seat a walk-in customer in the next available slot")
def seat_walk_in(shop_id: int, payload: WalkInCreate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    booking = BookingService(db).create_walk_in(shop_id=shop_id, service_id=payload.service_id, name=payload.name, starts_at=payload.starts_at)
    service = db.get(Service, booking.service_id)
    return owner_booking(booking, service.name, service.duration_minutes, service.price_paise, None)

@router.put("/shops/{shop_id}/status", response_model=ShopStatusOut, summary="Open or close the shop for bookings")
def set_shop_status(shop_id: int, payload: ShopStatusUpdate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = owned_shop(shop_id, user, db)
    shop.is_active = payload.is_open
    db.commit(); db.refresh(shop)
    return ShopStatusOut(shop_id=shop.id, is_open=shop.is_active)

@router.get("/shops/{shop_id}/business-hours", response_model=list[BusinessHoursOut], summary="My shop's business hours")
def shop_hours(shop_id: int, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    return db.scalars(select(BusinessHours).where(BusinessHours.shop_id == shop_id).order_by(BusinessHours.weekday)).all()

@router.put("/shops/{shop_id}/business-hours", response_model=BusinessHoursOut, summary="Set business hours")
def upsert_hours(shop_id: int, payload: BusinessHoursUpsert, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    item = db.scalar(select(BusinessHours).where(BusinessHours.shop_id == shop_id, BusinessHours.weekday == payload.weekday))
    if item:
        for key, value in payload.model_dump().items(): setattr(item, key, value)
    else:
        item = BusinessHours(shop_id=shop_id, **payload.model_dump()); db.add(item)
    db.commit(); db.refresh(item)
    return item

@router.put("/shops/{shop_id}/slot-settings", response_model=SlotSettingsOut, summary="Set slot interval")
def slot_settings(shop_id: int, payload: SlotSettingsUpdate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    item = db.scalar(select(SlotSettings).where(SlotSettings.shop_id == shop_id))
    if item: item.interval_minutes = payload.interval_minutes
    else: item = SlotSettings(shop_id=shop_id, **payload.model_dump()); db.add(item)
    db.commit(); db.refresh(item)
    return item

@router.put("/shops/{shop_id}/convenience-fee", response_model=ConvenienceFeeOut, summary="Set the convenience fee charged on WhatsApp payments")
def set_convenience_fee(shop_id: int, payload: ConvenienceFeeUpdate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = owned_shop(shop_id, user, db)
    shop.convenience_fee_paise = payload.convenience_fee_paise
    db.commit(); db.refresh(shop)
    return ConvenienceFeeOut(shop_id=shop.id, convenience_fee_paise=shop.convenience_fee_paise)

# Logo bytes go through the storage boundary: local disk in development, an
# S3-compatible bucket (R2) in production, where the disk does not survive a deploy.
LOGO_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


@router.put("/shops/{shop_id}/logo", summary="Upload the shop logo/photo (shown as the map avatar)")
def upload_logo(shop_id: int, file: UploadFile = File(...), user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = owned_shop(shop_id, user, db)
    suffix = LOGO_CONTENT_TYPES.get(file.content_type or "")
    if not suffix:
        raise HTTPException(422, "Logo must be a JPEG, PNG, or WebP image")
    data = file.file.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(413, "Logo must be 2 MB or smaller")
    if not data:
        raise HTTPException(422, "Empty file")
    # Content hash in the name: re-uploads replace the object and the browser re-fetches.
    shop.logo_url = get_logo_storage().save(data, suffix, file.content_type or "image/jpeg")
    db.commit()
    return {"logo_url": shop.logo_url}


@router.delete("/shops/{shop_id}/logo", summary="Remove the shop logo")
def delete_logo(shop_id: int, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = owned_shop(shop_id, user, db)
    shop.logo_url = None
    db.commit()
    return {"logo_url": None}


@router.put("/shops/{shop_id}/location", response_model=ShopLocationOut, summary="Set or clear the shop location pin")
def set_location(shop_id: int, payload: ShopLocationUpdate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = owned_shop(shop_id, user, db)
    if payload.latitude is None:
        shop.latitude = None; shop.longitude = None; shop.place_id = None
    else:
        shop.latitude = payload.latitude; shop.longitude = payload.longitude; shop.place_id = payload.place_id
    if "postal_code" in payload.model_fields_set:
        shop.postal_code = payload.postal_code
    if "address" in payload.model_fields_set:
        shop.address = payload.address
    db.commit(); db.refresh(shop)
    return shop
