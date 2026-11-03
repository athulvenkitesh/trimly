from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.dependencies import require_shop_owner
from app.core.database import get_db
from app.core.security import decode_token
from app.models import User
from app.schemas.chat import ChatReply, ChatRequest, OwnerChatRequest
from app.services.chat.customer_chat import CustomerChat
from app.services.chat.owner_chat import OwnerChat, resolve_owner_shop

router = APIRouter(prefix="/chat", tags=["assistant"])

optional_bearer = HTTPBearer(auto_error=False)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Sign-in is optional for browsing the customer assistant.

    Discovery questions work signed out; only booking needs the account, and
    the assistant says so instead of failing. A token that *is* sent must still
    be valid — silently treating a broken session as anonymous would look like
    the user got signed out for no reason.
    """
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        user = db.get(User, int(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials") from exc
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/customer", response_model=ChatReply,
             summary="Ask the customer assistant about shops, prices and slots")
def customer_chat(payload: ChatRequest, user: User | None = Depends(get_optional_user),
                  db: Session = Depends(get_db)):
    return CustomerChat(db).reply(
        message=payload.message, user=user, latitude=payload.latitude, longitude=payload.longitude,
        shop_id=payload.shop_id, service_id=payload.service_id)


@router.post("/owner", response_model=ChatReply,
             summary="Ask the shop-owner assistant about bookings, revenue and reviews")
def owner_chat(payload: OwnerChatRequest, user: User = Depends(require_shop_owner),
               db: Session = Depends(get_db)):
    shop = resolve_owner_shop(db, user, payload.shop_id)
    if not shop:
        raise HTTPException(404, "Create your shop before asking about your numbers.")
    return OwnerChat(db).reply(message=payload.message, shop=shop)
