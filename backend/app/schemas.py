from decimal import Decimal
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    role: str
    supplier_id: int | None
    active: bool
    permissions: list[str] = Field(default_factory=list)


class AccountCreate(BaseModel):
    username: str
    password: str = Field(min_length=6)
    name: str
    role: str
    supplier_id: int | None = None
    active: bool = True
    permissions: list[str] = Field(default_factory=list)


class AccountUpdate(BaseModel):
    username: str
    password: str | None = Field(default=None, min_length=6)
    name: str
    role: str
    supplier_id: int | None = None
    active: bool = True
    permissions: list[str] = Field(default_factory=list)


class LoginOut(BaseModel):
    token: str
    user: UserOut


class SupplierCreate(BaseModel):
    name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    login_username: str | None = None
    login_password: str | None = None


class SupplierUpdate(BaseModel):
    name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    active: bool = True


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    address: str | None
    active: bool


class CategoryCreate(BaseModel):
    name: str
    description: str | None = None


class CategoryUpdate(CategoryCreate):
    active: bool = True


class CategoryOut(CategoryUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class UnitIn(BaseModel):
    name: str
    conversion_rate: Decimal = Field(gt=0)
    is_base: bool = False
    sales_price: Decimal | None = Field(default=None, ge=0)
    reference_purchase_price: Decimal | None = Field(default=None, ge=0)


class UnitOut(UnitIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class UnitPriceIn(BaseModel):
    unit_id: int
    sales_price: Decimal | None = Field(default=None, ge=0)
    reference_purchase_price: Decimal | None = Field(default=None, ge=0)


class ProductUnitPricesUpdate(BaseModel):
    units: list[UnitPriceIn]


class CustomerProductAliasIn(BaseModel):
    customer_id: int
    alias: str


class ProductCreate(BaseModel):
    name: str
    category: str = "未分类"
    category_id: int
    sku: str | None = None
    reference_price: Decimal | None = Field(default=None, ge=0)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    customer_aliases: list[CustomerProductAliasIn] = Field(default_factory=list)
    shelf_life_days: int | None = Field(default=None, ge=1)
    storage_temperature_min: Decimal | None = None
    storage_temperature_max: Decimal | None = None
    loss_rate: Decimal | None = Field(default=None, ge=0, le=100)
    storage_notes: str | None = None
    units: list[UnitIn]
    supplier_ids: list[int] = Field(default_factory=list)
    mini_visible: bool = True
    mini_all_customers: bool = False
    mini_customer_ids: list[int] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    name: str
    category: str = "未分类"
    category_id: int
    sku: str | None = None
    reference_price: Decimal | None = Field(default=None, ge=0)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    customer_aliases: list[CustomerProductAliasIn] = Field(default_factory=list)
    shelf_life_days: int | None = Field(default=None, ge=1)
    storage_temperature_min: Decimal | None = None
    storage_temperature_max: Decimal | None = None
    loss_rate: Decimal | None = Field(default=None, ge=0, le=100)
    storage_notes: str | None = None
    active: bool = True
    supplier_ids: list[int] = Field(default_factory=list)
    mini_visible: bool = True
    mini_all_customers: bool = False
    mini_customer_ids: list[int] = Field(default_factory=list)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: str
    category_id: int | None
    sku: str | None
    reference_price: Decimal | None
    description: str | None
    aliases: list[str] = Field(default_factory=list)
    customer_aliases: list[CustomerProductAliasIn] = Field(default_factory=list)
    shelf_life_days: int | None
    storage_temperature_min: Decimal | None
    storage_temperature_max: Decimal | None
    loss_rate: Decimal | None
    storage_notes: str | None
    quality_report_name: str | None
    quality_report_url: str | None
    image_name: str | None
    image_url: str | None
    mini_visible: bool
    mini_all_customers: bool
    mini_customer_ids: list[int] = Field(default_factory=list)
    active: bool
    units: list[UnitOut]
    supplier_ids: list[int] = Field(default_factory=list)


class AssignmentCreate(BaseModel):
    product_ids: list[int] = Field(default_factory=list)
    category_ids: list[int] = Field(default_factory=list)
    supplier_ids: list[int]


class IdsRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


class OrderItemIn(BaseModel):
    product_id: int
    unit_id: int
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    remark: str | None = None


class OrderCreate(BaseModel):
    supplier_id: int
    title: str = "采购订单"
    expected_date: date | None = None
    notes: str | None = None
    report_footer: str | None = None
    items: list[OrderItemIn] = Field(min_length=1)


class OrderUpdate(BaseModel):
    title: str
    expected_date: date | None = None
    notes: str | None = None
    report_footer: str | None = None
    items: list[OrderItemIn] = Field(min_length=1)


class SalesOrderItemIn(BaseModel):
    product_id: int
    unit_id: int
    specification: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    remark: str | None = None


class SalesOrderCreate(BaseModel):
    customer_id: int
    order_date: date
    delivery_date: date | None = None
    title: str = "销售订单"
    notes: str | None = None
    items: list[SalesOrderItemIn] = Field(min_length=1)


class SalesOrderUpdate(SalesOrderCreate):
    pass


class FinanceSettlementItemIn(BaseModel):
    sales_order_item_id: int
    delivered_quantity: Decimal | None = Field(default=None, ge=0)
    accepted_quantity: Decimal | None = Field(default=None, ge=0)
    variance_reason: str | None = None
    cost_unit_price: Decimal | None = Field(default=None, ge=0)


class FinanceSettlementIn(BaseModel):
    invoice_amount: Decimal = Field(default=0, ge=0)
    invoice_date: date | None = None
    items: list[FinanceSettlementItemIn] = Field(min_length=1)


class ProcurementAllocationIn(BaseModel):
    product_id: int
    supplier_id: int


class GeneratePurchasesRequest(BaseModel):
    automatic: bool = True
    allocations: list[ProcurementAllocationIn] = Field(default_factory=list)


class StaffCreate(BaseModel):
    name: str
    staff_type: str
    phone: str | None = None
    remark: str | None = None
    active: bool = True


class StaffOut(StaffCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    mobile_token: str | None = None
    has_work_pin: bool = False


class StaffPinIn(BaseModel):
    pin: str


class StaffMobileLoginIn(BaseModel):
    pin: str


class CustomerCreate(BaseModel):
    name: str
    customer_code: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    address: str | None = None
    sorter_id: int | None = None
    delivery_id: int | None = None
    order_clerk_id: int | None = None
    ai_reply_rules: str | None = None
    remark: str | None = None
    active: bool = True


class CustomerOut(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CustomerBatchAssign(BaseModel):
    customer_ids: list[int] = Field(min_length=1)
    sorter_id: int | None = None
    delivery_id: int | None = None
    order_clerk_id: int | None = None


class GoodsReceiptItemIn(BaseModel):
    product_id: int
    unit_id: int
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    batch_no: str | None = None
    production_date: date | None = None
    shelf_life_days: int | None = Field(default=None, ge=1)
    remark: str | None = None


class GoodsReceiptIn(BaseModel):
    supplier_id: int
    receipt_date: date
    warehouse: str | None = None
    notes: str | None = None
    items: list[GoodsReceiptItemIn] = Field(min_length=1)


class PurchaseReturnItemIn(BaseModel):
    product_id: int
    unit_id: int
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    batch_no: str | None = None
    remark: str | None = None


class PurchaseReturnIn(BaseModel):
    supplier_id: int
    receipt_id: int | None = None
    return_date: date
    reason: str
    notes: str | None = None
    items: list[PurchaseReturnItemIn] = Field(min_length=1)


class WarehouseDocumentItemIn(BaseModel):
    product_id: int
    unit_id: int
    quantity: Decimal = Field(gt=0)
    batch_no: str | None = None
    remark: str | None = None


class WarehouseDocumentIn(BaseModel):
    document_type: str
    business_date: date
    warehouse: str = "主仓库"
    target_name: str | None = None
    notes: str | None = None
    items: list[WarehouseDocumentItemIn] = Field(min_length=1)


class PickingGenerateIn(BaseModel):
    sales_order_ids: list[int] = Field(min_length=1)


class PickingScanIn(BaseModel):
    stage: str
    note: str | None = None


class DefaultAdminPermissionsIn(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class WeComBindingCreate(BaseModel):
    customer_id: int
    external_userid: str
    open_kfid: str = ""
    verified: bool = True
    wechat_remark: str | None = None


class WeComSimulateMessage(BaseModel):
    external_userid: str
    content: str
    open_kfid: str = "test-kf"


class ComplaintUpdate(BaseModel):
    status: str
    customer_id: int | None = None
    category: str | None = None
    severity: str | None = None
    content: str | None = None
    assigned_to: int | None = None
    resolution: str | None = None


class ComplaintCreate(BaseModel):
    customer_id: int
    assigned_to: int | None = None
    sales_order_id: int | None = None
    category: str = "其他"
    severity: str = "P2"
    content: str = Field(min_length=1)


class QuoteUpsert(BaseModel):
    unit_id: int
    price: Decimal = Field(gt=0)
    currency: str = "CNY"
    remark: str | None = None


class QuoteBatchItem(QuoteUpsert):
    assignment_id: int


class QuoteBatchUpsert(BaseModel):
    quotes: list[QuoteBatchItem] = Field(min_length=1)


class AIAnalysisRequest(BaseModel):
    question: str = "请分析各供应商在哪些商品品类更有价格优势，并给出采购建议。"


class InventoryQueryRequest(BaseModel):
    question: str = ""
    categories: list[str] = Field(default_factory=list)
    only_available: bool = False
    only_expiring: bool = False
