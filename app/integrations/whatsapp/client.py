import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v20.0"


def is_configured() -> bool:
    return bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id)


def send_text(phone: str, body: str) -> bool:
    """Send a WhatsApp text message. Returns False in dev mode (no credentials)."""
    if not is_configured():
        log.info("WhatsApp dev mode — would send to %s: %s", phone, body)
        return False
    response = httpx.post(
        f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages",
        headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"preview_url": False, "body": body}},
        timeout=15,
    )
    response.raise_for_status()
    return True
