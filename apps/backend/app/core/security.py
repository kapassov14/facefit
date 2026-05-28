from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AdminRole, AdminUser
from app.db.session import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)
    payload = {"sub": subject, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_admin(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить авторизацию",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        email = payload.get("sub")
        if not email:
            raise credentials_error
    except JWTError as exc:
        raise credentials_error from exc
    admin = db.query(AdminUser).filter(AdminUser.email == email, AdminUser.is_active.is_(True)).first()
    if not admin:
        raise credentials_error
    return admin


AdminAuth = Annotated[AdminUser, Depends(get_current_admin)]


ROLE_LEVELS = {
    AdminRole.VIEWER: 0,
    AdminRole.MANAGER: 1,
    AdminRole.ADMIN: 2,
    AdminRole.OWNER: 3,
}


def role_level(role: str | None) -> int:
    return ROLE_LEVELS.get(role or "", -1)


def require_roles(admin: AdminUser, *roles: str) -> None:
    if admin.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


def require_min_role(admin: AdminUser, min_role: str) -> None:
    if role_level(admin.role) < role_level(min_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


def require_write_access(admin: AdminUser) -> None:
    require_min_role(admin, AdminRole.MANAGER)


def require_admin_access(admin: AdminUser) -> None:
    require_min_role(admin, AdminRole.ADMIN)


def require_owner(admin: AdminUser) -> None:
    require_roles(admin, AdminRole.OWNER)
