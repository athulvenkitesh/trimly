from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models import Booking, Service, Shop, User
from app.schemas.admin import AdminServiceOut, AdminShopOut, AdminShopStatusUpdate

router = APIRouter(prefix="/admin", tags=["administration"])

@router.get("/shops", response_model=list[AdminShopOut], summary="List every shop for administration")
def list_shops(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Shop, User.email, func.count(Service.id))
        .join(User, Shop.owner_id == User.id)
        .outerjoin(Service, Service.shop_id == Shop.id)
        .group_by(Shop.id, User.email)
        .order_by(Shop.created_at.desc())
    ).all()
    return [AdminShopOut(id=shop.id, name=shop.name, address=shop.address, is_active=shop.is_active,
                         owner_email=email, service_count=count, created_at=shop.created_at)
            for shop, email, count in rows]

@router.patch("/shops/{shop_id}", response_model=AdminShopOut, summary="Enable or disable a shop")
def update_shop_status(shop_id: int, payload: AdminShopStatusUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    shop.is_active = payload.is_active
    db.commit()
    owner = db.get(User, shop.owner_id)
    count = db.scalar(select(func.count(Service.id)).where(Service.shop_id == shop.id))
    return AdminShopOut(id=shop.id, name=shop.name, address=shop.address, is_active=shop.is_active,
                        owner_email=owner.email, service_count=count, created_at=shop.created_at)

@router.delete("/shops/{shop_id}", status_code=204, summary="Permanently delete a shop without bookings")
def delete_shop(shop_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    booking_count = db.scalar(select(func.count(Booking.id)).where(Booking.shop_id == shop.id))
    if booking_count:
        raise HTTPException(status_code=409, detail="This shop has booking history and cannot be deleted. Disable it instead.")
    db.delete(shop)
    db.commit()

@router.get("/services", response_model=list[AdminServiceOut], summary="List every service for administration")
def list_services(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(Service, Shop.name).join(Shop, Service.shop_id == Shop.id).order_by(Service.id.desc())).all()
    return [AdminServiceOut(id=service.id, name=service.name, duration_minutes=service.duration_minutes,
                            price_paise=service.price_paise, is_active=service.is_active,
                            shop_id=service.shop_id, shop_name=shop_name)
            for service, shop_name in rows]

@router.patch("/services/{service_id}/deactivate", response_model=AdminServiceOut, summary="Deactivate a service")
def deactivate_service(service_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Service not found")
    service.is_active = False
    db.commit()
    shop = db.get(Shop, service.shop_id)
    return AdminServiceOut(id=service.id, name=service.name, duration_minutes=service.duration_minutes,
                           price_paise=service.price_paise, is_active=service.is_active,
                           shop_id=service.shop_id, shop_name=shop.name)

@router.delete("/services/{service_id}", status_code=204, summary="Permanently delete a service without bookings")
def delete_service(service_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Service not found")
    booking_count = db.scalar(select(func.count(Booking.id)).where(Booking.service_id == service.id))
    if booking_count:
        raise HTTPException(status_code=409, detail="This service has booking history and cannot be deleted. Deactivate it instead.")
    db.delete(service)
    db.commit()
