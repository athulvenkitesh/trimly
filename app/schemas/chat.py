from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """One turn of the assistant conversation.

    `shop_id`/`service_id` carry the context the client got back from the
    previous reply, so a follow-up like "and its price?" stays on the same shop
    without the user repeating themselves. Coordinates are optional: send them
    and "near me" style answers are ranked by real distance.
    """

    message: str = Field(min_length=1, max_length=600)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    shop_id: int | None = None
    service_id: int | None = None


class OwnerChatRequest(ChatRequest):
    """Owner-side question; shop_id picks the shop when an owner has several."""


class ChatSource(BaseModel):
    """A retrieved row the answer was built from (the "R" in RAG)."""

    doc_id: str
    kind: str
    label: str


class ChatCard(BaseModel):
    """A tappable result the client can render (a shop, a service, a slot)."""

    kind: str
    id: int
    title: str
    meta: str = ""
    shop_id: int | None = None


class ChatBooking(BaseModel):
    """A booking the assistant just made on the customer's behalf."""

    id: int
    code: str
    shop_id: int
    shop_name: str
    service_id: int
    service_name: str
    starts_at: str
    price_paise: int
    convenience_fee_paise: int
    total_paise: int


class ChatReply(BaseModel):
    answer: str
    intent: str
    sources: list[ChatSource] = []
    suggestions: list[str] = []
    cards: list[ChatCard] = []
    booking: ChatBooking | None = None
    shop_id: int | None = None
    service_id: int | None = None
