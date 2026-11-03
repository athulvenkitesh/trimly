from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import require_shop_owner
from app.api.routes.shops import owned_shop
from app.core.database import get_db
from app.models import Service, User
from app.schemas.service import ServiceCreate, ServiceOut

router = APIRouter(prefix="/shops/{shop_id}/services", tags=["services"])

@router.get("", response_model=list[ServiceOut], summary="List a shop's services")
def list_services(shop_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(Service).where(Service.shop_id == shop_id, Service.is_active)).all()

@router.post("", response_model=ServiceOut, status_code=201, summary="Add a service")
def create_service(shop_id: int, payload: ServiceCreate, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    service = Service(shop_id=shop_id, **payload.model_dump())
    db.add(service); db.commit(); db.refresh(service)
    return service

@router.delete("/{service_id}", status_code=204, summary="Deactivate a service")
def deactivate_service(shop_id: int, service_id: int, user: User = Depends(require_shop_owner), db: Session = Depends(get_db)):
    owned_shop(shop_id, user, db)
    service = db.get(Service, service_id)
    if not service or service.shop_id != shop_id: raise HTTPException(404, "Service not found")
    service.is_active = False; db.commit()
