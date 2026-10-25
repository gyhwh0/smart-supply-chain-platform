from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


bearer = HTTPBearer(auto_error=False)

ALL_PERMISSIONS = {
    "dashboard",
    "account_management",
    "supplier_management",
    "category_management",
    "product_management",
    "assignment_management",
    "quote_management",
    "analysis",
    "inventory",
    "inventory_update",
    "order_management",
    "staff_management",
    "customer_management",
    "sales_order_management",
    "sales_summary",
    "wecom_management",
    "complaint_management",
    "inbound_management",
    "label_printing",
    "picking_management",
    "picking_monitor",
    "finance_management",
}
ROLE_PERMISSIONS = {
    # 财务数据属于敏感权限，所有角色（包括管理员）默认都不启用。
    "admin": ALL_PERMISSIONS - {"finance_management"},
    "purchaser": {
        "dashboard", "account_management", "supplier_management", "category_management",
        "product_management", "assignment_management", "analysis", "inventory", "inventory_update",
        "order_management", "staff_management", "customer_management",
        "sales_order_management", "sales_summary", "wecom_management",
        "complaint_management",
        "inbound_management", "label_printing", "picking_management", "picking_monitor",
    },
    "warehouse": {"dashboard", "inventory", "inventory_update", "staff_management", "customer_management", "inbound_management", "label_printing", "picking_management", "picking_monitor"},
    "supplier": {"dashboard", "product_management", "quote_management", "inventory"},
    "order_clerk": {
        "dashboard", "sales_order_management", "sales_summary",
        "wecom_management", "complaint_management",
        "label_printing", "picking_management", "picking_monitor",
    },
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.JWT_SECRET_KEY, algorithm="HS256")


def effective_permissions(user: User) -> set[str]:
    if user.permissions_csv is not None:
        return set(user.permissions)
    return set(ROLE_PERMISSIONS.get(user.role, set()))


def require_permission(permission: str):
    def checker(user: User = Depends(current_user)) -> User:
        if permission not in effective_permissions(user):
            raise HTTPException(status_code=403, detail="当前账号没有此功能权限")
        return user
    return checker


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        user = db.get(User, int(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="用户不可用")
    return user


def require_purchaser(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "purchaser"}:
        raise HTTPException(status_code=403, detail="仅采购员可执行此操作")
    return user


def require_supplier(user: User = Depends(current_user)) -> User:
    if user.role != "supplier" or not user.supplier_id:
        raise HTTPException(status_code=403, detail="仅供应商可执行此操作")
    return user
