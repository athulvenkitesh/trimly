from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    customer_id: int
    rating: int
    comment: str | None
    created_at: datetime
    # Display label derived from the customer email (local part only).
    customer_name: str = ""


class ReviewListOut(BaseModel):
    rating_avg: float | None
    rating_count: int
    reviews: list[ReviewOut]
