"""Shop-owner assistant: today's bookings, revenue, popular services and reviews.

Answers are computed from the owner's own rows only (scoped by shop_id), and
the documents behind each answer are returned as citations. Times follow the
rest of the product and are reported in UTC.
"""

import re
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, BusinessHours, Payment, PaymentStatus, Review, Service, Shop, User
from app.schemas.chat import ChatCard, ChatReply, ChatSource
from app.services.chat import intents
from app.services.chat.rag import Document, RagIndex, citations, inr, owner_documents

MAX_CARDS = 5
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

OWNER_INTENTS: dict[str, list[str]] = {
    "greeting": ["hi", "hello", "hey", "good morning", "good evening", "namaste"],
    "help": ["help", "what can you do", "how does this work", "options", "what can i ask"],
    "today_bookings": ["today's bookings", "todays bookings", "bookings today", "today's booking",
                       "appointments today", "today's appointments", "how many bookings today",
                       "today's schedule", "schedule today", "bookings for today"],
    "today_revenue": ["today's revenue", "todays revenue", "revenue today", "today's collection",
                      "collection today", "today's earnings", "earnings today", "today's income",
                      "how much did i make", "how much money today", "money today", "sales today"],
    "period_report": ["this week", "this month", "last week", "yesterday", "weekly", "monthly",
                      "revenue", "earnings", "collection", "income", "turnover", "sales", "bookings"],
    "next_appointment": ["next appointment", "next booking", "who is next", "who's next",
                         "upcoming", "next customer", "coming up", "later today"],
    "top_services": ["top service", "top services", "most popular", "best selling", "best seller",
                     "which service", "popular service", "service performance", "most booked"],
    "walk_ins": ["walk in", "walk-in", "walk-ins", "walkins", "walk ins"],
    "cancellations": ["cancelled", "cancellations", "cancellation", "no show", "no-shows",
                      "cancel rate", "how many cancelled"],
    "reviews": ["review", "reviews", "rating", "ratings", "feedback", "stars", "complaints"],
    "hours": ["hours", "opening", "closing", "timings", "what time do i open", "am i open"],
    "customers": ["how many customers", "customers", "repeat customers", "loyal", "regulars"],
}


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(moment.date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def month_bounds(moment: datetime) -> datetime:
    return datetime.combine(moment.date().replace(day=1), time.min, tzinfo=timezone.utc)


def window_text(start: datetime, end: datetime, label: str, single_day: bool) -> str:
    """Label the window the numbers cover, so the headline can't misstate it."""
    if single_day:
        return f"{label.lower()} ({start.strftime('%a %d %b')}, UTC)"
    last_day = end - timedelta(days=1)
    return f"{label.lower()} ({start.strftime('%d %b')} – {last_day.strftime('%d %b')}, UTC)"


def sentence(text: str) -> str:
    """Capitalise a window label when it opens a line."""
    return text[:1].upper() + text[1:]


def fmt_when(moment: datetime) -> str:
    return moment.strftime("%a %d %b, %H:%M") + " UTC"


class OwnerChat:
    def __init__(self, db: Session):
        self.db = db
        self.shop: Shop | None = None
        self.index = RagIndex([])
        self.services: dict[int, Service] = {}
        self.bookings: list[Booking] = []
        self.payments: list[Payment] = []

    # ── Entry point ────────────────────────────────────────────────────────
    def reply(self, *, message: str, shop: Shop) -> ChatReply:
        self.shop = shop
        self.services = {service.id: service for service in
                         self.db.scalars(select(Service).where(Service.shop_id == shop.id)).all()}
        # A 30-day window keeps the corpus small while covering every question
        # the assistant can answer with row-level citations.
        horizon = datetime.now(timezone.utc) - timedelta(days=30)
        self.bookings = self.db.scalars(
            select(Booking).where(Booking.shop_id == shop.id, Booking.starts_at >= horizon)
            .order_by(Booking.starts_at)).all()
        self.payments = self.db.scalars(
            select(Payment).join(Booking, Booking.id == Payment.booking_id)
            .where(Booking.shop_id == shop.id, Booking.starts_at >= horizon)).all()
        self.index = RagIndex(owner_documents(self.db, shop, self.bookings, self.payments, self.services))

        intent, score = intents.detect_intent(message, OWNER_INTENTS)
        if score < 1.0:
            return self._fallback(message)
        return {
            "greeting": self._greeting, "help": self._help,
            "today_bookings": self._today_bookings, "today_revenue": self._today_revenue,
            "period_report": self._period_report, "next_appointment": self._next_appointment,
            "top_services": self._top_services, "walk_ins": self._walk_ins,
            "cancellations": self._cancellations, "reviews": self._reviews,
            "hours": self._hours, "customers": self._customers,
        }[intent](message)

    def parse_period(self, message: str, *, weekly_default: bool = False,
                     ) -> tuple[datetime, datetime, str, bool]:
        """Resolve the window an owner means: today, yesterday, week, month.

        All three report handlers share this one parser, so the label and the
        rows counted can never come from different windows ("how many bookings
        do I have today?" must not answer with this week's total).
        Returns (start, end, label, is_single_day).
        """
        lowered = intents.normalize(message)
        day_start, day_end = day_bounds(datetime.now(timezone.utc))
        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = month_bounds(day_start)

        if re.search(r"\byesterday\b|\blast night\b", lowered):
            return day_start - timedelta(days=1), day_start, "Yesterday", True
        if re.search(r"\b(today|tonight|so far)\b", lowered):
            return day_start, day_end, "Today", True
        if re.search(r"\blast month\b", lowered):
            return month_bounds(month_start - timedelta(days=1)), month_start, "Last month", False
        if re.search(r"\b(this month|month to date|monthly|month)\b", lowered):
            return month_start, day_end, "This month", False
        if re.search(r"\blast week\b", lowered):
            return week_start - timedelta(days=7), week_start, "Last week", False
        if re.search(r"\b(this week|week to date|weekly|week)\b", lowered):
            return week_start, week_start + timedelta(days=7), "This week", False
        if weekly_default:
            return week_start, week_start + timedelta(days=7), "This week", False
        return day_start, day_end, "Today", True

    # ── Facts ──────────────────────────────────────────────────────────────
    @staticmethod
    def _as_utc(moment: datetime) -> datetime:
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    def _in_period(self, start: datetime, end: datetime) -> list[Booking]:
        return [booking for booking in self.bookings if start <= self._as_utc(booking.starts_at) < end]

    def _payment_for(self, booking_id: int, status: PaymentStatus | None = None) -> list[Payment]:
        return [payment for payment in self.payments
                if payment.booking_id == booking_id and (status is None or payment.status == status)]

    def _report(self, start: datetime, end: datetime) -> dict:
        rows = self._in_period(start, end)
        confirmed = [booking for booking in rows if booking.status == BookingStatus.CONFIRMED]
        cancelled = [booking for booking in rows if booking.status == BookingStatus.CANCELLED]
        walk_ins = [booking for booking in confirmed if booking.customer_id is None]
        expected = sum(self.services[booking.service_id].price_paise
                       for booking in confirmed if booking.service_id in self.services)
        collected = 0
        pending = 0
        for booking in confirmed:
            for payment in self._payment_for(booking.id):
                if payment.status == PaymentStatus.COMPLETED:
                    collected += payment.amount_paise
                elif payment.status == PaymentStatus.PENDING:
                    pending += 1
        uncovered = len([booking for booking in confirmed if not self._payment_for(booking.id)])
        return {"bookings": confirmed, "cancelled": cancelled, "walk_ins": walk_ins,
                "expected_paise": expected, "collected_paise": collected,
                "pending_payments": pending, "unpaid": uncovered}

    def _money_line(self, report: dict) -> str:
        parts = [f"Expected from booked services: {inr(report['expected_paise'])}",
                 f"Collected: {inr(report['collected_paise'])}"]
        if report["pending_payments"]:
            parts.append(f"{report['pending_payments']} payment"
                         f"{'' if report['pending_payments'] == 1 else 's'} pending")
        if report["unpaid"]:
            parts.append(f"{report['unpaid']} booking{'' if report['unpaid'] == 1 else 's'} with no payment yet")
        return " · ".join(parts)

    def _shop_prefix(self) -> str:
        # Plain text: the dashboard chat renders answers verbatim, so markdown
        # emphasis would show up as literal asterisks.
        return self.shop.name if self.shop else "your shop"

    def _sources(self, query: str, fallback: list[Document] | None = None, limit: int = 4) -> list[ChatSource]:
        results = self.index.search(query, limit=6)
        if results:
            return [ChatSource(**item) for item in citations(results, limit)]
        return [ChatSource(doc_id=document.doc_id, kind=document.kind, label=document.label)
                for document in (fallback or [])[:limit]]

    def _booking_docs(self, rows: list[Booking]) -> list[Document]:
        by_id = {document.doc_id: document for document in self.index.documents}
        return [by_id[f"booking:{row.id}"] for row in rows if f"booking:{row.id}" in by_id]

    # ── Handlers ───────────────────────────────────────────────────────────
    def _greeting(self, message: str) -> ChatReply:
        return ChatReply(
            answer=(f"Hi! Ask me about {self._shop_prefix()} and I'll answer from your live data — "
                    "today's bookings, revenue, popular services, cancellations or reviews."),
            intent="greeting",
            suggestions=["How many bookings today?", "Today's revenue", "Who is next?"])

    def _help(self, message: str) -> ChatReply:
        return ChatReply(
            answer=("Ask me things like:\n"
                    "• “How many bookings today?”\n"
                    "• “What's today's revenue?”\n"
                    "• “How much did I collect this week?”\n"
                    "• “Who is my next customer?”\n"
                    "• “Which service is most popular?”\n"
                    "• “How many walk-ins today?” · “Cancellations this month?”\n"
                    "• “How are my reviews?” · “Am I open on Sunday?”\n\n"
                    "Every number comes from your bookings and payments — all times UTC."),
            intent="help",
            suggestions=["How many bookings today?", "Today's revenue", "Top services"])

    def _today_bookings(self, message: str) -> ChatReply:
        start, end, label, single_day = self.parse_period(message)
        if not single_day:  # "bookings this week" is a report, not a schedule
            return self._period_report(message)
        report = self._report(start, end)
        rows = report["bookings"]
        if not rows and not report["cancelled"]:
            return ChatReply(
                answer=(f"No bookings yet for {window_text(start, end, label, single_day)} "
                        f"at {self._shop_prefix()}. "
                        f"Your shop is {'open' if self.shop.is_active else 'closed'} — "
                        "walk-ins can still be seated from the dashboard."),
                intent="today_bookings", sources=self._sources(message),
                suggestions=["Today's revenue", "Next appointment", "Am I open tomorrow?"])
        lines = [f"📅 {sentence(window_text(start, end, label, single_day))} at {self._shop_prefix()}: "
                 f"{len(rows)} confirmed booking{'' if len(rows) == 1 else 's'}"
                 + (f", {len(report['cancelled'])} cancelled" if report["cancelled"] else "")
                 + (f", {len(report['walk_ins'])} walk-in{'' if len(report['walk_ins']) == 1 else 's'}"
                    if report["walk_ins"] else "")]
        for booking in rows[:8]:
            service = self.services.get(booking.service_id)
            who = booking.walk_in_name or (f"customer #{booking.customer_id}" if booking.customer_id else "customer")
            lines.append(f"• {self._as_utc(booking.starts_at).strftime('%H:%M')} — {service.name if service else 'service'} "
                         f"({who}) · {inr(service.price_paise) if service else '—'} · {booking.code}")
            payment = self._payment_for(booking.id)
            if payment:
                status = payment[-1].status.value if hasattr(payment[-1].status, "value") else str(payment[-1].status)
                lines.append(f"   payment {status.lower()}")
        lines.append(f"\n{self._money_line(report)}")
        cards = [ChatCard(kind="booking", id=booking.id, title=f"{self._as_utc(booking.starts_at).strftime('%H:%M')} "
                                                               f"{(self.services.get(booking.service_id).name if self.services.get(booking.service_id) else 'service')}",
                          meta=f"{booking.code} · {booking.status.value}") for booking in rows[:MAX_CARDS]]
        return ChatReply(answer="\n".join(lines), intent="today_bookings", cards=cards,
                         sources=self._sources(message, self._booking_docs(rows)),
                         suggestions=["Today's revenue", "Next appointment", "Top services"])

    def _today_revenue(self, message: str) -> ChatReply:
        start, end, label, single_day = self.parse_period(message)
        report = self._report(start, end)
        when = window_text(start, end, label, single_day)
        if not report["bookings"]:
            return ChatReply(
                answer=(f"No completed bookings in {when}, "
                        f"so revenue at {self._shop_prefix()} is {inr(0)}."),
                intent="today_revenue", sources=self._sources(message),
                suggestions=["How many bookings today?", "This week's revenue"])
        answer = (f"💰 {sentence(when)} at {self._shop_prefix()}:\n"
                  f"• {len(report['bookings'])} confirmed booking"
                  f"{'' if len(report['bookings']) == 1 else 's'}\n"
                  f"• Expected: {inr(report['expected_paise'])}\n"
                  f"• Collected: {inr(report['collected_paise'])}\n"
                  + (f"• Pending payments: {report['pending_payments']}\n"
                     if report["pending_payments"] else "")
                  + f"• Bookings without payment: {report['unpaid']}")
        return ChatReply(answer=answer, intent="today_revenue",
                         sources=self._sources(message, self._booking_docs(report["bookings"])),
                         suggestions=["This week's revenue", "Top services", "Who is next?"])

    def _period_report(self, message: str) -> ChatReply:
        # Bare "revenue" / "sales" with no window means the current week.
        start, end, label, single_day = self.parse_period(message, weekly_default=True)
        report = self._report(start, end)
        if not report["bookings"] and not report["cancelled"]:
            return ChatReply(
                answer=(f"Nothing booked in {window_text(start, end, label, single_day)} "
                        f"at {self._shop_prefix()} yet."),
                intent="period_report", sources=self._sources(message),
                suggestions=["How many bookings today?", "Top services"])
        answer = (f"📊 {sentence(window_text(start, end, label, single_day))} at {self._shop_prefix()}:\n"
                  f"• {len(report['bookings'])} confirmed booking"
                  f"{'' if len(report['bookings']) == 1 else 's'}"
                  + (f" · {len(report['walk_ins'])} walk-in"
                     f"{'' if len(report['walk_ins']) == 1 else 's'}" if report["walk_ins"] else "")
                  + (f" · {len(report['cancelled'])} cancelled" if report["cancelled"] else "") + "\n"
                  f"• Expected: {inr(report['expected_paise'])}\n"
                  f"• Collected: {inr(report['collected_paise'])}\n"
                  + (f"• Pending payments: {report['pending_payments']}\n"
                     if report["pending_payments"] else "")
                  + f"• Bookings without payment: {report['unpaid']}")
        return ChatReply(answer=answer, intent="period_report",
                         sources=self._sources(message, self._booking_docs(report["bookings"])),
                         suggestions=["Today's revenue", "Top services", "Cancellations this month"])

    def _next_appointment(self, message: str) -> ChatReply:
        now = datetime.now(timezone.utc)
        upcoming = [booking for booking in self.bookings
                    if booking.status == BookingStatus.CONFIRMED and self._as_utc(booking.starts_at) >= now]
        if not upcoming:
            return ChatReply(
                answer=(f"No upcoming appointments at {self._shop_prefix()} in the next 30 days. "
                        "Customers can book whenever your hours and services are published."),
                intent="next_appointment", sources=self._sources(message),
                suggestions=["Show services", "Am I open?"])
        booking = upcoming[0]
        service = self.services.get(booking.service_id)
        starts_at = self._as_utc(booking.starts_at)
        who = booking.walk_in_name or (f"customer #{booking.customer_id}" if booking.customer_id else "customer")
        minutes = int((starts_at - now).total_seconds() // 60)
        when = (f"in {minutes} minutes" if 0 < minutes < 90 else
                (f"in {round(minutes / 60)} hours" if minutes < 60 * 36 else f"in {minutes // 1440} days"))
        answer = (f"⏭ Next up at {self._shop_prefix()}:\n"
                  f"• {fmt_when(starts_at)} ({when})\n"
                  f"• {service.name if service else 'service'} · {booking.code}\n"
                  f"• {who}" + (f" · {inr(service.price_paise)}" if service else ""))
        later = upcoming[1:4]
        if later:
            answer += "\n\nAfter that:\n" + "\n".join(
                f"• {fmt_when(self._as_utc(item.starts_at))} — "
                f"{self.services[item.service_id].name if item.service_id in self.services else 'service'} "
                f"({item.code})" for item in later)
        return ChatReply(answer=answer, intent="next_appointment",
                         sources=self._sources(message, self._booking_docs(upcoming[:4])),
                         cards=[ChatCard(kind="booking", id=item.id,
                                         title=fmt_when(self._as_utc(item.starts_at)),
                                         meta=f"{item.code} · "
                                              f"{self.services[item.service_id].name if item.service_id in self.services else 'service'}")
                                for item in upcoming[:MAX_CARDS]],
                         suggestions=["How many bookings today?", "Today's revenue"])

    def _top_services(self, message: str) -> ChatReply:
        window_start = datetime.now(timezone.utc) - timedelta(days=30)
        rows = [booking for booking in self.bookings
                if self._as_utc(booking.starts_at) >= window_start and booking.status == BookingStatus.CONFIRMED]
        if not rows:
            return ChatReply(answer=f"No bookings in the last 30 days at {self._shop_prefix()} yet.",
                             intent="top_services", suggestions=["Show services", "How many bookings today?"])
        tally: dict[int, dict] = {}
        for booking in rows:
            entry = tally.setdefault(booking.service_id, {"count": 0, "paise": 0, "cancelled": 0})
            service = self.services.get(booking.service_id)
            entry["count"] += 1
            entry["paise"] += service.price_paise if service else 0
        ranked = sorted(tally.items(), key=lambda item: (-item[1]["count"], -item[1]["paise"]))
        lines = ["🏆 Most booked services (last 30 days):"]
        for service_id, entry in ranked[:MAX_CARDS]:
            service = self.services.get(service_id)
            lines.append(f"• {service.name if service else f'service #{service_id}'} — {entry['count']} booking"
                         f"{'' if entry['count'] == 1 else 's'} · {inr(entry['paise'])}")
        total = sum(entry["count"] for entry in tally.values())
        lines.append(f"\n{total} bookings in total. Add or reprice the quiet services to fill the gaps.")
        return ChatReply(answer="\n".join(lines), intent="top_services",
                         sources=self._sources(message, self._booking_docs(rows)),
                         suggestions=["Today's revenue", "How are my reviews?", "Cancellations this month"])

    def _walk_ins(self, message: str) -> ChatReply:
        if "today" in intents.normalize(message):
            start, end = day_bounds(datetime.now(timezone.utc))
            rows = [booking for booking in self._in_period(start, end) if booking.customer_id is None]
            scope = "today"
        else:
            start = datetime.now(timezone.utc) - timedelta(days=30)
            rows = [booking for booking in self.bookings
                    if booking.customer_id is None and self._as_utc(booking.starts_at) >= start]
            scope = "in the last 30 days"
        if not rows:
            return ChatReply(answer=f"No walk-ins {scope} at {self._shop_prefix()}.",
                             intent="walk_ins", suggestions=["How many bookings today?"])
        confirmed = [booking for booking in rows if booking.status == BookingStatus.CONFIRMED]
        takings = sum(self.services[booking.service_id].price_paise
                      for booking in confirmed if booking.service_id in self.services)
        return ChatReply(
            answer=(f"🚶 {len(confirmed)} walk-in{'' if len(confirmed) == 1 else 's'} {scope} at "
                    f"{self._shop_prefix()}"
                    + (f", worth {inr(takings)} in services" if takings else "") + "."),
            intent="walk_ins", sources=self._sources(message, self._booking_docs(rows)),
            suggestions=["Today's revenue", "Who is next?"])

    def _cancellations(self, message: str) -> ChatReply:
        start = datetime.now(timezone.utc) - timedelta(days=30)
        rows = [booking for booking in self.bookings if self._as_utc(booking.starts_at) >= start]
        cancelled = [booking for booking in rows if booking.status == BookingStatus.CANCELLED]
        total = len(rows)
        if not total:
            return ChatReply(answer=f"No bookings recorded in the last 30 days at {self._shop_prefix()}.",
                             intent="cancellations", suggestions=["How many bookings today?"])
        rate = round(len(cancelled) / total * 100, 1)
        lost = sum(self.services[booking.service_id].price_paise
                   for booking in cancelled if booking.service_id in self.services)
        answer = (f"❌ {len(cancelled)} cancellation{'' if len(cancelled) == 1 else 's'} out of {total} bookings "
                  f"in the last 30 days ({rate}% cancel rate)")
        answer += f", worth {inr(lost)} in lost services." if lost else "."
        if len(cancelled) > 3:
            answer += "\nA reminder message a day before an appointment usually cuts this."
        return ChatReply(answer=answer, intent="cancellations",
                         sources=self._sources(message, self._booking_docs(cancelled or rows)),
                         suggestions=["How many bookings today?", "Top services"])

    def _reviews(self, message: str) -> ChatReply:
        reviews = self.db.scalars(select(Review).where(Review.shop_id == self.shop.id)
                                  .order_by(Review.created_at.desc())).all()
        if not reviews:
            return ChatReply(answer=f"No reviews yet at {self._shop_prefix()}. Ask happy customers to rate "
                                    "their visit from their bookings page.",
                             intent="reviews", suggestions=["Today's revenue", "Top services"])
        average = sum(review.rating for review in reviews) / len(reviews)
        buckets = {stars: sum(1 for review in reviews if review.rating == stars) for stars in range(5, 0, -1)}
        lines = [f"⭐ {self._shop_prefix()} is rated {average:.1f}/5 from {len(reviews)} review"
                 f"{'' if len(reviews) == 1 else 's'}."]
        lines += [f"• {stars}★ × {count}" for stars, count in buckets.items() if count]
        recent = [review for review in reviews if review.comment][:3]
        if recent:
            lines.append("\nLatest comments:")
            lines += [f"• {review.rating}★ — “{review.comment.strip()[:120]}”" for review in recent]
        return ChatReply(answer="\n".join(lines), intent="reviews",
                         sources=[ChatSource(doc_id=f"review:{review.id}", kind="review",
                                             label=f"Review ({review.rating}/5)") for review in reviews[:4]],
                         suggestions=["Top services", "How many bookings today?"])

    def _hours(self, message: str) -> ChatReply:
        rows = self.db.scalars(select(BusinessHours).where(BusinessHours.shop_id == self.shop.id)
                               .order_by(BusinessHours.weekday)).all()
        state = "open" if self.shop.is_active else "closed for new bookings"
        if not rows:
            return ChatReply(
                answer=(f"{self._shop_prefix()} is {state}, but no business hours are set yet — "
                        "customers see no free slots until you publish them in Shop settings."),
                intent="hours", suggestions=["How many bookings today?", "Today's revenue"])
        lines = [f"🕒 {self._shop_prefix()} is {state}. Hours (UTC):"]
        for row in rows:
            label = DAY_NAMES[row.weekday % 7][:3]
            lines.append(f"• {label} — " + ("closed" if row.is_closed
                                            else f"{row.opens_at.strftime('%H:%M')}–{row.closes_at.strftime('%H:%M')}"))
        today = datetime.now(timezone.utc).weekday()
        row = next((item for item in rows if item.weekday == today), None)
        lines.append("\nToday: " + ("closed" if not row or row.is_closed
                                    else f"{row.opens_at.strftime('%H:%M')}–{row.closes_at.strftime('%H:%M')} UTC"))
        return ChatReply(answer="\n".join(lines), intent="hours",
                         sources=self._sources(message), suggestions=["How many bookings today?", "Show services"])

    def _customers(self, message: str) -> ChatReply:
        start = datetime.now(timezone.utc) - timedelta(days=30)
        rows = [booking for booking in self.bookings
                if self._as_utc(booking.starts_at) >= start and booking.status == BookingStatus.CONFIRMED]
        account_ids = [booking.customer_id for booking in rows if booking.customer_id]
        walk_ins = len([booking for booking in rows if booking.customer_id is None])
        unique = set(account_ids)
        repeats = len([customer for customer in unique if account_ids.count(customer) > 1])
        if not rows:
            return ChatReply(answer=f"No customers booked in the last 30 days at {self._shop_prefix()}.",
                             intent="customers", suggestions=["Show services"])
        answer = (f"👥 Last 30 days at {self._shop_prefix()}:\n"
                  f"• {len(unique)} customer account{'' if len(unique) == 1 else 's'} booked online\n"
                  f"• {repeats} of them booked more than once\n"
                  f"• {walk_ins} walk-in{'' if walk_ins == 1 else 's'}")
        return ChatReply(answer=answer, intent="customers",
                         sources=self._sources(message, self._booking_docs(rows)),
                         suggestions=["Top services", "Cancellations this month"])

    def _fallback(self, message: str) -> ChatReply:
        results = self.index.search(message, limit=4)
        if not results:
            return ChatReply(
                answer=("I couldn't match that to your data. Try “how many bookings today”, "
                        "“today's revenue”, “who is next”, “top services”, “cancellations” or “reviews”."),
                intent="unknown", suggestions=["How many bookings today?", "Today's revenue", "Top services"])
        lines = ["Here's what I found in your records:"]
        cards: list[ChatCard] = []
        for _score, document in results:
            if document.kind == "booking":
                lines.append(f"• {document.text[:150]}")
                cards.append(ChatCard(kind="booking", id=int(document.doc_id.split(":")[1]),
                                      title=document.label, meta=document.data.get("status", "")))
            elif document.kind == "review":
                lines.append(f"• {document.text[:150]}")
            elif document.kind == "payment":
                lines.append(f"• {document.text[:150]}")
            elif document.kind == "shop":
                lines.append(f"• {document.text[:150]}")
        return ChatReply(answer="\n".join(lines), intent="unknown", cards=cards[:MAX_CARDS],
                         sources=self._sources(message),
                         suggestions=["How many bookings today?", "Today's revenue", "Top services"])


def resolve_owner_shop(db: Session, user: User, shop_id: int | None) -> Shop | None:
    """The shop an owner question is about: the requested one, else their first."""
    shops = db.scalars(select(Shop).where(Shop.owner_id == user.id).order_by(Shop.created_at)).all()
    if not shops:
        return None
    if shop_id is None:
        return shops[0]
    return next((shop for shop in shops if shop.id == shop_id), None)
