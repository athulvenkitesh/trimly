"""Small, deterministic natural-language helpers shared by both assistants.

No model download and no API key: the app must answer chats offline, so intents
are matched with weighted keyword patterns and the few entities that matter
(day, time, budget) are extracted with explicit rules. Everything the assistant
*states* still comes from retrieved database rows — these helpers only decide
which question was asked.
"""

import re
from datetime import date, datetime, time, timedelta, timezone

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}

# Phrases, not words: "how many bookings" must beat the bare "booking".
INTENTS: dict[str, list[str]] = {
    "greeting": ["hi", "hello", "hey", "namaste", "good morning", "good evening", "yo"],
    "help": ["help", "what can you do", "how does this work", "who are you", "options"],
    "nearby": ["near me", "nearby", "close to me", "around me", "around here", "near here",
               "near my", "in my area", "close by", "closest", "nearest"],
    "compare_prices": ["cheapest", "cheap", "cheaper", "affordable", "lowest price", "best price",
                       "compare prices", "price comparison", "least expensive", "sort by price",
                       "price list"],
    "find_shops": ["find a shop", "find shops", "any shops", "shops", "barbers", "barbershop",
                   "salon", "list shops", "show shops", "which shop", "nearby shops"],
    "services": ["services", "service menu", "prices", "price", "cost", "how much", "charges",
                 "rate", "rates", "menu", "what do you offer", "offers"],
    "hours": ["hours", "open", "closed", "timing", "timings", "opening", "closing", "when do they open"],
    "reviews": ["review", "reviews", "rating", "ratings", "feedback", "good", "best", "popular"],
    "availability": ["slots", "available", "availability", "free slot", "free time", "openings",
                     "what time", "which time", "next available"],
    "book": ["book", "booking please", "reserve", "make an appointment", "schedule", "i want a haircut",
             "book a", "appointment for"],
    "cancel": ["cancel", "cancel my"],
    "my_bookings": ["my booking", "my bookings", "my appointment", "my appointments"],
}


# Words that say what kind of answer is wanted, not which service it is about.
STOPWORDS = {
    "the", "and", "for", "any", "are", "can", "you", "have", "with", "what", "which", "who",
    "how", "much", "does", "cost", "costs", "price", "prices", "cheap", "cheapest", "cheaper",
    "affordable", "lowest", "best", "least", "expensive", "compare", "comparison", "near", "nearby",
    "around", "here", "there", "me", "my", "show", "list", "all", "shop", "shops", "salon",
    "salons", "barber", "barbers", "barbershop", "barbershops", "service", "services", "menu",
    "please", "want", "need", "looking", "find", "give", "tell", "about", "today",
    "tomorrow", "open", "closed", "book", "booking", "slot", "slots", "available", "under",
    "below", "less", "than", "max", "upto", "get", "your", "this", "that", "some", "them",
}


def content_tokens(text: str) -> set[str]:
    """Meaningful words, singularised, so "haircuts" still matches "Haircut"."""
    words = re.findall(r"[a-z0-9]+", normalize(text))
    out = set()
    for word in words:
        if len(word) <= 2 or word in STOPWORDS:
            continue
        out.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return out


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def detect_intent(text: str, intents: dict[str, list[str]] | None = None) -> tuple[str, float]:
    """Return (intent, score). Longer matched phrases weigh more than short ones."""
    lowered = normalize(text)
    if not lowered:
        return "unknown", 0.0
    best, best_score = "unknown", 0.0
    for intent, phrases in (intents or INTENTS).items():
        score = 0.0
        for phrase in phrases:
            if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lowered):
                score += 1.0 + len(phrase.split()) * 0.75
        if score > best_score:
            best, best_score = intent, score
    return best, best_score


PRICE_PHRASES: list[str] = INTENTS["compare_prices"]


def has_phrase(text: str, phrases: list[str]) -> bool:
    lowered = normalize(text)
    return any(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lowered) for phrase in phrases)


def parse_day(text: str, today: date | None = None) -> date | None:
    """Resolve "today", "tomorrow", a weekday name or a calendar date."""
    lowered = normalize(text)
    today = today or datetime.now(timezone.utc).date()
    if re.search(r"\bday after tomorrow\b", lowered):
        return today + timedelta(days=2)
    if re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", lowered):
        return today
    if re.search(r"\btomorrow\b|\btmrw\b|\btmrw\b", lowered):
        return today + timedelta(days=1)
    for offset, name in enumerate(WEEKDAY_NAMES):
        if re.search(rf"\b{name}\b", lowered):
            ahead = (offset - today.weekday()) % 7
            return today + timedelta(days=ahead or 7)
    # "12 october", "oct 12", "12-10", "2026-10-12"
    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lowered)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    day_month = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b", lowered)
    month_day = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b", lowered)
    for match, day_first in ((day_month, True), (month_day, False)):
        if not match:
            continue
        raw_day, raw_month = (match.group(1), match.group(2)) if day_first else (match.group(2), match.group(1))
        for index, name in enumerate(MONTH_NAMES):
            if name.startswith(raw_month[:3]) and len(raw_month) >= 3:
                try:
                    candidate = date(today.year, index + 1, int(raw_day))
                except ValueError:
                    return None
                if candidate < today:  # a bare date in the past means next year
                    candidate = date(today.year + 1, index + 1, int(raw_day))
                return candidate
    relative = re.search(r"\bin (\d{1,2}) days?\b", lowered)
    if relative:
        return today + timedelta(days=int(relative.group(1)))
    return None


def parse_time(text: str) -> time | None:
    """Resolve "5pm", "17:30", "at 5", "noon" or "evening" to a wall-clock time."""
    lowered = normalize(text)
    if re.search(r"\bnoon\b|\bmidday\b", lowered):
        return time(12, 0)
    if re.search(r"\bmidnight\b", lowered):
        return time(0, 0)

    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", lowered)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        meridiem = match.group(3)[0]
        if not 1 <= hour <= 12:
            return None
        if meridiem == "p" and hour != 12:
            hour += 12
        if meridiem == "a" and hour == 12:
            hour = 0
        return time(hour, minute)

    colon = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)
    if colon:
        hour, minute = int(colon.group(1)), int(colon.group(2))
        if hour > 23 or minute > 59:
            return None
        return time(hour, minute)

    at_hour = re.search(r"\b(?:at|by|around|@)\s*(\d{1,2})\b", lowered)
    if at_hour:
        hour = int(at_hour.group(1))
        if hour > 23:
            return None
        if hour < 8:  # "at 5" in a barbershop conversation means 5pm
            hour += 12
        return time(hour, 0)

    for phrase, hour in (("morning", 9), ("afternoon", 14), ("evening", 18), ("night", 19)):
        if re.search(rf"\b{phrase}\b", lowered):
            return time(hour, 0)
    return None


def parse_budget_paise(text: str) -> int | None:
    """Extract a price ceiling ("under 300", "below ₹250") in paise."""
    match = re.search(r"\b(?:under|below|less than|cheaper than|max|upto|up to)\s*₹?\s*(\d{2,6})\b", normalize(text))
    if not match:
        return None
    return int(match.group(1)) * 100


def number_from_word(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return WORD_NUMBERS.get(token)
