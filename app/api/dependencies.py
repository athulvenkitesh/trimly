from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token
from app.models import User, UserRole

bearer = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        user = db.get(User, int(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials") from exc
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def require_role(role: UserRole):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency

require_customer = require_role(UserRole.CUSTOMER)
require_shop_owner = require_role(UserRole.SHOP_OWNER)
require_admin = require_role(UserRole.ADMIN)
