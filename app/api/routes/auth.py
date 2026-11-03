from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["authentication"])

def tokens_for(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_token(str(user.id), user.role.value, "access", timedelta(minutes=settings.jwt_access_token_expire_minutes)),
                         refresh_token=create_token(str(user.id), user.role.value, "refresh", timedelta(days=settings.jwt_refresh_token_expire_days)))

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, summary="Register a user")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(409, "Email is already registered")
    user = User(email=str(payload.email), password_hash=hash_password(payload.password), role=payload.role)
    db.add(user); db.commit(); db.refresh(user)
    return tokens_for(user)

@router.post("/login", response_model=TokenResponse, summary="Log in")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return tokens_for(user)

@router.post("/refresh", response_model=TokenResponse, summary="Refresh an access token")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        data = decode_token(payload.refresh_token)
        if data.get("type") != "refresh": raise ValueError()
        user = db.get(User, int(data["sub"]))
    except Exception as exc:
        raise HTTPException(401, "Invalid refresh token") from exc
    if not user: raise HTTPException(401, "Invalid refresh token")
    return tokens_for(user)

@router.get("/me", summary="Get the authenticated user")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "role": user.role}

@router.put("/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change the current user's password")
def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password is incorrect")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a password that differs from your current password")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
