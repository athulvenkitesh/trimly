import secrets

class BookingCodeService:
    def new_code(self) -> str:
        return secrets.token_urlsafe(6).upper()
