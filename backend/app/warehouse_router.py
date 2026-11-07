from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import get_db
from app.models import Product, ProductUnit, User, WarehouseDocument
from app.schemas import WarehouseDocumentIn
from app import warehouse_service


router = APIRouter(prefix="/api/warehouse", tags=["仓库管理"])
VALID_TYPES = {"inbound", "outbound", "material", "preparation"}


@router.get("/options")
def options(
    _: User = Depends(require_permission("warehouse_management")),
    db: Session = Depends(get_db),
):
    products = db.scalars(
        select(Product).options(selectinload(Product.units)).where(Product.active.is_(True)).order_by(Product.category, Product.name)
    ).all()
    return {"products": [{
        "id": product.id, "name": product.name, "category": product.category, "sku": product.sku,
        "units": [{"id": unit.id, "name": unit.name, "is_base": unit.is_base,
                   "conversion_rate": float(unit.conversion_rate)} for unit in product.units],
    } for product in products]}


@router.get("/summary")
def summary(
    _: User = Depends(require_permission("warehouse_management")),
    db: Session = Depends(get_db),
):
    rows = warehouse_service.stock_rows(db)
    return {
        "rows": rows,
        "product_count": len(rows),
        "negative_count": sum(row["available"] < 0 for row in rows),
        "reserved_count": sum(row["reserved"] > 0 for row in rows),
        "available_total": round(sum(row["available"] for row in rows), 4),
    }


@router.get("/documents")
def documents(
    document_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str = "",
    _: User = Depends(require_permission("warehouse_management")),
    db: Session = Depends(get_db),
):
    statement = warehouse_service.document_query().order_by(
        WarehouseDocument.business_date.desc(), WarehouseDocument.id.desc()
    )
    if document_type in VALID_TYPES:
        statement = statement.where(WarehouseDocument.document_type == document_type)
    if date_from:
        statement = statement.where(WarehouseDocument.business_date >= date_from)
    if date_to:
        statement = statement.where(WarehouseDocument.business_date <= date_to)
    term = keyword.strip().lower()
    rows = db.scalars(statement.limit(2000)).unique().all()
    if term:
        rows = [row for row in rows if term in f"{row.document_no}{row.source_no or ''}{row.target_name or ''}{row.warehouse}{''.join(item.product.name for item in row.items)}".lower()]
    return [warehouse_service.output(row) for row in rows]


@router.post("/documents")
def create_document(
    data: WarehouseDocumentIn,
    user: User = Depends(require_permission("warehouse_management")),
    db: Session = Depends(get_db),
):
    if data.document_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="仓库单据类型不正确")
    if not data.warehouse.strip():
        raise HTTPException(status_code=400, detail="请填写仓库名称")
    document = WarehouseDocument(
        document_no=warehouse_service._number(data.document_type),
        document_type=data.document_type, business_date=data.business_date,
        warehouse=data.warehouse.strip(), target_name=(data.target_name or "").strip() or None,
        source_type="manual", status="confirmed", notes=(data.notes or "").strip() or None,
        created_by=user.id,
    )
    db.add(document)
    try:
        warehouse_service.replace_items(document, [item.model_dump() for item in data.items], db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return warehouse_service.output(db.scalar(warehouse_service.document_query().where(WarehouseDocument.id == document.id)))


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    _: User = Depends(require_permission("warehouse_management")),
    db: Session = Depends(get_db),
):
    document = db.get(WarehouseDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="仓库单据不存在")
    if document.source_type != "manual":
        raise HTTPException(status_code=400, detail="联动生成的仓库单据不能直接删除，请修改对应来源单据")
    db.delete(document)
    db.commit()
    return {"message": "仓库单据已删除，库存结余已重新计算"}
