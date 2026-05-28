from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import AdminCreate, AdminPatch, AdminResetPassword
from app.api.serializers import admin_dict
from app.core.exceptions import not_found
from app.core.security import AdminAuth, hash_password, require_admin_access, require_owner
from app.db.models import AdminRole, AdminUser, ClientStatus, Lead
from app.db.session import get_db

router = APIRouter(prefix="/api/admins", tags=["admins"])
manager_router = APIRouter(prefix="/api/admin/managers", tags=["admin-managers"])


VALID_ROLES = {AdminRole.OWNER, AdminRole.ADMIN, AdminRole.MANAGER, AdminRole.VIEWER}


def _manager_dict(db: Session, admin: AdminUser) -> dict:
    data = admin_dict(admin)
    active_statuses = [
        ClientStatus.NEW,
        ClientStatus.PHOTO_SENT,
        ClientStatus.PROTOCOL_SENT,
        ClientStatus.REPORT_OPENED,
        ClientStatus.CTA_CLICKED,
        ClientStatus.MANUAL_CONTACT,
        ClientStatus.IN_DIALOG,
        ClientStatus.THINKING,
    ]
    data["active_leads"] = (
        db.query(Lead)
        .filter(Lead.assigned_manager_id == admin.id, Lead.crm_status.in_(active_statuses))
        .count()
    )
    data["processed_leads"] = (
        db.query(Lead)
        .filter(Lead.assigned_manager_id == admin.id, Lead.crm_status.in_([ClientStatus.PAID, ClientStatus.NOT_RELEVANT, ClientStatus.ARCHIVED]))
        .count()
    )
    data["total_assigned_leads"] = db.query(Lead).filter(Lead.assigned_manager_id == admin.id).count()
    return data


def _create_manager(payload: AdminCreate, db: Session) -> AdminUser:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неизвестная роль")
    existing = db.query(AdminUser).filter(func.lower(AdminUser.email) == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Менеджер с таким email уже существует")
    item = AdminUser(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
        can_broadcast=payload.can_broadcast,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _patch_manager(item: AdminUser, payload: AdminPatch) -> None:
    data = payload.model_dump(exclude_unset=True)
    if data.get("password"):
        item.password_hash = hash_password(data["password"])
    if data.get("role") is not None:
        if data["role"] not in VALID_ROLES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неизвестная роль")
        item.role = data["role"]
    if data.get("is_active") is not None:
        item.is_active = data["is_active"]
    if data.get("name") is not None:
        item.name = data["name"]
    if data.get("can_broadcast") is not None:
        item.can_broadcast = data["can_broadcast"]


@router.get("")
def list_admins(admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    items = db.query(AdminUser).order_by(AdminUser.created_at.desc()).all()
    return {"items": [_manager_dict(db, item) for item in items]}


@router.post("")
def create_admin(payload: AdminCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    return _manager_dict(db, _create_manager(payload, db))


@router.patch("/{admin_id}")
def patch_admin(admin_id: int, payload: AdminPatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    item = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not item:
        raise not_found("Администратор не найден")
    _patch_manager(item, payload)
    db.commit()
    db.refresh(item)
    return _manager_dict(db, item)


@manager_router.get("")
def list_managers(admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_admin_access(admin)
    items = db.query(AdminUser).order_by(AdminUser.is_active.desc(), AdminUser.created_at.desc()).all()
    return {"items": [_manager_dict(db, item) for item in items]}


@manager_router.post("")
def create_manager(payload: AdminCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    return _manager_dict(db, _create_manager(payload, db))


@manager_router.patch("/{manager_id}")
def patch_manager(manager_id: int, payload: AdminPatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    item = db.query(AdminUser).filter(AdminUser.id == manager_id).first()
    if not item:
        raise not_found("Менеджер не найден")
    _patch_manager(item, payload)
    db.commit()
    db.refresh(item)
    return _manager_dict(db, item)


@manager_router.delete("/{manager_id}")
def delete_manager(manager_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    item = db.query(AdminUser).filter(AdminUser.id == manager_id).first()
    if not item:
        raise not_found("Менеджер не найден")
    if item.id == admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Нельзя отключить самого себя")
    item.is_active = False
    db.commit()
    return {"ok": True}


@manager_router.post("/{manager_id}/reset-password")
def reset_manager_password(manager_id: int, payload: AdminResetPassword, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_owner(admin)
    item = db.query(AdminUser).filter(AdminUser.id == manager_id).first()
    if not item:
        raise not_found("Менеджер не найден")
    item.password_hash = hash_password(payload.password)
    db.commit()
    return {"ok": True}
