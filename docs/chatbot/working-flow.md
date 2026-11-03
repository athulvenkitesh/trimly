# How the Trimly assistants work

Two chat surfaces, one retrieval layer, zero hallucinated facts.

```
Customer portal  ──▶  POST /api/v1/chat/customer  ──▶  CustomerChat
Owner dashboard  ──▶  POST /api/v1/chat/owner     ──▶  OwnerChat
                              │
                              ├── RagIndex  (BM25 over live rows)
                              ├── intents   (which question was asked)
                              ├── AvailabilityService  (real free slots)
                              └── BookingService       (real reservations)
```

---

## 1. One request, start to finish

```
[1] User types "book a beard trim at The Corner Chair tomorrow at 2pm"
        │
        ▼
[2] customer_web/app.js  sendChat()
        POST /api/v1/chat/customer
        { message, shop_id?, service_id?, latitude?, longitude? }
        Authorization: Bearer <access token>   (optional)
        │
        ▼
[3] api/routes/chat.py  get_optional_user()
        no token   -> anonymous, discovery still allowed, booking politely refused
        bad token  -> 401 (never silently downgraded to "signed out")
        │
        ▼
[4] CustomerChat.reply()
        builds the corpus for THIS request:
          customer_documents(db, lat, lon)
        │
        ▼
[5] intents.detect_intent()
        "book"  ──▶  _book()
        │
        ▼
[6] _resolve_shop()      named in the message > context from last reply > single shop
    _resolve_service()   "beard trim" -> Beard Trim (₹150, 20 min)
    parse_day()          "tomorrow"  -> tomorrow's date
    parse_time()         "2pm"       -> 14:00
        │
        ▼
[7] AvailabilityService.get_available_slots(shop, service, day)
        business hours  ∩  slot interval  ∩  not already CONFIRMED  ∩  in the future
        │
        ▼
[8] _pick_slot()  -> 14:00 if free, else the closest opening (and says so)
        │
        ▼
[9] BookingService.create_booking()          <-- the same code the web dialog uses
        double-booking is impossible: partial unique index on (shop_id, starts_at)
        on conflict -> 409 -> the assistant apologises and offers other times
        │
        ▼
[10] ChatReply { answer, intent, cards, booking, sources, suggestions }
        │
        ▼
[11] renderChatReply()  writes the bubble, the tappable cards,
        the "Pay ₹160 with UPI" button and 3 follow-up chips.
```

## 2. The retrieval layer (the "R" in RAG)

The corpus is rebuilt from the database on **every request** — small, current, and
impossible to outlive the rows it describes.

| Document | Customer corpus | Owner corpus |
|---|---|---|
| `shop:<id>` | name, address, pincode, menu summary, rating, hours, distance | name, address, open/closed, menu |
| `service:<id>` | name, price, duration, shop | — |
| `hours:<id>` | one sheet per shop, all seven days | — |
| `booking:<id>` | — | code, service, price, customer/walk-in, time, status |
| `payment:<id>` | — | amount, method, status |
| `review:<id>` | stars + comment text | stars + comment text |

Scoring is BM25 with the usual defaults (`k1 = 1.5`, `b = 0.75`):

```
idf(t)   = ln( 1 + (N - df + 0.5) / (df + 0.5) )
score(d) = Σ  idf(t) · tf · 2.5 / ( tf + 1.5 · (0.25 + 0.75 · len(d) / avg_len) )
```

Three details do most of the work in practice:

- **Aliases** — "haircut", "trim" and "hair cut" land on the same document; "shops" expands
  to "barbershop".
- **Stopwords** — "near me", "how much", "show" carry no signal and are dropped before scoring.
- **Distance beats relevance when coordinates exist** — "haircut near me" lists the closest
  shop that does haircuts, not the best keyword match.

Why BM25 and not embeddings? The corpus is tens of documents per shop, the product has to answer
offline and with no API key, and a lexical retriever can never invent a price. If the corpus
grows past a few thousand documents, swap `RagIndex` for a vector store behind the same
`search(query, limit, kinds)` interface — nothing else changes.

## 3. Intent routing

Classification is weighted phrase matching, not guesswork: longer phrases weigh more, so
"how many bookings" beats a bare "booking".

| Customer intent | Example | Handler |
|---|---|---|
| `nearby` | "shops near me" | distance-ranked, ≤ 25 km, cards per shop |
| `find_shops` | "any fade shops" | BM25 + distance sort |
| `compare_prices` | "cheapest haircut", "compare prices" | menu rows ranked by price, optional "under ₹200" |
| `services` | "how much is a fade?" | menu for one shop, or the first three shops |
| `hours` | "when is The Corner Chair open?" | seven-day sheet per shop |
| `reviews` | "is it any good?" | average, count, latest comments |
| `availability` | "free slots tomorrow?" | real slots, next 5 |
| `book` | "book a beard trim tomorrow 2pm" | books through `BookingService` |
| `my_bookings` / `cancel` | "my bookings", "cancel MD9M4RVP" | account-scoped rows |
| fallback | anything else | top-4 BM25 hits, cited |

A price word anywhere in the sentence wins over everything else — "cheapest haircut near me"
is a price question that mentions distance, not a distance question.

| Owner intent | Example |
|---|---|
| `today_bookings` / `today_revenue` | "how many bookings today", "today's revenue" |
| `period_report` | "how much did I collect this week / last month" |
| `next_appointment` | "who is next?" |
| `top_services` | "which service is selling the most?" |
| `walk_ins` · `cancellations` | "any walk-ins today", "cancel rate this month" |
| `reviews` · `hours` · `customers` | "how are my reviews", "am I open Sunday" |

## 4. Owner answers: one parser for the window

Every report handler resolves the time window through `parse_period()`, which returns
`(start, end, label, single_day)`. The label can therefore never disagree with the rows
that were counted:

```
"how many bookings do I have today?"      -> Today (Mon 02 Nov, UTC)
"what did I collect this week?"           -> This week (02 Nov – 08 Nov, UTC)
"how many last month?"                    -> Last month (01 Oct – 31 Oct, UTC)
```

Money is always split into three numbers an owner actually cares about:

```
📊 Today (Mon 02 Nov, UTC) at The Corner Chair:
• 4 confirmed bookings · 1 walk-in · 1 cancelled
• Expected: ₹950          <- sum of booked service prices
• Collected: ₹700         <- COMPLETED payments only
• Bookings without payment: 1
```

`Sources: Booking QRU4JHDO · Booking 0ODJ43OX · Booking XH9OGTGK` — the citations *are* the
rows, so the owner can audit any number in the answer.

## 5. Sample session (seeded data: 2 shops, 5 services, 6 bookings, 2 reviews)

**Customer**

```
> which shops are near me?
📍 2 shops near you:
• The Corner Chair — from ₹150 · 0.02 km away · ★4.5 (2) · 12 Market Street, Indiranagar
• Fade Factory — from ₹180 · 3.63 km away · 88 Brigade Road

> cheapest haircut around here
💰 Cheapest haircut across 1 shop:
• Haircut — ₹250 · 30 min · The Corner Chair · ★4.5 (2)
Service prices only — each shop adds its own convenience fee at checkout.

> compare prices
💰 Cheapest services across 2 shops:
• Beard Trim — ₹150 · 20 min · The Corner Chair
• Kids Cut — ₹180 · 25 min · Fade Factory
• Haircut — ₹250 · 30 min · The Corner Chair
...
The Corner Chair is the cheapest at ₹150 — ₹200 less than the priciest option listed.

> book a beard trim at The Corner Chair tomorrow at 2pm
✅ Booked! The Corner Chair · Beard Trim
Tue 03 Nov, 14:00 UTC — code MD9M4RVP
₹150 + ₹10 convenience fee = ₹160.
Your slot is reserved; pay in the app to settle it.
[Pay ₹160 with UPI] [Show my bookings] [Book another slot]
```

**Owner**

```
> how many bookings do I have today?
📊 Today (Mon 02 Nov, UTC) at The Corner Chair:
• 4 confirmed bookings · 1 walk-in · 1 cancelled
• Expected: ₹950
• Collected: ₹700
• Bookings without payment: 1

> which service is selling the most?
🏆 Most booked services (last 30 days):
• Haircut — 2 bookings · ₹500
• Hot Towel Shave — 1 booking · ₹300
• Beard Trim — 1 booking · ₹150
4 bookings in total. Add or reprice the quiet services to fill the gaps.
```

## 6. Rules that keep it honest

1. **Grounding first, wording second.** Handlers retrieve rows, then compose the sentence —
   never the other way round.
2. **Citations on every answer.** `ChatReply.sources` names the exact documents used, and the
   UI renders them as `From: …`.
3. **Scope by construction.** `OwnerChat` is built with one shop; every query filters on
   `shop_id`, so one owner can never see another's numbers.
4. **Auth is honest.** Anonymous browsing works; booking asks for sign-in; an invalid token is
   a 401, not a silent downgrade.
5. **No invented availability.** Slots come from `AvailabilityService`, bookings from
   `BookingService` — the chat has no private path to the database.
6. **UTC is stated, not assumed.** Every time in an answer carries its unit.

## 7. A bug this flow caught

`"how many bookings do I have today?"` was answered under the headline **"This week"** — the
numbers were today's, the label wasn't, because the intent matched on "bookings" and the
handler fell back to its weekly default. It looked right in a screenshot and was wrong in a
board meeting.

Fix: one `parse_period()` parser shared by all three report handlers, so the window label and
the rows counted are the same object. There is now a test that fails if a "today" question
ever answers under a week label.

## 8. Tests

`tests/test_chat.py` — 13 tests, part of a 37-test suite:

- shops ranked by distance with prices from the menu
- prices read from the menu, not from prose
- booking from chat lands in `/customer/bookings`
- single shop used when none is named
- cheapest question ranks menu prices (new)
- named day overrides the default report window (new)
- owner sees today's bookings, revenue, next appointment, top service
- walk-in counted; opening hours reported
- customers get 403 on `/chat/owner`; unauthenticated gets 401/403
