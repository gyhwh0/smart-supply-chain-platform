import json
from decimal import Decimal
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default="purchaser")
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions_csv: Mapped[str | None] = mapped_column("permissions", Text, nullable=True)

    supplier: Mapped["Supplier | None"] = relationship(back_populates="users")

    @property
    def permissions(self) -> list[str]:
        return [item for item in (self.permissions_csv or "").split(",") if item]


class Supplier(Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    contact_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[list[User]] = relationship(back_populates="supplier")
    assignments: Mapped[list["ProductSupplier"]] = relationship(back_populates="supplier")


class Category(Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category_rel")


class Product(Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    category: Mapped[str] = mapped_column(String(100), default="未分类")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_temperature_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    storage_temperature_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    storage_notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_report_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_report_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_report_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    units: Mapped[list["ProductUnit"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductUnit.id"
    )
    assignments: Mapped[list["ProductSupplier"]] = relationship(back_populates="product")
    category_rel: Mapped[Category | None] = relationship(back_populates="products")

    @property
    def supplier_ids(self) -> list[int]:
        return [row.supplier_id for row in self.assignments if row.active]

    @property
    def aliases(self) -> list[str]:
        try:
            value = json.loads(self.aliases_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @property
    def customer_aliases(self) -> list[dict]:
        try:
            value = json.loads(self.customer_aliases_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @property
    def quality_report_url(self) -> str | None:
        return f"/api/products/{self.id}/quality-report" if self.quality_report_path else None


class ProductUnit(Base):
    __tablename__ = "product_units"
    __table_args__ = (UniqueConstraint("product_id", "name", name="uq_product_unit"),)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(30))
    conversion_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=1)
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    reference_purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    product: Mapped[Product] = relationship(back_populates="units")


class ProductSupplier(Base):
    __tablename__ = "product_suppliers"
    __table_args__ = (
        UniqueConstraint("product_id", "supplier_id", name="uq_product_supplier"),
    )

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product] = relationship(back_populates="assignments")
    supplier: Mapped[Supplier] = relationship(back_populates="assignments")
    purchaser: Mapped[User] = relationship(foreign_keys=[assigned_by])
    quotes: Mapped[list["Quote"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("assignment_id", "unit_id", name="uq_quote_unit"),)

    assignment_id: Mapped[int] = mapped_column(ForeignKey("product_suppliers.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    currency: Mapped[str] = mapped_column(String(10), default="CNY")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    assignment: Mapped[ProductSupplier] = relationship(back_populates="quotes")
    unit: Mapped[ProductUnit] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(150), default="采购订单")
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_footer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    supplier: Mapped[Supplier] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="PurchaseOrderItem.id"
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    is_best_price: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    unit: Mapped[ProductUnit] = relationship()


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    receipt_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    receipt_date: Mapped[date] = mapped_column(Date)
    warehouse: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    supplier: Mapped[Supplier] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    items: Mapped[list["GoodsReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="GoodsReceiptItem.id"
    )


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"

    receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    batch_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    production_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    receipt: Mapped[GoodsReceipt] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    unit: Mapped[ProductUnit] = relationship()


class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"

    return_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipts.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    return_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    supplier: Mapped[Supplier] = relationship()
    receipt: Mapped[GoodsReceipt | None] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    items: Mapped[list["PurchaseReturnItem"]] = relationship(
        back_populates="return_order", cascade="all, delete-orphan", order_by="PurchaseReturnItem.id"
    )


class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"

    return_id: Mapped[int] = mapped_column(ForeignKey("purchase_returns.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    batch_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    return_order: Mapped[PurchaseReturn] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    unit: Mapped[ProductUnit] = relationship()


class WarehouseDocument(Base):
    __tablename__ = "warehouse_documents"
    __table_args__ = (
        UniqueConstraint("document_type", "source_type", "source_id", name="uq_warehouse_source"),
    )

    document_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    document_type: Mapped[str] = mapped_column(String(20), index=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse: Mapped[str] = mapped_column(String(100), default="主仓库")
    target_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="manual")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    items: Mapped[list["WarehouseDocumentItem"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="WarehouseDocumentItem.id"
    )


class WarehouseDocumentItem(Base):
    __tablename__ = "warehouse_document_items"

    document_id: Mapped[int] = mapped_column(ForeignKey("warehouse_documents.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    batch_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    document: Mapped[WarehouseDocument] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    unit: Mapped[ProductUnit] = relationship()


class LogisticsStaff(Base):
    __tablename__ = "logistics_staff"

    name: Mapped[str] = mapped_column(String(50))
    staff_type: Mapped[str] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mobile_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    work_pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mobile_session_version: Mapped[int] = mapped_column(Integer, default=1)

    @property
    def has_work_pin(self) -> bool:
        return bool(self.work_pin_hash)


class Customer(Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(100))
    customer_code: Mapped[str | None] = mapped_column(String(50), unique=True, index=True, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sorter_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_staff.id"), nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_staff.id"), nullable=True)
    order_clerk_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ai_reply_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    sorter: Mapped[LogisticsStaff | None] = relationship(foreign_keys=[sorter_id])
    delivery: Mapped[LogisticsStaff | None] = relationship(foreign_keys=[delivery_id])
    order_clerk: Mapped[User | None] = relationship(foreign_keys=[order_clerk_id])


class InventoryQueryLog(Base):
    __tablename__ = "inventory_query_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    query_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_count: Mapped[int] = mapped_column(default=0)
    source: Mapped[str] = mapped_column(String(20), default="new")

    user: Mapped[User | None] = relationship()


class AIAnalysisQueryLog(Base):
    __tablename__ = "ai_analysis_query_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    user: Mapped[User | None] = relationship()


class SalesOrder(Base):
    __tablename__ = "sales_orders"

    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_date: Mapped[date] = mapped_column(Date)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str] = mapped_column(String(150), default="销售订单")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    procurement_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    external_reference: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    supplement_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    invoice_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    acceptance_status: Mapped[str] = mapped_column(String(20), default="pending")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    customer: Mapped[Customer] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    accepter: Mapped[User | None] = relationship(foreign_keys=[accepted_by])
    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="SalesOrderItem.id"
    )
    procurement_links: Mapped[list["SalesProcurementLink"]] = relationship(
        back_populates="sales_order", cascade="all, delete-orphan"
    )


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"

    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))
    specification: Mapped[str | None] = mapped_column(String(120), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    accepted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    acceptance_variance_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    order: Mapped[SalesOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    unit: Mapped[ProductUnit] = relationship()


class SalesProcurementLink(Base):
    __tablename__ = "sales_procurement_links"
    __table_args__ = (
        UniqueConstraint("sales_order_id", "purchase_order_id", name="uq_sales_purchase_link"),
    )

    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))

    sales_order: Mapped[SalesOrder] = relationship(back_populates="procurement_links")
    purchase_order: Mapped[PurchaseOrder] = relationship()


class PickingTask(Base):
    __tablename__ = "picking_tasks"

    task_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    sorter_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_staff.id"), nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_staff.id"), nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sales_order: Mapped[SalesOrder] = relationship()
    customer: Mapped[Customer] = relationship()
    sorter: Mapped[LogisticsStaff | None] = relationship(foreign_keys=[sorter_id])
    delivery: Mapped[LogisticsStaff | None] = relationship(foreign_keys=[delivery_id])
    items: Mapped[list["PickingTaskItem"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="PickingTaskItem.id"
    )


class PickingTaskItem(Base):
    __tablename__ = "picking_task_items"

    task_id: Mapped[int] = mapped_column(ForeignKey("picking_tasks.id"))
    sales_order_item_id: Mapped[int] = mapped_column(ForeignKey("sales_order_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unit_name: Mapped[str] = mapped_column(String(30))
    scan_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exception_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    task: Mapped[PickingTask] = relationship(back_populates="items")
    sales_order_item: Mapped[SalesOrderItem] = relationship()
    product: Mapped[Product] = relationship()


class PickingOperationLog(Base):
    __tablename__ = "picking_operation_logs"

    task_id: Mapped[int] = mapped_column(ForeignKey("picking_tasks.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("picking_task_items.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("logistics_staff.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class WeComCustomerBinding(Base):
    __tablename__ = "wecom_customer_bindings"
    __table_args__ = (UniqueConstraint("external_userid", "open_kfid", name="uq_wecom_external_kf"),)

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    external_userid: Mapped[str] = mapped_column(String(100), index=True)
    open_kfid: Mapped[str] = mapped_column(String(100), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    bind_method: Mapped[str] = mapped_column(String(30), default="manual")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wechat_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wechat_remark: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer] = relationship()


class WeComMessage(Base):
    __tablename__ = "wecom_messages"

    msgid: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    external_userid: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    open_kfid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(20), default="inbound")
    msg_type: Mapped[str] = mapped_column(String(30), default="text")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str] = mapped_column(String(30), default="pending")
    status: Mapped[str] = mapped_column(String(30), default="received")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer | None] = relationship()


class WeComOrderDraft(Base):
    __tablename__ = "wecom_order_drafts"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_msgid: Mapped[str] = mapped_column(String(100), unique=True)
    external_userid: Mapped[str] = mapped_column(String(100))
    open_kfid: Mapped[str] = mapped_column(String(100), default="")
    raw_message: Mapped[str] = mapped_column(Text)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="needs_review")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0)
    parse_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True)

    customer: Mapped[Customer] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assigned_to])
    sales_order: Mapped[SalesOrder | None] = relationship()
    items: Mapped[list["WeComOrderDraftItem"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", order_by="WeComOrderDraftItem.id"
    )


class WeComOrderDraftItem(Base):
    __tablename__ = "wecom_order_draft_items"

    draft_id: Mapped[int] = mapped_column(ForeignKey("wecom_order_drafts.id"))
    requested_name: Mapped[str] = mapped_column(String(120))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("product_units.id"), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)

    draft: Mapped[WeComOrderDraft] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()
    unit: Mapped[ProductUnit | None] = relationship()


class Complaint(Base):
    __tablename__ = "complaints"

    complaint_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True)
    source_msgid: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    category: Mapped[str] = mapped_column(String(30), default="其他")
    severity: Mapped[str] = mapped_column(String(10), default="P2")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="new")
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped[Customer] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assigned_to])
    sales_order: Mapped[SalesOrder | None] = relationship()
