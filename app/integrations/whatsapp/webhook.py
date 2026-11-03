from fastapi import HTTPException

def verify_webhook(mode: str | None, token: str | None, challenge: str | None, expected_token: str) -> str:
    """Verify Meta's handshake. Message processing calls application services, not models."""
    if mode == "subscribe" and token == expected_token and challenge:
        return challenge
    raise HTTPException(status_code=403, detail="Webhook verification failed")
