from typing import List, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user import User
from app.core.security import decode_access_token
from app.models.enums import UserRoleEnum

# auto_error=False so missing tokens yield None instead of a default 403
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that extracts the Bearer token, decodes the sub
    claim (canonical user id), and fetches the active User from the database.

    Raises 401 Unauthorized if the token is missing, invalid, expired,
    or the user account is disabled/missing.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing sub claim",
            )
        user_id = int(user_id_str)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )
    return user


def require_roles(allowed_roles: List[UserRoleEnum]):
    """Dependency factory that restricts access to users whose role
    is in the allowed_roles list.

    Normalizes enum objects to their string values before comparison
    so SQLAlchemy enum columns and Python enums both work correctly.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))])
    """
    def _role_checker(current_user: User = Depends(get_current_user)) -> User:
        current_role = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else current_user.role
        )
        allowed = [
            r.value if hasattr(r, "value") else r
            for r in allowed_roles
        ]
        if current_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return _role_checker

