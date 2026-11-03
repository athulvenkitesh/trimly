from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user, require_customer
from app.core.database import get_db
from app.models import Booking, User
from app.schemas.booking import BookingCreate, BookingOut
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["bookings"])

@router.post("", response_model=BookingOut, status_code=201, responses={409: {"description": "Slot not available"}}, summary="Reserve a slot")
def create_booking(payload: BookingCreate, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return BookingService(db).create_booking(customer_id=user.id, **payload.model_dump())

@router.get("/me", response_model=list[BookingOut], summary="List my bookings")
def my_bookings(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return db.scalars(select(Booking).where(Booking.customer_id == user.id).order_by(Booking.starts_at.desc())).all()

@router.get("/{booking_id}", response_model=BookingOut, summary="Get a booking")
def get_booking(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking: raise HTTPException(404, "Booking not found")
    if user.id != booking.customer_id and user.role.value != "ADMIN": raise HTTPException(403, "Insufficient permissions")
    return booking

@router.post("/{booking_id}/cancel", response_model=BookingOut, summary="Cancel my booking")
def cancel_booking(booking_id: int, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return BookingService(db).cancel_booking(booking_id, user.id)
