"""Retrieval layer for the Trimly assistants.

The assistants never invent facts: every sentence they produce is composed from
documents retrieved here, and those documents are built from live database rows
(shop profiles, the service menu, opening hours, reviews, bookings, payments).

Retrieval is BM25 over tokenised document text — a lexical retriever that needs
no embedding service, no API key and no index rebuild job: the corpus is small
and is rebuilt from the database on every request, so an answer can never cite
a shop, price or booking that no longer exists.
"""

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessHours, Payment, Review, Service, Shop
from app.services.whatsapp_flow import haversine_km

TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "do", "does", "for", "from",
    "get", "has", "have", "how", "i", "in", "is", "it", "its", "me", "my", "of",
    "on", "or", "please", "show", "the", "to", "want", "was", "what", "when",
    "where", "which", "who", "why", "with", "you", "your", "any", "there", "this",
    "that", "near", "nearby", "around", "about", "list", "give", "tell", "much",
    "many", "would", "could", "should", "need", "would", "like",
}

# "haircut" and "hair cut" should land on the same document.
ALIASES = {
    "haircut": "hair cut", "haircuts": "hair cut", "trim": "hair cut",
    "shave": "shaving beard", "beard": "beard", "fade": "fade hair cut",
    # Customers say "shops"; the documents call them barbershops/salons.
    "shop": "barbershop", "shops": "barbershop", "barbershop": "barbershop barber",
    "barbershops": "barbershop barber", "barbers": "barber", "salons": "salon barbershop",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def inr(paise: int) -> str:
    rupees = paise / 100
    return f"₹{rupees:,.0f}" if rupees == int(rupees) else f"₹{rupees:,.2f}"


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    for alias, expansion in ALIASES.items():
        lowered = re.sub(rf"\b{alias}\b", expansion, lowered)
    return [token for token in TOKEN_RE.findall(lowered) if token not in STOPWORDS]


@dataclass(frozen=True)
class Document:
    """One retrievable unit: a shop, a service, a review, a booking or a payment."""

    doc_id: str
    kind: str
    label: str
    text: str
    shop_id: int | None = None
    data: dict = field(default_factory=dict)


class RagIndex:
    """BM25 index over a document list (k1=1.5, b=0.75 — the usual defaults)."""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        self._tokens = [tokenize(doc.text) for doc in documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        self._postings: dict[str, dict[int, int]] = {}
        for position, tokens in enumerate(self._tokens):
            for token in tokens:
                bucket = self._postings.setdefault(token, {})
                bucket[position] = bucket.get(position, 0) + 1

    def __len__(self) -> int:
        return len(self.documents)

    def _idf(self, token: str) -> float:
        frequency = len(self._postings.get(token, {}))
        return math.log(1 + (len(self.documents) - frequency + 0.5) / (frequency + 0.5))

    def search(self, query: str, limit: int = 5, kinds: set[str] | None = None) -> list[tuple[float, Document]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores: dict[int, float] = {}
        for token in query_tokens:
            for position, term_frequency in self._postings.get(token, {}).items():
                if kinds and self.documents[position].kind not in kinds:
                    continue
                length_norm = 1 - 0.75 + 0.75 * (self._lengths[position] / self._avg_length)
                saturation = term_frequency * 2.5 / (term_frequency + 1.5 * length_norm)
                scores[position] = scores.get(position, 0.0) + self._idf(token) * saturation
        ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        return [(round(score, 4), self.documents[position]) for position, score in ranked[:limit]]


# ── Corpus: customers ───────────────────────────────────────────────────────

def _hours_text(hours: list[BusinessHours]) -> str:
    if not hours:
        return "opening hours not published yet"
    parts = []
    for entry in sorted(hours, key=lambda row: row.weekday):
        day = DAY_NAMES[entry.weekday % 7]
        parts.append(f"{day} closed" if entry.is_closed
                     else f"{day} {entry.opens_at.strftime('%H:%M')}-{entry.closes_at.strftime('%H:%M')}")
    return "; ".join(parts)


def _rating(reviews: list[Review]) -> str:
    if not reviews:
        return "no ratings yet"
    average = sum(review.rating for review in reviews) / len(reviews)
    return f"rated {average:.1f}/5 from {len(reviews)} review{'' if len(reviews) == 1 else 's'}"


def customer_documents(db: Session, latitude: float | None = None, longitude: float | None = None) -> list[Document]:
    """One document per shop, service, opening-hours sheet and review."""
    shops = db.scalars(select(Shop)).all()
    services = db.scalars(select(Service)).all()
    hours = db.scalars(select(BusinessHours)).all()
    reviews = db.scalars(select(Review)).all()

    active_services: dict[int, list[Service]] = {}
    for service in services:
        if service.is_active:
            active_services.setdefault(service.shop_id, []).append(service)
    hours_by_shop: dict[int, list[BusinessHours]] = {}
    for entry in hours:
        hours_by_shop.setdefault(entry.shop_id, []).append(entry)
    reviews_by_shop: dict[int, list[Review]] = {}
    for review in reviews:
        reviews_by_shop.setdefault(review.shop_id, []).append(review)

    documents: list[Document] = []
    for shop in shops:
        if not shop.is_active:
            continue  # closed shops are not offered to customers
        shop_services = active_services.get(shop.id, [])
        shop_reviews = reviews_by_shop.get(shop.id, [])
        distance = None
        if latitude is not None and longitude is not None and shop.latitude is not None and shop.longitude is not None:
            distance = round(haversine_km(latitude, longitude, shop.latitude, shop.longitude), 2)
        menu = ", ".join(f"{service.name} {inr(service.price_paise)} ({service.duration_minutes} min)"
                         for service in shop_services) or "no services published yet"
        text = (
            f"{shop.name} barbershop salon at {shop.address or 'address not published'}"
            f"{f' pincode {shop.postal_code}' if shop.postal_code else ''}. "
            f"Services: {menu}. Convenience fee {inr(shop.convenience_fee_paise)}. "
            f"This shop is {_rating(shop_reviews)}. "
            f"Opening hours: {_hours_text(hours_by_shop.get(shop.id, []))}. "
            + (f"{distance} km away from the customer. " if distance is not None else "")
            + f"{'Open for bookings.' if shop.is_active else 'Currently closed.'}"
        )
        documents.append(Document(
            doc_id=f"shop:{shop.id}", kind="shop", label=shop.name, text=text, shop_id=shop.id,
            data={"name": shop.name, "address": shop.address, "postal_code": shop.postal_code,
                  "distance_km": distance, "convenience_fee_paise": shop.convenience_fee_paise,
                  "is_active": shop.is_active, "service_ids": [service.id for service in shop_services]},
        ))
        for service in shop_services:
            documents.append(Document(
                doc_id=f"service:{service.id}", kind="service",
                label=f"{service.name} at {shop.name}",
                text=(f"{service.name} at {shop.name} barbershop costs {inr(service.price_paise)} "
                      f"and takes {service.duration_minutes} minutes. Located at {shop.address or 'address not set'}."),
                shop_id=shop.id,
                data={"name": service.name, "shop_id": shop.id, "price_paise": service.price_paise,
                      "duration_minutes": service.duration_minutes},
            ))
        hours_row = hours_by_shop.get(shop.id, [])
        if hours_row:
            documents.append(Document(
                doc_id=f"hours:{shop.id}", kind="hours", label=f"{shop.name} opening hours",
                text=f"{shop.name} opening hours and timings: {_hours_text(hours_row)}.",
                shop_id=shop.id,
            ))
        for review in shop_reviews:
            if not review.comment:
                continue
            documents.append(Document(
                doc_id=f"review:{review.id}", kind="review",
                label=f"Review of {shop.name} ({review.rating}/5)",
                text=f"Customer review of {shop.name}: {review.rating} out of 5 stars. {review.comment}",
                shop_id=shop.id, data={"rating": review.rating},
            ))
    return documents


# ── Corpus: shop owners ─────────────────────────────────────────────────────

def owner_documents(db: Session, shop: Shop, bookings: list, payments: list[Payment],
                    services: dict[int, Service], days: int = 30) -> list[Document]:
    """Booking/payment/review rows as documents, so answers can cite them."""
    documents: list[Document] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for booking in bookings:
        starts_at = booking.starts_at if booking.starts_at.tzinfo else booking.starts_at.replace(tzinfo=timezone.utc)
        if starts_at < cutoff:
            continue
        service = services.get(booking.service_id)
        customer = booking.walk_in_name or (booking.customer_id and f"customer #{booking.customer_id}") or "customer"
        documents.append(Document(
            doc_id=f"booking:{booking.id}", kind="booking", label=f"Booking {booking.code}",
            text=(f"Booking {booking.code}: {service.name if service else 'service'} "
                  f"{inr(service.price_paise) if service else ''} for {customer} "
                  f"on {starts_at.strftime('%a %d %b %Y')} at {starts_at.strftime('%H:%M')} UTC "
                  f"status {booking.status.value if hasattr(booking.status, 'value') else booking.status}"
                  f"{' walk-in' if booking.customer_id is None else ''}."),
            shop_id=shop.id,
            data={"starts_at": starts_at.isoformat(), "service_id": booking.service_id,
                  "status": booking.status.value if hasattr(booking.status, "value") else str(booking.status)},
        ))
    for payment in payments:
        documents.append(Document(
            doc_id=f"payment:{payment.id}", kind="payment", label=f"Payment {payment.provider_reference or payment.id}",
            text=(f"Payment {inr(payment.amount_paise)} for booking #{payment.booking_id} via {payment.method} "
                  f"status {payment.status.value if hasattr(payment.status, 'value') else payment.status}."),
            shop_id=shop.id,
            data={"status": payment.status.value if hasattr(payment.status, "value") else str(payment.status),
                  "amount_paise": payment.amount_paise},
        ))
    reviews = db.scalars(select(Review).where(Review.shop_id == shop.id)).all()
    for review in reviews:
        documents.append(Document(
            doc_id=f"review:{review.id}", kind="review", label=f"Review ({review.rating}/5)",
            text=f"Customer review {review.rating} out of 5 stars. {review.comment or 'no comment'}",
            shop_id=shop.id, data={"rating": review.rating},
        ))
    documents.append(Document(
        doc_id=f"shop:{shop.id}", kind="shop", label=shop.name,
        text=(f"{shop.name} barbershop at {shop.address or 'address not set'} "
              f"{'open' if shop.is_active else 'closed'}. Services: "
              + ", ".join(f"{service.name} {inr(service.price_paise)}" for service in services.values())),
        shop_id=shop.id,
    ))
    return documents


def citations(results: list[tuple[float, Document]], limit: int = 4) -> list[dict]:
    """Small, de-duplicated source list for the reply footer."""
    seen: set[str] = set()
    out: list[dict] = []
    for _score, document in results:
        if document.doc_id in seen:
            continue
        seen.add(document.doc_id)
        out.append({"doc_id": document.doc_id, "kind": document.kind, "label": document.label})
        if len(out) >= limit:
            break
    return out


def today_utc() -> date:
    return datetime.now(timezone.utc).date()
