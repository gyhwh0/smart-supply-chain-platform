import ast
import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from openai import OpenAI
from sqlalchemy import distinct, func, inspect, select, text
from sqlalchemy.orm import Session, selectinload

from app.auth import (
    ALL_PERMISSIONS,
    create_token,
    current_user,
    effective_permissions,
    hash_password,
    require_permission,
    require_supplier,
    verify_password,
)
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app import finance_router, inventory_service, picking_service, report_service, sales_order_service, sales_report_service, wecom_service
from app.wecom_router import router as wecom_router
from app.inbound_router import router as inbound_router
from app.picking_router import router as picking_router
from app.models import (
    Category, Customer, LogisticsStaff, Product, ProductSupplier, ProductUnit,
    AIAnalysisQueryLog, InventoryQueryLog, PurchaseOrder, PurchaseOrderItem, Quote,
    PickingTask, SalesOrder, SalesOrderItem, SalesProcurementLink, Supplier, User, WeComOrderDraft,
    WeComOrderDraftItem,
)
from app.schemas import (
    AIAnalysisRequest,
    AccountCreate,
    AccountUpdate,
    AssignmentCreate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    CustomerCreate,
    CustomerBatchAssign,
    CustomerOut,
    DefaultAdminPermissionsIn,
    GeneratePurchasesRequest,
    InventoryQueryRequest,
    IdsRequest,
    LoginOut,
    LoginRequest,
    OrderCreate,
    OrderItemIn,
    OrderUpdate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    QuoteBatchUpsert,
    QuoteUpsert,
    SalesOrderCreate,
    SalesOrderUpdate,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
    StaffCreate,
    StaffOut,
    StaffPinIn,
    UnitIn,
    ProductUnitPricesUpdate,
    UnitOut,
    UserOut,
)


app = FastAPI(title="嘉采供应链管理平台", version="1.0.0")
app.include_router(wecom_router)
app.include_router(inbound_router)
app.include_router(picking_router)
app.include_router(finance_router.router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    required_columns = {
        "users": {"permissions": "TEXT NULL"},
        "customers": {
            "customer_code": "VARCHAR(50) NULL",
            "order_clerk_id": "INTEGER NULL",
            "ai_reply_rules": "TEXT NULL",
        },
        "sales_orders": {
            "source": "VARCHAR(30) NOT NULL DEFAULT 'manual'",
            "external_reference": "VARCHAR(100) NULL",
            "supplement_amount": "DECIMAL(12,4) NOT NULL DEFAULT 0",
            "invoice_amount": "DECIMAL(12,4) NOT NULL DEFAULT 0",
            "invoice_date": "DATE NULL",
            "acceptance_status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "accepted_at": "DATETIME NULL",
            "accepted_by": "INTEGER NULL",
        },
        "products": {
            "aliases_json": "TEXT NULL",
            "customer_aliases_json": "TEXT NULL",
            "shelf_life_days": "INTEGER NULL",
            "storage_temperature_min": "DECIMAL(6,2) NULL",
            "storage_temperature_max": "DECIMAL(6,2) NULL",
            "loss_rate": "DECIMAL(6,3) NULL",
            "storage_notes": "VARCHAR(255) NULL",
            "quality_report_name": "VARCHAR(255) NULL",
            "quality_report_path": "VARCHAR(255) NULL",
            "quality_report_content_type": "VARCHAR(100) NULL",
        },
        "sales_order_items": {
            "display_name": "VARCHAR(120) NULL",
            "delivered_quantity": "DECIMAL(12,4) NULL",
            "accepted_quantity": "DECIMAL(12,4) NULL",
            "acceptance_variance_reason": "VARCHAR(255) NULL",
            "cost_unit_price": "DECIMAL(12,4) NULL",
        },
        "product_units": {
            "sales_price": "DECIMAL(12,4) NULL",
            "reference_purchase_price": "DECIMAL(12,4) NULL",
        },
        "wecom_customer_bindings": {
            "wechat_name": "VARCHAR(100) NULL",
            "wechat_remark": "VARCHAR(100) NULL",
            "profile_synced_at": "DATETIME NULL",
        },
        "logistics_staff": {
            "mobile_token": "VARCHAR(64) NULL",
            "work_pin_hash": "VARCHAR(255) NULL",
            "pin_fail_count": "INTEGER NOT NULL DEFAULT 0",
            "pin_locked_until": "DATETIME NULL",
            "mobile_session_version": "INTEGER NOT NULL DEFAULT 1",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, additions in required_columns.items():
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in additions.items():
                if column_name not in columns:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                    )
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == "buyer")):
            db.add(
                User(
                    username="buyer",
                    password_hash=hash_password("buyer123"),
                    name="演示采购员",
                    role="purchaser",
                )
            )
            db.commit()
        if not db.scalar(select(Category.id).limit(1)):
            db.add_all(
                [
                    Category(name="办公用品", description="办公耗材、文具及设备"),
                    Category(name="食品饮料", description="食品、饮品及员工福利物资"),
                    Category(name="日化用品", description="清洁、洗护及日常消耗品"),
                    Category(name="生产物料", description="生产使用的原辅料与零配件"),
                    Category(name="其他", description="暂未归入其他分类的商品"),
                ]
            )
            db.commit()
        # Existing purchaser/admin accounts may have an explicit permission list
        # saved before newer business modules were introduced. Managers who can
        # administer accounts should receive the new management entries once.
        new_manager_permissions = {
            "order_management", "staff_management", "customer_management",
            "sales_order_management", "sales_summary", "wecom_management",
            "complaint_management",
        }
        managers = db.scalars(
            select(User).where(User.role.in_({"admin", "purchaser"}), User.username != "system_admin")
        ).all()
        changed = False
        for manager in managers:
            if manager.permissions_csv is None:
                continue
            current = set(manager.permissions)
            if "account_management" in current and not new_manager_permissions.issubset(current):
                manager.permissions_csv = ",".join(sorted(current | new_manager_permissions))
                changed = True
        if changed:
            db.commit()
        new_order_clerk_permissions = {"wecom_management", "complaint_management"}
        order_clerks = db.scalars(select(User).where(User.role == "order_clerk")).all()
        clerk_changed = False
        for clerk in order_clerks:
            if clerk.permissions_csv is None:
                continue
            current = set(clerk.permissions)
            if "sales_order_management" in current and not new_order_clerk_permissions.issubset(current):
                clerk.permissions_csv = ",".join(sorted(current | new_order_clerk_permissions))
                clerk_changed = True
        if clerk_changed:
            db.commit()
        staff_without_tokens = db.scalars(
            select(LogisticsStaff).where(LogisticsStaff.mobile_token.is_(None))
        ).all()
        for staff in staff_without_tokens:
            staff.mobile_token = uuid4().hex + uuid4().hex
        if staff_without_tokens:
            db.commit()
        duplicate_pairs = db.execute(
            select(ProductSupplier.product_id, ProductSupplier.supplier_id)
            .group_by(ProductSupplier.product_id, ProductSupplier.supplier_id)
            .having(func.count(ProductSupplier.id) > 1)
        ).all()
        for product_id, supplier_id in duplicate_pairs:
            duplicate_rows = db.scalars(
                select(ProductSupplier)
                .options(selectinload(ProductSupplier.quotes))
                .where(
                    ProductSupplier.product_id == product_id,
                    ProductSupplier.supplier_id == supplier_id,
                )
                .order_by(ProductSupplier.active.desc(), ProductSupplier.id)
            ).all()
            keeper = duplicate_rows[0]
            keeper.active = any(row.active for row in duplicate_rows)
            for duplicate in duplicate_rows[1:]:
                for quote in list(duplicate.quotes):
                    existing = db.scalar(
                        select(Quote).where(
                            Quote.assignment_id == keeper.id,
                            Quote.unit_id == quote.unit_id,
                        )
                    )
                    if existing:
                        if quote.updated_at and (not existing.updated_at or quote.updated_at > existing.updated_at):
                            existing.price = quote.price
                            existing.currency = quote.currency
                            existing.remark = quote.remark
                        db.delete(quote)
                    else:
                        quote.assignment_id = keeper.id
                db.delete(duplicate)
        if duplicate_pairs:
            db.commit()
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_product_supplier_pair "
                    "ON product_suppliers(product_id, supplier_id)"
                )
            )
    staff_indexes = inspect(engine).get_indexes("logistics_staff")
    if not any(index.get("unique") and index.get("column_names") == ["mobile_token"] for index in staff_indexes):
        with engine.begin() as connection:
            connection.execute(
                text("CREATE UNIQUE INDEX ux_logistics_staff_mobile_token ON logistics_staff(mobile_token)")
            )


@app.get("/")
def root():
    return {"message": "Procurement comparison API", "docs": "/docs"}


@app.post("/api/auth/login", response_model=LoginOut)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username))
    if not user or not user.active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="账号或密码错误")
    if user.role == "supplier" and (not user.supplier or not user.supplier.active):
        raise HTTPException(status_code=403, detail="供应商已停用，请联系采购员")
    output = UserOut.model_validate(user).model_copy(
        update={"permissions": sorted(effective_permissions(user))}
    )
    return LoginOut(token=create_token(user.id), user=output)


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut.model_validate(user).model_copy(
        update={"permissions": sorted(effective_permissions(user))}
    )


@app.post("/api/auth/default-admin", response_model=LoginOut)
def default_admin_login(db: Session = Depends(get_db)):
    if not settings.SKIP_LOGIN:
        raise HTTPException(status_code=404, detail="临时免登录模式未启用")
    user = db.scalar(select(User).where(User.username == "system_admin"))
    if not user:
        user = User(
            username="system_admin",
            password_hash=hash_password(uuid4().hex),
            name="默认管理员",
            role="admin",
            active=True,
            permissions_csv=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.active or user.role != "admin":
        user.active = True
        user.role = "admin"
        user.permissions_csv = None
        db.commit()
    output = account_output(user)
    return LoginOut(token=create_token(user.id), user=output)


def ensure_admin_role(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以进入超级管理员入口")
    return user


@app.get("/api/super-admin/default-permissions")
def get_default_admin_permissions(
    _: User = Depends(ensure_admin_role), db: Session = Depends(get_db),
):
    account = db.scalar(select(User).where(User.username == "system_admin"))
    if not account:
        raise HTTPException(status_code=404, detail="默认管理员账号不存在")
    return {
        "id": account.id,
        "name": account.name,
        "permissions": sorted(effective_permissions(account)),
        "available_permissions": sorted(ALL_PERMISSIONS),
    }


@app.put("/api/super-admin/default-permissions")
def update_default_admin_permissions(
    data: DefaultAdminPermissionsIn,
    _: User = Depends(ensure_admin_role),
    db: Session = Depends(get_db),
):
    unknown = set(data.permissions) - ALL_PERMISSIONS
    if unknown:
        raise HTTPException(status_code=400, detail=f"包含无效权限：{', '.join(sorted(unknown))}")
    account = db.scalar(select(User).where(User.username == "system_admin"))
    if not account:
        raise HTTPException(status_code=404, detail="默认管理员账号不存在")
    account.permissions_csv = ",".join(sorted(set(data.permissions)))
    db.commit()
    return {"message": "默认管理员权限已保存，刷新页面后生效", "permissions": sorted(effective_permissions(account))}


VALID_ROLES = {"admin", "purchaser", "warehouse", "supplier", "order_clerk"}


def account_output(user: User) -> UserOut:
    return UserOut.model_validate(user).model_copy(
        update={"permissions": sorted(effective_permissions(user))}
    )


def validate_account_data(data: AccountCreate | AccountUpdate, db: Session):
    if data.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="账号角色不正确")
    if data.role == "supplier":
        supplier = db.get(Supplier, data.supplier_id) if data.supplier_id else None
        if not supplier or not supplier.active:
            raise HTTPException(status_code=400, detail="供应商账号必须绑定一个启用中的供应商")
    elif data.supplier_id:
        raise HTTPException(status_code=400, detail="只有供应商账号可以绑定供应商")


@app.get("/api/accounts", response_model=list[UserOut])
def list_accounts(
    _: User = Depends(require_permission("account_management")),
    db: Session = Depends(get_db),
):
    return [account_output(user) for user in db.scalars(select(User).order_by(User.id.desc())).all()]


@app.post("/api/accounts", response_model=UserOut)
def create_account(
    data: AccountCreate,
    _: User = Depends(require_permission("account_management")),
    db: Session = Depends(get_db),
):
    username = data.username.strip()
    if not username or not data.name.strip():
        raise HTTPException(status_code=400, detail="账号和姓名不能为空")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=400, detail="登录账号已存在")
    validate_account_data(data, db)
    account = User(
        username=username,
        password_hash=hash_password(data.password),
        name=data.name.strip(),
        role=data.role,
        supplier_id=data.supplier_id if data.role == "supplier" else None,
        active=data.active,
        permissions_csv=",".join(sorted(set(data.permissions))),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_output(account)


@app.put("/api/accounts/{account_id}", response_model=UserOut)
def update_account(
    account_id: int,
    data: AccountUpdate,
    operator: User = Depends(require_permission("account_management")),
    db: Session = Depends(get_db),
):
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.id == operator.id and not data.active:
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    duplicated = db.scalar(
        select(User).where(User.username == data.username.strip(), User.id != account_id)
    )
    if duplicated:
        raise HTTPException(status_code=400, detail="登录账号已存在")
    validate_account_data(data, db)
    account.username = data.username.strip()
    account.name = data.name.strip()
    account.role = data.role
    account.supplier_id = data.supplier_id if data.role == "supplier" else None
    account.active = data.active
    account.permissions_csv = ",".join(sorted(set(data.permissions)))
    if data.password:
        account.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(account)
    return account_output(account)


def remove_account(account: User, operator: User, db: Session) -> str:
    if account.id == operator.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    has_assignment_history = db.scalar(
        select(ProductSupplier.id).where(ProductSupplier.assigned_by == account.id).limit(1)
    )
    has_order_history = db.scalar(
        select(PurchaseOrder.id).where(PurchaseOrder.created_by == account.id).limit(1)
    )
    has_sales_history = db.scalar(
        select(SalesOrder.id).where(SalesOrder.created_by == account.id).limit(1)
    )
    if has_assignment_history or has_order_history or has_sales_history:
        account.active = False
        return "disabled"
    db.delete(account)
    return "deleted"


@app.delete("/api/accounts/{account_id}")
def delete_account(
    account_id: int,
    operator: User = Depends(require_permission("account_management")),
    db: Session = Depends(get_db),
):
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    mode = remove_account(account, operator, db)
    db.commit()
    return {"message": "账号已删除" if mode == "deleted" else "账号存在业务历史，已安全禁用", "mode": mode}


@app.post("/api/accounts/batch-delete")
def batch_delete_accounts(
    data: IdsRequest,
    operator: User = Depends(require_permission("account_management")),
    db: Session = Depends(get_db),
):
    deleted = disabled = 0
    for account_id in set(data.ids):
        account = db.get(User, account_id)
        if not account:
            continue
        mode = remove_account(account, operator, db)
        deleted += mode == "deleted"
        disabled += mode == "disabled"
    db.commit()
    return {"message": f"批量处理完成：删除 {deleted} 个，安全禁用 {disabled} 个"}


@app.get("/api/suppliers", response_model=list[SupplierOut])
def list_suppliers(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Supplier).order_by(Supplier.id.desc())).all()


@app.post("/api/suppliers", response_model=SupplierOut)
def create_supplier(
    data: SupplierCreate,
    _: User = Depends(require_permission("supplier_management")),
    db: Session = Depends(get_db),
):
    if db.scalar(select(Supplier).where(Supplier.name == data.name)):
        raise HTTPException(status_code=400, detail="供应商名称已存在")
    if data.login_username and db.scalar(select(User).where(User.username == data.login_username)):
        raise HTTPException(status_code=400, detail="登录账号已存在")
    supplier = Supplier(**data.model_dump(exclude={"login_username", "login_password"}))
    db.add(supplier)
    db.flush()
    if data.login_username:
        if not data.login_password:
            raise HTTPException(status_code=400, detail="请填写供应商登录密码")
        db.add(
            User(
                username=data.login_username,
                password_hash=hash_password(data.login_password),
                name=data.contact_name or data.name,
                role="supplier",
                supplier_id=supplier.id,
            )
        )
    db.commit()
    db.refresh(supplier)
    return supplier


@app.put("/api/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    _: User = Depends(require_permission("supplier_management")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="供应商不存在")
    duplicated = db.scalar(
        select(Supplier).where(Supplier.name == data.name.strip(), Supplier.id != supplier_id)
    )
    if duplicated:
        raise HTTPException(status_code=400, detail="供应商名称已存在")
    for key, value in data.model_dump().items():
        setattr(supplier, key, value)
    supplier.name = data.name.strip()
    if not data.active:
        for assignment in supplier.assignments:
            assignment.active = False
    db.commit()
    db.refresh(supplier)
    return supplier


def remove_supplier(supplier: Supplier, db: Session) -> str:
    assignments = db.scalars(
        select(ProductSupplier).where(ProductSupplier.supplier_id == supplier.id)
    ).all()
    has_orders = db.scalar(
        select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == supplier.id).limit(1)
    )
    if assignments or has_orders:
        supplier.active = False
        for assignment in assignments:
            assignment.active = False
        for user in supplier.users:
            user.active = False
        mode = "disabled"
    else:
        for user in list(supplier.users):
            db.delete(user)
        db.delete(supplier)
        mode = "deleted"
    return mode


@app.delete("/api/suppliers/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    _: User = Depends(require_permission("supplier_management")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="供应商不存在")
    mode = remove_supplier(supplier, db)
    db.commit()
    message = "供应商已删除" if mode == "deleted" else "供应商已有历史分配或报价，已安全禁用并保留历史数据"
    return {"message": message, "mode": mode}


@app.post("/api/suppliers/batch-delete")
def batch_delete_suppliers(
    data: IdsRequest,
    _: User = Depends(require_permission("supplier_management")),
    db: Session = Depends(get_db),
):
    deleted = disabled = 0
    for supplier_id in set(data.ids):
        supplier = db.get(Supplier, supplier_id)
        if not supplier:
            continue
        mode = remove_supplier(supplier, db)
        deleted += mode == "deleted"
        disabled += mode == "disabled"
    db.commit()
    return {"message": f"批量处理完成：删除 {deleted} 个，安全禁用 {disabled} 个"}


@app.get("/api/categories", response_model=list[CategoryOut])
def list_categories(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.active.desc(), Category.name)).all()


@app.post("/api/categories", response_model=CategoryOut)
def create_category(
    data: CategoryCreate,
    _: User = Depends(require_permission("category_management")),
    db: Session = Depends(get_db),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名称不能为空")
    if db.scalar(select(Category).where(Category.name == name)):
        raise HTTPException(status_code=400, detail="分类名称已存在")
    category = Category(name=name, description=data.description)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@app.put("/api/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    data: CategoryUpdate,
    _: User = Depends(require_permission("category_management")),
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="分类名称不能为空")
    duplicated = db.scalar(
        select(Category).where(Category.name == data.name.strip(), Category.id != category_id)
    )
    if duplicated:
        raise HTTPException(status_code=400, detail="分类名称已存在")
    old_name = category.name
    category.name = data.name.strip()
    category.description = data.description
    category.active = data.active
    for product in category.products:
        if product.category == old_name:
            product.category = category.name
    db.commit()
    db.refresh(category)
    return category


def remove_category(category: Category, db: Session) -> str:
    if category.products:
        category.active = False
        return "disabled"
    db.delete(category)
    return "deleted"


@app.delete("/api/categories/{category_id}")
def delete_category(
    category_id: int,
    _: User = Depends(require_permission("category_management")),
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    mode = remove_category(category, db)
    db.commit()
    return {"message": "分类已删除" if mode == "deleted" else "分类下已有商品，已禁用并保留关联数据", "mode": mode}


@app.post("/api/categories/batch-delete")
def batch_delete_categories(
    data: IdsRequest,
    _: User = Depends(require_permission("category_management")),
    db: Session = Depends(get_db),
):
    deleted = disabled = 0
    for category_id in set(data.ids):
        category = db.get(Category, category_id)
        if not category:
            continue
        mode = remove_category(category, db)
        deleted += mode == "deleted"
        disabled += mode == "disabled"
    db.commit()
    return {"message": f"批量处理完成：删除 {deleted} 个，安全禁用 {disabled} 个"}


def product_query():
    return select(Product).options(
        selectinload(Product.units), selectinload(Product.assignments)
    ).execution_options(populate_existing=True).order_by(Product.id.desc())


def normalize_product_metadata(data: ProductCreate | ProductUpdate, db: Session, product_id: int | None = None):
    aliases = []
    seen = set()
    product_name = data.name.strip()
    for raw in data.aliases:
        alias = raw.strip()
        key = alias.casefold()
        if alias and key != product_name.casefold() and key not in seen:
            aliases.append(alias)
            seen.add(key)
    if data.storage_temperature_min is not None and data.storage_temperature_max is not None:
        if data.storage_temperature_min > data.storage_temperature_max:
            raise HTTPException(status_code=400, detail="最低储存温度不能高于最高储存温度")
    customer_aliases = []
    customer_ids = set()
    for row in data.customer_aliases:
        alias = row.alias.strip()
        if not alias:
            continue
        customer = db.get(Customer, row.customer_id)
        if not customer or not customer.active:
            raise HTTPException(status_code=400, detail=f"客户 {row.customer_id} 不存在或已停用")
        if row.customer_id in customer_ids:
            raise HTTPException(status_code=400, detail=f"客户“{customer.name}”只能设置一个专属商品名称")
        customer_ids.add(row.customer_id)
        customer_aliases.append({"customer_id": row.customer_id, "alias": alias})
    for other in db.scalars(select(Product).where(Product.id != product_id) if product_id else select(Product)).all():
        occupied = {other.name.casefold(), *(value.casefold() for value in other.aliases)}
        if product_name.casefold() in occupied:
            raise HTTPException(status_code=400, detail=f"商品名称“{product_name}”已被商品“{other.name}”作为名称或别名使用")
        conflict = next((alias for alias in aliases if alias.casefold() in occupied), None)
        if conflict:
            raise HTTPException(status_code=400, detail=f"别名“{conflict}”已被商品“{other.name}”使用")
        global_conflict = next(
            (row for row in customer_aliases if row["alias"].casefold() in occupied),
            None,
        )
        if global_conflict:
            raise HTTPException(status_code=400, detail=f"该客户的别名“{global_conflict['alias']}”已绑定商品“{other.name}”")
        other_customer_aliases = {
            (int(row.get("customer_id")), str(row.get("alias", "")).casefold())
            for row in other.customer_aliases
            if row.get("customer_id") and row.get("alias")
        }
        global_alias_conflict = next(
            (
                alias for alias in aliases
                if any(alias.casefold() == value for _, value in other_customer_aliases)
            ),
            None,
        )
        if global_alias_conflict:
            raise HTTPException(status_code=400, detail=f"别名“{global_alias_conflict}”已被其他商品用作客户专属名称")
        conflict_row = next(
            (
                row for row in customer_aliases
                if (row["customer_id"], row["alias"].casefold()) in other_customer_aliases
            ),
            None,
        )
        if conflict_row:
            raise HTTPException(status_code=400, detail=f"该客户的别名“{conflict_row['alias']}”已绑定其他商品")
    return aliases, customer_aliases


def customer_product_name(product: Product, customer_id: int) -> str:
    row = next(
        (item for item in product.customer_aliases if int(item.get("customer_id", 0)) == customer_id),
        None,
    )
    return str(row.get("alias")) if row else product.name


def sync_product_suppliers(
    product: Product,
    supplier_ids: list[int],
    operator_id: int,
    db: Session,
):
    requested = set(supplier_ids)
    for supplier_id in requested:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or not supplier.active:
            raise HTTPException(status_code=400, detail=f"供应商 {supplier_id} 不存在或已停用")
    existing = {row.supplier_id: row for row in product.assignments}
    for supplier_id, assignment in existing.items():
        assignment.active = supplier_id in requested and product.active
    for supplier_id in requested - existing.keys():
        db.add(
            ProductSupplier(
                product_id=product.id,
                supplier_id=supplier_id,
                assigned_by=operator_id,
                active=product.active,
            )
        )


@app.get("/api/products", response_model=list[ProductOut])
def list_products(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(product_query()).all()


@app.post("/api/products", response_model=ProductOut)
def create_product(
    data: ProductCreate,
    user: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="商品名称不能为空")
    if db.scalar(select(Product).where(Product.name == name)):
        raise HTTPException(status_code=400, detail="商品名称已存在")
    if data.sku and db.scalar(select(Product).where(Product.sku == data.sku.strip())):
        raise HTTPException(status_code=400, detail="SKU 已存在")
    if not data.units:
        raise HTTPException(status_code=400, detail="至少需要一个商品单位")
    if sum(1 for unit in data.units if unit.is_base) != 1:
        raise HTTPException(status_code=400, detail="必须且只能设置一个基础单位")
    aliases, customer_aliases = normalize_product_metadata(data, db)
    values = data.model_dump(exclude={"units", "supplier_ids", "aliases", "customer_aliases"})
    category = db.get(Category, data.category_id)
    if not category or not category.active:
        raise HTTPException(status_code=400, detail="请选择有效商品分类")
    values["name"] = name
    values["sku"] = data.sku.strip() if data.sku else None
    values["category"] = category.name
    values["aliases_json"] = json.dumps(aliases, ensure_ascii=False)
    values["customer_aliases_json"] = json.dumps(customer_aliases, ensure_ascii=False)
    product = Product(**values)
    product.units = [ProductUnit(**unit.model_dump()) for unit in data.units]
    db.add(product)
    db.flush()
    sync_product_suppliers(product, data.supplier_ids, user.id, db)
    wecom_service.rematch_pending_items_for_product(db, product)
    db.commit()
    return db.scalar(product_query().where(Product.id == product.id))


@app.put("/api/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    data: ProductUpdate,
    user: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    duplicate_name = db.scalar(
        select(Product).where(Product.name == data.name.strip(), Product.id != product_id)
    )
    duplicate_sku = data.sku and db.scalar(
        select(Product).where(Product.sku == data.sku.strip(), Product.id != product_id)
    )
    if duplicate_name:
        raise HTTPException(status_code=400, detail="商品名称已存在")
    if duplicate_sku:
        raise HTTPException(status_code=400, detail="SKU 已存在")
    category = db.get(Category, data.category_id)
    if not category or not category.active:
        raise HTTPException(status_code=400, detail="请选择有效商品分类")
    aliases, customer_aliases = normalize_product_metadata(data, db, product_id)
    values = data.model_dump(exclude={"supplier_ids", "aliases", "customer_aliases"})
    values["name"] = data.name.strip()
    values["sku"] = data.sku.strip() if data.sku else None
    values["category"] = category.name
    values["aliases_json"] = json.dumps(aliases, ensure_ascii=False)
    values["customer_aliases_json"] = json.dumps(customer_aliases, ensure_ascii=False)
    for key, value in values.items():
        setattr(product, key, value)
    wecom_service.rematch_pending_items_for_product(db, product)
    if not data.active:
        for assignment in product.assignments:
            assignment.active = False
    else:
        sync_product_suppliers(product, data.supplier_ids, user.id, db)
    db.commit()
    return db.scalar(product_query().where(Product.id == product.id))


QUALITY_REPORT_DIR = Path(__file__).resolve().parent.parent / "uploads" / "quality_reports"
QUALITY_REPORT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


@app.post("/api/products/{product_id}/quality-report")
async def upload_product_quality_report(
    product_id: int,
    file: UploadFile = File(...),
    _: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    content_type = file.content_type or ""
    if content_type not in QUALITY_REPORT_TYPES:
        raise HTTPException(status_code=400, detail="质检报告仅支持 PDF、JPG、PNG 或 WEBP")
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="质检报告不能为空且不能超过10MB")
    suffix = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
    QUALITY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"product-{product_id}-{uuid4().hex}{suffix}"
    target = QUALITY_REPORT_DIR / stored_name
    target.write_bytes(content)
    product.quality_report_name = (file.filename or f"质检报告{suffix}")[:255]
    product.quality_report_path = stored_name
    product.quality_report_content_type = content_type
    db.commit()
    return {"message": "质检报告上传成功", "name": product.quality_report_name, "url": product.quality_report_url}


@app.get("/api/products/{product_id}/quality-report")
def download_product_quality_report(
    product_id: int,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product or not product.quality_report_path:
        raise HTTPException(status_code=404, detail="该商品尚未上传质检报告")
    target = QUALITY_REPORT_DIR / Path(product.quality_report_path).name
    if not target.exists():
        raise HTTPException(status_code=404, detail="质检报告文件不存在")
    return FileResponse(
        target,
        media_type=product.quality_report_content_type or "application/octet-stream",
        filename=product.quality_report_name or target.name,
    )


def remove_product(product: Product, db: Session) -> str:
    assignments = db.scalars(
        select(ProductSupplier).where(ProductSupplier.product_id == product.id)
    ).all()
    has_order_history = db.scalar(
        select(PurchaseOrderItem.id).where(PurchaseOrderItem.product_id == product.id).limit(1)
    ) or db.scalar(
        select(SalesOrderItem.id).where(SalesOrderItem.product_id == product.id).limit(1)
    )
    if assignments or has_order_history:
        product.active = False
        for assignment in assignments:
            assignment.active = False
        mode = "disabled"
    else:
        db.delete(product)
        mode = "deleted"
    return mode


@app.delete("/api/products/{product_id}")
def delete_product(
    product_id: int,
    _: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    mode = remove_product(product, db)
    db.commit()
    message = "商品已删除" if mode == "deleted" else "商品已有历史分配或报价，已安全禁用并保留历史数据"
    return {"message": message, "mode": mode}


@app.post("/api/products/batch-delete")
def batch_delete_products(
    data: IdsRequest,
    _: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    deleted = disabled = 0
    for product_id in set(data.ids):
        product = db.get(Product, product_id)
        if not product:
            continue
        mode = remove_product(product, db)
        deleted += mode == "deleted"
        disabled += mode == "disabled"
    db.commit()
    return {"message": f"批量处理完成：删除 {deleted} 个，安全禁用 {disabled} 个"}


@app.post("/api/products/{product_id}/units", response_model=UnitOut)
def add_unit(
    product_id: int,
    data: UnitIn,
    _: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    if not db.get(Product, product_id):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.is_base:
        raise HTTPException(status_code=400, detail="新增单位不能替换已有基础单位")
    if db.scalar(
        select(ProductUnit).where(
            ProductUnit.product_id == product_id,
            ProductUnit.name == data.name.strip(),
        )
    ):
        raise HTTPException(status_code=400, detail="该商品已存在同名单位")
    unit = ProductUnit(product_id=product_id, **data.model_dump(exclude={"name"}), name=data.name.strip())
    db.add(unit)
    db.flush()
    product = db.get(Product, product_id)
    wecom_service.rematch_pending_items_for_product(db, product)
    db.commit()
    db.refresh(unit)
    return unit


@app.put("/api/products/{product_id}/unit-prices", response_model=list[UnitOut])
def update_unit_prices(
    product_id: int,
    data: ProductUnitPricesUpdate,
    _: User = Depends(require_permission("product_management")),
    db: Session = Depends(get_db),
):
    product = db.scalar(
        select(Product).options(selectinload(Product.units)).where(Product.id == product_id)
    )
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    units = {unit.id: unit for unit in product.units}
    if len(data.units) != len({row.unit_id for row in data.units}):
        raise HTTPException(status_code=400, detail="单位价格中包含重复单位")
    for incoming in data.units:
        unit = units.get(incoming.unit_id)
        if not unit:
            raise HTTPException(status_code=400, detail=f"单位 {incoming.unit_id} 不属于该商品")
        unit.sales_price = incoming.sales_price
        unit.reference_purchase_price = incoming.reference_purchase_price
        if unit.is_base and incoming.sales_price is not None:
            product.reference_price = incoming.sales_price
    wecom_service.rematch_pending_items_for_product(db, product)
    db.commit()
    return db.scalars(
        select(ProductUnit).where(ProductUnit.product_id == product_id).order_by(ProductUnit.id)
    ).all()


def assignment_rows(db: Session, supplier_id: int | None = None):
    query = (
        select(ProductSupplier)
        .options(
            selectinload(ProductSupplier.product).selectinload(Product.units),
            selectinload(ProductSupplier.supplier),
            selectinload(ProductSupplier.quotes).selectinload(Quote.unit),
        )
        .where(ProductSupplier.active.is_(True))
        .order_by(ProductSupplier.id.desc())
    )
    if supplier_id:
        query = query.where(ProductSupplier.supplier_id == supplier_id)
    rows = db.scalars(query).all()
    result = []
    seen_pairs = set()
    for row in rows:
        pair = (row.product_id, row.supplier_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        result.append(
        {
            "id": row.id,
            "product": ProductOut.model_validate(row.product),
            "supplier": SupplierOut.model_validate(row.supplier),
            "quotes": [
                {
                    "id": quote.id,
                    "unit_id": quote.unit_id,
                    "unit_name": quote.unit.name,
                    "price": float(quote.price),
                    "currency": quote.currency,
                    "remark": quote.remark,
                    "updated_at": quote.updated_at,
                }
                for quote in row.quotes
            ],
        }
        )
    return result


@app.get("/api/assignments")
def list_assignments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return assignment_rows(db, user.supplier_id if user.role == "supplier" else None)


@app.post("/api/assignments")
def create_assignments(
    data: AssignmentCreate,
    user: User = Depends(require_permission("assignment_management")),
    db: Session = Depends(get_db),
):
    product_ids = set(data.product_ids)
    if data.category_ids:
        category_products = db.scalars(
            select(Product.id).where(
                Product.category_id.in_(set(data.category_ids)),
                Product.active.is_(True),
            )
        ).all()
        product_ids.update(category_products)
    if not product_ids:
        raise HTTPException(status_code=400, detail="请选择商品或商品分类")
    if not data.supplier_ids:
        raise HTTPException(status_code=400, detail="请选择供应商")
    created = 0
    for product_id in product_ids:
        product = db.get(Product, product_id)
        if not product or not product.active:
            raise HTTPException(status_code=404, detail=f"商品 {product_id} 不存在")
        for supplier_id in set(data.supplier_ids):
            supplier = db.get(Supplier, supplier_id)
            if not supplier or not supplier.active:
                raise HTTPException(status_code=404, detail=f"供应商 {supplier_id} 不存在")
            row = db.scalar(
                select(ProductSupplier).where(
                    ProductSupplier.product_id == product_id,
                    ProductSupplier.supplier_id == supplier_id,
                )
            )
            if row:
                row.active = True
            else:
                db.add(
                    ProductSupplier(
                        product_id=product_id,
                        supplier_id=supplier_id,
                        assigned_by=user.id,
                    )
                )
                created += 1
    db.commit()
    return {"message": "分配完成", "created": created}


@app.put("/api/quotes/{assignment_id}")
def upsert_quote(
    assignment_id: int,
    data: QuoteUpsert,
    user: User = Depends(require_supplier),
    db: Session = Depends(get_db),
):
    save_quote_row(assignment_id, data, user, db)
    db.commit()
    return {"message": "报价已保存"}


def save_quote_row(
    assignment_id: int,
    data: QuoteUpsert,
    user: User,
    db: Session,
):
    assignment = db.get(ProductSupplier, assignment_id)
    if not assignment or assignment.supplier_id != user.supplier_id or not assignment.active:
        raise HTTPException(status_code=404, detail="未找到已分配商品")
    unit = db.get(ProductUnit, data.unit_id)
    if not unit or unit.product_id != assignment.product_id:
        raise HTTPException(status_code=400, detail="报价单位不属于该商品")
    quote = db.scalar(
        select(Quote).where(Quote.assignment_id == assignment_id, Quote.unit_id == data.unit_id)
    )
    if quote:
        for key, value in data.model_dump().items():
            setattr(quote, key, value)
    else:
        quote = Quote(assignment_id=assignment_id, **data.model_dump())
        db.add(quote)


@app.put("/api/quotes/batch/all")
def upsert_quotes_batch(
    data: QuoteBatchUpsert,
    user: User = Depends(require_supplier),
    db: Session = Depends(get_db),
):
    for item in data.quotes:
        save_quote_row(
            item.assignment_id,
            QuoteUpsert(
                unit_id=item.unit_id,
                price=item.price,
                currency=item.currency,
                remark=item.remark,
            ),
            user,
            db,
        )
    db.commit()
    return {"message": f"已一次性保存 {len(data.quotes)} 条报价", "saved": len(data.quotes)}


def build_analysis(db: Session):
    rows = assignment_rows(db)
    comparisons = defaultdict(list)
    for row in rows:
        product = row["product"]
        unit_map = {unit.id: unit for unit in product.units}
        for quote in row["quotes"]:
            unit = unit_map[quote["unit_id"]]
            normalized = Decimal(str(quote["price"])) / unit.conversion_rate
            comparisons[product.id].append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "category": product.category,
                    "supplier_id": row["supplier"].id,
                    "supplier_name": row["supplier"].name,
                    "unit_name": quote["unit_name"],
                    "quoted_price": quote["price"],
                    "base_unit_price": round(float(normalized), 4),
                    "currency": quote["currency"],
                }
            )
    products = []
    wins = defaultdict(lambda: defaultdict(int))
    for product_quotes in comparisons.values():
        product_quotes.sort(key=lambda item: item["base_unit_price"])
        lowest = product_quotes[0]
        wins[lowest["supplier_name"]][lowest["category"]] += 1
        products.append({"lowest": lowest, "quotes": product_quotes})
    advantages = [
        {
            "supplier_name": supplier,
            "categories": [
                {"category": category, "winning_products": count}
                for category, count in sorted(categories.items(), key=lambda item: -item[1])
            ],
        }
        for supplier, categories in wins.items()
    ]
    return {"products": products, "supplier_advantages": advantages}


@app.get("/api/analysis")
def analysis(_: User = Depends(require_permission("analysis")), db: Session = Depends(get_db)):
    return build_analysis(db)


@app.post("/api/analysis/ai")
def ai_analysis(
    data: AIAnalysisRequest,
    user: User = Depends(require_permission("analysis")),
    db: Session = Depends(get_db),
):
    log = AIAnalysisQueryLog(
        user_id=user.id,
        username=user.username,
        user_name=user.name,
        question=data.question.strip(),
        model_name=settings.LLM_MODEL,
        status="pending",
    )
    db.add(log)
    db.commit()
    try:
        summary = build_analysis(db)
        if not summary["products"]:
            log.status = "rejected"
            db.commit()
            raise HTTPException(status_code=400, detail="暂无有效报价，无法分析")
        if not settings.LLM_API_KEY:
            log.status = "fallback"
            db.commit()
            return {
                "content": "尚未配置大模型 API Key。系统已完成确定性最低价计算，请查看下方比价表。",
                "mode": "fallback",
            }
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是采购分析助手。必须依据给定报价数据分析，不得编造；指出各供应商优势品类、价差与采购建议。",
                },
                {
                    "role": "user",
                    "content": f"问题：{data.question}\n报价分析数据：{json.dumps(summary, ensure_ascii=False)}",
                },
            ],
        )
        log.status = "success"
        db.commit()
        return {"content": response.choices[0].message.content, "mode": "llm"}
    except HTTPException:
        raise
    except Exception as exc:
        log.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"大模型分析失败：{exc}") from exc


@app.get("/api/analysis/query-records")
def ai_analysis_query_records(
    admin: str = "",
    keyword: str = "",
    status: str = "all",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if admin != "yes" or user.role != "admin":
        raise HTTPException(status_code=404, detail="页面不存在")
    rows = db.scalars(select(AIAnalysisQueryLog).order_by(AIAnalysisQueryLog.created_at.desc())).all()
    term = keyword.strip().lower()
    records = [
        {
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "username": row.username,
            "user_name": row.user_name,
            "question": row.question,
            "model_name": row.model_name,
            "status": row.status,
        }
        for row in rows
        if (status == "all" or row.status == status)
        and (not term or term in " ".join(filter(None, [row.question, row.username, row.user_name, row.model_name])).lower())
    ]
    return {"total": len(records), "records": records[:1000]}


def best_base_price(product_id: int, db: Session) -> Decimal | None:
    quotes = db.execute(
        select(Quote.price, ProductUnit.conversion_rate)
        .join(ProductSupplier, Quote.assignment_id == ProductSupplier.id)
        .join(ProductUnit, Quote.unit_id == ProductUnit.id)
        .where(
            ProductSupplier.product_id == product_id,
            ProductSupplier.active.is_(True),
        )
    ).all()
    normalized = [price / rate for price, rate in quotes if rate]
    return min(normalized) if normalized else None


@app.get("/api/orders/options")
def order_options(
    supplier_id: int,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier or not supplier.active:
        raise HTTPException(status_code=404, detail="供应商不存在或已停用")
    assignments = db.scalars(
        select(ProductSupplier)
        .options(
            selectinload(ProductSupplier.product).selectinload(Product.units),
            selectinload(ProductSupplier.quotes).selectinload(Quote.unit),
        )
        .where(
            ProductSupplier.supplier_id == supplier_id,
            ProductSupplier.active.is_(True),
        )
    ).all()
    products = []
    for assignment in assignments:
        if not assignment.product.active or not assignment.quotes:
            continue
        best = best_base_price(assignment.product_id, db)
        quote_units = []
        for quote in assignment.quotes:
            normalized = quote.price / quote.unit.conversion_rate
            quote_units.append(
                {
                    "unit_id": quote.unit_id,
                    "unit_name": quote.unit.name,
                    "price": float(quote.price),
                    "base_unit_price": round(float(normalized), 4),
                    "is_best_price": best is not None and normalized == best,
                }
            )
        quote_units.sort(key=lambda item: item["base_unit_price"])
        products.append(
            {
                "product_id": assignment.product.id,
                "name": assignment.product.name,
                "aliases": assignment.product.aliases,
                "sku": assignment.product.sku,
                "category_id": assignment.product.category_id,
                "category": assignment.product.category,
                "quote_units": quote_units,
                "has_best_price": any(item["is_best_price"] for item in quote_units),
            }
        )
    return {"supplier": SupplierOut.model_validate(supplier), "products": products}


def order_query():
    return select(PurchaseOrder).options(
        selectinload(PurchaseOrder.supplier),
        selectinload(PurchaseOrder.creator),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.product),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
    )


def order_output(order: PurchaseOrder):
    items = [
        {
            "id": item.id,
            "product_id": item.product_id,
            "product_name": item.product.name,
            "category": item.product.category,
            "unit_id": item.unit_id,
            "unit_name": item.unit.name,
            "quantity": float(item.quantity),
            "unit_price": float(item.unit_price),
            "amount": round(float(item.quantity * item.unit_price), 2),
            "is_best_price": item.is_best_price,
            "remark": item.remark,
        }
        for item in order.items
    ]
    return {
        "id": order.id,
        "order_no": order.order_no,
        "supplier_id": order.supplier_id,
        "supplier_name": order.supplier.name,
        "title": order.title,
        "expected_date": order.expected_date,
        "notes": order.notes,
        "report_footer": order.report_footer,
        "status": order.status,
        "confirmed_at": order.confirmed_at,
        "created_at": order.created_at,
        "creator_name": order.creator.name,
        "items": items,
        "total_amount": round(sum(item["amount"] for item in items), 2),
    }


def replace_order_items(order: PurchaseOrder, items, db: Session):
    order.items.clear()
    db.flush()
    for incoming in items:
        product = db.get(Product, incoming.product_id)
        unit = db.get(ProductUnit, incoming.unit_id)
        if not product or not product.active or not unit or unit.product_id != product.id:
            raise HTTPException(status_code=400, detail="订单中包含无效商品或单位")
        assignment = db.scalar(
            select(ProductSupplier).where(
                ProductSupplier.product_id == product.id,
                ProductSupplier.supplier_id == order.supplier_id,
                ProductSupplier.active.is_(True),
            )
        )
        if not assignment:
            raise HTTPException(status_code=400, detail=f"{product.name} 未分配给该供应商")
        best = best_base_price(product.id, db)
        normalized = incoming.unit_price / unit.conversion_rate
        order.items.append(
            PurchaseOrderItem(
                product_id=product.id,
                unit_id=unit.id,
                quantity=incoming.quantity,
                unit_price=incoming.unit_price,
                is_best_price=best is not None and normalized <= best,
                remark=incoming.remark,
            )
        )


@app.get("/api/orders")
def list_orders(
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    orders = db.scalars(order_query().order_by(PurchaseOrder.id.desc())).all()
    return [order_output(order) for order in orders]


@app.get("/api/orders/{order_id}")
def get_order(
    order_id: int,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    order = db.scalar(order_query().where(PurchaseOrder.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    return order_output(order)


@app.post("/api/orders")
def create_order(
    data: OrderCreate,
    user: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier or not supplier.active:
        raise HTTPException(status_code=400, detail="请选择有效供应商")
    order = PurchaseOrder(
        order_no=f"PO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
        supplier_id=data.supplier_id,
        created_by=user.id,
        title=data.title.strip() or "采购订单",
        expected_date=data.expected_date,
        notes=data.notes,
        report_footer=data.report_footer,
    )
    db.add(order)
    db.flush()
    replace_order_items(order, data.items, db)
    db.commit()
    saved = db.scalar(order_query().where(PurchaseOrder.id == order.id))
    return order_output(saved)


@app.put("/api/orders/{order_id}")
def update_order(
    order_id: int,
    data: OrderUpdate,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    order = db.scalar(order_query().where(PurchaseOrder.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    order.title = data.title.strip() or "采购订单"
    order.expected_date = data.expected_date
    order.notes = data.notes
    order.report_footer = data.report_footer
    replace_order_items(order, data.items, db)
    db.commit()
    saved = db.scalar(order_query().execution_options(populate_existing=True).where(PurchaseOrder.id == order_id))
    return order_output(saved)


@app.post("/api/orders/{order_id}/confirm")
def confirm_order(
    order_id: int,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    order.status = "confirmed"
    order.confirmed_at = datetime.now()
    db.commit()
    return {"message": "订单已确认，采购报表已生成"}


def report_order(order_id: int, db: Session):
    order = db.scalar(order_query().where(PurchaseOrder.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    if order.status != "confirmed":
        raise HTTPException(status_code=400, detail="请先确认订单再下载报表")
    return order


@app.get("/api/orders/{order_id}/report.xlsx")
def download_order_excel(
    order_id: int,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    order = report_order(order_id, db)
    return StreamingResponse(
        report_service.build_excel(order),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{order.order_no}.xlsx"'},
    )


@app.get("/api/orders/{order_id}/report.png")
def download_order_image(
    order_id: int,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    order = report_order(order_id, db)
    return StreamingResponse(
        report_service.build_image(order),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{order.order_no}.png"'},
    )


def sales_order_query():
    return select(SalesOrder).options(
        selectinload(SalesOrder.customer),
        selectinload(SalesOrder.creator),
        selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
        selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
        selectinload(SalesOrder.procurement_links)
        .selectinload(SalesProcurementLink.purchase_order)
        .selectinload(PurchaseOrder.supplier),
        selectinload(SalesOrder.procurement_links)
        .selectinload(SalesProcurementLink.purchase_order)
        .selectinload(PurchaseOrder.items),
    )


def sales_order_output(order: SalesOrder):
    items = [
        {
            "id": item.id,
            "product_id": item.product_id,
            "product_name": item.display_name or customer_product_name(item.product, order.customer_id),
            "canonical_product_name": item.product.name,
            "category": item.product.category,
            "unit_id": item.unit_id,
            "unit_name": item.unit.name,
            "specification": item.specification,
            "quantity": float(item.quantity),
            "unit_price": float(item.unit_price),
            "amount": round(float(item.quantity * item.unit_price), 2),
            "remark": item.remark,
        }
        for item in order.items
    ]
    purchases = [
        {
            "id": link.purchase_order.id,
            "order_no": link.purchase_order.order_no,
            "supplier_id": link.purchase_order.supplier_id,
            "supplier_name": link.purchase_order.supplier.name,
            "status": link.purchase_order.status,
            "product_ids": [item.product_id for item in link.purchase_order.items],
        }
        for link in order.procurement_links
    ]
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_id": order.customer_id,
        "customer_name": order.customer.name,
        "creator_name": order.creator.name,
        "order_date": order.order_date,
        "delivery_date": order.delivery_date,
        "title": order.title,
        "notes": order.notes,
        "status": order.status,
        "confirmed_at": order.confirmed_at,
        "procurement_generated_at": order.procurement_generated_at,
        "created_at": order.created_at,
        "items": items,
        "purchases": purchases,
        "total_amount": round(sum(item["amount"] for item in items), 2),
    }


def replace_sales_order_items(order: SalesOrder, items, db: Session):
    product_ids = [incoming.product_id for incoming in items]
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=400, detail="同一销售单中请合并相同商品")
    order.items.clear()
    db.flush()
    for incoming in items:
        product = db.get(Product, incoming.product_id)
        unit = db.get(ProductUnit, incoming.unit_id)
        if not product or not product.active or not unit or unit.product_id != product.id:
            raise HTTPException(status_code=400, detail="销售单中包含无效商品或单位")
        order.items.append(
            SalesOrderItem(
                product_id=product.id,
                unit_id=unit.id,
                display_name=customer_product_name(product, order.customer_id),
                specification=(incoming.specification or "").strip() or None,
                quantity=incoming.quantity,
                unit_price=incoming.unit_price,
                remark=(incoming.remark or "").strip() or None,
            )
        )


@app.get("/api/sales/orders/options")
def sales_order_options(
    _: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    customers = db.scalars(
        select(Customer).where(Customer.active.is_(True)).order_by(Customer.name)
    ).all()
    products = db.scalars(
        select(Product)
        .options(selectinload(Product.units))
        .where(Product.active.is_(True))
        .order_by(Product.category, Product.name)
    ).all()
    return {
        "customers": [
            {"id": row.id, "name": row.name, "contact_name": row.contact_name, "phone": row.phone}
            for row in customers
        ],
        "products": [
            {
                "id": row.id,
                "name": row.name,
                "aliases": row.aliases,
                "customer_aliases": row.customer_aliases,
                "sku": row.sku,
                "category": row.category,
                "reference_price": float(row.reference_price or 0),
                "units": [
                    {
                        "id": unit.id,
                        "name": unit.name,
                        "conversion_rate": float(unit.conversion_rate),
                        "is_base": unit.is_base,
                        "sales_price": float(unit.sales_price) if unit.sales_price is not None else None,
                        "reference_purchase_price": float(unit.reference_purchase_price) if unit.reference_purchase_price is not None else None,
                    }
                    for unit in row.units
                ],
            }
            for row in products
        ],
    }


@app.get("/api/sales/orders")
def list_sales_orders(
    status: str | None = None,
    _: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    statement = sales_order_query().order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
    if status in {"draft", "confirmed"}:
        statement = statement.where(SalesOrder.status == status)
    return [sales_order_output(row) for row in db.scalars(statement).all()]


@app.post("/api/sales/orders")
def create_sales_order(
    data: SalesOrderCreate,
    user: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, data.customer_id)
    if not customer or not customer.active:
        raise HTTPException(status_code=400, detail="请选择有效客户")
    product_ids = [incoming.product_id for incoming in data.items]
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=400, detail="本次加单中请合并相同商品")
    order = sales_order_service.find_daily_order(
        db,
        customer_id=data.customer_id,
        order_date=data.order_date,
        delivery_date=data.delivery_date,
    )
    merged = order is not None
    if not order:
        order = SalesOrder(
            order_no=f"SO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
            customer_id=data.customer_id,
            created_by=user.id,
            order_date=data.order_date,
            delivery_date=data.delivery_date,
            title=data.title.strip() or "销售订单",
            notes=(data.notes or "").strip() or None,
        )
        db.add(order)
        db.flush()
        replace_sales_order_items(order, data.items, db)
    else:
        summary = []
        supplement_amount = Decimal("0")
        for incoming in data.items:
            product = db.get(Product, incoming.product_id)
            unit = db.get(ProductUnit, incoming.unit_id)
            if not product or not product.active or not unit or unit.product_id != product.id:
                raise HTTPException(status_code=400, detail="销售单中包含无效商品或单位")
            sales_order_service.add_or_merge_item(
                db,
                order,
                product=product,
                unit=unit,
                display_name=customer_product_name(product, order.customer_id),
                specification=incoming.specification,
                quantity=incoming.quantity,
                unit_price=incoming.unit_price,
                remark=incoming.remark,
            )
            summary.append(f"{customer_product_name(product, order.customer_id)} {incoming.quantity:g}{unit.name}")
            supplement_amount += incoming.quantity * incoming.unit_price
        order.supplement_amount = Decimal(order.supplement_amount or 0) + supplement_amount
        note = "、".join(summary)
        if data.notes:
            note += f"；{data.notes.strip()}"
        sales_order_service.append_note(order, note, "手工加单")
        db.flush()
        picking_service.sync_picking_task(db, order)
    db.commit()
    saved = db.scalar(sales_order_query().where(SalesOrder.id == order.id))
    output = sales_order_output(saved)
    output["merged_into_existing"] = merged
    output["message"] = (
        f"已合并到当天销售单 {order.order_no}，分拣配送任务已同步"
        if merged else "销售单保存成功"
    )
    return output


@app.put("/api/sales/orders/{order_id}")
def update_sales_order(
    order_id: int,
    data: SalesOrderUpdate,
    _: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    order = db.scalar(sales_order_query().where(SalesOrder.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="销售单不存在")
    if order.status != "draft":
        raise HTTPException(status_code=400, detail="已确认销售单不可修改")
    customer = db.get(Customer, data.customer_id)
    if not customer or not customer.active:
        raise HTTPException(status_code=400, detail="请选择有效客户")
    order.customer_id = data.customer_id
    order.order_date = data.order_date
    order.delivery_date = data.delivery_date
    order.title = data.title.strip() or "销售订单"
    order.notes = (data.notes or "").strip() or None
    replace_sales_order_items(order, data.items, db)
    db.commit()
    saved = db.scalar(
        sales_order_query().execution_options(populate_existing=True).where(SalesOrder.id == order_id)
    )
    return sales_order_output(saved)


@app.post("/api/sales/orders/{order_id}/confirm")
def confirm_sales_order(
    order_id: int,
    _: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="销售单不存在")
    order.status = "confirmed"
    order.confirmed_at = datetime.now()
    db.commit()
    return {"message": "销售单已确认，可转为采购订单"}


@app.delete("/api/sales/orders/{order_id}")
def delete_sales_order(
    order_id: int,
    _: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="销售单不存在")
    if order.status != "draft" or order.procurement_links:
        raise HTTPException(status_code=400, detail="仅可删除尚未确认、未生成采购单的草稿")
    db.delete(order)
    db.commit()
    return {"message": "销售单已删除"}


def best_supplier_quote(product_id: int, db: Session):
    rows = db.execute(
        select(ProductSupplier, Quote, ProductUnit, Supplier)
        .join(Quote, Quote.assignment_id == ProductSupplier.id)
        .join(ProductUnit, ProductUnit.id == Quote.unit_id)
        .join(Supplier, Supplier.id == ProductSupplier.supplier_id)
        .where(
            ProductSupplier.product_id == product_id,
            ProductSupplier.active.is_(True),
            Supplier.active.is_(True),
        )
    ).all()
    if not rows:
        return None
    return min(rows, key=lambda row: row[1].price / row[2].conversion_rate)


def supplier_quote_options(product_id: int, db: Session):
    rows = db.execute(
        select(ProductSupplier, Quote, ProductUnit, Supplier)
        .join(Quote, Quote.assignment_id == ProductSupplier.id)
        .join(ProductUnit, ProductUnit.id == Quote.unit_id)
        .join(Supplier, Supplier.id == ProductSupplier.supplier_id)
        .where(
            ProductSupplier.product_id == product_id,
            ProductSupplier.active.is_(True),
            Supplier.active.is_(True),
        )
    ).all()
    best_by_supplier = {}
    for assignment, quote, unit, supplier in rows:
        normalized = quote.price / unit.conversion_rate
        current = best_by_supplier.get(supplier.id)
        if current is None or normalized < current[4]:
            best_by_supplier[supplier.id] = (assignment, quote, unit, supplier, normalized)
    return sorted(best_by_supplier.values(), key=lambda row: row[4])


@app.get("/api/sales/orders/{order_id}/procurement-options")
def sales_procurement_options(
    order_id: int,
    _: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    order = db.scalar(sales_order_query().where(SalesOrder.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="销售单不存在")
    if order.status != "confirmed":
        raise HTTPException(status_code=400, detail="请先确认销售单")
    procured_product_ids = {
        item.product_id
        for link in order.procurement_links
        for item in link.purchase_order.items
    }
    items = []
    for sales_item in order.items:
        options = supplier_quote_options(sales_item.product_id, db)
        items.append(
            {
                "product_id": sales_item.product_id,
                "product_name": sales_item.product.name,
                "category": sales_item.product.category,
                "sales_quantity": float(sales_item.quantity),
                "sales_unit_name": sales_item.unit.name,
                "required_base_quantity": float(sales_item.quantity * sales_item.unit.conversion_rate),
                "already_procured": sales_item.product_id in procured_product_ids,
                "recommended_supplier_id": options[0][3].id if options else None,
                "supplier_options": [
                    {
                        "supplier_id": supplier.id,
                        "supplier_name": supplier.name,
                        "unit_id": unit.id,
                        "unit_name": unit.name,
                        "unit_price": float(quote.price),
                        "base_unit_price": round(float(normalized), 4),
                        "purchase_quantity": round(
                            float(sales_item.quantity * sales_item.unit.conversion_rate / unit.conversion_rate), 4
                        ),
                        "is_recommended": index == 0,
                    }
                    for index, (_, quote, unit, supplier, normalized) in enumerate(options)
                ],
            }
        )
    return {
        "sales_order_id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer.name,
        "items": items,
    }


@app.post("/api/sales/orders/{order_id}/generate-purchases")
def generate_purchases_from_sales(
    order_id: int,
    data: GeneratePurchasesRequest | None = None,
    user: User = Depends(require_permission("order_management")),
    db: Session = Depends(get_db),
):
    sales_order = db.scalar(sales_order_query().where(SalesOrder.id == order_id))
    if not sales_order:
        raise HTTPException(status_code=404, detail="销售单不存在")
    if sales_order.status != "confirmed":
        raise HTTPException(status_code=400, detail="请先确认销售单")
    procured_product_ids = {
        item.product_id
        for link in sales_order.procurement_links
        for item in link.purchase_order.items
    }
    grouped: dict[int, dict] = {}
    unquoted = []
    unassigned = []
    allocation_map = {row.product_id: row.supplier_id for row in (data.allocations if data else [])}
    automatic = data is None or data.automatic
    for sales_item in sales_order.items:
        if sales_item.product_id in procured_product_ids:
            continue
        requested_supplier_id = allocation_map.get(sales_item.product_id)
        if not automatic and not requested_supplier_id:
            if supplier_quote_options(sales_item.product_id, db):
                unassigned.append(sales_item.product.name)
            else:
                unquoted.append(sales_item.product.name)
            continue
        if requested_supplier_id:
            choices = supplier_quote_options(sales_item.product_id, db)
            best = next((row[:4] for row in choices if row[3].id == requested_supplier_id), None)
            if not best:
                raise HTTPException(
                    status_code=400,
                    detail=f"{sales_item.product.name} 在所选供应商处没有有效报价",
                )
        else:
            best = best_supplier_quote(sales_item.product_id, db)
        if not best:
            unquoted.append(sales_item.product.name)
            continue
        assignment, quote, quote_unit, supplier = best
        required_base_quantity = sales_item.quantity * sales_item.unit.conversion_rate
        purchase_quantity = required_base_quantity / quote_unit.conversion_rate
        group = grouped.setdefault(supplier.id, {"supplier": supplier, "items": []})
        group["items"].append(
            OrderItemIn(
                product_id=sales_item.product_id,
                unit_id=quote_unit.id,
                quantity=purchase_quantity,
                unit_price=quote.price,
                remark=f"引用销售单 {sales_order.order_no}"
                + (f"；{sales_item.remark}" if sales_item.remark else ""),
            )
        )
        sales_item.cost_unit_price = quote.price / quote_unit.conversion_rate * sales_item.unit.conversion_rate
    created = []
    for supplier_id, group in grouped.items():
        purchase = PurchaseOrder(
            order_no=f"PO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
            supplier_id=supplier_id,
            created_by=user.id,
            title=f"{sales_order.customer.name} - {sales_order.order_no}",
            expected_date=sales_order.delivery_date,
            notes=f"由销售单 {sales_order.order_no} 一键自动分配生成",
            report_footer="请按销售单需求及时备货并确认交期",
        )
        db.add(purchase)
        db.flush()
        replace_order_items(purchase, group["items"], db)
        db.add(SalesProcurementLink(sales_order_id=sales_order.id, purchase_order_id=purchase.id))
        created.append({"id": purchase.id, "order_no": purchase.order_no, "supplier_name": group["supplier"].name})
    if created:
        sales_order.procurement_generated_at = datetime.now()
    db.commit()
    return {
        "message": f"已按最低报价自动生成 {len(created)} 张采购单",
        "created": created,
        "unquoted_products": unquoted,
        "unassigned_products": unassigned,
        "already_procured_count": len(procured_product_ids),
    }


def filtered_sales_orders(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: int | None = None,
    sorter_id: int | None = None,
    delivery_id: int | None = None,
    creator_id: int | None = None,
):
    statement = sales_order_query().join(Customer, SalesOrder.customer_id == Customer.id).where(
        SalesOrder.status == "confirmed"
    )
    if date_from:
        statement = statement.where(SalesOrder.order_date >= date_from)
    if date_to:
        statement = statement.where(SalesOrder.order_date <= date_to)
    if customer_id:
        statement = statement.where(SalesOrder.customer_id == customer_id)
    if sorter_id:
        statement = statement.where(Customer.sorter_id == sorter_id)
    if delivery_id:
        statement = statement.where(Customer.delivery_id == delivery_id)
    if creator_id:
        statement = statement.where(SalesOrder.created_by == creator_id)
    return db.scalars(statement.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())).unique().all()


def order_supplier_map(order: SalesOrder):
    return {
        item.product_id: {
            "id": link.purchase_order.supplier_id,
            "name": link.purchase_order.supplier.name,
        }
        for link in order.procurement_links
        for item in link.purchase_order.items
    }


def matching_sales_items(
    order: SalesOrder,
    category: str | None = None,
    supplier_id: int | None = None,
):
    suppliers = order_supplier_map(order)
    return [
        (item, suppliers.get(item.product_id))
        for item in order.items
        if (not category or item.product.category == category)
        and (not supplier_id or suppliers.get(item.product_id, {}).get("id") == supplier_id)
    ]


def build_sales_summary(
    db: Session,
    dimension: str,
    date_from: date | None,
    date_to: date | None,
    category: str | None,
    customer_id: int | None,
    supplier_id: int | None = None,
    sorter_id: int | None = None,
    delivery_id: int | None = None,
    creator_id: int | None = None,
):
    if dimension not in {"category", "product", "customer", "supplier", "creator", "sorter", "delivery"}:
        raise HTTPException(status_code=400, detail="不支持的汇总维度")
    orders = filtered_sales_orders(
        db, date_from, date_to, customer_id, sorter_id, delivery_id, creator_id
    )
    buckets = defaultdict(lambda: {"order_ids": set(), "item_count": 0, "quantities": defaultdict(Decimal), "amount": Decimal("0"), "products": {}})
    matched_order_ids = set()
    for order in orders:
        for item, supplier in matching_sales_items(order, category, supplier_id):
            display_name = item.display_name or customer_product_name(item.product, order.customer_id)
            names = {
                "category": item.product.category or "未分类",
                "product": display_name,
                "customer": order.customer.name,
                "supplier": supplier["name"] if supplier else "未生成采购",
                "creator": order.creator.name,
                "sorter": order.customer.sorter.name if order.customer.sorter else "未分配分拣员",
                "delivery": order.customer.delivery.name if order.customer.delivery else "未分配配送员",
            }
            bucket = buckets[names[dimension]]
            bucket["order_ids"].add(order.id)
            bucket["item_count"] += 1
            bucket["quantities"][item.unit.name] += item.quantity
            bucket["amount"] += item.quantity * item.unit_price
            product_bucket = bucket["products"].setdefault(
                display_name,
                {
                    "category": item.product.category,
                    "quantities": defaultdict(Decimal),
                    "customer_quantities": defaultdict(lambda: defaultdict(Decimal)),
                    "amount": Decimal("0"),
                    "order_ids": set(),
                    "item_count": 0,
                },
            )
            product_bucket["quantities"][item.unit.name] += item.quantity
            customer_label = (
                f"{order.customer.customer_code}-{order.customer.name}"
                if order.customer.customer_code
                else order.customer.name
            )
            product_bucket["customer_quantities"][customer_label][item.unit.name] += item.quantity
            product_bucket["amount"] += item.quantity * item.unit_price
            product_bucket["order_ids"].add(order.id)
            product_bucket["item_count"] += 1
            matched_order_ids.add(order.id)
    rows = []
    for name, bucket in buckets.items():
        rows.append(
            {
                "name": name,
                "order_count": len(bucket["order_ids"]),
                "item_count": bucket["item_count"],
                "quantity_display": " / ".join(
                    f"{float(value):g} {unit}" for unit, value in sorted(bucket["quantities"].items())
                ),
                "sales_amount": round(float(bucket["amount"]), 2),
                "product_names": "、".join(bucket["products"].keys()),
                "product_details": sorted(
                    [
                        {
                            "name": product_name,
                            "category": values["category"],
                            "quantity_display": " / ".join(
                                f"{float(quantity):g} {unit}"
                                for unit, quantity in sorted(values["quantities"].items())
                            ),
                            "order_count": len(values["order_ids"]),
                            "item_count": values["item_count"],
                            "order_breakdown": "、".join(
                                f"（{customer_name}）"
                                + " / ".join(
                                    f"{float(quantity):g}{unit}"
                                    for unit, quantity in sorted(customer_quantities.items())
                                )
                                for customer_name, customer_quantities in sorted(
                                    values["customer_quantities"].items()
                                )
                            ),
                            "sales_amount": round(float(values["amount"]), 2),
                        }
                        for product_name, values in bucket["products"].items()
                    ],
                    key=lambda row: row["sales_amount"],
                    reverse=True,
                ),
            }
        )
    rows.sort(key=lambda row: row["sales_amount"], reverse=True)
    return {
        "dimension": dimension,
        "date_from": date_from,
        "date_to": date_to,
        "category": category,
        "customer_id": customer_id,
        "supplier_id": supplier_id,
        "sorter_id": sorter_id,
        "delivery_id": delivery_id,
        "creator_id": creator_id,
        "rows": rows,
        "order_count": len(matched_order_ids),
        "group_count": len(rows),
        "total_amount": round(sum(row["sales_amount"] for row in rows), 2),
    }


@app.get("/api/sales/summary/options")
def sales_summary_options(
    _: User = Depends(require_permission("sales_summary")),
    db: Session = Depends(get_db),
):
    customers = db.scalars(select(Customer).order_by(Customer.name)).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
    staff = db.scalars(select(LogisticsStaff).order_by(LogisticsStaff.name)).all()
    creators = db.scalars(
        select(User).where(User.active.is_(True), User.role.in_({"admin", "purchaser", "order_clerk"})).order_by(User.name)
    ).all()
    categories = db.scalars(select(distinct(Product.category)).order_by(Product.category)).all()
    return {
        "customers": [{"id": row.id, "name": row.name} for row in customers],
        "suppliers": [{"id": row.id, "name": row.name} for row in suppliers],
        "categories": [row for row in categories if row],
        "sorters": [{"id": row.id, "name": row.name} for row in staff if row.staff_type == "sorter"],
        "deliveries": [{"id": row.id, "name": row.name} for row in staff if row.staff_type == "delivery"],
        "creators": [{"id": row.id, "name": row.name, "role": row.role} for row in creators],
    }


@app.get("/api/sales/overview")
def sales_overview(
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    sorter_id: int | None = None,
    delivery_id: int | None = None,
    creator_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    _: User = Depends(require_permission("sales_summary")),
    db: Session = Depends(get_db),
):
    orders = filtered_sales_orders(db, date_from, date_to, customer_id, sorter_id, delivery_id, creator_id)
    groups = {}
    for order in orders:
        items = matching_sales_items(order, category, supplier_id)
        if not items:
            continue
        group = groups.setdefault(
            order.customer_id,
            {
                "customer_id": order.customer_id,
                "customer_name": order.customer.name,
                "contact_name": order.customer.contact_name,
                "phone": order.customer.phone,
                "sorter_name": order.customer.sorter.name if order.customer.sorter else "未分配",
                "delivery_name": order.customer.delivery.name if order.customer.delivery else "未分配",
                "order_ids": set(),
                "creators": set(),
                "sales_amount": Decimal("0"),
                "item_count": 0,
                "first_order_date": order.order_date,
                "last_order_date": order.order_date,
                "last_created_at": order.created_at,
            },
        )
        group["order_ids"].add(order.id)
        group["creators"].add(order.creator.name)
        group["sales_amount"] += sum(item.quantity * item.unit_price for item, _ in items)
        group["item_count"] += len(items)
        group["first_order_date"] = min(group["first_order_date"], order.order_date)
        group["last_order_date"] = max(group["last_order_date"], order.order_date)
        group["last_created_at"] = max(group["last_created_at"], order.created_at)
    rows = [
        {
            **{key: value for key, value in group.items() if key not in {"order_ids", "creators", "sales_amount"}},
            "order_count": len(group["order_ids"]),
            "creator_names": "、".join(sorted(group["creators"])),
            "sales_amount": round(float(group["sales_amount"]), 2),
        }
        for group in groups.values()
    ]
    rows.sort(key=lambda row: row["sales_amount"], reverse=True)
    overall_total_amount = round(sum(row["sales_amount"] for row in rows), 2)
    if keyword and keyword.strip():
        term = keyword.strip().lower()
        rows = [
            row for row in rows
            if term in " ".join(
                filter(None, [row["customer_name"], row["contact_name"], row["phone"], row["creator_names"]])
            ).lower()
        ]
    total_customers = len(rows)
    page = max(page, 1)
    page_size = min(max(page_size, 10), 100)
    paged_rows = rows[(page - 1) * page_size:page * page_size]
    return {
        "rows": paged_rows,
        "customer_count": total_customers,
        "order_count": len({order_id for group in groups.values() for order_id in group["order_ids"]}),
        "total_amount": overall_total_amount,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/sales/customers/{customer_id}/detail")
def sales_customer_detail(
    customer_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    supplier_id: int | None = None,
    creator_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    _: User = Depends(require_permission("sales_summary")),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    orders = filtered_sales_orders(db, date_from, date_to, customer_id, creator_id=creator_id)
    output_orders = []
    for order in orders:
        matched = matching_sales_items(order, category, supplier_id)
        if not matched:
            continue
        items = [
            {
                "product_name": item.display_name or customer_product_name(item.product, order.customer_id),
                "category": item.product.category,
                "specification": item.specification,
                "quantity": float(item.quantity),
                "unit_name": item.unit.name,
                "unit_price": float(item.unit_price),
                "amount": round(float(item.quantity * item.unit_price), 2),
                "supplier_name": supplier["name"] if supplier else "未生成采购",
                "remark": item.remark,
            }
            for item, supplier in matched
        ]
        output_orders.append(
            {
                "id": order.id,
                "order_no": order.order_no,
                "order_date": order.order_date,
                "created_at": order.created_at,
                "creator_name": order.creator.name,
                "delivery_date": order.delivery_date,
                "notes": order.notes,
                "items": items,
                "total_amount": round(sum(item["amount"] for item in items), 2),
            }
        )
    total_orders = len(output_orders)
    total_items = sum(len(order["items"]) for order in output_orders)
    total_amount = round(sum(order["total_amount"] for order in output_orders), 2)
    page = max(page, 1)
    page_size = min(max(page_size, 10), 100)
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "contact_name": customer.contact_name,
            "phone": customer.phone,
            "address": customer.address,
            "sorter_name": customer.sorter.name if customer.sorter else "未分配",
            "delivery_name": customer.delivery.name if customer.delivery else "未分配",
        },
        "orders": output_orders[(page - 1) * page_size:page * page_size],
        "order_count": total_orders,
        "item_count": total_items,
        "total_amount": total_amount,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/sales/summary")
def sales_summary(
    dimension: str = "product",
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    sorter_id: int | None = None,
    delivery_id: int | None = None,
    creator_id: int | None = None,
    _: User = Depends(require_permission("sales_summary")),
    db: Session = Depends(get_db),
):
    return build_sales_summary(db, dimension, date_from, date_to, category, customer_id, supplier_id, sorter_id, delivery_id, creator_id)


@app.get("/api/sales/summary.xlsx")
def download_sales_summary(
    dimension: str = "product",
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    sorter_id: int | None = None,
    delivery_id: int | None = None,
    creator_id: int | None = None,
    report_type: str = "normal",
    _: User = Depends(require_permission("sales_summary")),
    db: Session = Depends(get_db),
):
    summary = build_sales_summary(db, dimension, date_from, date_to, category, customer_id, supplier_id, sorter_id, delivery_id, creator_id)
    summary["report_type"] = report_type if report_type in {"horizontal", "quantity", "normal", "custom"} else "normal"
    return StreamingResponse(
        sales_report_service.build_summary_excel(summary),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="sales-summary.xlsx"'},
    )


@app.get("/api/staff", response_model=list[StaffOut])
def list_staff(_: User = Depends(require_permission("staff_management")), db: Session = Depends(get_db)):
    return db.scalars(select(LogisticsStaff).order_by(LogisticsStaff.id.desc())).all()


def validate_staff(data: StaffCreate):
    if data.staff_type not in {"sorter", "delivery"}:
        raise HTTPException(status_code=400, detail="人员类型必须是分拣员或配送员")
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="人员姓名不能为空")


@app.post("/api/staff", response_model=StaffOut)
def create_staff(data: StaffCreate, _: User = Depends(require_permission("staff_management")), db: Session = Depends(get_db)):
    validate_staff(data)
    staff = LogisticsStaff(
        **data.model_dump(exclude={"name"}),
        name=data.name.strip(),
        mobile_token=uuid4().hex + uuid4().hex,
    )
    db.add(staff); db.commit(); db.refresh(staff)
    return staff


@app.put("/api/staff/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: int, data: StaffCreate, _: User = Depends(require_permission("staff_management")), db: Session = Depends(get_db)):
    validate_staff(data)
    staff = db.get(LogisticsStaff, staff_id)
    if not staff: raise HTTPException(status_code=404, detail="人员不存在")
    for key, value in data.model_dump().items(): setattr(staff, key, value)
    staff.name = data.name.strip(); db.commit(); db.refresh(staff)
    return staff


@app.delete("/api/staff/{staff_id}")
def delete_staff(staff_id: int, _: User = Depends(require_permission("staff_management")), db: Session = Depends(get_db)):
    staff = db.get(LogisticsStaff, staff_id)
    if not staff: raise HTTPException(status_code=404, detail="人员不存在")
    assigned = db.scalar(select(Customer.id).where((Customer.sorter_id == staff_id) | (Customer.delivery_id == staff_id)).limit(1))
    if assigned:
        staff.active = False; mode = "disabled"; message = "人员已分配客户，已安全禁用"
    else:
        db.delete(staff); mode = "deleted"; message = "人员已删除"
    db.commit(); return {"message": message, "mode": mode}


@app.post("/api/staff/{staff_id}/reset-mobile-token")
def reset_staff_mobile_token(
    staff_id: int,
    _: User = Depends(require_permission("staff_management")),
    db: Session = Depends(get_db),
):
    staff = db.get(LogisticsStaff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")
    staff.mobile_token = uuid4().hex + uuid4().hex
    staff.mobile_session_version = (staff.mobile_session_version or 1) + 1
    db.commit()
    return {"message": "手机入口已重新生成，原链接立即失效", "mobile_token": staff.mobile_token}


@app.put("/api/staff/{staff_id}/work-pin")
def set_staff_work_pin(
    staff_id: int,
    data: StaffPinIn,
    _: User = Depends(require_permission("staff_management")),
    db: Session = Depends(get_db),
):
    if not re.fullmatch(r"\d{6}", data.pin):
        raise HTTPException(status_code=400, detail="工作密码必须是6位数字")
    staff = db.get(LogisticsStaff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")
    staff.work_pin_hash = hash_password(data.pin)
    staff.pin_fail_count = 0
    staff.pin_locked_until = None
    staff.mobile_session_version = (staff.mobile_session_version or 1) + 1
    db.commit()
    return {"message": "工作密码已设置，之前登录的手机已退出"}


@app.get("/api/customers", response_model=list[CustomerOut])
def list_customers(_: User = Depends(require_permission("customer_management")), db: Session = Depends(get_db)):
    return db.scalars(select(Customer).order_by(Customer.id.desc())).all()


@app.get("/api/customers/order-clerks")
def list_customer_order_clerks(
    _: User = Depends(require_permission("customer_management")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(User)
        .where(User.active.is_(True), User.role == "order_clerk")
        .order_by(User.name)
    ).all()
    return [{"id": row.id, "name": row.name, "role": row.role} for row in rows]


def validate_customer(data: CustomerCreate, db: Session, customer_id: int | None = None):
    if not data.name.strip(): raise HTTPException(status_code=400, detail="客户名称不能为空")
    customer_code = (data.customer_code or "").strip()
    if customer_code:
        duplicate = db.scalar(select(Customer).where(Customer.customer_code == customer_code))
        if duplicate and duplicate.id != customer_id:
            raise HTTPException(status_code=400, detail="客户编号已存在")
    if data.sorter_id:
        staff = db.get(LogisticsStaff, data.sorter_id)
        if not staff or not staff.active or staff.staff_type != "sorter": raise HTTPException(status_code=400, detail="请选择有效分拣员")
    if data.delivery_id:
        staff = db.get(LogisticsStaff, data.delivery_id)
        if not staff or not staff.active or staff.staff_type != "delivery": raise HTTPException(status_code=400, detail="请选择有效配送员")
    if data.order_clerk_id:
        clerk = db.get(User, data.order_clerk_id)
        if not clerk or not clerk.active or clerk.role != "order_clerk":
            raise HTTPException(status_code=400, detail="请选择有效订单员")


def sync_pending_wecom_draft_assignee(db: Session, customer_id: int, order_clerk_id: int | None):
    """Keep existing, unconfirmed WeCom drafts aligned with the customer's current order clerk."""
    drafts = db.scalars(
        select(WeComOrderDraft).where(
            WeComOrderDraft.customer_id == customer_id,
            WeComOrderDraft.status.in_({"needs_review", "awaiting_confirmation"}),
        )
    ).all()
    for draft in drafts:
        draft.assigned_to = order_clerk_id


def sync_pending_picking_task_assignees(db: Session, customer: Customer):
    """New staff assignments should immediately reach tasks that have not started."""
    tasks = db.scalars(
        select(PickingTask).where(
            PickingTask.customer_id == customer.id,
            PickingTask.status == "pending",
        )
    ).all()
    for task in tasks:
        task.sorter_id = customer.sorter_id
        task.delivery_id = customer.delivery_id


@app.post("/api/customers", response_model=CustomerOut)
def create_customer(data: CustomerCreate, _: User = Depends(require_permission("customer_management")), db: Session = Depends(get_db)):
    validate_customer(data, db)
    values = data.model_dump(exclude={"name"})
    values["customer_code"] = (data.customer_code or "").strip() or f"KH{uuid4().hex[:8].upper()}"
    values["ai_reply_rules"] = (data.ai_reply_rules or "").strip() or None
    customer = Customer(**values, name=data.name.strip())
    db.add(customer); db.commit(); db.refresh(customer)
    return customer


@app.post("/api/customers/batch-assign")
def batch_assign_customers(
    data: CustomerBatchAssign,
    _: User = Depends(require_permission("customer_management")),
    db: Session = Depends(get_db),
):
    if data.sorter_id is None and data.delivery_id is None and data.order_clerk_id is None:
        raise HTTPException(status_code=400, detail="请至少选择一名订单员、分拣员或配送员")
    if data.sorter_id is not None:
        sorter = db.get(LogisticsStaff, data.sorter_id)
        if not sorter or not sorter.active or sorter.staff_type != "sorter":
            raise HTTPException(status_code=400, detail="请选择有效分拣员")
    if data.delivery_id is not None:
        delivery = db.get(LogisticsStaff, data.delivery_id)
        if not delivery or not delivery.active or delivery.staff_type != "delivery":
            raise HTTPException(status_code=400, detail="请选择有效配送员")
    if data.order_clerk_id is not None:
        clerk = db.get(User, data.order_clerk_id)
        if not clerk or not clerk.active or clerk.role != "order_clerk":
            raise HTTPException(status_code=400, detail="请选择有效订单员")
    updated = 0
    for customer_id in set(data.customer_ids):
        customer = db.get(Customer, customer_id)
        if not customer:
            continue
        if data.sorter_id is not None:
            customer.sorter_id = data.sorter_id
        if data.delivery_id is not None:
            customer.delivery_id = data.delivery_id
        if data.order_clerk_id is not None:
            customer.order_clerk_id = data.order_clerk_id
            sync_pending_wecom_draft_assignee(db, customer.id, data.order_clerk_id)
        sync_pending_picking_task_assignees(db, customer)
        updated += 1
    db.commit()
    return {"message": f"已完成 {updated} 个客户的批量人员分配", "updated": updated}


@app.put("/api/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, data: CustomerCreate, _: User = Depends(require_permission("customer_management")), db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="客户不存在")
    validate_customer(data, db, customer_id)
    values = data.model_dump()
    values["customer_code"] = (data.customer_code or "").strip() or customer.customer_code
    values["ai_reply_rules"] = (data.ai_reply_rules or "").strip() or None
    for key, value in values.items(): setattr(customer, key, value)
    sync_pending_wecom_draft_assignee(db, customer.id, customer.order_clerk_id)
    sync_pending_picking_task_assignees(db, customer)
    customer.name = data.name.strip(); db.commit(); db.refresh(customer)
    return customer


@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: int, _: User = Depends(require_permission("customer_management")), db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="客户不存在")
    has_sales = db.scalar(select(SalesOrder.id).where(SalesOrder.customer_id == customer_id).limit(1))
    if has_sales:
        customer.active = False
        db.commit()
        return {"message": "客户已有销售历史，已安全禁用并保留单据", "mode": "disabled"}
    db.delete(customer); db.commit(); return {"message": "客户已删除", "mode": "deleted"}


@app.get("/api/dashboard")
def dashboard(user: User = Depends(require_permission("dashboard")), db: Session = Depends(get_db)):
    if user.role == "supplier":
        assigned = db.scalar(
            select(func.count()).select_from(ProductSupplier).where(
                ProductSupplier.supplier_id == user.supplier_id,
                ProductSupplier.active.is_(True),
            )
        ) or 0
        quoted = db.scalar(
            select(func.count(distinct(Quote.assignment_id)))
            .select_from(Quote)
            .join(ProductSupplier)
            .where(ProductSupplier.supplier_id == user.supplier_id)
        ) or 0
        return {"assigned": assigned, "quoted": quoted, "pending": max(assigned - quoted, 0)}
    inventory = inventory_service.summary()
    return {
        "suppliers": len(db.scalars(select(Supplier).where(Supplier.active.is_(True))).all()),
        "products": len(db.scalars(select(Product).where(Product.active.is_(True))).all()),
        "assignments": len(db.scalars(select(ProductSupplier).where(ProductSupplier.active.is_(True))).all()),
        "sales_orders": db.scalar(select(func.count()).select_from(SalesOrder)) or 0,
        "zero_stock": inventory["zero_stock"],
        "expiring_30_days": inventory["expiring_30_days"],
    }


@app.get("/api/inventory/summary")
def inventory_summary(_: User = Depends(require_permission("inventory"))):
    try:
        return inventory_service.summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"库存表读取失败：{exc}") from exc


@app.post("/api/inventory/query")
def inventory_query(
    data: InventoryQueryRequest,
    user: User = Depends(require_permission("inventory")),
    db: Session = Depends(get_db),
):
    try:
        result = inventory_service.query(
            data.question, data.categories, data.only_available, data.only_expiring
        )
        db.add(
            InventoryQueryLog(
                user_id=user.id,
                username=user.username,
                user_name=user.name,
                question=data.question.strip() or f"按品类查询：{'、'.join(data.categories)}",
                query_type=result.get("query_type"),
                keyword=result.get("keyword"),
                result_count=result.get("count", 0),
                source="new",
            )
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"库存查询失败：{exc}") from exc


def legacy_inventory_query_records() -> list[dict]:
    log_path = inventory_service.DATA_PATH.parent / "legacy_app.log"
    if not log_path.exists():
        return []
    pattern = re.compile(
        r"^(?P<time>\d{4}-\d{2}-\d{2} [\d:,]+) INFO session=(?P<session>\S+) "
        r"query query_type=(?P<query_type>.+?) query=(?P<question>.+?) "
        r"keyword=(?P<keyword>.+?) rows=(?P<count>\d+)$"
    )
    records = []
    for index, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        match = pattern.match(line)
        if not match:
            continue
        values = match.groupdict()
        try:
            query_type = ast.literal_eval(values["query_type"])
            question = ast.literal_eval(values["question"])
            keyword = ast.literal_eval(values["keyword"])
        except (ValueError, SyntaxError):
            continue
        records.append(
            {
                "id": f"legacy-{index}",
                "created_at": datetime.strptime(values["time"], "%Y-%m-%d %H:%M:%S,%f").isoformat(),
                "username": values["session"],
                "user_name": "旧系统访客",
                "question": str(question),
                "query_type": str(query_type),
                "keyword": str(keyword),
                "result_count": int(values["count"]),
                "source": "legacy",
            }
        )
    return records


@app.get("/api/inventory/query-records")
def inventory_query_records(
    admin: str = "",
    keyword: str = "",
    source: str = "all",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if admin != "yes" or user.role != "admin":
        raise HTTPException(status_code=404, detail="页面不存在")
    records = [
        {
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "username": row.username,
            "user_name": row.user_name,
            "question": row.question,
            "query_type": row.query_type,
            "keyword": row.keyword,
            "result_count": row.result_count,
            "source": row.source,
        }
        for row in db.scalars(select(InventoryQueryLog).order_by(InventoryQueryLog.created_at.desc())).all()
    ]
    if source in {"all", "legacy"}:
        records.extend(legacy_inventory_query_records())
    if source in {"new", "legacy"}:
        records = [row for row in records if row["source"] == source]
    term = keyword.strip().lower()
    if term:
        records = [
            row for row in records
            if term in " ".join(str(row.get(field) or "") for field in ("question", "keyword", "username", "user_name", "query_type")).lower()
        ]
    records.sort(key=lambda row: row["created_at"], reverse=True)
    return {"total": len(records), "records": records[:1000]}


@app.post("/api/inventory/upload")
async def inventory_upload(
    file: UploadFile = File(...),
    _: User = Depends(require_permission("inventory_update")),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 xlsx 文件")
    try:
        return inventory_service.replace_data(await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"库存表上传失败：{exc}") from exc
