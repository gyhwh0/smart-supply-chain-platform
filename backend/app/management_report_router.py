from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.database import get_db
from app.management_report_service import REPORTS, ReportFilters, build_excel, build_report
from app.models import Customer, LogisticsStaff, Product, Supplier, User


router = APIRouter(prefix="/api/reports", tags=["report-management"])


def _filters(
    date_from: date = Query(default_factory=date.today),
    date_to: date = Query(default_factory=date.today),
    customer_id: int | None = None,
    supplier_id: int | None = None,
    creator_id: int | None = None,
    sorter_id: int | None = None,
    product_id: int | None = None,
    category: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
) -> ReportFilters:
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    if (date_to - date_from).days > 366:
        raise HTTPException(status_code=400, detail="单次查询范围不能超过 366 天")
    return ReportFilters(
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        supplier_id=supplier_id,
        creator_id=creator_id,
        sorter_id=sorter_id,
        product_id=product_id,
        category=category,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


def _option(rows, label="name"):
    return [{"id": row.id, "name": getattr(row, label)} for row in rows]


@router.get("/catalog")
def report_catalog(
    _: User = Depends(require_permission("report_management")),
    db: Session = Depends(get_db),
):
    customers = db.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.name)).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
    products = db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.name)).all()
    creators = db.scalars(
        select(User).where(User.active.is_(True), User.role.in_(["admin", "purchaser", "order_clerk"])).order_by(User.name)
    ).all()
    sorters = db.scalars(
        select(LogisticsStaff).where(LogisticsStaff.active.is_(True), LogisticsStaff.staff_type == "sorter").order_by(LogisticsStaff.name)
    ).all()
    categories = sorted({product.category for product in products if product.category})
    reports = [
        {"key": key, "name": value[0], "description": value[1], "group": "运营管理" if key in {"dashboard", "reconciliation", "order_clerk", "sorter"} else "经营报表"}
        for key, value in REPORTS.items()
    ]
    return {
        "reports": reports,
        "customers": _option(customers),
        "suppliers": _option(suppliers),
        "products": _option(products),
        "creators": _option(creators),
        "sorters": _option(sorters),
        "categories": categories,
        "statuses": [
            {"value": "draft", "name": "草稿"},
            {"value": "confirmed", "name": "已确认"},
        ],
    }


@router.get("/export/{report_key}")
def export_report(
    report_key: str,
    filters: ReportFilters = Depends(_filters),
    _: User = Depends(require_permission("report_management")),
    db: Session = Depends(get_db),
):
    try:
        payload = build_report(db, report_key, filters, export=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = quote(f"{payload['title']}_{filters.date_from}_{filters.date_to}.xlsx")
    return StreamingResponse(
        build_excel(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/{report_key}")
def report_data(
    report_key: str,
    filters: ReportFilters = Depends(_filters),
    _: User = Depends(require_permission("report_management")),
    db: Session = Depends(get_db),
):
    try:
        return build_report(db, report_key, filters)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
