from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import current_user, effective_permissions, require_permission
from app.database import get_db
from app.models import (
    Customer,
    PickingTaskItem,
    Product,
    ProductUnit,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    SalesProcurementLink,
    User,
)
from app.schemas import FinanceSettlementIn


router = APIRouter(prefix="/api/finance", tags=["财务管理"])


def _finance_or_sales(user: User = Depends(current_user)) -> User:
    if not ({"finance_management", "sales_order_management"} & effective_permissions(user)):
        raise HTTPException(status_code=403, detail="当前账号没有财务或销售单权限")
    return user


def _order_query():
    return select(SalesOrder).options(
        selectinload(SalesOrder.customer),
        selectinload(SalesOrder.creator),
        selectinload(SalesOrder.accepter),
        selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
        selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
        selectinload(SalesOrder.procurement_links)
        .selectinload(SalesProcurementLink.purchase_order)
        .selectinload(PurchaseOrder.items)
        .selectinload(PurchaseOrderItem.unit),
    )


def _money(value: Decimal | float | int) -> float:
    return round(float(value or 0), 2)


def _delivery_map(db: Session, item_ids: list[int]) -> set[int]:
    if not item_ids:
        return set()
    return set(db.scalars(
        select(PickingTaskItem.sales_order_item_id).where(
            PickingTaskItem.sales_order_item_id.in_(item_ids),
            PickingTaskItem.loaded_at.is_not(None),
        )
    ).all())


def _purchase_cost_map(order: SalesOrder) -> dict[int, Decimal]:
    costs: dict[int, Decimal] = {}
    for link in order.procurement_links:
        for item in link.purchase_order.items:
            if item.unit.conversion_rate:
                costs[item.product_id] = item.unit_price / item.unit.conversion_rate
    return costs


def _item_finance(item: SalesOrderItem, loaded_ids: set[int], purchase_costs: dict[int, Decimal]) -> dict:
    ordered = Decimal(item.quantity or 0)
    delivered = item.delivered_quantity
    if delivered is None and item.id in loaded_ids:
        delivered = ordered
    accepted = item.accepted_quantity
    cost_unit = item.cost_unit_price
    cost_source = "已核定成本"
    if cost_unit is None and item.product_id in purchase_costs:
        cost_unit = purchase_costs[item.product_id] * item.unit.conversion_rate
        cost_source = "采购单成本"
    if cost_unit is None and item.unit.reference_purchase_price is not None:
        cost_unit = item.unit.reference_purchase_price
        cost_source = "商品参考进价"
    ordered_amount = ordered * item.unit_price
    delivered_amount = (delivered or Decimal("0")) * item.unit_price
    accepted_amount = (accepted or Decimal("0")) * item.unit_price
    cost_amount = (accepted or Decimal("0")) * cost_unit if cost_unit is not None else None
    gross_profit = accepted_amount - cost_amount if cost_amount is not None else None
    return {
        "id": item.id,
        "product_id": item.product_id,
        "product_name": item.display_name or item.product.name,
        "canonical_product_name": item.product.name,
        "category": item.product.category,
        "unit_name": item.unit.name,
        "conversion_rate": float(item.unit.conversion_rate),
        "ordered_quantity": float(ordered),
        "delivered_quantity": float(delivered) if delivered is not None else None,
        "accepted_quantity": float(accepted) if accepted is not None else None,
        "unit_price": float(item.unit_price),
        "cost_unit_price": float(cost_unit) if cost_unit is not None else None,
        "cost_source": cost_source if cost_unit is not None else "成本待维护",
        "ordered_amount": _money(ordered_amount),
        "delivered_amount": _money(delivered_amount),
        "accepted_amount": _money(accepted_amount),
        "cost_amount": _money(cost_amount) if cost_amount is not None else None,
        "gross_profit": _money(gross_profit) if gross_profit is not None else None,
        "variance_quantity": float((delivered or Decimal("0")) - (accepted or Decimal("0"))) if accepted is not None else None,
        "variance_reason": item.acceptance_variance_reason,
    }


def _order_finance(order: SalesOrder, loaded_ids: set[int]) -> dict:
    purchase_costs = _purchase_cost_map(order)
    items = [_item_finance(item, loaded_ids, purchase_costs) for item in order.items]
    accepted_amount = sum(Decimal(str(item["accepted_amount"])) for item in items)
    calculable_profit = sum(
        Decimal(str(item["gross_profit"])) for item in items if item["gross_profit"] is not None
    )
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_id": order.customer_id,
        "customer_name": order.customer.name,
        "order_date": order.order_date,
        "delivery_date": order.delivery_date,
        "business_date": order.delivery_date or order.order_date,
        "creator_name": order.creator.name,
        "acceptance_status": order.acceptance_status or "pending",
        "accepted_at": order.accepted_at,
        "accepted_by_name": order.accepter.name if order.accepter else None,
        "supplement_amount": _money(order.supplement_amount or 0),
        "invoice_amount": _money(order.invoice_amount or 0),
        "invoice_date": order.invoice_date,
        "invoice_status": "unbilled" if not order.invoice_amount else "invoiced" if Decimal(order.invoice_amount) >= accepted_amount and accepted_amount else "partial",
        "ordered_amount": _money(sum(Decimal(str(item["ordered_amount"])) for item in items)),
        "delivered_amount": _money(sum(Decimal(str(item["delivered_amount"])) for item in items)),
        "accepted_amount": _money(accepted_amount),
        "gross_profit": _money(calculable_profit),
        "missing_cost_items": sum(item["accepted_quantity"] is not None and item["cost_unit_price"] is None for item in items),
        "variance_items": sum(item["variance_quantity"] not in (None, 0) for item in items),
        "items": items,
    }


@router.get("/options")
def finance_options(
    _: User = Depends(require_permission("finance_management")),
    db: Session = Depends(get_db),
):
    customers = db.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.name)).all()
    categories = db.scalars(select(Product.category).distinct().order_by(Product.category)).all()
    return {
        "customers": [{"id": row.id, "name": row.name} for row in customers],
        "categories": [value for value in categories if value],
    }


@router.get("/dashboard")
def finance_dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: int | None = None,
    category: str | None = None,
    _: User = Depends(require_permission("finance_management")),
    db: Session = Depends(get_db),
):
    start = date_from or date.today()
    end = date_to or start
    if end < start:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    if (end - start).days > 366:
        raise HTTPException(status_code=400, detail="单次最多统计367天")
    statement = _order_query().where(
        SalesOrder.status == "confirmed",
        func.coalesce(SalesOrder.delivery_date, SalesOrder.order_date) >= start,
        func.coalesce(SalesOrder.delivery_date, SalesOrder.order_date) <= end,
    ).order_by(SalesOrder.delivery_date.desc(), SalesOrder.id.desc())
    if customer_id:
        statement = statement.where(SalesOrder.customer_id == customer_id)
    orders = db.scalars(statement.limit(5000)).unique().all()
    item_ids = [item.id for order in orders for item in order.items]
    loaded_ids = _delivery_map(db, item_ids)
    order_rows = [_order_finance(order, loaded_ids) for order in orders]
    if category:
        for row in order_rows:
            row["items"] = [item for item in row["items"] if item["category"] == category]
            row["ordered_amount"] = _money(sum(item["ordered_amount"] for item in row["items"]))
            row["delivered_amount"] = _money(sum(item["delivered_amount"] for item in row["items"]))
            row["accepted_amount"] = _money(sum(item["accepted_amount"] for item in row["items"]))
            row["gross_profit"] = _money(sum(item["gross_profit"] or 0 for item in row["items"]))
            row["missing_cost_items"] = sum(item["accepted_quantity"] is not None and item["cost_unit_price"] is None for item in row["items"])
            row["variance_items"] = sum(item["variance_quantity"] not in (None, 0) for item in row["items"])
        order_rows = [row for row in order_rows if row["items"]]

    product_groups = {}
    customer_groups = defaultdict(lambda: {"amount": 0.0, "gross_profit": 0.0, "orders": set()})
    daily_groups = defaultdict(lambda: {"ordered_amount": 0.0, "delivered_amount": 0.0, "accepted_amount": 0.0, "invoice_amount": 0.0, "gross_profit": 0.0, "order_count": 0})
    for order in order_rows:
        customer_group = customer_groups[order["customer_name"]]
        customer_group["amount"] += order["accepted_amount"]
        customer_group["gross_profit"] += order["gross_profit"]
        customer_group["orders"].add(order["id"])
        day = order["business_date"].isoformat()
        daily = daily_groups[day]
        daily["ordered_amount"] += order["ordered_amount"]
        daily["delivered_amount"] += order["delivered_amount"]
        daily["accepted_amount"] += order["accepted_amount"]
        daily["invoice_amount"] += order["invoice_amount"]
        daily["gross_profit"] += order["gross_profit"]
        daily["order_count"] += 1
        for item in order["items"]:
            group = product_groups.setdefault(item["product_id"], {
                "product_id": item["product_id"], "product_name": item["canonical_product_name"],
                "category": item["category"], "base_quantity": 0.0, "amount": 0.0,
                "gross_profit": 0.0, "missing_cost": False,
            })
            group["base_quantity"] += (item["accepted_quantity"] or 0) * item["conversion_rate"]
            group["amount"] += item["accepted_amount"]
            group["gross_profit"] += item["gross_profit"] or 0
            group["missing_cost"] = group["missing_cost"] or (item["accepted_quantity"] is not None and item["cost_unit_price"] is None)

    metrics = {
        "sales_amount": _money(sum(row["accepted_amount"] for row in order_rows)),
        "ordered_amount": _money(sum(row["ordered_amount"] for row in order_rows)),
        "delivered_amount": _money(sum(row["delivered_amount"] for row in order_rows)),
        "accepted_amount": _money(sum(row["accepted_amount"] for row in order_rows)),
        "invoice_amount": _money(sum(row["invoice_amount"] for row in order_rows)),
        "supplement_amount": _money(sum(row["supplement_amount"] for row in order_rows)),
        "gross_profit": _money(sum(row["gross_profit"] for row in order_rows)),
        "order_count": len(order_rows),
        "customer_count": len({row["customer_id"] for row in order_rows}),
        "max_order_amount": _money(max((row["ordered_amount"] for row in order_rows), default=0)),
        "pending_acceptance_count": sum(row["acceptance_status"] != "accepted" for row in order_rows),
        "variance_order_count": sum(bool(row["variance_items"]) for row in order_rows),
        "missing_cost_items": sum(row["missing_cost_items"] for row in order_rows),
    }
    products = sorted(product_groups.values(), key=lambda row: row["amount"], reverse=True)
    for row in products:
        row["base_quantity"] = round(row["base_quantity"], 4)
        row["amount"] = _money(row["amount"])
        row["gross_profit"] = _money(row["gross_profit"])
    customers = [
        {"customer_name": name, "amount": _money(value["amount"]), "gross_profit": _money(value["gross_profit"]), "order_count": len(value["orders"])}
        for name, value in customer_groups.items()
    ]
    customers.sort(key=lambda row: row["amount"], reverse=True)
    daily = [{"date": key, **{name: _money(value) if name != "order_count" else value for name, value in values.items()}} for key, values in sorted(daily_groups.items())]
    return {
        "date_from": start,
        "date_to": end,
        "metrics": metrics,
        "orders": order_rows,
        "product_ranking": products,
        "customer_ranking": customers,
        "daily": daily,
    }


@router.get("/orders/{order_id}")
def finance_order_detail(
    order_id: int,
    _: User = Depends(_finance_or_sales),
    db: Session = Depends(get_db),
):
    order = db.scalar(_order_query().where(SalesOrder.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="销售单不存在")
    loaded_ids = _delivery_map(db, [item.id for item in order.items])
    return _order_finance(order, loaded_ids)


@router.put("/orders/{order_id}/settlement")
def save_finance_settlement(
    order_id: int,
    data: FinanceSettlementIn,
    user: User = Depends(_finance_or_sales),
    db: Session = Depends(get_db),
):
    order = db.scalar(_order_query().where(SalesOrder.id == order_id))
    if not order or order.status != "confirmed":
        raise HTTPException(status_code=404, detail="已确认销售单不存在")
    finance_enabled = "finance_management" in effective_permissions(user)
    incoming = {row.sales_order_item_id: row for row in data.items}
    if set(incoming) != {row.id for row in order.items}:
        raise HTTPException(status_code=400, detail="验收明细与销售单商品不一致，请刷新后重试")
    for item in order.items:
        row = incoming[item.id]
        if row.accepted_quantity is not None and row.delivered_quantity is None:
            raise HTTPException(status_code=400, detail=f"{item.display_name or item.product.name} 请先填写实配数量")
        if row.accepted_quantity is not None and row.delivered_quantity != row.accepted_quantity and not (row.variance_reason or "").strip():
            raise HTTPException(status_code=400, detail=f"{item.display_name or item.product.name} 实配与验收数量不同，请填写差异原因")
        item.delivered_quantity = row.delivered_quantity
        item.accepted_quantity = row.accepted_quantity
        item.acceptance_variance_reason = (row.variance_reason or "").strip() or None
        if finance_enabled:
            item.cost_unit_price = row.cost_unit_price
    accepted_values = [item.accepted_quantity for item in order.items]
    order.acceptance_status = "accepted" if all(value is not None for value in accepted_values) else "partial" if any(value is not None for value in accepted_values) else "pending"
    if order.acceptance_status == "accepted":
        order.accepted_at = datetime.now()
        order.accepted_by = user.id
    else:
        order.accepted_at = None
        order.accepted_by = None
    if finance_enabled:
        if data.invoice_amount and not data.invoice_date:
            raise HTTPException(status_code=400, detail="填写开票金额后必须选择开票日期")
        order.invoice_amount = data.invoice_amount
        order.invoice_date = data.invoice_date if data.invoice_amount else None
    db.commit()
    saved = db.scalar(_order_query().where(SalesOrder.id == order.id))
    loaded_ids = _delivery_map(db, [item.id for item in saved.items])
    return {"message": "配送验收与财务数据已保存", "order": _order_finance(saved, loaded_ids)}
