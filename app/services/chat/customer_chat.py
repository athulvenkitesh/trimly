"""Customer-facing assistant: find a shop, compare prices, pick a slot, book it.

Retrieval happens first (RAG) and the answer is composed afterwards, so every
shop, price and slot it mentions was read out of the database during this
request. Booking goes through the same BookingService as the web dialog, so the
partial unique index still makes double-booking impossible.
"""

from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, BusinessHours, Review, Service, Shop, User
from app.schemas.chat import ChatBooking, ChatCard, ChatReply, ChatSource
from app.services.availability_service import AvailabilityService
from app.services.booking_service import BookingService
from app.services.chat import intents
from app.services.chat.rag import Document, RagIndex, customer_documents, inr

MAX_CARDS = 5
LOOKAHEAD_DAYS = 7
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def slot_label(moment: datetime) -> str:
    return moment.strftime("%a %d %b, %H:%M") + " UTC"


def hours_label(hours: BusinessHours) -> str:
    return "closed" if hours.is_closed else f"{hours.opens_at.strftime('%H:%M')}–{hours.closes_at.strftime('%H:%M')}"


class CustomerChat:
    def __init__(self, db: Session):
        self.db = db
        self.availability = AvailabilityService(db)
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.index = RagIndex([])

    # ── Entry point ────────────────────────────────────────────────────────
    def reply(self, *, message: str, user: User | None = None,
              latitude: float | None = None, longitude: float | None = None,
              shop_id: int | None = None, service_id: int | None = None) -> ChatReply:
        self.latitude, self.longitude = latitude, longitude
        self.index = RagIndex(customer_documents(self.db, latitude, longitude))
        context = {
            "shop": self.db.get(Shop, shop_id) if shop_id else None,
            "service": self.db.get(Service, service_id) if service_id else None,
        }
        if context["service"] and not context["shop"]:
            context["shop"] = self.db.get(Shop, context["service"].shop_id)

        intent, score = intents.detect_intent(message)
        # "cheapest haircut near me" is a price question that mentions distance as
        # an aside: answer what was asked (the price ranking) rather than a list.
        if intent != "compare_prices" and intents.has_phrase(message, intents.PRICE_PHRASES):
            intent, score = "compare_prices", 2.0
        handlers = {
            "greeting": self._greeting, "help": self._help,
            "nearby": self._nearby, "find_shops": self._find_shops,
            "compare_prices": self._compare,
            "services": self._services, "hours": self._hours, "reviews": self._reviews,
            "availability": self._availability, "book": self._book,
            "my_bookings": self._my_bookings, "cancel": self._cancel,
        }
        handler = handlers.get(intent) if score >= 1.0 else None
        return (handler or self._fallback)(message, user, context)

    # ── Small talk ─────────────────────────────────────────────────────────
    def _greeting(self, message: str, user: User | None, context: dict) -> ChatReply:
        name = (user.email.split("@")[0] if user and user.email else "there")
        return ChatReply(
            answer=(f"Hey {name}! I can find barbershops near you, compare prices, check opening "
                    "hours and reviews, and book a slot for you.\n\n"
                    "Try: “haircut near me under ₹300”, “when is <shop> open?” or "
                    "“book a haircut tomorrow at 5pm”."),
            intent="greeting",
            suggestions=["Haircut near me", "Show shops", "Book a haircut tomorrow 5pm"],
        )

    def _help(self, message: str, user: User | None, context: dict) -> ChatReply:
        return ChatReply(
            answer=("Here's what I can do:\n"
                    "• Find shops near you or matching a service\n"
                    "• List services with prices and durations\n"
                    "• Check opening hours and customer reviews\n"
                    "• Show free slots and book one for you\n"
                    "• Show or cancel your bookings\n\n"
                    "Ask in plain English — “book a fade at Marutharoad on Saturday at 11am”."),
            intent="help",
            suggestions=["Haircut near me", "My bookings", "Show prices"],
        )

    # ── Shop discovery ─────────────────────────────────────────────────────
    def _active_shops(self) -> list[Shop]:
        return [shop for shop in self.db.scalars(select(Shop).where(Shop.is_active)).all()]

    def _distance(self, shop: Shop) -> float | None:
        from app.services.whatsapp_flow import haversine_km

        if self.latitude is None or self.longitude is None or shop.latitude is None or shop.longitude is None:
            return None
        return round(haversine_km(self.latitude, self.longitude, shop.latitude, shop.longitude), 2)

    def _ranked_shops(self) -> list[Shop]:
        """Shops with a published menu first, then by distance, then by name."""
        shops = self._active_shops()
        with_menu = {service.shop_id for service in
                     self.db.scalars(select(Service).where(Service.is_active.is_(True))).all()}
        placed = [(shop.id not in with_menu, self._distance(shop) is None,
                   self._distance(shop) or 0.0, int(shop.id), shop) for shop in shops]
        placed.sort(key=lambda item: item[:4])
        return [shop for *_, shop in placed]

    def _shop_services(self, shop: Shop) -> list[Service]:
        return self.db.scalars(
            select(Service).where(Service.shop_id == shop.id, Service.is_active.is_(True))
            .order_by(Service.price_paise, Service.duration_minutes)).all()

    def _rating(self, shop: Shop) -> tuple[float | None, int]:
        reviews = self.db.scalars(select(Review).where(Review.shop_id == shop.id)).all()
        if not reviews:
            return None, 0
        return round(sum(review.rating for review in reviews) / len(reviews), 1), len(reviews)

    def _shop_facts(self, shop: Shop) -> str:
        bits = []
        distance = self._distance(shop)
        if distance is not None:
            bits.append(f"{distance} km away")
        rating, count = self._rating(shop)
        if count:
            bits.append(f"★{rating} ({count})")
        if shop.address:
            bits.append(shop.address)
        return " · ".join(bits)

    def _shops_from_results(self, results: list[tuple[float, Document]], budget_paise: int | None) -> list[Shop]:
        shops: list[Shop] = []
        seen: set[int] = set()
        for _score, document in results:
            if document.shop_id is None or document.shop_id in seen:
                continue
            shop = self.db.get(Shop, document.shop_id)
            if not shop or not shop.is_active:
                continue
            if budget_paise is not None:
                affordable = [service for service in self._shop_services(shop)
                              if service.price_paise <= budget_paise]
                if not affordable:
                    continue  # the query was price-bounded: don't offer a shop that can't meet it
            seen.add(shop.id)
            shops.append(shop)
        return shops

    def _nearby(self, message: str, user: User | None, context: dict) -> ChatReply:
        if self.latitude is None or self.longitude is None:
            return ChatReply(
                answer=("I need your location to rank shops by distance. Tap “Use my location”, "
                        "or search by name or service instead."),
                intent="nearby",
                suggestions=["Use my location", "Show all shops", "Haircut near me"],
            )
        shops = [shop for shop in self._ranked_shops()
                 if self._distance(shop) is not None and self._distance(shop) <= 25]
        if not shops:
            return ChatReply(
                answer=("No shops with a pinned location within 25 km. You can still search by "
                        "shop or service name."), intent="nearby",
                suggestions=["Show all shops", "Haircut"], sources=[])
        shown = shops[:MAX_CARDS]
        return self._shop_list_reply(shown, retrieval=message, heading=f"📍 {len(shown)} shop"
                                     f"{'' if len(shown) == 1 else 's'} near you:", intent="nearby")

    def _find_shops(self, message: str, user: User | None, context: dict) -> ChatReply:
        budget = intents.parse_budget_paise(message)
        results = self.index.search(message, limit=12)
        shops = self._shops_from_results(results, budget)
        # With coordinates, distance beats lexical relevance: "haircut near me" should
        # list the closest shop that does haircuts, not the best keyword match.
        if shops and any(self._distance(shop) is not None for shop in shops):
            shops.sort(key=lambda shop: (self._distance(shop) is None, self._distance(shop) or 0.0))
        if not shops:
            shops = self._ranked_shops()
            heading = "Nothing matched that exactly — here are the shops I can see:"
        else:
            heading = f"🔍 {len(shops[:MAX_CARDS])} shop{'' if len(shops[:MAX_CARDS]) == 1 else 's'} matching your ask:"
        return self._shop_list_reply(shops, retrieval=message, heading=heading,
                                     intent="find_shops", budget=budget)

    def _shop_list_reply(self, shops: list[Shop], *, retrieval: str, heading: str, intent: str,
                         budget: int | None = None) -> ChatReply:
        shops = shops[:MAX_CARDS]
        lines = [heading]
        cards: list[ChatCard] = []
        cheapest_total = None
        for shop in shops:
            services = self._shop_services(shop)
            if budget is not None:
                services = [service for service in services if service.price_paise <= budget]
            cheapest = services[0] if services else None
            price_note = f"from {inr(cheapest.price_paise)}" if cheapest else "no services yet"
            facts = self._shop_facts(shop)
            lines.append(f"• {shop.name} — {price_note}{f' · {facts}' if facts else ''}")
            cards.append(ChatCard(kind="shop", id=shop.id, title=shop.name,
                                  meta=f"{price_note}{f' · {facts}' if facts else ''}", shop_id=shop.id))
            if cheapest and (cheapest_total is None or cheapest.price_paise < cheapest_total):
                cheapest_total = cheapest.price_paise
        if cheapest_total is not None:
            lines.append(f"\nCheapest service shown: {inr(cheapest_total)}. "
                         "Tap a shop to see its menu, or ask me to book.")
        # Cite the shops being listed: that is exactly what the answer was read from.
        sources = [ChatSource(doc_id=f"shop:{shop.id}", kind="shop", label=shop.name) for shop in shops]
        return ChatReply(answer="\n".join(lines), intent=intent, cards=cards, sources=sources,
                         suggestions=["Show services", "Book a slot", "Use my location"])

    def _compare(self, message: str, user: User | None, context: dict) -> ChatReply:
        """Rank real menu prices: "cheapest haircut", "compare prices".

        Every row here is read from the services table, so the ranking can never
        drift from what the shop actually charges.
        """
        budget = intents.parse_budget_paise(message)
        named_shop = self._resolve_shop(message, context)
        pools = [named_shop] if named_shop else self._ranked_shops()
        asked = intents.content_tokens(message)

        pairs = [(service, shop) for shop in pools for service in self._shop_services(shop)
                 if budget is None or service.price_paise <= budget]
        matching = [(service, shop) for service, shop in pairs
                    if intents.content_tokens(service.name) & asked]
        # A service word ("haircut") narrows the list; with no match, compare everything.
        chosen = matching or pairs
        if not chosen:
            cap = f" under {inr(budget)}" if budget else ""
            return ChatReply(
                answer=f"No service matches that{cap} right now. Ask for “shops near me” to browse.",
                intent="compare_prices", suggestions=["Show all shops", "Haircut near me"])

        chosen.sort(key=lambda pair: (pair[0].price_paise, pair[0].duration_minutes, pair[1].name))
        shown = chosen[:MAX_CARDS]
        # Name the comparison after what was asked ("haircut"); a bare "compare
        # prices" is a whole-menu question, so don't title it after one service.
        matched_tokens = intents.content_tokens(shown[0][0].name) & asked
        topic = " ".join(sorted(matched_tokens)) if matched_tokens else (
            "services" if not asked else shown[0][0].name.lower())
        shop_count = len({shop.id for _service, shop in shown})
        lines = [f"💰 Cheapest {topic}{f' under {inr(budget)}' if budget else ''} "
                 f"across {shop_count} shop{'' if shop_count == 1 else 's'}:"]
        for service, shop in shown:
            facts = self._shop_facts(shop)
            lines.append(f"• {service.name} — {inr(service.price_paise)} · {service.duration_minutes} min "
                         f"· {shop.name}{f' · {facts}' if facts else ''}")
        cheapest_service, cheapest_shop = shown[0]
        if len(shown) > 1:
            saving = shown[-1][0].price_paise - cheapest_service.price_paise
            lines.append(f"\n{cheapest_shop.name} is the cheapest at "
                         f"{inr(cheapest_service.price_paise)} — {inr(saving)} less than the "
                         "priciest option listed.")
        lines.append("Service prices only — each shop adds its own convenience fee at checkout.")
        return ChatReply(
            answer="\n".join(lines), intent="compare_prices",
            cards=[ChatCard(kind="service", id=service.id,
                            title=f"{service.name} — {inr(service.price_paise)}",
                            meta=f"{shop.name} · {service.duration_minutes} min", shop_id=shop.id)
                   for service, shop in shown],
            shop_id=cheapest_shop.id, service_id=cheapest_service.id,
            sources=[ChatSource(doc_id=f"service:{service.id}", kind="service",
                                label=f"{service.name} at {shop.name}")
                     for service, shop in shown[:4]],
            suggestions=[f"Book {cheapest_service.name} at {cheapest_shop.name} tomorrow",
                         "Shops near me", "When is it open?"])

    def _sources_for(self, query: str) -> list[dict]:
        from app.services.chat.rag import citations

        return citations(self.index.search(query, limit=6))

    # ── Shop-scoped questions ──────────────────────────────────────────────
    def _resolve_shop(self, message: str, context: dict) -> Shop | None:
        """Pick the shop a question is about: named in the message, else context, else nearest."""
        lowered = intents.normalize(message)
        best_shop, best_score = None, 0
        for shop in self._active_shops():
            name_tokens = [token for token in intents.normalize(shop.name).split() if len(token) > 2]
            score = sum(1 for token in name_tokens if token in lowered)
            if score > best_score:
                best_shop, best_score = shop, score
        if best_shop:
            return best_shop
        if context.get("shop"):
            return context["shop"]
        ranked = self._ranked_shops()
        return ranked[0] if len(ranked) == 1 else None

    def _resolve_service(self, message: str, shop: Shop | None, context: dict) -> Service | None:
        services = self._shop_services(shop) if shop else self.db.scalars(
            select(Service).where(Service.is_active.is_(True))).all()
        lowered = intents.normalize(message)
        best_service, best_score = None, 0
        for service in services:
            tokens = [token for token in intents.normalize(service.name).split() if len(token) > 2]
            score = sum(1 for token in tokens if token in lowered)
            # "haircut" should also match a menu entry called "Hair cut premium".
            if intents.normalize(service.name) in lowered:
                score += 2
            if score > best_score:
                best_service, best_score = service, score
        if best_service:
            return best_service
        if context.get("service") and (not shop or context["service"].shop_id == shop.id):
            return context["service"]
        return None

    def _services(self, message: str, user: User | None, context: dict) -> ChatReply:
        shops = self._active_shops()
        if not shops:
            return ChatReply(answer="No shops are listed yet. Check back soon.", intent="services")
        service = self._resolve_service(message, self._resolve_shop(message, context), context)
        named_shop = self._resolve_shop(message, context)
        targets = [named_shop] if named_shop else ([self.db.get(Shop, service.shop_id)] if service else shops[:3])
        lines, cards = [], []
        for shop in [target for target in targets if target]:
            services = self._shop_services(shop)
            if service and service.shop_id == shop.id:
                services = [item for item in services if item.id == service.id] or services
            lines.append(f"💈 {shop.name}" + (f" · {self._shop_facts(shop)}" if self._shop_facts(shop) else ""))
            if not services:
                lines.append("   No services published yet.")
                continue
            for item in services:
                lines.append(f"   • {item.name} — {inr(item.price_paise)} · {item.duration_minutes} min")
                cards.append(ChatCard(kind="service", id=item.id, title=f"{item.name} — {inr(item.price_paise)}",
                                      meta=f"{shop.name} · {item.duration_minutes} min", shop_id=shop.id))
            lines.append(f"   Convenience fee {inr(shop.convenience_fee_paise)}")
        lines.append("\nSay “book <service> at <shop> tomorrow 5pm” and I'll hold the slot.")
        sources = [ChatSource(**item) for item in self._sources_for(message)]
        shop_id = targets[0].id if len(targets) == 1 and targets[0] else None
        return ChatReply(answer="\n".join(lines), intent="services", cards=cards[:MAX_CARDS],
                         sources=sources, shop_id=shop_id,
                         service_id=service.id if service else None,
                         suggestions=["Book a slot", "When is it open?", "Show reviews"])

    def _hours(self, message: str, user: User | None, context: dict) -> ChatReply:
        shop = self._resolve_shop(message, context)
        shops = [shop] if shop else self._active_shops()[:3]
        if not shops:
            return ChatReply(answer="No shops are listed yet.", intent="hours")
        lines, cards = ["🕒 Opening hours (UTC):"], []
        for target in shops:
            rows = self.db.scalars(select(BusinessHours).where(BusinessHours.shop_id == target.id)
                                   .order_by(BusinessHours.weekday)).all()
            lines.append(f"💈 {target.name}")
            if not rows:
                lines.append("   Hours not published yet — ask the shop directly.")
                continue
            for row in rows:
                lines.append(f"   {DAY_NAMES[row.weekday % 7][:3]} {hours_label(row)}")
            cards.append(ChatCard(kind="shop", id=target.id, title=target.name, meta="opening hours",
                                  shop_id=target.id))
        sources = [ChatSource(**item) for item in self._sources_for(message)]
        return ChatReply(answer="\n".join(lines), intent="hours", cards=cards, sources=sources,
                         shop_id=shops[0].id if len(shops) == 1 else None,
                         suggestions=["Book a slot", "Show prices", "Show reviews"])

    def _reviews(self, message: str, user: User | None, context: dict) -> ChatReply:
        shop = self._resolve_shop(message, context)
        if not shop:
            ranked = self._ranked_shops()
            lines, cards = ["⭐ Shops by rating:"], []
            scored = []
            for candidate in ranked:
                rating, count = self._rating(candidate)
                scored.append((rating or 0, count, candidate))
            scored.sort(key=lambda item: (-item[0], -item[1]))
            for rating, count, candidate in scored[:MAX_CARDS]:
                lines.append(f"• {candidate.name} — " + (f"★{rating} from {count} review"
                                                          f"{'' if count == 1 else 's'}" if count else "no ratings yet"))
                cards.append(ChatCard(kind="shop", id=candidate.id, title=candidate.name,
                                      meta=f"★{rating} ({count})" if count else "no ratings yet",
                                      shop_id=candidate.id))
            return ChatReply(answer="\n".join(lines), intent="reviews", cards=cards,
                             sources=[ChatSource(**item) for item in self._sources_for(message)],
                             suggestions=["Show prices", "Book a slot"])
        reviews = self.db.scalars(select(Review).where(Review.shop_id == shop.id)
                                  .order_by(Review.created_at.desc()).limit(4)).all()
        rating, count = self._rating(shop)
        if not reviews:
            answer = f"{shop.name} has no reviews yet — you can be the first after your visit."
        else:
            lines = [f"⭐ {shop.name} is rated {rating}/5 from {count} review{'' if count == 1 else 's'}:"]
            for review in reviews:
                stars = "★" * review.rating + "☆" * (5 - review.rating)
                lines.append(f"• {stars}" + (f" — “{review.comment.strip()[:140]}”" if review.comment else ""))
            answer = "\n".join(lines)
        return ChatReply(answer=answer, intent="reviews", shop_id=shop.id,
                         sources=[ChatSource(**item) for item in self._sources_for(f"{shop.name} review")],
                         suggestions=["Book a slot", "Show prices", "When is it open?"])

    # ── Availability ───────────────────────────────────────────────────────
    def _availability(self, message: str, user: User | None, context: dict) -> ChatReply:
        shop = self._resolve_shop(message, context)
        service = self._resolve_service(message, shop, context)
        if not shop:
            return self._shop_list_reply(self._ranked_shops()[:MAX_CARDS], retrieval=message,
                                         heading="Which shop? Here's what's listed:", intent="availability")
        if not service:
            return self._service_prompt(shop, intent="availability")
        day = intents.parse_day(message) or datetime.now(timezone.utc).date()
        slots = self.availability.get_available_slots(shop.id, service.id, day)
        if not slots:
            fallback = self._next_days(shop, service, day)
            if not fallback:
                return ChatReply(
                    answer=(f"{shop.name} has no free {service.name} slots in the next {LOOKAHEAD_DAYS} days. "
                            "Their hours may not be set — try another shop."),
                    intent="availability", shop_id=shop.id, service_id=service.id,
                    suggestions=["Show all shops", "Book another service"])
            next_day, next_slots = fallback
            first = next_slots[0]
            return ChatReply(
                answer=(f"No free {service.name} slots left on {day.strftime('%a %d %b')} at {shop.name}. "
                        f"The next opening is {slot_label(first)}."),
                intent="availability", shop_id=shop.id, service_id=service.id,
                cards=[ChatCard(kind="slot", id=index, title=slot_label(moment),
                                meta=f"{service.name} · {inr(service.price_paise)}", shop_id=shop.id)
                       for index, moment in enumerate(next_slots[:MAX_CARDS], 1)],
                suggestions=[f"Book {first.strftime('%Y-%m-%d %H:%M')}", "Show all shops"])
        shown = slots[:MAX_CARDS]
        lines = [f"🗓 Free {service.name} slots at {shop.name} on {day.strftime('%a %d %b')}:",
                 "\n".join(f"• {slot_label(moment)}" for moment in shown),
                 f"\n{inr(service.price_paise)} · {service.duration_minutes} min · "
                 f"{inr(shop.convenience_fee_paise)} convenience fee"]
        return ChatReply(
            answer="\n".join(lines), intent="availability", shop_id=shop.id, service_id=service.id,
            cards=[ChatCard(kind="slot", id=index, title=slot_label(moment),
                            meta=f"{service.name} · {inr(service.price_paise)}", shop_id=shop.id)
                   for index, moment in enumerate(shown, 1)],
            sources=[ChatSource(**item) for item in self._sources_for(f"{shop.name} {service.name}")],
            suggestions=[f"Book {shown[0].strftime('%Y-%m-%d %H:%M')}", "Tomorrow morning", "Show prices"])

    def _next_days(self, shop: Shop, service: Service, day) -> tuple:
        for offset in range(1, LOOKAHEAD_DAYS):
            candidate_day = day + timedelta(days=offset)
            slots = self.availability.get_available_slots(shop.id, service.id, candidate_day)
            if slots:
                return candidate_day, slots
        return None

    def _service_prompt(self, shop: Shop, intent: str) -> ChatReply:
        services = self._shop_services(shop)
        if not services:
            return ChatReply(answer=f"{shop.name} hasn't published any services yet.", intent=intent,
                             shop_id=shop.id, suggestions=["Show all shops"])
        lines = [f"Which service at {shop.name}?"]
        cards = []
        for service in services:
            lines.append(f"• {service.name} — {inr(service.price_paise)} · {service.duration_minutes} min")
            cards.append(ChatCard(kind="service", id=service.id, title=service.name,
                                  meta=f"{inr(service.price_paise)} · {service.duration_minutes} min",
                                  shop_id=shop.id))
        return ChatReply(answer="\n".join(lines), intent=intent, shop_id=shop.id, cards=cards[:MAX_CARDS],
                         suggestions=[f"Book {services[0].name} tomorrow"])

    # ── Booking ────────────────────────────────────────────────────────────
    def _book(self, message: str, user: User | None, context: dict) -> ChatReply:
        if user is None:
            return ChatReply(
                answer="To book I need an account first — sign in and ask me again.",
                intent="book", suggestions=["Sign in", "Haircut near me"])
        shop = self._resolve_shop(message, context)
        if shop is None:
            # Naming a service does not choose a shop: if several shops offer it, ask.
            candidate = self._resolve_service(message, None, {"shop": None, "service": None})
            if candidate:
                offering = [candidate_shop for candidate_shop in self._active_shops()
                            if any(item.name == candidate.name for item in self._shop_services(candidate_shop))]
                if len(offering) == 1:
                    shop = offering[0]
        if not shop:
            return self._shop_list_reply(self._ranked_shops()[:MAX_CARDS], retrieval=message,
                                         heading="Which shop should I book? Reply with a shop name:",
                                         intent="book")
        service = self._resolve_service(message, shop, context)
        if not service:
            return self._service_prompt(shop, intent="book")
        if not shop.is_active:
            return ChatReply(answer=f"{shop.name} is closed for bookings right now.", intent="book",
                             shop_id=shop.id, suggestions=["Show all shops"])

        day = intents.parse_day(message) or datetime.now(timezone.utc).date()
        wanted = intents.parse_time(message)
        if wanted is not None and day == datetime.now(timezone.utc).date():
            now = datetime.now(timezone.utc).time()
            if wanted < now:  # "at 9" after 9am today means tomorrow
                day = day + timedelta(days=1)

        slots = self.availability.get_available_slots(shop.id, service.id, day)
        note = ""
        if not slots and wanted is not None and day == datetime.now(timezone.utc).date():
            day = day + timedelta(days=1)
            slots = self.availability.get_available_slots(shop.id, service.id, day)
            note = "Today is fully booked, so I moved to the next day.\n"
        if not slots:
            fallback = self._next_days(shop, service, day)
            if not fallback:
                return ChatReply(
                    answer=(f"No free {service.name} slots at {shop.name} in the next {LOOKAHEAD_DAYS} days."),
                    intent="book", shop_id=shop.id, service_id=service.id,
                    suggestions=["Show all shops", "Try another service"])
            next_day, next_slots = fallback
            return ChatReply(
                answer=(f"{day.strftime('%a %d %b')} is fully booked for {service.name} at {shop.name}. "
                        f"The first opening is {slot_label(next_slots[0])} — want it?"),
                intent="book", shop_id=shop.id, service_id=service.id,
                cards=[ChatCard(kind="slot", id=index, title=slot_label(moment),
                                meta=f"{service.name} · {inr(service.price_paise)}", shop_id=shop.id)
                       for index, moment in enumerate(next_slots[:MAX_CARDS], 1)],
                suggestions=[f"Book {next_slots[0].strftime('%Y-%m-%d %H:%M')}"])

        chosen = self._pick_slot(slots, day, wanted)
        try:
            booking = BookingService(self.db).create_booking(
                customer_id=user.id, shop_id=shop.id, service_id=service.id, starts_at=chosen)
        except HTTPException:
            self.db.rollback()
            return ChatReply(
                answer=(f"That slot at {shop.name} was taken while we talked. Free times on "
                        f"{day.strftime('%a %d %b')}: " + ", ".join(slot_label(moment)[:12] for moment in slots[:3])),
                intent="book", shop_id=shop.id, service_id=service.id,
                suggestions=[f"Book {slots[0].strftime('%Y-%m-%d %H:%M')}"])
        fee = shop.convenience_fee_paise
        total = service.price_paise + fee
        if wanted is not None and chosen.time() != wanted:
            note += (f"{wanted.strftime('%H:%M')} wasn't free, so I took the closest opening "
                     f"({slot_label(chosen)}).\n")
        return ChatReply(
            answer=(note + f"✅ Booked! {shop.name} · {service.name}\n"
                    f"{slot_label(chosen)} — code {booking.code}\n"
                    f"{inr(service.price_paise)} + {inr(fee)} convenience fee = {inr(total)}.\n"
                    "Your slot is reserved; pay in the app to settle it."),
            intent="book", shop_id=shop.id, service_id=service.id,
            booking=ChatBooking(id=booking.id, code=booking.code, shop_id=shop.id, shop_name=shop.name,
                                service_id=service.id, service_name=service.name,
                                starts_at=chosen.isoformat(), price_paise=service.price_paise,
                                convenience_fee_paise=fee, total_paise=total),
            sources=[ChatSource(**item) for item in self._sources_for(f"{shop.name} {service.name}")],
            suggestions=["Pay with UPI", "Show my bookings", "Book another slot"])

    @staticmethod
    def _pick_slot(slots: list[datetime], day, wanted: time | None) -> datetime:
        if wanted is None:
            return slots[0]
        target = datetime.combine(day, wanted, tzinfo=timezone.utc)
        later = [moment for moment in slots if moment >= target]
        if later:
            return min(later, key=lambda moment: moment - target)
        earlier = [moment for moment in slots if moment < target]
        return max(earlier, key=lambda moment: moment) if earlier else slots[0]

    # ── My bookings / cancel ───────────────────────────────────────────────
    def _my_bookings(self, message: str, user: User | None, context: dict) -> ChatReply:
        if user is None:
            return ChatReply(answer="Sign in and I'll list your bookings.", intent="my_bookings",
                             suggestions=["Sign in"])
        bookings = self.db.scalars(
            select(Booking).where(Booking.customer_id == user.id)
            .order_by(Booking.starts_at.desc()).limit(6)).all()
        if not bookings:
            return ChatReply(answer="You have no bookings yet. Want me to find a slot?",
                             intent="my_bookings", suggestions=["Haircut near me", "Book a haircut"])
        lines = ["🧾 Your recent bookings:"]
        for booking in bookings:
            shop = self.db.get(Shop, booking.shop_id)
            service = self.db.get(Service, booking.service_id)
            starts_at = booking.starts_at if booking.starts_at.tzinfo else booking.starts_at.replace(tzinfo=timezone.utc)
            lines.append(f"• {starts_at.strftime('%a %d %b, %H:%M')} UTC · {shop.name if shop else '—'} · "
                         f"{service.name if service else '—'} · {booking.code} · "
                         f"{booking.status.value if hasattr(booking.status, 'value') else booking.status}")
        return ChatReply(answer="\n".join(lines), intent="my_bookings",
                         sources=[ChatSource(doc_id=f"booking:{booking.id}", kind="booking",
                                             label=f"Booking {booking.code}") for booking in bookings[:3]],
                         suggestions=["Cancel a booking", "Book another slot"])

    def _cancel(self, message: str, user: User | None, context: dict) -> ChatReply:
        import re

        if user is None:
            return ChatReply(answer="Sign in and tell me the booking code to cancel it.",
                             intent="cancel", suggestions=["Sign in", "My bookings"])
        match = re.search(r"\b[A-Za-z0-9_-]{6,12}\b", message)
        code = match.group(0).upper() if match else None
        booking = None
        if code:
            booking = self.db.scalar(select(Booking).where(Booking.code == code,
                                                           Booking.customer_id == user.id))
        if not booking:
            return ChatReply(
                answer=("Tell me the booking code and I'll cancel it — for example "
                        "“cancel 7Q2K9XAB”. Your codes are in My bookings."),
                intent="cancel", suggestions=["My bookings"])
        if booking.status == BookingStatus.CANCELLED:
            return ChatReply(answer=f"Booking {booking.code} is already cancelled.", intent="cancel")
        BookingService(self.db).cancel_booking(booking.id, user.id)
        return ChatReply(answer=f"✅ Cancelled {booking.code}. The slot is free for someone else.",
                         intent="cancel", suggestions=["Book another slot", "My bookings"])

    # ── Retrieval fallback ─────────────────────────────────────────────────
    def _fallback(self, message: str, user: User | None, context: dict) -> ChatReply:
        results = self.index.search(message, limit=4)
        if not results:
            return ChatReply(
                answer=("I couldn't find anything for that. I know about shops, services, prices, "
                        "opening hours, reviews and slots — try “shops near me” or "
                        "“book a haircut tomorrow at 5pm”."),
                intent="unknown",
                suggestions=["Haircut near me", "Show all shops", "My bookings"])
        lines = ["Here's what I found:"]
        cards: list[ChatCard] = []
        for _score, document in results:
            if document.kind == "shop":
                shop = self.db.get(Shop, document.shop_id)
                if not shop:
                    continue
                lines.append(f"• {shop.name} — {self._shop_facts(shop) or 'shop'}")
                cards.append(ChatCard(kind="shop", id=shop.id, title=shop.name,
                                      meta=self._shop_facts(shop), shop_id=shop.id))
            elif document.kind == "service":
                lines.append(f"• {document.label} — {inr(document.data.get('price_paise', 0))}")
            elif document.kind == "review":
                lines.append(f"• {document.text[:160]}")
            elif document.kind == "hours":
                lines.append(f"• {document.text}")
        return ChatReply(answer="\n".join(lines), intent="unknown", cards=cards[:MAX_CARDS],
                         sources=[ChatSource(**item) for item in self._sources_for(message)],
                         suggestions=["Show prices", "Book a slot", "Use my location"])
