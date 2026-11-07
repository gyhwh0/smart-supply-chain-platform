from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import warehouse_service
from app.models import (
    Category,
    Complaint,
    Customer,
    DeletionRequest,
    LogisticsStaff,
    MiniProgramUser,
    MiniProductCustomer,
    PickingTask,
    Product,
    ProductSupplier,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    SalesProcurementLink,
    Supplier,
    User,
    WeComCustomerBinding,
    WeComOrderDraft,
    WarehouseDocument,
)


ENTITY_NAMES = {
    "account": "账号",
    "supplier": "供应商",
    "category": "商品分类",
    "product": "商品",
    "purchase_order": "采购单",
    "sales_order": "销售单",
    "staff": "分拣配送人员",
    "customer": "客户",
    "wecom_binding": "企业微信客户绑定",
    "complaint": "投诉记录",
    "warehouse_document": "仓库单据",
}


def queue_deletion(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    entity_label: str,
    requester: User,
) -> dict:
    if entity_type not in ENTITY_NAMES:
        raise HTTPException(status_code=400, detail="不支持的删除对象")
    pending = db.scalar(
        select(DeletionRequest).where(
            DeletionRequest.entity_type == entity_type,
            DeletionRequest.entity_id == entity_id,
            DeletionRequest.status == "pending",
        )
    )
    if pending:
        return {"message": "该数据已有待审核的删除申请，请勿重复提交", "mode": "pending", "request_id": pending.id}
    request = DeletionRequest(
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label[:200],
        requested_by=requester.id,
        status="pending",
    )
    db.add(request)
    db.commit()
    return {"message": "删除申请已提交，数据将在管理员审核通过前继续保留", "mode": "pending", "request_id": request.id}


def _account(db: Session, entity_id: int, reviewer: User) -> str:
    row = db.get(User, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="账号已不存在")
    if row.id == reviewer.id:
        raise HTTPException(status_code=400, detail="不能批准删除当前登录账号")
    history = (
        db.scalar(select(ProductSupplier.id).where(ProductSupplier.assigned_by == row.id).limit(1))
        or db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.created_by == row.id).limit(1))
        or db.scalar(select(SalesOrder.id).where(SalesOrder.created_by == row.id).limit(1))
        or db.scalar(select(DeletionRequest.id).where((DeletionRequest.requested_by == row.id) | (DeletionRequest.reviewed_by == row.id)).limit(1))
    )
    if history:
        row.active = False
        return "账号存在业务历史，审核后已安全禁用"
    db.delete(row)
    return "账号已删除"


def _supplier(db: Session, entity_id: int) -> str:
    row = db.get(Supplier, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="供应商已不存在")
    assignments = db.scalars(select(ProductSupplier).where(ProductSupplier.supplier_id == row.id)).all()
    has_orders = db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == row.id).limit(1))
    if assignments or has_orders:
        row.active = False
        for assignment in assignments:
            assignment.active = False
        for account in row.users:
            account.active = False
        return "供应商存在历史业务，审核后已安全禁用"
    for account in list(row.users):
        db.delete(account)
    db.delete(row)
    return "供应商已删除"


def _category(db: Session, entity_id: int) -> str:
    row = db.get(Category, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="分类已不存在")
    if row.products:
        row.active = False
        return "分类下已有商品，审核后已安全禁用"
    db.delete(row)
    return "分类已删除"


def _product(db: Session, entity_id: int) -> str:
    row = db.get(Product, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="商品已不存在")
    assignments = db.scalars(select(ProductSupplier).where(ProductSupplier.product_id == row.id)).all()
    history = (
        db.scalar(select(PurchaseOrderItem.id).where(PurchaseOrderItem.product_id == row.id).limit(1))
        or db.scalar(select(SalesOrderItem.id).where(SalesOrderItem.product_id == row.id).limit(1))
    )
    if assignments or history:
        row.active = False
        row.mini_visible = False
        for assignment in assignments:
            assignment.active = False
        return "商品存在历史业务，审核后已安全禁用并从小程序下架"
    db.delete(row)
    return "商品已删除"


def _purchase_order(db: Session, entity_id: int) -> str:
    order = db.get(PurchaseOrder, entity_id)
    if not order:
        raise HTTPException(status_code=404, detail="采购单已不存在")
    if order.status != "draft":
        raise HTTPException(status_code=400, detail="已确认采购单属于业务凭证，不能删除")
    product_ids = {item.product_id for item in order.items}
    links = db.scalars(select(SalesProcurementLink).where(SalesProcurementLink.purchase_order_id == entity_id)).all()
    affected = []
    for link in links:
        sales = db.get(SalesOrder, link.sales_order_id)
        if sales:
            for item in sales.items:
                if item.product_id in product_ids:
                    item.cost_unit_price = None
            affected.append(sales)
        db.delete(link)
    db.flush()
    for sales in affected:
        remaining = db.scalar(select(func.count()).select_from(SalesProcurementLink).where(SalesProcurementLink.sales_order_id == sales.id)) or 0
        if not remaining:
            sales.procurement_generated_at = None
    db.delete(order)
    return "采购草稿已删除，销售采购关联已同步更新"


def _sales_order(db: Session, entity_id: int) -> str:
    order = db.get(SalesOrder, entity_id)
    if not order:
        raise HTTPException(status_code=404, detail="销售单已不存在")
    if order.procurement_links:
        raise HTTPException(status_code=400, detail="销售单已生成采购单，请先申请删除对应采购草稿")
    if db.scalar(select(PickingTask.id).where(PickingTask.sales_order_id == entity_id)):
        raise HTTPException(status_code=400, detail="销售单已有分拣任务，不能删除")
    if db.scalar(select(Complaint.id).where(Complaint.sales_order_id == entity_id)):
        raise HTTPException(status_code=400, detail="销售单已关联投诉，不能删除")
    if db.scalar(select(WeComOrderDraft.id).where(WeComOrderDraft.sales_order_id == entity_id)):
        raise HTTPException(status_code=400, detail="企业微信生成的销售单不能直接删除")
    if order.acceptance_status != "pending" or order.accepted_at or Decimal(order.invoice_amount or 0) != 0:
        raise HTTPException(status_code=400, detail="销售单已有验收或开票数据，不能删除")
    db.delete(order)
    return "销售单已删除"


def _staff(db: Session, entity_id: int) -> str:
    row = db.get(LogisticsStaff, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="人员已不存在")
    assigned = db.scalar(select(Customer.id).where((Customer.sorter_id == entity_id) | (Customer.delivery_id == entity_id)).limit(1))
    assigned = assigned or db.scalar(select(PickingTask.id).where((PickingTask.sorter_id == entity_id) | (PickingTask.delivery_id == entity_id)).limit(1))
    if assigned:
        row.active = False
        return "人员仍有关联客户，审核后已安全禁用"
    db.delete(row)
    return "人员已删除"


def _customer(db: Session, entity_id: int) -> str:
    row = db.get(Customer, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="客户已不存在")
    has_history = (
        db.scalar(select(SalesOrder.id).where(SalesOrder.customer_id == entity_id).limit(1))
        or db.scalar(select(Complaint.id).where(Complaint.customer_id == entity_id).limit(1))
        or db.scalar(select(WeComCustomerBinding.id).where(WeComCustomerBinding.customer_id == entity_id).limit(1))
        or db.scalar(select(PickingTask.id).where(PickingTask.customer_id == entity_id).limit(1))
    )
    if has_history:
        row.active = False
        return "客户已有销售历史，审核后已安全禁用"
    for mini_user in db.scalars(select(MiniProgramUser).where(MiniProgramUser.customer_id == entity_id)).all():
        mini_user.customer_id = None
    for assignment in db.scalars(select(MiniProductCustomer).where(MiniProductCustomer.customer_id == entity_id)).all():
        db.delete(assignment)
    db.delete(row)
    return "客户已删除，小程序绑定已解除"


def execute_deletion(db: Session, request: DeletionRequest, reviewer: User) -> str:
    handlers = {
        "account": lambda: _account(db, request.entity_id, reviewer),
        "supplier": lambda: _supplier(db, request.entity_id),
        "category": lambda: _category(db, request.entity_id),
        "product": lambda: _product(db, request.entity_id),
        "purchase_order": lambda: _purchase_order(db, request.entity_id),
        "sales_order": lambda: _sales_order(db, request.entity_id),
        "staff": lambda: _staff(db, request.entity_id),
        "customer": lambda: _customer(db, request.entity_id),
        "wecom_binding": lambda: _simple_delete(db, WeComCustomerBinding, request.entity_id, "企业微信绑定"),
        "complaint": lambda: _simple_delete(db, Complaint, request.entity_id, "投诉记录"),
        "warehouse_document": lambda: _warehouse_document(db, request.entity_id),
    }
    handler = handlers.get(request.entity_type)
    if not handler:
        raise HTTPException(status_code=400, detail="不支持的删除对象")
    result = handler()
    request.status = "approved"
    request.reviewed_by = reviewer.id
    request.reviewed_at = datetime.now()
    request.execution_result = result
    return result


def _simple_delete(db: Session, model, entity_id: int, label: str) -> str:
    row = db.get(model, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"{label}已不存在")
    db.delete(row)
    return f"{label}已删除"


def _warehouse_document(db: Session, entity_id: int) -> str:
    row = db.get(WarehouseDocument, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="仓库单据已不存在")
    if row.source_type != "manual":
        raise HTTPException(status_code=400, detail="联动生成的仓库单据不能删除，请处理来源单据")
    db.delete(row)
    db.flush()
    warehouse_service.rebuild_requisitions(db)
    return "仓库单据已删除，库存和备货申请已重算"
