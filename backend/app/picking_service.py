from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import PickingTask, PickingTaskItem, SalesOrder


def _refresh_status(task: PickingTask) -> None:
    if not task.items:
        task.status = "pending"
        return
    all_picked = all(row.picked_at for row in task.items)
    all_loaded = all(row.loaded_at for row in task.items)
    any_picked = any(row.picked_at for row in task.items)
    any_loaded = any(row.loaded_at for row in task.items)
    task.status = (
        "completed" if all_loaded else
        "delivering" if any_loaded else
        "picked" if all_picked else
        "picking" if any_picked else
        "pending"
    )


def sync_picking_task(db: Session, order: SalesOrder) -> dict:
    """Synchronise a changed sales order into an already generated picking task."""
    task = db.scalar(
        select(PickingTask)
        .options(selectinload(PickingTask.items))
        .where(PickingTask.sales_order_id == order.id)
    )
    if not task:
        return {"task_found": False, "added": 0, "updated": 0}

    task.customer_id = order.customer_id
    task.sorter_id = order.customer.sorter_id
    task.delivery_id = order.customer.delivery_id
    task.delivery_date = order.delivery_date
    existing_by_sales_item = {row.sales_order_item_id: row for row in task.items}
    added = updated = 0
    for sales_item in order.items:
        picking_item = existing_by_sales_item.get(sales_item.id)
        if not picking_item:
            task.items.append(PickingTaskItem(
                sales_order_item_id=sales_item.id,
                product_id=sales_item.product_id,
                product_name=sales_item.display_name or sales_item.product.name,
                quantity=sales_item.quantity,
                unit_name=sales_item.unit.name,
                scan_code=uuid4().hex + uuid4().hex[:8],
            ))
            added += 1
            continue
        quantity_changed = picking_item.quantity != sales_item.quantity
        picking_item.product_id = sales_item.product_id
        picking_item.product_name = sales_item.display_name or sales_item.product.name
        picking_item.quantity = sales_item.quantity
        picking_item.unit_name = sales_item.unit.name
        if quantity_changed:
            # An add-on to a scanned line must be checked and scanned again.
            picking_item.picked_at = None
            picking_item.loaded_at = None
            picking_item.exception_note = None
            sales_item.delivered_quantity = None
            sales_item.accepted_quantity = None
            sales_item.acceptance_variance_reason = None
            order.acceptance_status = "pending"
            order.accepted_at = None
            order.accepted_by = None
        updated += 1
    _refresh_status(task)
    return {"task_found": True, "added": added, "updated": updated}
