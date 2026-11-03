# Chatbot — structure and naming

Two assistants, one retrieval layer:

- **Customer** — "which shops are near me", "cheapest haircut", "book a fade tomorrow at 5pm".
- **Owner** — "how many bookings today", "today's revenue", "which service is selling".

Everything they say is read out of the database during the request. Nothing is
hard-coded and nothing is invented.

- [working-flow.md](working-flow.md) — end-to-end request lifecycle, with diagrams and sample answers.
- [../linkedin-post.md](../linkedin-post.md) — the public write-up.
- [../trimly-report.pdf](../trimly-report.pdf) — printable PDF report: technology, architecture, flow and screenshots.
  Source: [../report/report.html](../report/report.html), screenshots in `report/screenshots/`.

## Where the code lives

```
app/
├── api/routes/
│   └── chat.py                  # POST /api/v1/chat/customer · /chat/owner
├── schemas/
│   └── chat.py                  # ChatRequest, ChatReply, ChatCard, ChatBooking, ChatSource
├── services/chat/               # the feature package
│   ├── __init__.py
│   ├── rag.py                   # Document, RagIndex (BM25), corpus builders, citations, inr()
│   ├── intents.py               # keyword intents, day/time/budget parsing, content tokens
│   ├── customer_chat.py         # CustomerChat: discovery, prices, slots, booking, cancel
│   └── owner_chat.py            # OwnerChat: today/week/month reports, top services, reviews
├── services/booking_service.py  # booking rules (unchanged — chat books through this)
├── services/availability_service.py  # the only source of bookable start times
├── customer_web/                # customer portal + floating assistant panel
│   ├── index.html               # #chat-launcher, #chat-panel, #chat-log, #chat-chips, #chat-form
│   ├── app.js                   # sendChat, renderChatReply, payFromChat, chatChips
│   └── styles.css               # .chat-panel, .chat-bubble, .chat-card, .chat-action
└── web/                         # owner portal + "Ask Trimly" view
    ├── index.html               # nav data-view="assistant", #assistant-section, #oc-log, #oc-chips
    ├── app.js                   # showView('assistant'), openOwnerChat, askOwnerAssistant
    └── styles.css               # .assistant-shell, .chat-bubble, .chat-chip

tests/
└── test_chat.py                 # 13 tests: discovery, prices, booking, owner reports, access control
```

## Naming rules used here

| Thing | Rule | Why |
|---|---|---|
| Python modules | `snake_case`, one responsibility | `rag.py` retrieves, `intents.py` classifies, `*_chat.py` answers |
| Feature package | `app/services/chat/` | keeps the four modules together instead of four top-level `chat_*` files |
| Route module | `app/api/routes/chat.py` | plural route modules (`shops.py`, `bookings.py`), one per resource |
| Schemas | `app/schemas/chat.py` | request/response models never live in the route file |
| Docs | `docs/<feature>/kebab-case.md` | `docs/chatbot/working-flow.md` |
| Tests | `tests/test_<module>.py` | mirrors the module under test |
| Frontend ids | feature prefix (`chat-`, `oc-`, `assistant-`) | `oc-log` is the owner chat, `chat-log` the customer one — no ambiguity |

## When this grows

- Split `tests/test_chat.py` → `test_chat_customer.py` + `test_chat_owner.py` once it passes ~300 lines.
- If an LLM is added later, put prompt text in `app/services/chat/prompts.py` and keep
  `rag.py`/`intents.py` as the grounding layer — the interface (`ChatReply`) does not change.
- New corpus documents (staff, offers, queue length) become new `Document(kind=...)` entries in
  `customer_documents()`/`owner_documents()`; retrieval and citations pick them up for free.

## Running it

```bash
uvicorn app.main:app --port 8000     # API + both portals
pytest -q                            # 37 tests, 13 of them for the assistants
```

Customer portal at `/`, owner portal at `/dashboard/`, API docs at `/docs`.
