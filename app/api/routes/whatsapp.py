import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.integrations.webhook_signature import verify_hmac
from app.integrations.whatsapp import client
from app.integrations.whatsapp.webhook import verify_webhook
from app.services.whatsapp_flow import WhatsAppFlow

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/webhook", response_class=PlainTextResponse, summary="Verify the WhatsApp webhook (Meta handshake)")
def webhook_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    return verify_webhook(hub_mode, hub_token, hub_challenge, settings.whatsapp_verify_token)


def _extract_messages(payload: dict) -> list[dict]:
    """Flatten Meta's entry/changes envelope into simple inbound messages."""
    messages: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                item: dict = {"id": message.get("id"), "phone": message.get("from"), "type": message.get("type", "unknown")}
                if message.get("type") == "text":
                    item["text"] = message.get("text", {}).get("body", "")
                elif message.get("type") == "location":
                    location = message.get("location", {})
                    item["latitude"] = location.get("latitude")
                    item["longitude"] = location.get("longitude")
                messages.append(item)
    return messages


@router.post("/webhook", summary="Receive WhatsApp messages and drive the booking flow")
async def webhook_receive(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    # Meta signs deliveries when an app secret is configured; verify before trusting.
    if settings.whatsapp_app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "").removeprefix("sha256=")
        if not verify_hmac(body, signature, settings.whatsapp_app_secret):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = json.loads(body or b"{}")
    flow = WhatsAppFlow(db)
    for message in _extract_messages(payload):
        phone = message.get("phone")
        if not phone:
            continue
        for reply in flow.handle(phone, message):
            client.send_text(phone, reply)
    # Always acknowledge fast so Meta does not retry the delivery.
    return {"status": "received"}
