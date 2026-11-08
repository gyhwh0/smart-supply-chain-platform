from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Category,
    ProcurementSplitAllocation,
    ProcurementSplitPlan,
    ProcurementSplitPlanItem,
    Product,
    ProductSupplier,
    ProductUnit,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    PurchaseRequisitionOrder,
    Quote,
    SalesOrder,
    SalesOrderItem,
    SalesProcurementLink,
    SmartSplitSetting,
    Supplier,
    SupplierTierPrice,
    User,
)


ZERO = Decimal("0")
QTY = Decimal("0.0001")
STRATEGIES = {
    "quota": "配额比例",
    "capacity": "供货能力",
    "price": "价格优先",
    "quality": "质量评分",
}


def decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def quantize(value: Decimal) -> Decimal:
    return max(ZERO, value).quantize(QTY, rounding=ROUND_HALF_UP)


def _setting(db: Session) -> SmartSplitSetting:
    row = db.scalar(select(SmartSplitSetting).where(SmartSplitSetting.name == "default"))
    if not row:
        row = SmartSplitSetting(name="default")
        db.add(row)
        db.flush()
    return row


def quality_score(supplier: Supplier, setting: SmartSplitSetting) -> Decimal:
    on_time_weight = decimal(setting.on_time_weight)
    inspection_weight = decimal(setting.inspection_weight)
    return_weight = decimal(setting.return_weight)
    weight_total = on_time_weight + inspection_weight + return_weight
    if not weight_total:
        return ZERO
    score = (
        decimal(supplier.on_time_rate) * on_time_weight
        + decimal(supplier.inspection_pass_rate) * inspection_weight
        + (Decimal("100") - decimal(supplier.return_rate)) * return_weight
    ) / weight_total
    return quantize(score)


def _assignment_query():
    return select(ProductSupplier).options(
        selectinload(ProductSupplier.product).selectinload(Product.units),
        selectinload(ProductSupplier.supplier),
        selectinload(ProductSupplier.quotes).selectinload(Quote.unit),
        selectinload(ProductSupplier.tier_prices),
    )


def configuration(db: Session) -> dict:
    setting = _setting(db)
    assignments = db.scalars(
        _assignment_query().join(Product, Product.id == ProductSupplier.product_id)
        .where(ProductSupplier.active.is_(True)).order_by(Product.category, Product.name)
    ).unique().all()
    categories = db.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
    return {
        "strategies": [{"value": key, "name": value} for key, value in STRATEGIES.items()],
        "weights": {
            "on_time": float(setting.on_time_weight),
            "inspection": float(setting.inspection_weight),
            "return": float(setting.return_weight),
        },
        "categories": [
            {"id": row.id, "name": row.name, "purchase_loss_rate": float(row.purchase_loss_rate)}
            for row in categories
        ],
        "suppliers": [
            {
                "id": row.id,
                "name": row.name,
                "on_time_rate": float(row.on_time_rate),
                "inspection_pass_rate": float(row.inspection_pass_rate),
                "return_rate": float(row.return_rate),
                "quality_score": float(quality_score(row, setting)),
                "payment_term_days": row.payment_term_days,
            }
            for row in suppliers
        ],
        "assignments": [_assignment_output(row, setting) for row in assignments],
    }


def _assignment_output(row: ProductSupplier, setting: SmartSplitSetting) -> dict:
    base_unit = next((unit for unit in row.product.units if unit.is_base), None)
    normalized_quotes = [
        (quote, quote.price / quote.unit.conversion_rate)
        for quote in row.quotes
        if quote.unit.conversion_rate
    ]
    standard = min(normalized_quotes, key=lambda value: value[1]) if normalized_quotes else None
    return {
        "id": row.id,
        "product_id": row.product_id,
        "product_name": row.product.name,
        "category": row.product.category,
        "supplier_id": row.supplier_id,
        "supplier_name": row.supplier.name,
        "base_unit_name": base_unit.name if base_unit else "基础单位",
        "standard_base_price": float(standard[1]) if standard else None,
        "split_enabled": row.split_enabled,
        "priority": row.priority,
        "daily_capacity_base": float(row.daily_capacity_base) if row.daily_capacity_base is not None else None,
        "order_capacity_base": float(row.order_capacity_base) if row.order_capacity_base is not None else None,
        "quota_percent": float(row.quota_percent),
        "quality_score": float(quality_score(row.supplier, setting)),
        "tier_prices": [
            {
                "id": tier.id,
                "min_base_quantity": float(tier.min_base_quantity),
                "base_unit_price": float(tier.base_unit_price),
            }
            for tier in row.tier_prices
        ],
    }


def update_assignment(db: Session, assignment_id: int, data: dict) -> dict:
    row = db.scalar(_assignment_query().where(ProductSupplier.id == assignment_id))
    if not row:
        raise HTTPException(status_code=404, detail="商品供应商关系不存在")
    row.split_enabled = bool(data["split_enabled"])
    row.priority = int(data["priority"])
    row.daily_capacity_base = decimal(data.get("daily_capacity_base")) if data.get("daily_capacity_base") is not None else None
    row.order_capacity_base = decimal(data.get("order_capacity_base")) if data.get("order_capacity_base") is not None else None
    row.quota_percent = decimal(data.get("quota_percent"))
    if row.priority < 1:
        raise HTTPException(status_code=400, detail="供应商优先级必须大于 0")
    if row.quota_percent < 0 or row.quota_percent > 100:
        raise HTTPException(status_code=400, detail="固定配额必须在 0% 到 100% 之间")
    if row.daily_capacity_base is not None and row.daily_capacity_base <= 0:
        raise HTTPException(status_code=400, detail="日最大供货量必须大于 0")
    if row.order_capacity_base is not None and row.order_capacity_base <= 0:
        raise HTTPException(status_code=400, detail="单订单最大供货量必须大于 0")
    tiers = sorted(data.get("tier_prices", []), key=lambda item: decimal(item["min_base_quantity"]))
    thresholds = [decimal(item["min_base_quantity"]) for item in tiers]
    if len(thresholds) != len(set(thresholds)) or any(value <= 0 for value in thresholds):
        raise HTTPException(status_code=400, detail="阶梯价起订量必须大于 0 且不能重复")
    if any(decimal(item["base_unit_price"]) <= 0 for item in tiers):
        raise HTTPException(status_code=400, detail="阶梯单价必须大于 0")
    row.tier_prices.clear()
    for item in tiers:
        row.tier_prices.append(SupplierTierPrice(
            min_base_quantity=decimal(item["min_base_quantity"]),
            base_unit_price=decimal(item["base_unit_price"]),
        ))
    db.commit()
    return _assignment_output(db.scalar(_assignment_query().where(ProductSupplier.id == row.id)), _setting(db))


def update_weights(db: Session, data: dict) -> dict:
    values = [decimal(data[key]) for key in ("on_time", "inspection", "return")]
    if any(value < 0 for value in values) or sum(values) <= 0:
        raise HTTPException(status_code=400, detail="评分权重不能为负数且合计必须大于 0")
    total = sum(values)
    setting = _setting(db)
    setting.on_time_weight, setting.inspection_weight, setting.return_weight = [value / total for value in values]
    db.commit()
    return configuration(db)["weights"]


def update_supplier_performance(db: Session, supplier_id: int, data: dict) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="供应商不存在")
    for field in ("on_time_rate", "inspection_pass_rate", "return_rate"):
        value = decimal(data[field])
        if value < 0 or value > 100:
            raise HTTPException(status_code=400, detail="绩效指标必须在 0 到 100 之间")
        setattr(supplier, field, value)
    supplier.payment_term_days = max(0, int(data.get("payment_term_days", 0)))
    db.commit()
    setting = _setting(db)
    return {
        "id": supplier.id,
        "quality_score": float(quality_score(supplier, setting)),
    }


def source_options(db: Session) -> dict:
    sales = db.scalars(
        select(SalesOrder).options(selectinload(SalesOrder.customer), selectinload(SalesOrder.items))
        .where(SalesOrder.status == "confirmed").order_by(SalesOrder.delivery_date.desc(), SalesOrder.id.desc()).limit(500)
    ).unique().all()
    requisitions = db.scalars(
        select(PurchaseRequisition).options(selectinload(PurchaseRequisition.items))
        .where(PurchaseRequisition.status == "pending").order_by(PurchaseRequisition.needed_date.desc()).limit(500)
    ).unique().all()
    return {
        "sales_orders": [{
            "id": row.id, "source_no": row.order_no, "name": f"{row.order_no} · {row.customer.name}",
            "needed_date": row.delivery_date or row.order_date, "item_count": len(row.items),
        } for row in sales],
        "requisitions": [{
            "id": row.id, "source_no": row.requisition_no,
            "name": f"{row.requisition_no} · {row.target_name or '仓库备货'}",
            "needed_date": row.needed_date, "item_count": len(row.items),
        } for row in requisitions],
    }


def _base_unit(product: Product) -> ProductUnit:
    unit = next((row for row in product.units if row.is_base), None)
    if not unit:
        raise HTTPException(status_code=400, detail=f"{product.name} 未设置基础单位，无法智能拆单")
    return unit


def _source_demands(db: Session, source_type: str, source_id: int) -> tuple[dict, list[dict]]:
    if source_type == "sales":
        source = db.scalar(
            select(SalesOrder).options(
                selectinload(SalesOrder.customer),
                selectinload(SalesOrder.items).selectinload(SalesOrderItem.product).selectinload(Product.units),
                selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
                selectinload(SalesOrder.procurement_links).selectinload(SalesProcurementLink.purchase_order).selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
            ).where(SalesOrder.id == source_id)
        )
        if not source or source.status != "confirmed":
            raise HTTPException(status_code=400, detail="销售单不存在或尚未确认")
        existing = defaultdict(lambda: ZERO)
        for link in source.procurement_links:
            if link.purchase_order.status == "cancelled":
                continue
            for item in link.purchase_order.items:
                existing[item.product_id] += item.quantity * item.unit.conversion_rate
        grouped = defaultdict(lambda: ZERO)
        for item in source.items:
            grouped[item.product_id] += item.quantity * item.unit.conversion_rate
        products = {item.product_id: item.product for item in source.items}
        info = {"source_no": source.order_no, "name": source.customer.name, "needed_date": source.delivery_date or source.order_date}
    elif source_type == "requisition":
        source = db.scalar(
            select(PurchaseRequisition).options(
                selectinload(PurchaseRequisition.items).selectinload(PurchaseRequisitionItem.product).selectinload(Product.units),
                selectinload(PurchaseRequisition.order_links).selectinload(PurchaseRequisitionOrder.purchase_order).selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
            ).where(PurchaseRequisition.id == source_id)
        )
        if not source:
            raise HTTPException(status_code=404, detail="采购需求不存在")
        existing = defaultdict(lambda: ZERO)
        for link in source.order_links:
            if link.purchase_order.status == "cancelled":
                continue
            for item in link.purchase_order.items:
                existing[item.product_id] += item.quantity * item.unit.conversion_rate
        grouped = defaultdict(lambda: ZERO)
        products = {}
        for item in source.items:
            grouped[item.product_id] += item.base_quantity
            products[item.product_id] = item.product
        info = {"source_no": source.requisition_no, "name": source.target_name or "仓库备货", "needed_date": source.needed_date}
    else:
        raise HTTPException(status_code=400, detail="不支持的采购需求来源")
    demands = []
    for product_id, demand in grouped.items():
        product = products[product_id]
        base_unit = _base_unit(product)
        category_rate = product.category_rel.purchase_loss_rate if product.category_rel else ZERO
        loss_rate = product.loss_rate if product.loss_rate is not None else category_rate
        target = quantize(demand * (Decimal("1") + loss_rate / Decimal("100")))
        remaining = max(ZERO, target - existing[product_id])
        demands.append({
            "product": product, "base_unit": base_unit, "demand": quantize(demand),
            "loss_rate": decimal(loss_rate), "target": target, "existing": quantize(existing[product_id]),
            "remaining": quantize(remaining),
        })
    return info, demands


def _daily_used(db: Session, assignment_id: int, needed_date: date) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(ProcurementSplitAllocation.base_quantity), 0))
        .join(ProcurementSplitPlanItem)
        .join(ProcurementSplitPlan)
        .where(
            ProcurementSplitAllocation.assignment_id == assignment_id,
            ProcurementSplitPlan.needed_date == needed_date,
            ProcurementSplitPlan.status == "generated",
        )
    )
    return decimal(value)


def _base_price(assignment: ProductSupplier, quantity: Decimal) -> tuple[Decimal | None, str]:
    tier = next((row for row in reversed(assignment.tier_prices) if quantity >= row.min_base_quantity), None)
    if tier:
        return tier.base_unit_price, "tier_price"
    quotes = [quote.price / quote.unit.conversion_rate for quote in assignment.quotes if quote.unit.conversion_rate]
    return (min(quotes), "standard_quote") if quotes else (None, "missing")


def _candidates(db: Session, product_id: int, quantity: Decimal, needed_date: date) -> list[dict]:
    setting = _setting(db)
    assignments = db.scalars(
        _assignment_query().where(
            ProductSupplier.product_id == product_id,
            ProductSupplier.active.is_(True),
            ProductSupplier.split_enabled.is_(True),
        )
    ).unique().all()
    output = []
    for row in assignments:
        if not row.supplier.active:
            continue
        daily_remaining = None if row.daily_capacity_base is None else max(ZERO, row.daily_capacity_base - _daily_used(db, row.id, needed_date))
        limits = [value for value in (row.order_capacity_base, daily_remaining) if value is not None]
        capacity = min(limits) if limits else quantity
        capacity = min(quantity, max(ZERO, capacity))
        price, source = _base_price(row, capacity or quantity)
        if price is None or capacity <= 0:
            continue
        output.append({
            "assignment": row, "assignment_id": row.id, "supplier_id": row.supplier_id,
            "supplier_name": row.supplier.name, "capacity": quantize(capacity),
            "daily_remaining": quantize(daily_remaining) if daily_remaining is not None else None,
            "order_capacity": quantize(row.order_capacity_base) if row.order_capacity_base is not None else None,
            "quota_percent": decimal(row.quota_percent), "priority": row.priority,
            "quality_score": quality_score(row.supplier, setting), "base_price": price,
            "price_source": source,
        })
    return output


def _sequential(quantity: Decimal, candidates: list[dict], sort_key) -> list[dict]:
    remaining = quantity
    allocations = []
    for candidate in sorted(candidates, key=sort_key):
        amount = quantize(min(remaining, candidate["capacity"]))
        if amount:
            allocations.append({**candidate, "quantity": amount})
            remaining = quantize(remaining - amount)
        if remaining <= 0:
            break
    return allocations


def _quota(quantity: Decimal, candidates: list[dict]) -> list[dict]:
    allocations = {candidate["assignment_id"]: ZERO for candidate in candidates}
    positive = [candidate for candidate in candidates if candidate["quota_percent"] > 0]
    quota_total = sum((candidate["quota_percent"] for candidate in positive), ZERO)
    if quota_total:
        for candidate in positive:
            target = quantity * candidate["quota_percent"] / quota_total
            allocations[candidate["assignment_id"]] = quantize(min(target, candidate["capacity"]))
    allocated = sum(allocations.values(), ZERO)
    remaining = quantize(quantity - allocated)
    for candidate in sorted(candidates, key=lambda row: (row["priority"], row["base_price"])):
        available = candidate["capacity"] - allocations[candidate["assignment_id"]]
        extra = quantize(min(remaining, max(ZERO, available)))
        allocations[candidate["assignment_id"]] += extra
        remaining = quantize(remaining - extra)
        if remaining <= 0:
            break
    return [{**candidate, "quantity": allocations[candidate["assignment_id"]]} for candidate in candidates if allocations[candidate["assignment_id"]] > 0]


def preview(db: Session, source_type: str, source_id: int, strategy: str) -> dict:
    if strategy not in STRATEGIES:
        raise HTTPException(status_code=400, detail="请选择有效拆分策略")
    info, demands = _source_demands(db, source_type, source_id)
    rows = []
    for demand in demands:
        candidates = _candidates(db, demand["product"].id, demand["remaining"], info["needed_date"])
        if strategy == "quota":
            allocations = _quota(demand["remaining"], candidates)
        elif strategy == "capacity":
            allocations = _sequential(demand["remaining"], candidates, lambda row: (row["priority"], row["base_price"]))
        elif strategy == "price":
            allocations = _sequential(demand["remaining"], candidates, lambda row: (row["base_price"], row["priority"]))
        else:
            allocations = _sequential(demand["remaining"], candidates, lambda row: (-row["quality_score"], row["priority"]))
        allocated = sum((row["quantity"] for row in allocations), ZERO)
        rows.append({
            "product_id": demand["product"].id, "product_name": demand["product"].name,
            "category": demand["product"].category, "base_unit_id": demand["base_unit"].id,
            "base_unit_name": demand["base_unit"].name, "demand_base_quantity": float(demand["demand"]),
            "loss_rate": float(demand["loss_rate"]), "target_base_quantity": float(demand["target"]),
            "existing_base_quantity": float(demand["existing"]), "required_base_quantity": float(demand["remaining"]),
            "allocated_base_quantity": float(allocated), "unallocated_base_quantity": float(max(ZERO, demand["remaining"] - allocated)),
            "allocations": [{
                "assignment_id": row["assignment_id"], "supplier_id": row["supplier_id"], "supplier_name": row["supplier_name"],
                "base_quantity": float(row["quantity"]), "base_unit_price": float(row["base_price"]),
                "amount": float(row["quantity"] * row["base_price"]), "price_source": row["price_source"],
                "capacity": float(row["capacity"]), "daily_remaining": float(row["daily_remaining"]) if row["daily_remaining"] is not None else None,
                "order_capacity": float(row["order_capacity"]) if row["order_capacity"] is not None else None,
                "quota_percent": float(row["quota_percent"]), "priority": row["priority"], "quality_score": float(row["quality_score"]),
            } for row in allocations],
            "candidates": [{
                "assignment_id": row["assignment_id"], "supplier_id": row["supplier_id"], "supplier_name": row["supplier_name"],
                "base_unit_price": float(row["base_price"]), "price_source": row["price_source"], "capacity": float(row["capacity"]),
                "quota_percent": float(row["quota_percent"]), "priority": row["priority"], "quality_score": float(row["quality_score"]),
            } for row in candidates],
        })
    return {"source_type": source_type, "source_id": source_id, **info, "strategy": strategy, "strategy_name": STRATEGIES[strategy], "items": rows}


def _purchase_unit(assignment: ProductSupplier) -> tuple[ProductUnit, Decimal]:
    choices = [(quote.unit, quote.price / quote.unit.conversion_rate) for quote in assignment.quotes if quote.unit.conversion_rate]
    if not choices:
        raise HTTPException(status_code=400, detail=f"{assignment.product.name} 在 {assignment.supplier.name} 没有有效报价")
    return min(choices, key=lambda row: row[1])


def generate(db: Session, data: dict, user: User) -> dict:
    source_type, source_id, strategy = data["source_type"], int(data["source_id"]), data["strategy"]
    assignment_ids = {
        int(allocation["assignment_id"])
        for item in data.get("items", [])
        for allocation in item.get("allocations", [])
    }
    if assignment_ids:
        # Serialize capacity checks for the same supplier-product relationships.
        # This prevents two purchasers from consuming the same daily capacity.
        db.execute(
            select(ProductSupplier.id)
            .where(ProductSupplier.id.in_(assignment_ids))
            .order_by(ProductSupplier.id)
            .with_for_update()
        ).all()
    current = preview(db, source_type, source_id, strategy)
    current_by_product = {row["product_id"]: row for row in current["items"]}
    incoming_items = data.get("items", [])
    if not incoming_items:
        raise HTTPException(status_code=400, detail="没有可生成采购的拆单明细")
    plan = ProcurementSplitPlan(
        plan_no=f"CF{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
        source_type=source_type, source_id=source_id, source_no=current["source_no"], strategy=strategy,
        reduction_strategy=data.get("reduction_strategy", "proportional"), needed_date=current["needed_date"],
        status="generated", created_by=user.id, generated_at=datetime.now(), notes=(data.get("notes") or "").strip() or None,
    )
    db.add(plan)
    db.flush()
    grouped = defaultdict(list)
    weighted_cost = defaultdict(lambda: [ZERO, ZERO])
    for incoming in incoming_items:
        product_id = int(incoming["product_id"])
        expected = current_by_product.get(product_id)
        if not expected:
            raise HTTPException(status_code=400, detail=f"商品 {product_id} 不在当前采购需求中")
        required = decimal(expected["required_base_quantity"])
        allocations = incoming.get("allocations", [])
        total = sum((decimal(row["base_quantity"]) for row in allocations), ZERO)
        if abs(total - required) > QTY:
            raise HTTPException(status_code=400, detail=f"{expected['product_name']} 拆分合计必须等于 {required} {expected['base_unit_name']}")
        plan_item = ProcurementSplitPlanItem(
            plan_id=plan.id, product_id=product_id, base_unit_id=expected["base_unit_id"],
            demand_base_quantity=decimal(expected["demand_base_quantity"]), loss_rate=decimal(expected["loss_rate"]),
            purchase_base_quantity=required, existing_base_quantity=decimal(expected["existing_base_quantity"]),
        )
        db.add(plan_item)
        db.flush()
        candidates = {row["assignment_id"]: row for row in expected["candidates"]}
        for incoming_allocation in allocations:
            assignment_id = int(incoming_allocation["assignment_id"])
            candidate = candidates.get(assignment_id)
            if not candidate:
                raise HTTPException(status_code=400, detail=f"{expected['product_name']} 包含无效供应商")
            base_quantity = quantize(decimal(incoming_allocation["base_quantity"]))
            if base_quantity <= 0 or base_quantity > decimal(candidate["capacity"]) + QTY:
                raise HTTPException(status_code=400, detail=f"{expected['product_name']} 分配量超过供应商可供量")
            assignment = db.scalar(_assignment_query().where(ProductSupplier.id == assignment_id))
            base_price, price_source = _base_price(assignment, base_quantity)
            unit, _ = _purchase_unit(assignment)
            purchase_quantity = quantize(base_quantity / unit.conversion_rate)
            unit_price = base_price * unit.conversion_rate
            allocation = ProcurementSplitAllocation(
                plan_item_id=plan_item.id, assignment_id=assignment.id, supplier_id=assignment.supplier_id,
                base_quantity=base_quantity, base_unit_price=base_price, price_source=price_source,
                allocation_percent=quantize(base_quantity / required * 100) if required else ZERO,
                priority_snapshot=assignment.priority,
                quality_score_snapshot=decimal(candidate["quality_score"]),
            )
            db.add(allocation)
            db.flush()
            grouped[assignment.supplier_id].append({
                "allocation": allocation, "assignment": assignment, "unit": unit,
                "quantity": purchase_quantity, "unit_price": unit_price,
            })
            weighted_cost[product_id][0] += base_quantity * base_price
            weighted_cost[product_id][1] += base_quantity
    total_base = sum((row["allocation"].base_quantity for rows in grouped.values() for row in rows), ZERO)
    created = []
    for supplier_id, rows in grouped.items():
        supplier = rows[0]["assignment"].supplier
        supplier_base = sum((row["allocation"].base_quantity for row in rows), ZERO)
        order = PurchaseOrder(
            order_no=f"PO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
            supplier_id=supplier_id, created_by=user.id,
            title=f"拆分采购 - {current['name']}", expected_date=current["needed_date"],
            notes=f"由智能拆单计划 {plan.plan_no} 生成；来源 {current['source_no']}",
            report_footer="请按本采购单明细备货；本单仅展示贵司供货信息。",
            source_requirement_no=current["source_no"], split_plan_id=plan.id,
            is_split_order=True, split_strategy=strategy,
            split_share=quantize(supplier_base / total_base * 100) if total_base else ZERO,
        )
        db.add(order)
        db.flush()
        for row in rows:
            allocation = row["allocation"]
            allocation.purchase_order_id = order.id
            order.items.append(PurchaseOrderItem(
                product_id=row["assignment"].product_id, unit_id=row["unit"].id,
                quantity=row["quantity"], unit_price=row["unit_price"],
                is_best_price=False,
                remark=f"拆单计划 {plan.plan_no}；分配 {allocation.allocation_percent}%",
            ))
        if source_type == "sales":
            db.add(SalesProcurementLink(sales_order_id=source_id, purchase_order_id=order.id))
        else:
            db.add(PurchaseRequisitionOrder(requisition_id=source_id, purchase_order_id=order.id))
        created.append({"id": order.id, "order_no": order.order_no, "supplier_name": supplier.name})
    if source_type == "sales":
        sales = db.scalar(select(SalesOrder).options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit)).where(SalesOrder.id == source_id))
        for item in sales.items:
            amount, quantity = weighted_cost[item.product_id]
            if quantity:
                item.cost_unit_price = amount / quantity * item.unit.conversion_rate
    db.commit()
    return {"message": f"已按{STRATEGIES[strategy]}生成 {len(created)} 张供应商采购草稿", "plan_id": plan.id, "plan_no": plan.plan_no, "created": created}


def plan_query():
    return select(ProcurementSplitPlan).options(
        selectinload(ProcurementSplitPlan.creator),
        selectinload(ProcurementSplitPlan.items).selectinload(ProcurementSplitPlanItem.product),
        selectinload(ProcurementSplitPlan.items).selectinload(ProcurementSplitPlanItem.base_unit),
        selectinload(ProcurementSplitPlan.items).selectinload(ProcurementSplitPlanItem.allocations).selectinload(ProcurementSplitAllocation.supplier),
        selectinload(ProcurementSplitPlan.items).selectinload(ProcurementSplitPlanItem.allocations).selectinload(ProcurementSplitAllocation.purchase_order),
    )


def plans(db: Session) -> list[dict]:
    rows = db.scalars(plan_query().order_by(ProcurementSplitPlan.id.desc()).limit(500)).unique().all()
    return [{
        "id": row.id, "plan_no": row.plan_no, "source_type": row.source_type, "source_no": row.source_no,
        "strategy": row.strategy, "strategy_name": STRATEGIES.get(row.strategy, row.strategy),
        "needed_date": row.needed_date, "status": row.status, "creator_name": row.creator.name,
        "generated_at": row.generated_at, "cancelled_at": row.cancelled_at,
        "total_base_quantity": float(sum((item.purchase_base_quantity for item in row.items), ZERO)),
        "supplier_count": len({allocation.supplier_id for item in row.items for allocation in item.allocations}),
        "items": [{
            "product_name": item.product.name, "base_unit_name": item.base_unit.name,
            "demand_base_quantity": float(item.demand_base_quantity), "loss_rate": float(item.loss_rate),
            "purchase_base_quantity": float(item.purchase_base_quantity),
            "allocations": [{
                "supplier_name": allocation.supplier.name, "base_quantity": float(allocation.base_quantity),
                "base_unit_price": float(allocation.base_unit_price), "allocation_percent": float(allocation.allocation_percent),
                "purchase_order_id": allocation.purchase_order_id,
                "purchase_order_no": allocation.purchase_order.order_no if allocation.purchase_order else None,
                "purchase_order_status": allocation.purchase_order.status if allocation.purchase_order else None,
            } for allocation in item.allocations],
        } for item in row.items],
    } for row in rows]


def cancel_plan(db: Session, plan_id: int) -> dict:
    plan = db.scalar(plan_query().where(ProcurementSplitPlan.id == plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="拆单计划不存在")
    if plan.status == "cancelled":
        return {"message": "拆单计划已撤销"}
    orders = {allocation.purchase_order for item in plan.items for allocation in item.allocations if allocation.purchase_order}
    if any(order.status != "draft" for order in orders):
        raise HTTPException(status_code=400, detail="存在已确认采购单，不能撤销；请先走采购退订/冲销流程")
    order_ids = {order.id for order in orders}
    if plan.source_type == "sales":
        links = db.scalars(select(SalesProcurementLink).where(SalesProcurementLink.purchase_order_id.in_(order_ids))).all()
    else:
        links = db.scalars(select(PurchaseRequisitionOrder).where(PurchaseRequisitionOrder.purchase_order_id.in_(order_ids))).all()
    for link in links:
        db.delete(link)
    for order in orders:
        order.status = "cancelled"
    plan.status = "cancelled"
    plan.cancelled_at = datetime.now()
    db.commit()
    return {"message": "拆单已撤销，原需求已恢复为可重新拆分状态"}
