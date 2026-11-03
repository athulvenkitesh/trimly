from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models import Booking, BookingStatus, Review, Shop, User
from app.schemas.review import ReviewCreate, ReviewListOut, ReviewOut

router = APIRouter(prefix="/shops/{shop_id}/reviews", tags=["reviews"])


def rating_summary(db: Session, shop_id: int) -> tuple[float | None, int]:
    avg, count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(Review.shop_id == shop_id)
    ).one()
    return (round(float(avg), 1) if avg is not None else None), count


def _display_name(email: str) -> str:
    """Reviews show the email local part only — never the full address."""
    local = email.split("@")[0]
    return local[:1] + local[1:24]


def to_out(review: Review, customer: User | None) -> ReviewOut:
    return ReviewOut(
        id=review.id, shop_id=review.shop_id, customer_id=review.customer_id,
        rating=review.rating, comment=review.comment, created_at=review.created_at,
        customer_name=_display_name(customer.email) if customer else "Guest",
    )


@router.get("", response_model=ReviewListOut, summary="Reviews for a shop with rating summary")
def list_reviews(shop_id: int, db: Session = Depends(get_db)):
    if not db.get(Shop, shop_id):
        raise HTTPException(404, "Shop not found")
    rows = db.execute(
        select(Review, User).join(User, Review.customer_id == User.id, isouter=True)
        .where(Review.shop_id == shop_id).order_by(Review.created_at.desc(), Review.id.desc())
    ).all()
    avg, count = rating_summary(db, shop_id)
    return ReviewListOut(rating_avg=avg, rating_count=count,
                         reviews=[to_out(review, user) for review, user in rows])


@router.post("", response_model=ReviewOut, status_code=201, summary="Leave a review (customer with a booking)")
def create_review(shop_id: int, payload: ReviewCreate,
                  user: User = Depends(require_customer), db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    # Only customers with a real, non-cancelled booking at this shop may review.
    booked = db.scalar(select(Booking.id).where(
        Booking.shop_id == shop_id, Booking.customer_id == user.id,
        Booking.status != BookingStatus.CANCELLED).limit(1))
    if not booked:
        raise HTTPException(403, "You can only review shops you've booked with")
    existing = db.scalar(select(Review).where(
        Review.shop_id == shop_id, Review.customer_id == user.id))
    if existing:
        raise HTTPException(409, "You've already reviewed this shop — editing comes next")
    review = Review(shop_id=shop_id, customer_id=user.id, booking_id=booked,
                    rating=payload.rating, comment=(payload.comment or "").strip() or None)
    db.add(review)
    db.commit()
    db.refresh(review)
    return to_out(review, user)
