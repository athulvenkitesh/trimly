# LinkedIn post — Trimly assistants

Three things in this file: the post text, a carousel script, and a longer
"build in public" variant. Pick one; don't post all three.

---

## Post text (primary — ~1,700 characters)

> I built a booking chatbot that answers "how much is a haircut near me?" and
> "what's my revenue today?" — and refuses to make up either answer.
>
> The trap with chat assistants on top of a database is that they're confident
> even when they're wrong. A barber asking "how many bookings today?" can't get a
> plausible-sounding number; they need the real one.
>
> So the rule became: retrieve first, write second.
>
> Every request builds a small document corpus from live rows — shops, the service
> menu, opening hours, reviews, and on the owner side, bookings and payments. BM25
> ranks it, intent detection decides which question was asked, and then the answer
> is composed only from what came back.
>
> That means:
> → Every price is read from the services table, never from prose
> → Every slot comes from the same availability engine the web dialog uses
> → Every answer carries its sources, so an owner can audit the number
> → No API key, no embeddings, no index rebuild — it runs offline
>
> Two surfaces, one layer:
> · Customer: nearby shops, price comparison, opening hours, reviews, free slots, booking
> · Owner: today's bookings, today's revenue, top services, walk-ins, cancellations
>
> Booking goes through the same service layer as the UI, so the database's unique
> index still makes double-booking impossible. The chat has no private path to the
> data — that's the whole point.
>
> The best bug this caught: "how many bookings do I have today?" was answered under
> the headline "This week". Today's numbers, week's label. It looked fine in a
> screenshot and would have been wrong in a Monday review. One shared period parser
> later, the label and the rows come from the same object.
>
> 37 tests green, 13 of them for the assistants.
>
> RAG isn't only about embeddings. When the corpus is your own database and the
> answers are prices and times, retrieval quality is a correctness feature, not a
> tuning knob.
>
> #buildinpublic #python #fastapi #rag #llm #saas

## Carousel (document post — 9 slides, 1080×1350)

**Slide 1 — hook**
> A booking chatbot that can't invent a price.
> ```
> Two assistants. One retrieval layer. Zero made-up numbers.
> ```

**Slide 2 — the problem**
> Chat + database = confident guesses.
> - "How much is a haircut?" → a plausible ₹200
> - "How many bookings today?" → today's numbers under a "This week" heading
> - Both look fine in a screenshot. Both are wrong.

**Slide 3 — the rule**
> Retrieve first, write second.
> ```
> question → intent → retrieve rows → compose sentence → cite rows
> ```
> The sentence is never written before the data arrives.

**Slide 4 — what gets retrieved**
> The corpus is the database, rebuilt per request.
> - 1 doc per shop · per service · per hours sheet · per review
> - Owner side adds bookings + payments
> - BM25 ranks it (k1=1.5, b=0.75) — no API key, no index job, works offline
> - Aliases so "haircut" and "hair cut" land together

**Slide 5 — customer side**
> `> cheapest haircut around here`
> ```
> 💰 Cheapest haircut across 1 shop:
> • Haircut — ₹250 · 30 min · The Corner Chair · ★4.5
> ```
> Nearby · price comparison · hours · reviews · free slots · booking

**Slide 6 — owner side**
> `> how many bookings do I have today?`
> ```
> 📊 Today (02 Nov, UTC) at The Corner Chair:
> • 4 confirmed bookings · 1 walk-in · 1 cancelled
> • Expected: ₹950 · Collected: ₹700
> • Bookings without payment: 1
> ```
> Counts, revenue, top services, walk-ins, cancellations.

**Slide 7 — booking stays boring**
> The chat doesn't own booking logic.
> - Slots come from the same availability service as the UI
> - Bookings go through the same `BookingService`
> - The unique index is still the final guard; a 409 becomes "that slot just went — here are three others"

**Slide 8 — the bug worth telling**
> Today's numbers under a week's label.
> - Intent matched "bookings", handler defaulted to weekly
> - Fix: one `parse_period()` for all report handlers
> - Now the label and the rows are the same object, with a test that fails if they drift

**Slide 9 — takeaway + CTA**
> RAG is a correctness feature.
> ```
> Grounding > fluency. When the answer is a price or a time,
> "sounds right" is not a pass criterion.
> ```
> What would you ask your own shop data first?

## Build-in-public variant (shorter, more personal)

> Spent this build on a chatbot that answers two very different questions from the
> same data:
>
> Customer: "cheapest haircut near me?"
> Owner: "what's my revenue today?"
>
> Same retrieval layer, different corpus. BM25 over live rows — no embeddings, no API
> key, rebuild everything per request. Every number in the answer is traceable to a
> booking, a payment or a menu row, and the reply carries its sources.
>
> Two things I got wrong and fixed:
> 1. "cheapest haircut" fell through to a generic dump that cited an unrelated review.
> 2. "how many bookings today?" answered under a "This week" headline.
>
> Both looked fine until I read the actual output. That's the habit that matters with
> RAG: test the answer, not the pipeline.
>
> #buildinpublic #python #fastapi

---

## Before you post

- **Screenshots to take** (dark theme, cropped, no browser chrome):
  the customer panel after "cheapest haircut"; the owner "Ask Trimly" view with the
  Today report; the two chat bubbles side by side for slide 1.
- **Don't overclaim.** Payments are on the mock provider in this build; say
  "bookings, not payments" if you show the pay button.
- **Numbers.** 37 tests / 13 for the assistants, 2 shops and 6 services seeded for the
  demo. Seeded data is fine to mention — it's what makes the transcript legible.
- **Alt text for the hook image:** "Chat transcript from a booking assistant showing
  its sources under the answer."
- **First comment** (keeps the post clean): a link to the flow doc or repo, plus
  "happy to share the intent-routing table if it's useful".
- **Reply with substance** for the first hour: "why not embeddings?", "how do you stop
  it inventing slots?", "what about Hindi/regional languages?" — the working-flow doc
  has the answers.
