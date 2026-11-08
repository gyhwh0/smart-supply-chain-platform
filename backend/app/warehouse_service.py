from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    GoodsReceipt, PickingTask, PickingTaskItem, Product, ProductUnit, PurchaseOrder, PurchaseOrderItem,
    PurchaseRequisition, PurchaseRequisitionItem, PurchaseRequisitionOrder, PurchaseReturn, SalesOrderItem,
    User, WarehouseDocument, WarehouseDocumentItem,
)


TYPE_PREFIX = {"inbound": "WRK", "outbound": "WCK", "material": "WLL", "preparation": "WBH"}


def document_query():
    return select(WarehouseDocument).options(
        selectinload(WarehouseDocument.creator),
        selectinload(WarehouseDocument.items).selectinload(WarehouseDocumentItem.product),
        selectinload(WarehouseDocument.items).selectinload(WarehouseDocumentItem.unit),
    )


def requisition_query():
    return select(PurchaseRequisition).options(
        selectinload(PurchaseRequisition.creator),
        selectinload(PurchaseRequisition.warehouse_document),
        selectinload(PurchaseRequisition.items).selectinload(PurchaseRequisitionItem.product),
        selectinload(PurchaseRequisition.items).selectinload(PurchaseRequisitionItem.unit),
        selectinload(PurchaseRequisition.order_links).selectinload(
            PurchaseRequisitionOrder.purchase_order
        ).selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
        selectinload(PurchaseRequisition.order_links).selectinload(
            PurchaseRequisitionOrder.purchase_order
        ).selectinload(PurchaseOrder.supplier),
    )


def _ordered_base(requisition: PurchaseRequisition) -> dict[int, Decimal]:
    ordered = defaultdict(lambda: Decimal("0"))
    for link in requisition.order_links:
        if link.purchase_order.status == "cancelled":
            continue
        for item in link.purchase_order.items:
            ordered[item.product_id] += item.quantity * item.unit.conversion_rate
    return ordered


def requisition_output(row: PurchaseRequisition) -> dict:
    ordered = _ordered_base(row)
    items = []
    for item in row.items:
        ordered_base = ordered[item.product_id]
        remaining_base = max(Decimal("0"), item.base_quantity - ordered_base)
        items.append({
            "id": item.id, "product_id": item.product_id, "product_name": item.product.name,
            "category": item.product.category, "unit_id": item.unit_id, "unit_name": item.unit.name,
            "quantity": float(item.quantity),
            "ordered_quantity": float(ordered_base / item.unit.conversion_rate),
            "remaining_quantity": float(remaining_base / item.unit.conversion_rate),
            "remaining_base_quantity": float(remaining_base),
        })
    return {
        "id": row.id, "requisition_no": row.requisition_no,
        "warehouse_document_id": row.warehouse_document_id,
        "warehouse_document_no": row.warehouse_document.document_no,
        "needed_date": row.needed_date, "target_name": row.target_name,
        "status": row.status, "creator_name": row.creator.name, "created_at": row.created_at,
        "items": items,
        "purchase_orders": [{
            "id": link.purchase_order.id, "order_no": link.purchase_order.order_no,
            "supplier_name": link.purchase_order.supplier.name, "status": link.purchase_order.status,
        } for link in row.order_links],
    }


def output(row: WarehouseDocument) -> dict:
    return {
        "id": row.id, "document_no": row.document_no, "document_type": row.document_type,
        "business_date": row.business_date, "warehouse": row.warehouse,
        "target_name": row.target_name, "source_type": row.source_type,
        "source_id": row.source_id, "source_no": row.source_no, "status": row.status,
        "notes": row.notes, "creator_name": row.creator.name, "created_at": row.created_at,
        "items": [{
            "id": item.id, "product_id": item.product_id, "product_name": item.product.name,
            "category": item.product.category, "unit_id": item.unit_id, "unit_name": item.unit.name,
            "quantity": float(item.quantity), "base_quantity": float(item.base_quantity),
            "batch_no": item.batch_no, "remark": item.remark,
        } for item in row.items],
    }


def _system_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == "system_admin"))
    if not user:
        user = db.scalar(select(User).where(User.active.is_(True)).order_by(User.id))
    if not user:
        raise RuntimeError("系统中没有可用于仓库联动的账号")
    return user


def _number(document_type: str) -> str:
    return f"{TYPE_PREFIX[document_type]}{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}"


def replace_items(document: WarehouseDocument, rows: list[dict], db: Session):
    document.items.clear()
    db.flush()
    for row in rows:
        product = db.get(Product, row["product_id"])
        unit = db.get(ProductUnit, row["unit_id"])
        if not product or not unit or unit.product_id != product.id:
            raise ValueError("仓库单据中包含无效商品或单位")
        quantity = Decimal(str(row["quantity"]))
        document.items.append(WarehouseDocumentItem(
            product_id=product.id, unit_id=unit.id, quantity=quantity,
            base_quantity=quantity * unit.conversion_rate,
            batch_no=(row.get("batch_no") or "").strip() or None,
            location=(row.get("location") or product.default_location or "").strip() or None,
            production_date=row.get("production_date"),
            shelf_life_days=row.get("shelf_life_days") or product.shelf_life_days,
            unit_cost_base=(Decimal(str(row["unit_price"])) / unit.conversion_rate) if row.get("unit_price") is not None else (
                Decimal(unit.reference_purchase_price) / unit.conversion_rate if unit.reference_purchase_price is not None else None
            ),
            supplier_id=row.get("supplier_id"),
            remark=(row.get("remark") or "").strip() or None,
        ))


def upsert_source_document(
    db: Session, *, document_type: str, business_date: date, source_type: str,
    source_id: int, source_no: str, target_name: str | None, warehouse: str | None,
    rows: list[dict], status: str = "confirmed", notes: str | None = None,
) -> WarehouseDocument:
    document = db.scalar(select(WarehouseDocument).where(
        WarehouseDocument.document_type == document_type,
        WarehouseDocument.source_type == source_type,
        WarehouseDocument.source_id == source_id,
    ))
    if not document:
        document = WarehouseDocument(
            document_no=_number(document_type), document_type=document_type,
            source_type=source_type, source_id=source_id, source_no=source_no,
            created_by=_system_user(db).id,
        )
        db.add(document)
    document.business_date = business_date
    document.warehouse = warehouse or "主仓库"
    document.target_name = target_name
    document.status = status
    document.notes = notes
    replace_items(document, rows, db)
    db.flush()
    return document


def sync_receipt(db: Session, receipt: GoodsReceipt):
    db.flush()
    receipt = db.scalar(
        select(GoodsReceipt).options(selectinload(GoodsReceipt.supplier), selectinload(GoodsReceipt.items))
        .where(GoodsReceipt.id == receipt.id)
    )
    upsert_source_document(
        db, document_type="inbound", business_date=receipt.receipt_date,
        source_type="goods_receipt", source_id=receipt.id, source_no=receipt.receipt_no,
        target_name=receipt.supplier.name, warehouse=receipt.warehouse,
        notes="进货单确认后自动入库",
        rows=[{"product_id": i.product_id, "unit_id": i.unit_id, "quantity": i.quantity,
               "unit_price": i.unit_price, "supplier_id": receipt.supplier_id,
               "batch_no": i.batch_no, "production_date": i.production_date,
               "shelf_life_days": i.shelf_life_days, "remark": i.remark} for i in receipt.items],
    )


def sync_return(db: Session, order: PurchaseReturn):
    db.flush()
    order = db.scalar(
        select(PurchaseReturn).options(selectinload(PurchaseReturn.supplier), selectinload(PurchaseReturn.items))
        .where(PurchaseReturn.id == order.id)
    )
    upsert_source_document(
        db, document_type="outbound", business_date=order.return_date,
        source_type="purchase_return", source_id=order.id, source_no=order.return_no,
        target_name=order.supplier.name, warehouse="主仓库", notes=f"进货退货：{order.reason}",
        rows=[{"product_id": i.product_id, "unit_id": i.unit_id, "quantity": i.quantity,
               "batch_no": i.batch_no, "remark": i.remark} for i in order.items],
    )


def sync_picking_task(db: Session, task: PickingTask):
    task = db.scalar(
        select(PickingTask).options(
            selectinload(PickingTask.customer), selectinload(PickingTask.sales_order),
            selectinload(PickingTask.items).selectinload(PickingTaskItem.sales_order_item).selectinload(SalesOrderItem.unit),
        ).where(PickingTask.id == task.id)
    )
    rows = [{
        "product_id": item.product_id, "unit_id": item.sales_order_item.unit_id,
        "quantity": item.quantity, "remark": f"客户：{task.customer.name}",
    } for item in task.items]
    prep = upsert_source_document(
        db, document_type="preparation", business_date=task.delivery_date or task.sales_order.order_date,
        source_type="picking_task", source_id=task.id, source_no=task.task_no,
        target_name=task.customer.name, warehouse="主仓库", rows=rows,
        status="released" if task.status == "completed" else "confirmed",
        notes="分拣任务自动占用库存",
    )
    if task.status == "completed":
        upsert_source_document(
            db, document_type="outbound", business_date=task.delivery_date or task.sales_order.order_date,
            source_type="picking_task", source_id=task.id, source_no=task.task_no,
            target_name=task.customer.name, warehouse="主仓库", rows=rows,
            notes="配送装车完成后自动出库",
        )
    return prep


def stock_rows(db: Session) -> list[dict]:
    documents = db.scalars(document_query().where(WarehouseDocument.status == "confirmed")).unique().all()
    balances = defaultdict(lambda: {"on_hand": Decimal("0"), "reserved": Decimal("0"), "inbound": Decimal("0"), "outbound": Decimal("0"), "material": Decimal("0")})
    products = {}
    for document in documents:
        for item in document.items:
            products[item.product_id] = item.product
            row = balances[item.product_id]
            if document.document_type == "inbound":
                row["on_hand"] += item.base_quantity; row["inbound"] += item.base_quantity
            elif document.document_type == "outbound":
                row["on_hand"] -= item.base_quantity; row["outbound"] += item.base_quantity
            elif document.document_type == "material":
                row["on_hand"] -= item.base_quantity; row["material"] += item.base_quantity
            elif document.document_type == "preparation":
                row["reserved"] += item.base_quantity
    output_rows = []
    for product_id, values in balances.items():
        product = products[product_id]
        base_unit = next((unit for unit in product.units if unit.is_base), product.units[0] if product.units else None)
        output_rows.append({
            "product_id": product_id, "product_name": product.name, "category": product.category,
            "unit_name": base_unit.name if base_unit else "基础单位",
            "on_hand": float(values["on_hand"]), "reserved": float(values["reserved"]),
            "available": float(values["on_hand"] - values["reserved"]),
            "total_inbound": float(values["inbound"]), "total_outbound": float(values["outbound"]),
            "total_material": float(values["material"]),
        })
    return sorted(output_rows, key=lambda row: (row["category"], row["product_name"]))


def rebuild_requisitions(db: Session):
    """Allocate stock to preparation documents in date/id order and expose only the uncovered shortage."""
    db.flush()
    documents = db.scalars(document_query().order_by(WarehouseDocument.business_date, WarehouseDocument.id)).unique().all()
    balance = defaultdict(lambda: Decimal("0"))
    for document in documents:
        if document.status not in {"confirmed", "released"}:
            continue
        if document.document_type == "inbound":
            for item in document.items:
                balance[item.product_id] += item.base_quantity
        elif document.document_type in {"outbound", "material"}:
            for item in document.items:
                balance[item.product_id] -= item.base_quantity
        elif document.document_type == "preparation":
            shortages = []
            if document.status == "confirmed":
                for item in document.items:
                    usable = max(Decimal("0"), balance[item.product_id])
                    shortage = max(Decimal("0"), item.base_quantity - usable)
                    balance[item.product_id] -= item.base_quantity
                    if shortage:
                        shortages.append((item, shortage))
            requisition = db.scalar(select(PurchaseRequisition).where(
                PurchaseRequisition.warehouse_document_id == document.id
            ))
            if not requisition:
                requisition = PurchaseRequisition(
                    requisition_no=f"CGXQ{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
                    warehouse_document_id=document.id, needed_date=document.business_date,
                    target_name=document.target_name, created_by=document.created_by,
                )
                db.add(requisition)
                db.flush()
            requisition.needed_date = document.business_date
            requisition.target_name = document.target_name
            requisition.items.clear()
            for item, shortage in shortages:
                requisition.items.append(PurchaseRequisitionItem(
                    product_id=item.product_id, unit_id=item.unit_id,
                    quantity=shortage / item.unit.conversion_rate, base_quantity=shortage,
                ))
            db.flush()
            ordered = _ordered_base(requisition)
            remaining = any(item.base_quantity > ordered[item.product_id] for item in requisition.items)
            requisition.status = "pending" if remaining else "ordered" if requisition.order_links else "sufficient"


def backfill(db: Session):
    receipts = db.scalars(select(GoodsReceipt).options(selectinload(GoodsReceipt.supplier), selectinload(GoodsReceipt.items))).all()
    for receipt in receipts:
        sync_receipt(db, receipt)
    returns = db.scalars(select(PurchaseReturn).options(selectinload(PurchaseReturn.supplier), selectinload(PurchaseReturn.items))).all()
    for order in returns:
        sync_return(db, order)
    tasks = db.scalars(select(PickingTask)).all()
    for task in tasks:
        sync_picking_task(db, task)
    rebuild_requisitions(db)
    db.commit()
