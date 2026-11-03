import hashlib
import hmac


def verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 check used by WhatsApp and payment webhooks."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
