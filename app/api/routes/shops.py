from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user, require_shop_owner
from app.core.database import get_db
from app.models import Shop, User
from app.schemas.shop import ShopCreate, ShopOut

router = APIRouter(prefix="/shops", tags=["shops"])

@router.get("", response_model=list[ShopOut], summary="List active shops")
def list_shops(db: Session = Depends(get_db)):
    return db.scalars(select(Shop).where(Shop.is_active)).all()

@router.get("/{shop_id}", response_model=ShopOut, summary="Get a shop")
def get_shop(shop_id: int, db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    if not shop: raise HTTPException(404, "Shop not found")
    return shop

@router.post("", response_model=ShopOut, status_code=201, summary="Create a shop")
def create_shop(payload: ShopCreate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    shop = Shop(owner_id=user.id, **payload.model_dump())
    db.add(shop); db.commit(); db.refresh(shop)
    return shop

def owned_shop(shop_id: int, user: User, db: Session) -> Shop:
    shop = db.get(Shop, shop_id)
    if not shop: raise HTTPException(404, "Shop not found")
    if shop.owner_id != user.id: raise HTTPException(403, "You do not own this shop")
    return shop
