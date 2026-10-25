from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Product, ProductUnit, SalesOrder, SalesOrderItem


def find_daily_order(
    db: Session,
    *,
    customer_id: int,
    order_date: date,
    delivery_date: date | None,
) -> SalesOrder | None:
    """Return the customer's existing order for the same fulfilment day."""
    fulfilment_date = delivery_date or order_date
    return db.scalar(
        select(SalesOrder)
        .options(
            selectinload(SalesOrder.customer),
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
        )
        .where(
            SalesOrder.customer_id == customer_id,
            SalesOrder.status.in_(("draft", "confirmed")),
            func.coalesce(SalesOrder.delivery_date, SalesOrder.order_date) == fulfilment_date,
        )
        .order_by(SalesOrder.id.asc())
    )


def append_note(order: SalesOrder, note: str | None, source_label: str = "加单") -> None:
    cleaned = (note or "").strip()
    if not cleaned:
        return
    line = f"{source_label} {datetime.now():%Y-%m-%d %H:%M}：{cleaned}"
    order.notes = f"{order.notes}\n{line}" if order.notes else line


def add_or_merge_item(
    db: Session,
    order: SalesOrder,
    *,
    product: Product,
    unit: ProductUnit,
    display_name: str,
    specification: str | None,
    quantity: Decimal,
    unit_price: Decimal,
    remark: str | None,
) -> tuple[SalesOrderItem, bool]:
    """Add a new product line or increase its existing line using unit conversion."""
    existing = next((row for row in order.items if row.product_id == product.id), None)
    if not existing:
        item = SalesOrderItem(
            product_id=product.id,
            unit_id=unit.id,
            display_name=display_name,
            specification=(specification or "").strip() or None,
            quantity=quantity,
            unit_price=unit_price,
            remark=(remark or "").strip() or None,
        )
        order.items.append(item)
        return item, True

    existing_unit = existing.unit or db.get(ProductUnit, existing.unit_id)
    converted_quantity = quantity * unit.conversion_rate / existing_unit.conversion_rate
    old_amount = existing.quantity * existing.unit_price
    incoming_amount = quantity * unit_price
    combined_quantity = existing.quantity + converted_quantity
    existing.quantity = combined_quantity
    if combined_quantity:
        existing.unit_price = (old_amount + incoming_amount) / combined_quantity
    if specification and specification.strip() and specification.strip() != (existing.specification or ""):
        existing.specification = "；".join(filter(None, [existing.specification, specification.strip()]))[:120]
    if remark and remark.strip() and remark.strip() != (existing.remark or ""):
        existing.remark = "；".join(filter(None, [existing.remark, f"加单：{remark.strip()}"]))[:255]
    return existing, False
