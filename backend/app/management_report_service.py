from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Customer,
    LogisticsStaff,
    PickingTask,
    PickingTaskItem,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    SalesProcurementLink,
    Supplier,
    User,
    WarehouseDocument,
    WarehouseDocumentItem,
)


REPORTS = {
    "dashboard": ("数据看板", "订单、履约、毛利、加单和人员效率的经营总览"),
    "reconciliation": ("核单统计", "检查销售单确认、配送验收、差异与成本完整性"),
    "order_clerk": ("订单员统计", "订单员录单量、客户覆盖、加单与待处理情况"),
    "sorter": ("分拣员统计", "分拣任务、商品工作量、完成率与处理耗时"),
    "sales_orders": ("销售订单查询", "销售单状态、金额、验收、采购及加单信息"),
    "profit_detail": ("明细利润查询", "逐订单逐商品核对销售、成本、毛利及成本来源"),
    "supplier_profit": ("供应商明细利润", "按实际关联采购单归集供应商供货成本与销售毛利"),
    "purchase_orders": ("采购订单信息查询", "采购单、供应商、金额、最优价和销售来源"),
    "inventory_flow": ("进销存表", "按基础单位统计期初、入库、出库、领料和期末库存"),
    "customer_profit": ("客户利润表", "按客户统计验收销售额、成本、毛利与毛利率"),
    "product_profit": ("商品利润表", "按商品统计验收数量、销售额、成本和毛利"),
    "adjustments": ("加减单统计表", "加单与实配/验收减量分开统计，避免口径混淆"),
}

SPLIT_STRATEGIES = {"quota": "配额比例", "capacity": "供货能力", "price": "价格优先", "quality": "质量评分"}


@dataclass
class ReportFilters:
    date_from: date
    date_to: date
    customer_id: int | None = None
    supplier_id: int | None = None
    creator_id: int | None = None
    sorter_id: int | None = None
    product_id: int | None = None
    category: str | None = None
    status: str | None = None
    keyword: str | None = None
    page: int = 1
    page_size: int = 50


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _number(value: Any) -> float:
    return round(float(value or 0), 4)


def _column(key: str, label: str, value_type: str = "text", width: int = 120) -> dict:
    return {"key": key, "label": label, "type": value_type, "width": width}


def _metric(key: str, label: str, value: Any, value_type: str = "number", help_text: str = "") -> dict:
    return {"key": key, "label": label, "value": value, "type": value_type, "help": help_text}


def _paginate(payload: dict, filters: ReportFilters, export: bool) -> dict:
    rows = payload.get("rows", [])
    payload["total_rows"] = len(rows)
    payload["page"] = filters.page
    payload["page_size"] = filters.page_size
    if not export:
        start = (filters.page - 1) * filters.page_size
        payload["rows"] = rows[start:start + filters.page_size]
    return payload


def _sales_query(filters: ReportFilters):
    statement = (
        select(SalesOrder)
        .options(
            selectinload(SalesOrder.customer),
            selectinload(SalesOrder.creator),
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
            selectinload(SalesOrder.procurement_links)
            .selectinload(SalesProcurementLink.purchase_order)
            .selectinload(PurchaseOrder.supplier),
            selectinload(SalesOrder.procurement_links)
            .selectinload(SalesProcurementLink.purchase_order)
            .selectinload(PurchaseOrder.items)
            .selectinload(PurchaseOrderItem.unit),
        )
        .where(
            func.coalesce(SalesOrder.delivery_date, SalesOrder.order_date) >= filters.date_from,
            func.coalesce(SalesOrder.delivery_date, SalesOrder.order_date) <= filters.date_to,
        )
        .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
    )
    if filters.customer_id:
        statement = statement.where(SalesOrder.customer_id == filters.customer_id)
    if filters.creator_id:
        statement = statement.where(SalesOrder.created_by == filters.creator_id)
    if filters.status in {"draft", "confirmed"}:
        statement = statement.where(SalesOrder.status == filters.status)
    elif filters.status == "cancelled":
        statement = statement.where(SalesOrder.id == -1)
    return statement


def _orders(db: Session, filters: ReportFilters) -> list[SalesOrder]:
    rows = db.scalars(_sales_query(filters).limit(5000)).unique().all()
    keyword = (filters.keyword or "").strip().lower()
    output = []
    for order in rows:
        if filters.category and not any(item.product.category == filters.category for item in order.items):
            continue
        if filters.product_id and not any(item.product_id == filters.product_id for item in order.items):
            continue
        if filters.supplier_id and not any(link.purchase_order.supplier_id == filters.supplier_id for link in order.procurement_links):
            continue
        if keyword:
            text = " ".join([order.order_no, order.customer.name, order.creator.name, order.title or "", *[item.product.name for item in order.items]]).lower()
            if keyword not in text:
                continue
        output.append(order)
    return output


def _purchase_map(order: SalesOrder) -> dict[int, dict]:
    output = {}
    for link in order.procurement_links:
        purchase = link.purchase_order
        if purchase.status == "cancelled":
            continue
        for item in purchase.items:
            if item.product_id not in output and item.unit.conversion_rate:
                output[item.product_id] = {
                    "supplier_id": purchase.supplier_id,
                    "supplier_name": purchase.supplier.name,
                    "purchase_order_no": purchase.order_no,
                    "base_cost": Decimal(item.unit_price) / Decimal(item.unit.conversion_rate),
                }
    return output


def _item_values(order: SalesOrder, item: SalesOrderItem, purchase_map: dict[int, dict]) -> dict:
    ordered = Decimal(item.quantity or 0)
    delivered = item.delivered_quantity
    accepted = item.accepted_quantity
    settlement_quantity = accepted if accepted is not None else Decimal("0")
    purchase = purchase_map.get(item.product_id)
    cost_unit = item.cost_unit_price
    cost_source = "已核定成本"
    if cost_unit is None and purchase:
        cost_unit = purchase["base_cost"] * Decimal(item.unit.conversion_rate)
        cost_source = "关联采购单"
    if cost_unit is None and item.unit.reference_purchase_price is not None:
        cost_unit = Decimal(item.unit.reference_purchase_price)
        cost_source = "商品参考进价"
    sales_amount = settlement_quantity * Decimal(item.unit_price)
    cost_amount = settlement_quantity * cost_unit if cost_unit is not None else None
    profit = sales_amount - cost_amount if cost_amount is not None else None
    margin = (profit / sales_amount * 100) if profit is not None and sales_amount else None
    addition_amount = Decimal(item.addition_quantity or 0) * Decimal(item.unit_price)
    reduction_quantity = max(Decimal("0"), ordered - accepted) if accepted is not None else Decimal("0")
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "business_date": order.delivery_date or order.order_date,
        "customer_id": order.customer_id,
        "customer_name": order.customer.name,
        "creator_id": order.created_by,
        "creator_name": order.creator.name,
        "product_id": item.product_id,
        "product_name": item.display_name or item.product.name,
        "canonical_product_name": item.product.name,
        "category": item.product.category,
        "unit_name": item.unit.name,
        "conversion_rate": Decimal(item.unit.conversion_rate),
        "ordered_quantity": ordered,
        "delivered_quantity": delivered,
        "accepted_quantity": accepted,
        "settlement_quantity": settlement_quantity,
        "unit_price": Decimal(item.unit_price),
        "ordered_amount": ordered * Decimal(item.unit_price),
        "sales_amount": sales_amount,
        "cost_unit_price": cost_unit,
        "cost_source": cost_source if cost_unit is not None else "成本待维护",
        "cost_amount": cost_amount,
        "gross_profit": profit,
        "margin": margin,
        "supplier_id": purchase["supplier_id"] if purchase else None,
        "supplier_name": purchase["supplier_name"] if purchase else "未关联供应商",
        "purchase_order_no": purchase["purchase_order_no"] if purchase else None,
        "addition_count": item.addition_count or 0,
        "addition_quantity": Decimal(item.addition_quantity or 0),
        "addition_amount": addition_amount,
        "last_addition_at": item.last_addition_at,
        "reduction_quantity": reduction_quantity,
        "reduction_amount": reduction_quantity * Decimal(item.unit_price),
        "variance_reason": item.acceptance_variance_reason,
        "remark": item.remark,
    }


def _lines(orders: list[SalesOrder], filters: ReportFilters) -> list[dict]:
    output = []
    for order in orders:
        purchases = _purchase_map(order)
        for item in order.items:
            if filters.product_id and item.product_id != filters.product_id:
                continue
            if filters.category and item.product.category != filters.category:
                continue
            values = _item_values(order, item, purchases)
            if filters.supplier_id and values["supplier_id"] != filters.supplier_id:
                continue
            output.append(values)
    return output


def _profit_metrics(lines: list[dict]) -> list[dict]:
    sales = sum((row["sales_amount"] for row in lines), Decimal("0"))
    known = [row for row in lines if row["cost_amount"] is not None]
    known_sales = sum((row["sales_amount"] for row in known), Decimal("0"))
    cost = sum((row["cost_amount"] for row in known), Decimal("0"))
    profit = sum((row["gross_profit"] for row in known), Decimal("0"))
    return [
        _metric("sales", "验收销售额", _money(sales), "money", "仅统计已填写验收数量的商品"),
        _metric("cost", "已知成本", _money(cost), "money", "核定成本优先，其次采购成本和参考进价"),
        _metric("profit", "可计算毛利", _money(profit), "money"),
        _metric("margin", "已知成本毛利率", _money(profit / known_sales * 100) if known_sales else 0, "percent", "仅使用成本完整的销售明细计算"),
        _metric("missing", "成本待维护", len(lines) - len(known), "number"),
    ]


def _sales_orders_report(orders: list[SalesOrder]) -> dict:
    rows = []
    for order in orders:
        lines = [_item_values(order, item, _purchase_map(order)) for item in order.items]
        ordered = sum((row["ordered_amount"] for row in lines), Decimal("0"))
        accepted = sum((row["sales_amount"] for row in lines), Decimal("0"))
        rows.append({
            "business_date": order.delivery_date or order.order_date,
            "order_no": order.order_no,
            "customer_name": order.customer.name,
            "creator_name": order.creator.name,
            "source": {"manual": "后台录单", "wecom": "企业微信", "miniprogram": "小程序"}.get(order.source, order.source),
            "status": "已确认" if order.status == "confirmed" else "草稿",
            "item_count": len(order.items),
            "ordered_amount": _money(ordered),
            "accepted_amount": _money(accepted),
            "invoice_amount": _money(order.invoice_amount),
            "acceptance_status": {"pending": "待验收", "partial": "部分验收", "accepted": "已验收"}.get(order.acceptance_status, order.acceptance_status),
            "addition_items": sum(bool(item.addition_count) for item in order.items),
            "purchase_count": len(order.procurement_links),
        })
    return {
        "columns": [
            _column("business_date", "业务日期", "date", 115), _column("order_no", "销售单号", "text", 185),
            _column("customer_name", "客户", "text", 150), _column("creator_name", "订单员", "text", 110),
            _column("source", "来源", "text", 100), _column("status", "单据状态", "status", 95),
            _column("acceptance_status", "验收状态", "status", 100), _column("item_count", "商品行", "number", 85),
            _column("ordered_amount", "预定金额", "money", 120), _column("accepted_amount", "验收金额", "money", 120),
            _column("invoice_amount", "开票金额", "money", 120), _column("addition_items", "加单商品", "number", 95),
            _column("purchase_count", "采购单", "number", 85),
        ],
        "metrics": [
            _metric("orders", "销售单数", len(rows)),
            _metric("confirmed", "已确认", sum(row["status"] == "已确认" for row in rows)),
            _metric("accepted", "已验收", sum(row["acceptance_status"] == "已验收" for row in rows)),
            _metric("amount", "预定金额", _money(sum(Decimal(str(row["ordered_amount"])) for row in rows)), "money"),
        ],
        "rows": rows,
    }


def _reconciliation_report(orders: list[SalesOrder]) -> dict:
    rows = []
    for order in orders:
        lines = [_item_values(order, item, _purchase_map(order)) for item in order.items]
        variance = sum(row["accepted_quantity"] is not None and row["delivered_quantity"] != row["accepted_quantity"] for row in lines)
        missing = sum(row["accepted_quantity"] is not None and row["cost_unit_price"] is None for row in lines)
        if order.status == "draft":
            check_status = "待确认"
        elif order.acceptance_status != "accepted":
            check_status = "待验收"
        elif variance:
            check_status = "差异已登记"
        else:
            check_status = "已核清"
        rows.append({
            "business_date": order.delivery_date or order.order_date, "order_no": order.order_no,
            "customer_name": order.customer.name, "creator_name": order.creator.name,
            "check_status": check_status, "item_count": len(lines), "variance_items": variance,
            "missing_cost_items": missing, "purchase_count": len(order.procurement_links),
            "accepted_at": order.accepted_at, "notes": "；".join(sorted({row["variance_reason"] for row in lines if row["variance_reason"]})) or "—",
        })
    return {
        "columns": [
            _column("business_date", "业务日期", "date", 115), _column("order_no", "销售单号", "text", 185),
            _column("customer_name", "客户", "text", 150), _column("creator_name", "订单员", "text", 110),
            _column("check_status", "核单状态", "status", 110), _column("item_count", "商品行", "number", 85),
            _column("variance_items", "差异商品", "number", 95), _column("missing_cost_items", "缺成本", "number", 85),
            _column("purchase_count", "采购单", "number", 85), _column("accepted_at", "核单时间", "datetime", 165),
            _column("notes", "差异原因", "text", 220),
        ],
        "metrics": [
            _metric("total", "应核销售单", len(rows)), _metric("cleared", "已核清", sum(row["check_status"] == "已核清" for row in rows)),
            _metric("pending", "待处理", sum(row["check_status"] in {"待确认", "待验收"} for row in rows)),
            _metric("variance", "存在差异", sum(bool(row["variance_items"]) for row in rows)),
            _metric("missing", "成本待补", sum(row["missing_cost_items"] for row in rows)),
        ],
        "rows": rows,
        "notes": ["核单以销售单确认、配送/客户验收和差异原因完整为准；成本缺失单独提示，不会用 0 成本虚增利润。"],
    }


def _order_clerk_report(orders: list[SalesOrder]) -> dict:
    groups = defaultdict(lambda: {"orders": [], "customers": set(), "items": 0, "ordered": Decimal("0"), "accepted": Decimal("0"), "additions": 0, "addition_amount": Decimal("0"), "pending": 0})
    for order in orders:
        group = groups[(order.created_by, order.creator.name)]
        group["orders"].append(order.id); group["customers"].add(order.customer_id); group["items"] += len(order.items)
        for item in order.items:
            group["ordered"] += Decimal(item.quantity) * Decimal(item.unit_price)
            if item.accepted_quantity is not None:
                group["accepted"] += Decimal(item.accepted_quantity) * Decimal(item.unit_price)
            group["additions"] += item.addition_count or 0
            group["addition_amount"] += Decimal(item.addition_quantity or 0) * Decimal(item.unit_price)
        group["pending"] += order.status == "draft" or order.acceptance_status != "accepted"
    rows = [{
        "creator_name": name, "order_count": len(value["orders"]), "customer_count": len(value["customers"]),
        "item_count": value["items"], "ordered_amount": _money(value["ordered"]), "accepted_amount": _money(value["accepted"]),
        "addition_count": value["additions"], "addition_amount": _money(value["addition_amount"]), "pending_count": value["pending"],
        "average_order_amount": _money(value["ordered"] / len(value["orders"])) if value["orders"] else 0,
    } for (_, name), value in groups.items()]
    rows.sort(key=lambda row: row["order_count"], reverse=True)
    return {
        "columns": [
            _column("creator_name", "订单员", "text", 130), _column("order_count", "销售单", "number", 90),
            _column("customer_count", "下单客户", "number", 95), _column("item_count", "商品行", "number", 85),
            _column("ordered_amount", "预定金额", "money", 120), _column("accepted_amount", "验收金额", "money", 120),
            _column("addition_count", "加单次数", "number", 90), _column("addition_amount", "加单金额", "money", 115),
            _column("pending_count", "待处理订单", "number", 105), _column("average_order_amount", "平均客单", "money", 115),
        ],
        "metrics": [
            _metric("people", "订单员人数", len(rows)), _metric("orders", "录入销售单", sum(row["order_count"] for row in rows)),
            _metric("customers", "服务客户数", len({order.customer_id for order in orders})),
            _metric("pending", "待处理订单", sum(row["pending_count"] for row in rows)),
        ],
        "rows": rows,
    }


def _sorter_report(db: Session, filters: ReportFilters) -> dict:
    statement = select(PickingTask).options(
        selectinload(PickingTask.sorter), selectinload(PickingTask.customer),
        selectinload(PickingTask.items).selectinload(PickingTaskItem.product),
    ).where(
        func.coalesce(PickingTask.delivery_date, func.date(PickingTask.created_at)) >= filters.date_from,
        func.coalesce(PickingTask.delivery_date, func.date(PickingTask.created_at)) <= filters.date_to,
    ).order_by(PickingTask.id.desc())
    if filters.sorter_id:
        statement = statement.where(PickingTask.sorter_id == filters.sorter_id)
    tasks = db.scalars(statement.limit(5000)).unique().all()
    groups = defaultdict(lambda: {"tasks": 0, "customers": set(), "items": 0, "picked": 0, "loaded": 0, "completed": 0, "seconds": 0.0, "timed_tasks": 0, "products": Counter()})
    for task in tasks:
        key = (task.sorter_id, task.sorter.name if task.sorter else "未分配分拣员")
        group = groups[key]; group["tasks"] += 1; group["customers"].add(task.customer_id); group["items"] += len(task.items)
        picked_times = [item.picked_at for item in task.items if item.picked_at]
        group["picked"] += len(picked_times); group["loaded"] += sum(bool(item.loaded_at) for item in task.items)
        group["completed"] += task.status == "completed"
        for item in task.items:
            group["products"][item.product_name] += 1
        if picked_times:
            start = min(picked_times)
            end = max(picked_times)
            group["seconds"] += max(0, (end - start).total_seconds())
            group["timed_tasks"] += 1
    rows = []
    for (_, name), value in groups.items():
        completion = value["picked"] / value["items"] * 100 if value["items"] else 0
        rows.append({
            "sorter_name": name, "task_count": value["tasks"], "customer_count": len(value["customers"]),
            "item_count": value["items"], "picked_count": value["picked"], "loaded_count": value["loaded"],
            "completed_tasks": value["completed"], "completion_rate": round(completion, 2),
            "avg_customer_minutes": round(value["seconds"] / value["timed_tasks"] / 60, 2) if value["timed_tasks"] else 0,
            "avg_item_seconds": round(value["seconds"] / value["picked"], 2) if value["picked"] else 0,
            "work_content": "、".join(name for name, _ in value["products"].most_common(5)) or "—",
        })
    rows.sort(key=lambda row: row["item_count"], reverse=True)
    return {
        "columns": [
            _column("sorter_name", "分拣员", "text", 130), _column("task_count", "客户任务", "number", 95),
            _column("customer_count", "负责客户", "number", 90), _column("item_count", "商品行", "number", 85),
            _column("picked_count", "已分拣", "number", 85), _column("loaded_count", "已装车", "number", 85),
            _column("completed_tasks", "完成任务", "number", 90), _column("completion_rate", "完成率", "percent", 95),
            _column("avg_customer_minutes", "平均每客户(分钟)", "number", 145), _column("avg_item_seconds", "平均每商品(秒)", "number", 140),
            _column("work_content", "主要工作商品", "text", 260),
        ],
        "metrics": [
            _metric("people", "参与分拣员", len(rows)), _metric("tasks", "客户任务", sum(row["task_count"] for row in rows)),
            _metric("items", "商品工作量", sum(row["item_count"] for row in rows)),
            _metric("rate", "整体完成率", round(sum(row["picked_count"] for row in rows) / max(sum(row["item_count"] for row in rows), 1) * 100, 2), "percent"),
        ],
        "rows": rows,
        "notes": ["平均每客户时间按该客户任务首个与最后一个分拣完成时间计算；无扫码时间的任务不进入耗时平均值。"],
    }


def _profit_detail(lines: list[dict]) -> dict:
    rows = [{
        "business_date": row["business_date"], "order_no": row["order_no"], "customer_name": row["customer_name"],
        "product_name": row["product_name"], "category": row["category"], "supplier_name": row["supplier_name"],
        "accepted_quantity": _number(row["accepted_quantity"]), "unit_name": row["unit_name"], "unit_price": _money(row["unit_price"]),
        "sales_amount": _money(row["sales_amount"]), "cost_unit_price": _money(row["cost_unit_price"]) if row["cost_unit_price"] is not None else None,
        "cost_source": row["cost_source"], "cost_amount": _money(row["cost_amount"]) if row["cost_amount"] is not None else None,
        "gross_profit": _money(row["gross_profit"]) if row["gross_profit"] is not None else None,
        "margin": _money(row["margin"]) if row["margin"] is not None else None,
    } for row in lines]
    return {
        "columns": [
            _column("business_date", "业务日期", "date", 115), _column("order_no", "销售单号", "text", 180),
            _column("customer_name", "客户", "text", 140), _column("product_name", "商品", "text", 150),
            _column("category", "分类", "text", 105), _column("supplier_name", "供应商", "text", 140),
            _column("accepted_quantity", "验收数量", "number", 100), _column("unit_name", "单位", "text", 70),
            _column("unit_price", "销售单价", "money", 105), _column("sales_amount", "销售金额", "money", 110),
            _column("cost_unit_price", "成本单价", "money", 105), _column("cost_source", "成本来源", "status", 110),
            _column("cost_amount", "成本金额", "money", 110), _column("gross_profit", "毛利", "money", 110),
            _column("margin", "毛利率", "percent", 95),
        ],
        "metrics": _profit_metrics(lines), "rows": rows,
        "notes": ["未验收商品的结算销售额为 0；成本缺失时毛利留空，不按 0 成本计算。"],
    }


def _group_profit(lines: list[dict], dimension: str) -> dict:
    if dimension == "customer":
        key_of = lambda row: (row["customer_id"], row["customer_name"])
        name_key, title = "customer_name", "客户"
    else:
        key_of = lambda row: (row["product_id"], row["canonical_product_name"])
        name_key, title = "product_name", "商品"
    groups = defaultdict(lambda: {"orders": set(), "quantity": Decimal("0"), "sales": Decimal("0"), "known_sales": Decimal("0"), "cost": Decimal("0"), "profit": Decimal("0"), "missing": 0, "category": ""})
    for row in lines:
        group = groups[key_of(row)]; group["orders"].add(row["order_id"]); group["quantity"] += row["settlement_quantity"] * row["conversion_rate"]
        group["sales"] += row["sales_amount"]; group["category"] = row["category"]
        if row["cost_amount"] is None: group["missing"] += 1
        else: group["known_sales"] += row["sales_amount"]; group["cost"] += row["cost_amount"]; group["profit"] += row["gross_profit"]
    rows = []
    for (_, name), value in groups.items():
        rows.append({name_key: name, "category": value["category"], "order_count": len(value["orders"]), "base_quantity": _number(value["quantity"]),
                     "sales_amount": _money(value["sales"]), "cost_amount": _money(value["cost"]), "gross_profit": _money(value["profit"]),
                     "margin": _money(value["profit"] / value["known_sales"] * 100) if value["known_sales"] else 0, "missing_cost_items": value["missing"]})
    rows.sort(key=lambda row: row["sales_amount"], reverse=True)
    columns = [_column(name_key, title, "text", 170)]
    if dimension == "product": columns.append(_column("category", "分类", "text", 110))
    columns += [_column("order_count", "销售单", "number", 85), _column("base_quantity", "验收数量(基础单位)", "number", 150),
                _column("sales_amount", "销售金额", "money", 120), _column("cost_amount", "已知成本", "money", 115),
                _column("gross_profit", "毛利", "money", 115), _column("margin", "毛利率", "percent", 95),
                _column("missing_cost_items", "缺成本明细", "number", 105)]
    return {"columns": columns, "metrics": _profit_metrics(lines), "rows": rows,
            "notes": ["数量统一折算为商品基础单位；不同商品的基础单位不可直接相加作为经营总数量。"]}


def _supplier_profit(lines: list[dict]) -> dict:
    groups = defaultdict(lambda: {"orders": set(), "purchases": set(), "products": set(), "sales": Decimal("0"), "known_sales": Decimal("0"), "cost": Decimal("0"), "profit": Decimal("0"), "missing": 0})
    for row in lines:
        group = groups[(row["supplier_id"], row["supplier_name"])]
        group["orders"].add(row["order_id"]); group["products"].add(row["product_id"])
        if row["purchase_order_no"]: group["purchases"].add(row["purchase_order_no"])
        group["sales"] += row["sales_amount"]
        if row["cost_amount"] is None: group["missing"] += 1
        else: group["known_sales"] += row["sales_amount"]; group["cost"] += row["cost_amount"]; group["profit"] += row["gross_profit"]
    rows = [{"supplier_name": name, "sales_order_count": len(v["orders"]), "purchase_order_count": len(v["purchases"]),
             "product_count": len(v["products"]), "sales_amount": _money(v["sales"]), "cost_amount": _money(v["cost"]),
             "gross_profit": _money(v["profit"]), "margin": _money(v["profit"] / v["known_sales"] * 100) if v["known_sales"] else 0,
             "missing_cost_items": v["missing"]} for (_, name), v in groups.items()]
    rows.sort(key=lambda row: row["sales_amount"], reverse=True)
    return {"columns": [_column("supplier_name", "供应商", "text", 170), _column("sales_order_count", "销售单", "number", 85),
                        _column("purchase_order_count", "采购单", "number", 85), _column("product_count", "供货商品", "number", 90),
                        _column("sales_amount", "对应销售额", "money", 120), _column("cost_amount", "供货成本", "money", 115),
                        _column("gross_profit", "贡献毛利", "money", 115), _column("margin", "毛利率", "percent", 95),
                        _column("missing_cost_items", "缺成本", "number", 85)],
            "metrics": _profit_metrics(lines), "rows": rows,
            "notes": ["供应商利润按销售单实际关联的采购单归属；未转采购商品归入“未关联供应商”。"]}


def _purchase_orders(db: Session, filters: ReportFilters) -> dict:
    statement = select(PurchaseOrder).options(
        selectinload(PurchaseOrder.supplier), selectinload(PurchaseOrder.creator),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.product),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
    ).order_by(PurchaseOrder.id.desc())
    if filters.supplier_id: statement = statement.where(PurchaseOrder.supplier_id == filters.supplier_id)
    if filters.creator_id: statement = statement.where(PurchaseOrder.created_by == filters.creator_id)
    if filters.status in {"draft", "confirmed", "cancelled"}: statement = statement.where(PurchaseOrder.status == filters.status)
    purchases = db.scalars(statement.limit(5000)).unique().all()
    rows = []
    keyword = (filters.keyword or "").strip().lower()
    for order in purchases:
        business_date = order.expected_date or order.created_at.date()
        if not filters.date_from <= business_date <= filters.date_to: continue
        if filters.category and not any(item.product.category == filters.category for item in order.items): continue
        if filters.product_id and not any(item.product_id == filters.product_id for item in order.items): continue
        text = f"{order.order_no} {order.source_requirement_no or ''} {order.supplier.name} {' '.join(item.product.name for item in order.items)}".lower()
        if keyword and keyword not in text: continue
        amount = sum((Decimal(item.quantity) * Decimal(item.unit_price) for item in order.items), Decimal("0"))
        rows.append({"business_date": business_date, "order_no": order.order_no, "supplier_name": order.supplier.name,
                     "creator_name": order.creator.name, "status": {"confirmed": "已确认", "cancelled": "已撤销"}.get(order.status, "草稿"),
                     "source_requirement_no": order.source_requirement_no or "—",
                     "split_type": SPLIT_STRATEGIES.get(order.split_strategy, "智能拆单") if order.is_split_order else "普通采购",
                     "item_count": len(order.items), "purchase_amount": _money(amount),
                     "best_price_items": sum(item.is_best_price for item in order.items), "expected_date": order.expected_date,
                     "confirmed_at": order.confirmed_at})
    return {"columns": [_column("business_date", "业务日期", "date", 115), _column("order_no", "采购单号", "text", 185),
                        _column("source_requirement_no", "采购需求号", "text", 180), _column("supplier_name", "供应商", "text", 160),
                        _column("split_type", "拆单方式", "status", 110), _column("creator_name", "采购员", "text", 110),
                        _column("status", "状态", "status", 90), _column("item_count", "商品行", "number", 85),
                        _column("purchase_amount", "采购金额", "money", 120), _column("best_price_items", "最优价商品", "number", 105),
                        _column("expected_date", "预计到货", "date", 110), _column("confirmed_at", "确认时间", "datetime", 165)],
            "metrics": [_metric("orders", "采购单数", len(rows)), _metric("confirmed", "已确认", sum(row["status"] == "已确认" for row in rows)),
                        _metric("cancelled", "已撤销", sum(row["status"] == "已撤销" for row in rows)),
                        _metric("amount", "有效采购金额", _money(sum(Decimal(str(row["purchase_amount"])) for row in rows if row["status"] != "已撤销")), "money"),
                        _metric("best", "最优价商品行", sum(row["best_price_items"] for row in rows))], "rows": rows}


def _inventory_flow(db: Session, filters: ReportFilters) -> dict:
    documents = db.scalars(select(WarehouseDocument).options(
        selectinload(WarehouseDocument.items).selectinload(WarehouseDocumentItem.product),
        selectinload(WarehouseDocument.items).selectinload(WarehouseDocumentItem.unit),
    ).where(WarehouseDocument.business_date <= filters.date_to, WarehouseDocument.status.in_({"confirmed", "released"}))).unique().all()
    groups = defaultdict(lambda: {"opening": Decimal("0"), "inbound": Decimal("0"), "outbound": Decimal("0"), "material": Decimal("0"), "product": None, "unit": ""})
    for document in documents:
        for item in document.items:
            if filters.product_id and item.product_id != filters.product_id: continue
            if filters.category and item.product.category != filters.category: continue
            group = groups[item.product_id]; group["product"] = item.product
            if item.unit.is_base: group["unit"] = item.unit.name
            sign = 1 if document.document_type == "inbound" else -1 if document.document_type in {"outbound", "material"} else 0
            if document.business_date < filters.date_from:
                group["opening"] += item.base_quantity * sign
            elif document.document_type == "inbound": group["inbound"] += item.base_quantity
            elif document.document_type == "outbound": group["outbound"] += item.base_quantity
            elif document.document_type == "material": group["material"] += item.base_quantity
    rows = []
    for value in groups.values():
        product = value["product"]; ending = value["opening"] + value["inbound"] - value["outbound"] - value["material"]
        rows.append({"product_name": product.name, "category": product.category, "base_unit": value["unit"] or "基础单位",
                     "opening_quantity": _number(value["opening"]), "inbound_quantity": _number(value["inbound"]),
                     "outbound_quantity": _number(value["outbound"]), "material_quantity": _number(value["material"]),
                     "ending_quantity": _number(ending), "stock_status": "负库存" if ending < 0 else "正常"})
    rows.sort(key=lambda row: (row["category"], row["product_name"]))
    return {"columns": [_column("product_name", "商品", "text", 170), _column("category", "分类", "text", 110),
                        _column("base_unit", "基础单位", "text", 90), _column("opening_quantity", "期初库存", "number", 105),
                        _column("inbound_quantity", "本期入库", "number", 105), _column("outbound_quantity", "本期出库", "number", 105),
                        _column("material_quantity", "本期领料", "number", 105), _column("ending_quantity", "期末库存", "number", 105),
                        _column("stock_status", "库存状态", "status", 95)],
            "metrics": [_metric("products", "有库存轨迹商品", len(rows)), _metric("negative", "负库存商品", sum(row["ending_quantity"] < 0 for row in rows)),
                        _metric("inbound", "本期入库商品", sum(row["inbound_quantity"] > 0 for row in rows)),
                        _metric("outbound", "本期出库商品", sum(row["outbound_quantity"] > 0 for row in rows))],
            "rows": rows, "notes": ["进销存数量统一折算为各商品基础单位；备货仅占用库存，不作为实际出库，装车完成后才计入出库。"]}


def _adjustments(lines: list[dict]) -> dict:
    selected = [row for row in lines if row["addition_count"] or row["reduction_quantity"]]
    rows = [{"business_date": row["business_date"], "order_no": row["order_no"], "customer_name": row["customer_name"],
             "creator_name": row["creator_name"], "product_name": row["product_name"], "unit_name": row["unit_name"],
             "addition_count": row["addition_count"], "addition_quantity": _number(row["addition_quantity"]),
             "addition_amount": _money(row["addition_amount"]), "reduction_quantity": _number(row["reduction_quantity"]),
             "reduction_amount": _money(row["reduction_amount"]), "last_addition_at": row["last_addition_at"],
             "reason": row["variance_reason"] or row["remark"] or "—"} for row in selected]
    return {"columns": [_column("business_date", "业务日期", "date", 115), _column("order_no", "销售单号", "text", 180),
                        _column("customer_name", "客户", "text", 140), _column("creator_name", "订单员", "text", 110),
                        _column("product_name", "商品", "text", 145), _column("unit_name", "单位", "text", 70),
                        _column("addition_count", "加单次数", "number", 90), _column("addition_quantity", "加单数量", "number", 95),
                        _column("addition_amount", "加单金额", "money", 110), _column("reduction_quantity", "验收减量", "number", 95),
                        _column("reduction_amount", "减量金额", "money", 110), _column("last_addition_at", "最后加单", "datetime", 165),
                        _column("reason", "备注/差异原因", "text", 210)],
            "metrics": [_metric("rows", "变动商品行", len(rows)), _metric("additions", "加单次数", sum(row["addition_count"] for row in rows)),
                        _metric("addition_amount", "加单金额", _money(sum(Decimal(str(row["addition_amount"])) for row in rows)), "money"),
                        _metric("reduction_amount", "验收减量金额", _money(sum(Decimal(str(row["reduction_amount"])) for row in rows)), "money")],
            "rows": rows, "notes": ["加单来自系统记录的追加数量；减单当前按预定数量与客户验收数量的减少量统计，属于履约减量，不等同于历史编辑日志。"]}


def _dashboard(orders: list[SalesOrder], lines: list[dict], db: Session, filters: ReportFilters) -> dict:
    profit = _profit_metrics(lines)
    total_orders = len(orders); confirmed = sum(order.status == "confirmed" for order in orders)
    accepted = sum(order.acceptance_status == "accepted" for order in orders)
    addition_orders = sum(any(item.addition_count for item in order.items) for order in orders)
    customers = Counter(); products = Counter()
    for row in lines:
        customers[row["customer_name"]] += float(row["sales_amount"])
        products[row["canonical_product_name"]] += float(row["sales_amount"])
    sorter = _sorter_report(db, filters)
    rows = []
    for index, (name, amount) in enumerate(customers.most_common(10), 1):
        rows.append({"rank": index, "dimension": "客户", "name": name, "amount": _money(amount)})
    for index, (name, amount) in enumerate(products.most_common(10), 1):
        rows.append({"rank": index, "dimension": "商品", "name": name, "amount": _money(amount)})
    return {"columns": [_column("dimension", "排行类型", "status", 100), _column("rank", "排名", "number", 70),
                        _column("name", "名称", "text", 190), _column("amount", "验收销售额", "money", 130)],
            "metrics": [_metric("orders", "销售单", total_orders), _metric("confirmed", "确认率", round(confirmed / total_orders * 100, 2) if total_orders else 0, "percent"),
                        _metric("accepted", "验收完成率", round(accepted / confirmed * 100, 2) if confirmed else 0, "percent"),
                        _metric("addition_rate", "加单订单占比", round(addition_orders / total_orders * 100, 2) if total_orders else 0, "percent"),
                        *profit[:4], _metric("picking_rate", "分拣完成率", next((m["value"] for m in sorter["metrics"] if m["key"] == "rate"), 0), "percent")],
            "rows": rows, "sections": {"top_customers": [{"name": n, "amount": _money(a)} for n, a in customers.most_common(5)],
                                         "top_products": [{"name": n, "amount": _money(a)} for n, a in products.most_common(5)],
                                         "sorters": sorter["rows"][:5]},
            "notes": ["看板销售额与毛利采用客户验收口径；未验收订单不会提前计入实际销售。"]}


def build_report(db: Session, report_key: str, filters: ReportFilters, *, export: bool = False) -> dict:
    if report_key not in REPORTS:
        raise ValueError("未知报表类型")
    orders = _orders(db, filters) if report_key not in {"sorter", "purchase_orders", "inventory_flow"} else []
    lines = _lines(orders, filters) if orders else []
    builders = {
        "dashboard": lambda: _dashboard(orders, lines, db, filters),
        "reconciliation": lambda: _reconciliation_report(orders),
        "order_clerk": lambda: _order_clerk_report(orders),
        "sorter": lambda: _sorter_report(db, filters),
        "sales_orders": lambda: _sales_orders_report(orders),
        "profit_detail": lambda: _profit_detail(lines),
        "supplier_profit": lambda: _supplier_profit(lines),
        "purchase_orders": lambda: _purchase_orders(db, filters),
        "inventory_flow": lambda: _inventory_flow(db, filters),
        "customer_profit": lambda: _group_profit(lines, "customer"),
        "product_profit": lambda: _group_profit(lines, "product"),
        "adjustments": lambda: _adjustments(lines),
    }
    payload = builders[report_key]()
    payload.update({"report_key": report_key, "title": REPORTS[report_key][0], "description": REPORTS[report_key][1],
                    "date_from": filters.date_from, "date_to": filters.date_to})
    return _paginate(payload, filters, export)


def build_excel(payload: dict) -> BytesIO:
    workbook = Workbook(); sheet = workbook.active; sheet.title = payload["title"][:31]
    columns = payload["columns"]
    count = max(len(columns), 4)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=count)
    title = sheet.cell(1, 1, payload["title"]); title.font = Font(size=18, bold=True, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="2F6FB2"); title.alignment = Alignment(horizontal="center")
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=count)
    sheet.cell(2, 1, f"统计区间：{payload['date_from']} 至 {payload['date_to']} · 导出时间：{datetime.now():%Y-%m-%d %H:%M}")
    metric_text = "    ".join(f"{item['label']}：{item['value']}{'%' if item['type'] == 'percent' else ''}" for item in payload.get("metrics", []))
    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=count); sheet.cell(3, 1, metric_text)
    header_fill = PatternFill("solid", fgColor="4D88C7"); thin = Side(style="thin", color="D9E0E8")
    for index, column in enumerate(columns, 1):
        cell = sheet.cell(5, index, column["label"]); cell.font = Font(bold=True, color="FFFFFF"); cell.fill = header_fill; cell.alignment = Alignment(horizontal="center")
        sheet.column_dimensions[get_column_letter(index)].width = max(12, min(36, column.get("width", 120) / 7))
    for row_index, row in enumerate(payload.get("rows", []), 6):
        for column_index, column in enumerate(columns, 1):
            value = row.get(column["key"])
            if isinstance(value, (date, datetime)): value = value.strftime("%Y-%m-%d %H:%M" if isinstance(value, datetime) else "%Y-%m-%d")
            cell = sheet.cell(row_index, column_index, value); cell.border = Border(left=thin, right=thin, top=thin, bottom=thin); cell.alignment = Alignment(vertical="center", wrap_text=True)
            if column["type"] == "money" and value is not None: cell.number_format = '¥#,##0.00'
            elif column["type"] == "percent" and value is not None: cell.number_format = '0.00"%"'
    sheet.freeze_panes = "A6"; sheet.auto_filter.ref = f"A5:{get_column_letter(len(columns))}{max(5, 5 + len(payload.get('rows', [])))}"
    stream = BytesIO(); workbook.save(stream); stream.seek(0); return stream
