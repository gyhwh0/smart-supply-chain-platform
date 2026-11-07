from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import current_user, require_permission
from app.database import get_db
from app.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    PickingTask,
    Product,
    ProductUnit,
    PurchaseReturn,
    PurchaseReturnItem,
    SalesOrder,
    SalesOrderItem,
    Supplier,
    User,
)
from app.schemas import GoodsReceiptIn, PurchaseReturnIn
from app import warehouse_service


router = APIRouter(prefix="/api", tags=["进货管理"])


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _receipt_query():
    return select(GoodsReceipt).options(
        selectinload(GoodsReceipt.supplier),
        selectinload(GoodsReceipt.creator),
        selectinload(GoodsReceipt.items).selectinload(GoodsReceiptItem.product),
        selectinload(GoodsReceipt.items).selectinload(GoodsReceiptItem.unit),
    )


def _receipt_output(row: GoodsReceipt) -> dict:
    items = []
    for item in row.items:
        expiry = (
            item.production_date + timedelta(days=item.shelf_life_days)
            if item.production_date and item.shelf_life_days
            else None
        )
        items.append(
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
                "batch_no": item.batch_no,
                "production_date": item.production_date,
                "shelf_life_days": item.shelf_life_days,
                "expiry_date": expiry,
                "remark": item.remark,
            }
        )
    return {
        "id": row.id,
        "receipt_no": row.receipt_no,
        "supplier_id": row.supplier_id,
        "supplier_name": row.supplier.name,
        "receipt_date": row.receipt_date,
        "warehouse": row.warehouse,
        "status": row.status,
        "notes": row.notes,
        "creator_name": row.creator.name,
        "created_at": row.created_at,
        "items": items,
        "total_amount": round(sum(item["amount"] for item in items), 2),
    }


def _replace_receipt_items(receipt: GoodsReceipt, incoming_items, db: Session):
    receipt.items.clear()
    db.flush()
    seen = set()
    for incoming in incoming_items:
        key = (incoming.product_id, incoming.unit_id, incoming.batch_no or "")
        if key in seen:
            raise HTTPException(status_code=400, detail="同商品、单位和批次请合并为一行")
        seen.add(key)
        product = db.get(Product, incoming.product_id)
        unit = db.get(ProductUnit, incoming.unit_id)
        if not product or not product.active or not unit or unit.product_id != product.id:
            raise HTTPException(status_code=400, detail="进货明细包含无效商品或单位")
        receipt.items.append(
            GoodsReceiptItem(
                product_id=product.id,
                unit_id=unit.id,
                quantity=incoming.quantity,
                unit_price=incoming.unit_price,
                batch_no=_clean(incoming.batch_no),
                production_date=incoming.production_date,
                shelf_life_days=incoming.shelf_life_days or product.shelf_life_days,
                remark=_clean(incoming.remark),
            )
        )


@router.get("/inbound/options")
def inbound_options(
    _: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    suppliers = db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
    products = db.scalars(
        select(Product).options(selectinload(Product.units)).where(Product.active.is_(True)).order_by(Product.category, Product.name)
    ).all()
    return {
        "suppliers": [{"id": row.id, "name": row.name} for row in suppliers],
        "products": [
            {
                "id": row.id,
                "name": row.name,
                "aliases": row.aliases,
                "category": row.category,
                "shelf_life_days": row.shelf_life_days,
                "units": [
                    {
                        "id": unit.id,
                        "name": unit.name,
                        "is_base": unit.is_base,
                        "conversion_rate": float(unit.conversion_rate),
                        "reference_purchase_price": float(unit.reference_purchase_price) if unit.reference_purchase_price is not None else None,
                    }
                    for unit in row.units
                ],
            }
            for row in products
        ],
    }


@router.get("/inbound/receipts")
def list_receipts(
    _: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    return [_receipt_output(row) for row in db.scalars(_receipt_query().order_by(GoodsReceipt.receipt_date.desc(), GoodsReceipt.id.desc())).all()]


@router.post("/inbound/receipts")
def create_receipt(
    data: GoodsReceiptIn,
    user: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier or not supplier.active:
        raise HTTPException(status_code=400, detail="请选择有效供应商")
    receipt = GoodsReceipt(
        receipt_no=f"RK{datetime_number()}",
        supplier_id=supplier.id,
        created_by=user.id,
        receipt_date=data.receipt_date,
        warehouse=_clean(data.warehouse),
        notes=_clean(data.notes),
        status="confirmed",
    )
    db.add(receipt)
    db.flush()
    _replace_receipt_items(receipt, data.items, db)
    warehouse_service.sync_receipt(db, receipt)
    warehouse_service.rebuild_requisitions(db)
    db.commit()
    return _receipt_output(db.scalar(_receipt_query().where(GoodsReceipt.id == receipt.id)))


@router.put("/inbound/receipts/{receipt_id}")
def update_receipt(
    receipt_id: int,
    data: GoodsReceiptIn,
    _: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    receipt = db.scalar(_receipt_query().where(GoodsReceipt.id == receipt_id))
    if not receipt:
        raise HTTPException(status_code=404, detail="进货单不存在")
    if db.scalar(select(PurchaseReturn.id).where(PurchaseReturn.receipt_id == receipt_id).limit(1)):
        raise HTTPException(status_code=400, detail="该进货单已有退货记录，不能直接修改，请新增调整单")
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier or not supplier.active:
        raise HTTPException(status_code=400, detail="请选择有效供应商")
    receipt.supplier_id = supplier.id
    receipt.receipt_date = data.receipt_date
    receipt.warehouse = _clean(data.warehouse)
    receipt.notes = _clean(data.notes)
    _replace_receipt_items(receipt, data.items, db)
    warehouse_service.sync_receipt(db, receipt)
    warehouse_service.rebuild_requisitions(db)
    db.commit()
    return _receipt_output(db.scalar(_receipt_query().where(GoodsReceipt.id == receipt.id)))


@router.get("/inbound/details")
def inbound_details(
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_id: int | None = None,
    product_id: int | None = None,
    keyword: str = "",
    _: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    statement = (
        select(GoodsReceiptItem)
        .join(GoodsReceipt)
        .options(
            selectinload(GoodsReceiptItem.receipt).selectinload(GoodsReceipt.supplier),
            selectinload(GoodsReceiptItem.receipt).selectinload(GoodsReceipt.creator),
            selectinload(GoodsReceiptItem.product),
            selectinload(GoodsReceiptItem.unit),
        )
        .order_by(GoodsReceipt.receipt_date.desc(), GoodsReceiptItem.id.desc())
    )
    if date_from:
        statement = statement.where(GoodsReceipt.receipt_date >= date_from)
    if date_to:
        statement = statement.where(GoodsReceipt.receipt_date <= date_to)
    if supplier_id:
        statement = statement.where(GoodsReceipt.supplier_id == supplier_id)
    if product_id:
        statement = statement.where(GoodsReceiptItem.product_id == product_id)
    term = keyword.strip().lower()
    rows = []
    for item in db.scalars(statement.limit(2000)).all():
        if term and term not in f"{item.receipt.receipt_no}{item.product.name}{item.batch_no or ''}{item.receipt.supplier.name}".lower():
            continue
        expiry = item.production_date + timedelta(days=item.shelf_life_days) if item.production_date and item.shelf_life_days else None
        rows.append({
            "id": item.id,
            "receipt_id": item.receipt_id,
            "receipt_no": item.receipt.receipt_no,
            "receipt_date": item.receipt.receipt_date,
            "supplier_id": item.receipt.supplier_id,
            "supplier_name": item.receipt.supplier.name,
            "product_id": item.product_id,
            "product_name": item.product.name,
            "category": item.product.category,
            "quantity": float(item.quantity),
            "unit_name": item.unit.name,
            "unit_price": float(item.unit_price),
            "amount": round(float(item.quantity * item.unit_price), 2),
            "batch_no": item.batch_no,
            "production_date": item.production_date,
            "shelf_life_days": item.shelf_life_days,
            "expiry_date": expiry,
            "warehouse": item.receipt.warehouse,
            "creator_name": item.receipt.creator.name,
        })
    return {"rows": rows, "total_amount": round(sum(row["amount"] for row in rows), 2)}


def _return_query():
    return select(PurchaseReturn).options(
        selectinload(PurchaseReturn.supplier),
        selectinload(PurchaseReturn.receipt),
        selectinload(PurchaseReturn.creator),
        selectinload(PurchaseReturn.items).selectinload(PurchaseReturnItem.product),
        selectinload(PurchaseReturn.items).selectinload(PurchaseReturnItem.unit),
    )


def _return_output(row: PurchaseReturn) -> dict:
    items = [{
        "id": item.id, "product_id": item.product_id, "product_name": item.product.name,
        "unit_id": item.unit_id, "unit_name": item.unit.name, "quantity": float(item.quantity),
        "unit_price": float(item.unit_price), "amount": round(float(item.quantity * item.unit_price), 2),
        "batch_no": item.batch_no, "remark": item.remark,
    } for item in row.items]
    return {
        "id": row.id, "return_no": row.return_no, "supplier_id": row.supplier_id,
        "supplier_name": row.supplier.name, "receipt_id": row.receipt_id,
        "receipt_no": row.receipt.receipt_no if row.receipt else None, "return_date": row.return_date,
        "reason": row.reason, "notes": row.notes, "creator_name": row.creator.name,
        "created_at": row.created_at, "items": items,
        "total_amount": round(sum(item["amount"] for item in items), 2),
    }


@router.get("/inbound/returns")
def list_returns(
    _: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    return [_return_output(row) for row in db.scalars(_return_query().order_by(PurchaseReturn.return_date.desc(), PurchaseReturn.id.desc())).all()]


@router.post("/inbound/returns")
def create_return(
    data: PurchaseReturnIn,
    user: User = Depends(require_permission("inbound_management")),
    db: Session = Depends(get_db),
):
    if not data.reason.strip():
        raise HTTPException(status_code=400, detail="请填写退货原因")
    receipt = db.scalar(_receipt_query().where(GoodsReceipt.id == data.receipt_id)) if data.receipt_id else None
    if receipt and receipt.supplier_id != data.supplier_id:
        raise HTTPException(status_code=400, detail="退货供应商与原进货单不一致")
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=400, detail="供应商不存在")
    receipt_items = {(item.product_id, item.unit_id, item.batch_no or ""): item for item in receipt.items} if receipt else {}
    returned = {}
    if receipt:
        existing = db.execute(
            select(PurchaseReturnItem.product_id, PurchaseReturnItem.unit_id, PurchaseReturnItem.batch_no, func.sum(PurchaseReturnItem.quantity))
            .join(PurchaseReturn)
            .where(PurchaseReturn.receipt_id == receipt.id)
            .group_by(PurchaseReturnItem.product_id, PurchaseReturnItem.unit_id, PurchaseReturnItem.batch_no)
        ).all()
        returned = {(pid, uid, batch or ""): Decimal(str(qty)) for pid, uid, batch, qty in existing}
    order = PurchaseReturn(
        return_no=f"TH{datetime_number()}", supplier_id=supplier.id, receipt_id=receipt.id if receipt else None,
        created_by=user.id, return_date=data.return_date, reason=data.reason.strip(), notes=_clean(data.notes),
    )
    db.add(order)
    for incoming in data.items:
        product = db.get(Product, incoming.product_id)
        unit = db.get(ProductUnit, incoming.unit_id)
        if not product or not unit or unit.product_id != product.id:
            raise HTTPException(status_code=400, detail="退货明细包含无效商品或单位")
        key = (incoming.product_id, incoming.unit_id, incoming.batch_no or "")
        if receipt:
            source = receipt_items.get(key)
            if not source:
                raise HTTPException(status_code=400, detail=f"{product.name}的单位或批次不在原进货单中")
            available = source.quantity - returned.get(key, Decimal("0"))
            if incoming.quantity > available:
                raise HTTPException(status_code=400, detail=f"{product.name}退货数量超过可退数量 {float(available):g}")
        order.items.append(PurchaseReturnItem(
            product_id=product.id, unit_id=unit.id, quantity=incoming.quantity,
            unit_price=incoming.unit_price, batch_no=_clean(incoming.batch_no), remark=_clean(incoming.remark),
        ))
    warehouse_service.sync_return(db, order)
    warehouse_service.rebuild_requisitions(db)
    db.commit()
    return _return_output(db.scalar(_return_query().where(PurchaseReturn.id == order.id)))


@router.get("/labels/sales-orders")
def label_sales_orders(
    _: User = Depends(require_permission("label_printing")),
    db: Session = Depends(get_db),
):
    orders = db.scalars(
        select(SalesOrder)
        .options(
            selectinload(SalesOrder.customer),
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
        )
        .where(SalesOrder.status == "confirmed")
        .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
        .limit(300)
    ).all()
    output = []
    for order in orders:
        picking_task = db.scalar(
            select(PickingTask)
            .options(selectinload(PickingTask.items))
            .where(PickingTask.sales_order_id == order.id)
        )
        picking_codes = {
            row.sales_order_item_id: row.scan_code for row in (picking_task.items if picking_task else [])
        }
        items = []
        cutoff = order.delivery_date or order.order_date
        for item in order.items:
            latest_batch = db.scalar(
                select(GoodsReceiptItem)
                .join(GoodsReceipt)
                .where(
                    GoodsReceiptItem.product_id == item.product_id,
                    GoodsReceipt.receipt_date <= cutoff,
                )
                .order_by(GoodsReceipt.receipt_date.desc(), GoodsReceiptItem.id.desc())
                .limit(1)
            )
            items.append({
                "id": item.id, "product_name": item.display_name or item.product.name,
                "canonical_product_name": item.product.name, "quantity": float(item.quantity),
                "unit_name": item.unit.name,
                "production_date": latest_batch.production_date if latest_batch else None,
                "batch_no": latest_batch.batch_no if latest_batch else None,
                "shelf_life_days": (
                    latest_batch.shelf_life_days
                    if latest_batch and latest_batch.shelf_life_days
                    else item.product.shelf_life_days
                ),
                "picking_code": picking_codes.get(item.id),
            })
        output.append({
            "id": order.id, "order_no": order.order_no, "customer_name": order.customer.name,
            "customer_code": order.customer.customer_code, "order_date": order.order_date,
            "delivery_date": order.delivery_date,
            "picking_task_no": picking_task.task_no if picking_task else None,
            "items": items,
        })
    return output


def datetime_number() -> str:
    from datetime import datetime
    return f"{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}"
