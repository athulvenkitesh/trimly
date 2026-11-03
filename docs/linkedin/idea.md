# LinkedIn post idea — "An assistant with no model in it"

This is a *third* angle, separate from the technical post in
[linkedin-post.md](../linkedin-post.md) and the 9-slide carousel in
[carousel.html](carousel.html). Those two explain how it works. This one is an
argument, and arguments get comments.

**The idea in one line:** the surprising claim is not that a chatbot works — it
is that the useful one here has no model in the answer path, and that this was a
correctness decision, not a budget one.

---

## The post (ready to paste)

> An assistant with no model in it.
>
> No GPT. No embeddings. No API key.
>
> It answers "how much is a haircut near me?" and "what's my revenue today?" from
> a BM25 index built out of my own Postgres tables — rebuilt on every request, in
> memory.
>
> Everyone's first instinct with chat-on-top-of-data is: hand a model the schema
> or a JSON dump and hope. I built the boring version first, and the boring
> version turned out to be the correct one.
>
> Three steps, no generation:
>
> 1. Route — a small rule table decides which question is being asked
> 2. Retrieve — BM25 ranks documents built from live rows: one per shop, service,
>    hours sheet, review, booking and payment
> 3. Compose — the answer is a template filled only with what came back, and it
>    carries its sources
>
> There is no hallucination surface because there is no generation step.
>
> What that costs me: ask "I want to look good for my sister's wedding" and you
> get "Shops by rating." There is no intent for taste. It cannot riff — it buckets
> your question into the nearest one it knows and grounds the answer in whatever
> matched.
>
> What it buys me: a barber asks for today's revenue and gets a number summed
> from the booking and payment rows, with those rows listed under it. If a fetched
> row is wrong, you fix one query. If a model invents a row, you fix a class of
> bug forever.
>
> Safe isn't the same as smart, though. It never invents a price, and it will
> still answer the wrong question confidently — "what's the weather" gets an
> honest "I couldn't find anything for that", but a wedding question gets a
> rating list. Misrouting is a much easier bug to fix than confabulation: one is
> a rule, the other is a distribution.
>
> The question I ask before reaching for a model now: is the answer a fact or a
> phrasing? Counts, prices, slots — facts. Tone, summaries, "make this sound
> human" — phrasing.
>
> 37 tests green. The one that matters: ask the same question twice, get the
> same answer.
>
> What's a feature you shipped without a model, on purpose?

---

## Tested before writing the claims (4 Nov 2026, live on :8001)

The "cannot riff" paragraph is a real transcript, not a guess:

| Asked | Routed to | Answered |
|---|---|---|
| `I want to look good for my sister's wedding` | `reviews` | "Shops by rating" — ignores the wedding |
| `something cheap for a wedding, not sure what` | `compare_prices` | cheapest services: beard trim ₹150, kids cut ₹180 |
| `what's the weather in kochi` | `unknown` | "I couldn't find anything for that." + suggestions |
| `can you do a fade that suits a round face` | `unknown` | falls back to BM25 hits: Skin Fade ₹350, a review |

If a commenter asks "so what happens when it doesn't know?", the third row is
the answer — and the first two rows are why the post says *misrouting*, not
*hallucination*.

---

## Why this version, not the explainer

- **It starts with a claim someone can disagree with.** "No model" reads as
  wrong for a second, which is what earns a comment. The explainer post opens
  with a description and gets nods instead.
- **The comments are the actual content.** "But that's not AI" and "what about
  paraphrases?" are both answerable with real evidence — the aliases table, the
  fallback transcript — so you can reply with substance instead of vibes.
- **It ages well.** If you add an LLM later, this post becomes the before/after
  story rather than something you have to quietly delete.
- **It is honest about the cost.** The "it cannot riff" paragraph is the part
  that makes the rest believable.

## The image

One image, not a carousel: [owner-chat.png](images/owner-chat.png) cropped to
the answer plus its `From:` line. The proof is the sources note sitting under a
number that came from the database — let the screenshot say "look, it cited the
row".

Alt text: *"Owner dashboard chat: a Today revenue report with the database rows
it was built from listed underneath."*

## First comment (keep the post link-free)

> Repo and the flow write-up (retrieval, intent table, the period-parser bug) are
> here if useful: [link]. Happy to share the corpus builder — about 120 lines, and
> that's the whole trick.

## Before posting

- Do **not** say "AI" in the hook if you are going to argue there is no model —
  the contradiction is the point, so keep it deliberate and resolve it in line 3.
- Say "assistant", never "LLM-powered".
- Payments still settle on the mock provider; the post only claims reports and
  bookings, which is true.
- Don't claim it "declines when unsure" — it always answers something. The
  honest version is "it grounds the answer, and when the question is out of
  scope it says so; the failure mode is answering the wrong question, not
  inventing a fact."
- Numbers to keep straight: 37 tests, 13 of them for the assistants, 2 shops and
  6 services seeded for the demo.

## Two alternates if this one feels too combative

1. **"The bug that looked fine."** Open on the screenshot where today's numbers
   sat under a "This week" heading. Everything rendered correctly; the label was
   the lie. Lesson: for data answers, the test is the *output*, not the pipeline.
2. **"Two chatbots, one corpus builder."** Same retrieval layer, two corpora —
   customers get shops and menus, owners get bookings and payments, and neither
   can see the other's rows. Best if you want to talk multi-tenancy and
   authorization rather than RAG.
