import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import picking_service, sales_order_service
from app.config import settings
from app.database import get_db
from app.models import (
    Customer,
    MiniProgramOrder,
    MiniProgramUser,
    Product,
    ProductUnit,
    SalesOrder,
    SalesOrderItem,
    User,
)


router = APIRouter(prefix="/api/mini", tags=["mini-program"])
mini_bearer = HTTPBearer(auto_error=False)


class LoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    nickname: str | None = Field(default=None, max_length=80)


class BindIn(BaseModel):
    customer_code: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=4, max_length=30)


class MiniOrderItemIn(BaseModel):
    product_id: int
    unit_id: int
    quantity: Decimal = Field(gt=0, le=1000000)
    remark: str | None = Field(default=None, max_length=255)


class MiniOrderIn(BaseModel):
    external_order_no: str = Field(min_length=8, max_length=100)
    delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)
    items: list[MiniOrderItemIn] = Field(min_length=1, max_length=200)


def _token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode(
        {"sub": str(user_id), "purpose": "mini_program", "exp": expires},
        settings.JWT_SECRET_KEY,
        algorithm="HS256",
    )


def _current_mini_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(mini_bearer),
    db: Session = Depends(get_db),
) -> MiniProgramUser:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录小程序")
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        if payload.get("purpose") != "mini_program":
            raise ValueError("wrong token purpose")
        user = db.get(MiniProgramUser, int(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="小程序登录已失效，请重新进入") from exc
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="当前小程序账号不可用")
    return user


def _bound_customer(user: MiniProgramUser, db: Session) -> Customer:
    customer = db.get(Customer, user.customer_id) if user.customer_id else None
    if not customer or not customer.active:
        raise HTTPException(status_code=403, detail="请先绑定有效客户档案")
    return customer


def _profile(user: MiniProgramUser, db: Session) -> dict:
    customer = db.get(Customer, user.customer_id) if user.customer_id else None
    return {
        "bound": bool(customer and customer.active),
        "nickname": user.nickname,
        "customer": None if not customer else {
            "id": customer.id,
            "name": customer.name,
            "customer_code": customer.customer_code,
            "contact_name": customer.contact_name,
            "phone": customer.phone,
        },
    }


def _customer_product_name(product: Product, customer_id: int) -> str:
    for row in product.customer_aliases:
        if row.get("customer_id") == customer_id and str(row.get("alias") or "").strip():
            return str(row["alias"]).strip()
    return product.name


def _sales_price(product: Product, unit: ProductUnit) -> Decimal | None:
    if unit.sales_price is not None:
        return Decimal(unit.sales_price)
    if product.reference_price is not None:
        return Decimal(product.reference_price) * Decimal(unit.conversion_rate)
    return None


def _system_creator(customer: Customer, db: Session) -> User:
    if customer.order_clerk_id:
        clerk = db.get(User, customer.order_clerk_id)
        if clerk and clerk.active:
            return clerk
    creator = db.scalar(
        select(User)
        .where(User.active.is_(True))
        .order_by((User.role == "admin").desc(), User.id.asc())
    )
    if not creator:
        raise HTTPException(status_code=503, detail="系统尚未配置可用的订单员")
    return creator


@router.post("/login")
def mini_login(data: LoginIn, db: Session = Depends(get_db)):
    if not settings.MINI_PROGRAM_APP_ID or not settings.MINI_PROGRAM_APP_SECRET:
        raise HTTPException(status_code=503, detail="服务器尚未配置微信小程序 AppID 和 AppSecret")
    query = urlencode({
        "appid": settings.MINI_PROGRAM_APP_ID,
        "secret": settings.MINI_PROGRAM_APP_SECRET,
        "js_code": data.code,
        "grant_type": "authorization_code",
    })
    try:
        with urlopen(f"https://api.weixin.qq.com/sns/jscode2session?{query}", timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="连接微信登录服务失败，请稍后重试") from exc
    openid = result.get("openid")
    if not openid:
        raise HTTPException(status_code=400, detail=f"微信登录失败：{result.get('errmsg') or '无效登录凭证'}")
    user = db.scalar(select(MiniProgramUser).where(MiniProgramUser.openid == openid))
    if not user:
        user = MiniProgramUser(openid=openid, unionid=result.get("unionid"), nickname=data.nickname)
        db.add(user)
    else:
        user.unionid = result.get("unionid") or user.unionid
        user.nickname = data.nickname or user.nickname
    user.last_login_at = datetime.now()
    db.commit()
    return {"token": _token(user.id), **_profile(user, db)}


@router.get("/profile")
def mini_profile(user: MiniProgramUser = Depends(_current_mini_user), db: Session = Depends(get_db)):
    return _profile(user, db)


@router.post("/bind")
def bind_customer(
    data: BindIn,
    user: MiniProgramUser = Depends(_current_mini_user),
    db: Session = Depends(get_db),
):
    customer = db.scalar(
        select(Customer).where(
            Customer.customer_code == data.customer_code.strip(),
            Customer.active.is_(True),
        )
    )
    if not customer or not customer.phone:
        raise HTTPException(status_code=400, detail="客户编号不存在，或后台尚未填写预留手机号")
    normalize = lambda value: "".join(character for character in (value or "") if character.isdigit())
    if normalize(customer.phone) != normalize(data.phone):
        raise HTTPException(status_code=400, detail="客户编号与预留手机号不匹配")
    occupied = db.scalar(
        select(MiniProgramUser).where(
            MiniProgramUser.customer_id == customer.id,
            MiniProgramUser.id != user.id,
            MiniProgramUser.active.is_(True),
        )
    )
    if occupied:
        raise HTTPException(status_code=409, detail="该客户已绑定其他微信，请联系订单员处理")
    user.customer_id = customer.id
    db.commit()
    return _profile(user, db)


@router.get("/products")
def mini_products(
    keyword: str | None = None,
    category: str | None = None,
    user: MiniProgramUser = Depends(_current_mini_user),
    db: Session = Depends(get_db),
):
    customer = _bound_customer(user, db)
    statement = (
        select(Product)
        .options(selectinload(Product.units))
        .where(Product.active.is_(True), Product.mini_visible.is_(True))
        .order_by(Product.category, Product.name)
    )
    products = db.scalars(statement).all()
    query = (keyword or "").strip().lower()
    output = []
    for product in products:
        display_name = _customer_product_name(product, customer.id)
        if category and product.category != category:
            continue
        searchable = " ".join([product.name, display_name, product.sku or "", *product.aliases]).lower()
        if query and query not in searchable:
            continue
        units = []
        for unit in product.units:
            price = _sales_price(product, unit)
            units.append({
                "id": unit.id,
                "name": unit.name,
                "conversion_rate": float(unit.conversion_rate),
                "price": float(price) if price is not None else None,
                "available": price is not None,
            })
        output.append({
            "id": product.id,
            "name": display_name,
            "standard_name": product.name,
            "category": product.category,
            "sku": product.sku,
            "description": product.description,
            "image_url": product.image_url,
            "shelf_life_days": product.shelf_life_days,
            "storage_notes": product.storage_notes,
            "units": units,
        })
    return {"categories": sorted({row["category"] for row in output}), "products": output}


@router.post("/orders")
def submit_mini_order(
    data: MiniOrderIn,
    user: MiniProgramUser = Depends(_current_mini_user),
    db: Session = Depends(get_db),
):
    customer = _bound_customer(user, db)
    existing_link = db.scalar(
        select(MiniProgramOrder)
        .options(selectinload(MiniProgramOrder.sales_order))
        .where(MiniProgramOrder.external_order_no == data.external_order_no.strip())
    )
    if existing_link:
        if existing_link.mini_user_id != user.id:
            raise HTTPException(status_code=409, detail="订单请求编号已被使用")
        return {
            "id": existing_link.sales_order.id,
            "order_no": existing_link.sales_order.order_no,
            "status": existing_link.sales_order.status,
            "merged": True,
            "idempotent": True,
        }
    if data.delivery_date and data.delivery_date < date.today():
        raise HTTPException(status_code=400, detail="配送日期不能早于今天")
    product_ids = [row.product_id for row in data.items]
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=400, detail="购物车中请合并相同商品")
    resolved = []
    for incoming in data.items:
        product = db.scalar(
            select(Product).options(selectinload(Product.units)).where(Product.id == incoming.product_id)
        )
        unit = db.get(ProductUnit, incoming.unit_id)
        if not product or not product.active or not product.mini_visible or not unit or unit.product_id != product.id:
            raise HTTPException(status_code=400, detail="订单包含已下架商品或无效单位，请刷新商品列表")
        price = _sales_price(product, unit)
        if price is None:
            raise HTTPException(status_code=400, detail=f"{product.name}（{unit.name}）尚未设置销售价")
        resolved.append((incoming, product, unit, price))
    order_date = date.today()
    order = sales_order_service.find_daily_order(
        db,
        customer_id=customer.id,
        order_date=order_date,
        delivery_date=data.delivery_date,
    )
    merged = order is not None
    if not order:
        order = SalesOrder(
            order_no=f"SO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
            customer_id=customer.id,
            created_by=_system_creator(customer, db).id,
            order_date=order_date,
            delivery_date=data.delivery_date,
            title="小程序销售订单",
            notes=(data.notes or "").strip() or None,
            status="draft",
            source="miniprogram",
        )
        db.add(order)
        db.flush()
    summary = []
    for incoming, product, unit, price in resolved:
        sales_order_service.add_or_merge_item(
            db,
            order,
            product=product,
            unit=unit,
            display_name=_customer_product_name(product, customer.id),
            specification=None,
            quantity=incoming.quantity,
            unit_price=price,
            remark=incoming.remark,
        )
        summary.append(f"{_customer_product_name(product, customer.id)} {incoming.quantity:g}{unit.name}")
    if merged:
        note = "、".join(summary)
        if data.notes:
            note += f"；{data.notes.strip()}"
        sales_order_service.append_note(order, note, "小程序加单")
    db.flush()
    if merged:
        picking_service.sync_picking_task(db, order)
    db.add(MiniProgramOrder(
        mini_user_id=user.id,
        sales_order_id=order.id,
        external_order_no=data.external_order_no.strip(),
    ))
    db.commit()
    return {"id": order.id, "order_no": order.order_no, "status": order.status, "merged": merged, "idempotent": False}


@router.get("/orders")
def mini_orders(user: MiniProgramUser = Depends(_current_mini_user), db: Session = Depends(get_db)):
    _bound_customer(user, db)
    links = db.scalars(
        select(MiniProgramOrder)
        .options(
            selectinload(MiniProgramOrder.sales_order).selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
            selectinload(MiniProgramOrder.sales_order).selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
        )
        .where(MiniProgramOrder.mini_user_id == user.id)
        .order_by(MiniProgramOrder.id.desc())
    ).all()
    seen = set()
    output = []
    for link in links:
        order = link.sales_order
        if order.id in seen:
            continue
        seen.add(order.id)
        items = [{
            "name": row.display_name or row.product.name,
            "unit_name": row.unit.name,
            "quantity": float(row.quantity),
            "unit_price": float(row.unit_price),
            "amount": round(float(row.quantity * row.unit_price), 2),
        } for row in order.items]
        output.append({
            "id": order.id,
            "order_no": order.order_no,
            "order_date": order.order_date,
            "delivery_date": order.delivery_date,
            "status": order.status,
            "items": items,
            "total_amount": round(sum(row["amount"] for row in items), 2),
            "created_at": order.created_at,
        })
    return output
