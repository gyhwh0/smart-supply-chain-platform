from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import get_db
from app.models import InventoryCount, Product, ProductUnit, Supplier, User, WarehouseDocument, WarehouseDocumentItem
from app.schemas import InventoryCountCreate, InventoryCountEntries, InventoryRecountIn, WarehouseDocumentIn
from app import deletion_service, inventory_count_service, warehouse_service


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
    users = db.scalars(select(User).where(User.active.is_(True), User.role.in_(["admin", "warehouse", "purchaser"])).order_by(User.name)).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)).all()
    warehouses = db.scalars(select(WarehouseDocument.warehouse).distinct().order_by(WarehouseDocument.warehouse)).all()
    locations = db.scalars(select(WarehouseDocumentItem.location).where(WarehouseDocumentItem.location.is_not(None)).distinct().order_by(WarehouseDocumentItem.location)).all()
    return {"products": [{
        "id": product.id, "name": product.name, "category": product.category, "sku": product.sku,
        "units": [{"id": unit.id, "name": unit.name, "is_base": unit.is_base,
                   "conversion_rate": float(unit.conversion_rate)} for unit in product.units],
        "abc_level": product.abc_level, "batch_management": product.batch_management,
        "default_location": product.default_location,
    } for product in products], "users": [{"id":u.id,"name":u.name} for u in users],
      "suppliers": [{"id":s.id,"name":s.name} for s in suppliers],
      "warehouses": sorted({"主仓库", *warehouses}),
      "categories": sorted({p.category for p in products}),
      "locations": locations,
      "difference_reasons": inventory_count_service.REASONS}


@router.get("/counts")
def counts(status: str | None = None, date_from: date | None = None, date_to: date | None = None,
           _: User = Depends(require_permission("warehouse_management")), db: Session = Depends(get_db)):
    statement=inventory_count_service.query().order_by(InventoryCount.id.desc())
    if status: statement=statement.where(InventoryCount.status==status)
    if date_from: statement=statement.where(InventoryCount.planned_start>=datetime.combine(date_from,datetime.min.time()))
    if date_to: statement=statement.where(InventoryCount.planned_start<datetime.combine(date_to+timedelta(days=1),datetime.min.time()))
    return [inventory_count_service.output(row) for row in db.scalars(statement.limit(1000)).unique().all()]


@router.get("/counts/{count_id}")
def count_detail(count_id:int, _:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    row=db.scalar(inventory_count_service.query().where(InventoryCount.id==count_id))
    if not row: raise HTTPException(404,"盘点单不存在")
    return inventory_count_service.output(row,True)


@router.post("/counts")
def create_count(data:InventoryCountCreate,user:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    try: row=inventory_count_service.create_count(db,data.model_dump(),user)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    return inventory_count_service.output(row,True)


@router.put("/counts/{count_id}/entries")
def save_count_entries(count_id:int,data:InventoryCountEntries,user:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    try: row=inventory_count_service.save_items(db,count_id,[item.model_dump() for item in data.items],user)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    return inventory_count_service.output(row,True)


@router.post("/counts/{count_id}/recount")
def recount(count_id:int,data:InventoryRecountIn,user:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    try: inventory_count_service.start_recount(db,count_id,data.item_ids,data.assigned_user_ids,user)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    return {"message":"复盘任务已生成"}


@router.post("/counts/{count_id}/confirm")
def confirm_count(count_id:int,user:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    try: return inventory_count_service.confirm(db,count_id,user)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc


@router.get("/counts/{count_id}/template")
def count_template(count_id:int,_:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    row=db.scalar(inventory_count_service.query().where(InventoryCount.id==count_id))
    if not row: raise HTTPException(404,"盘点单不存在")
    return StreamingResponse(inventory_count_service.excel_template(row),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":f'attachment; filename="inventory-count-{row.count_no}.xlsx"'})


@router.post("/counts/{count_id}/import")
async def import_count(count_id:int,file:UploadFile=File(...),user:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    try: return inventory_count_service.import_excel(db,count_id,await file.read(),user)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc


@router.get("/counts/{count_id}/export")
def export_count(count_id:int,_:User=Depends(require_permission("warehouse_management")),db:Session=Depends(get_db)):
    row=db.scalar(inventory_count_service.query().where(InventoryCount.id==count_id))
    if not row: raise HTTPException(404,"盘点单不存在")
    return StreamingResponse(inventory_count_service.report_excel(row),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":f'attachment; filename="inventory-count-report-{row.count_no}.xlsx"'})


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
    warehouse_service.rebuild_requisitions(db)
    db.commit()
    return warehouse_service.output(db.scalar(warehouse_service.document_query().where(WarehouseDocument.id == document.id)))


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    user: User = Depends(require_permission("warehouse_management")),
    db: Session = Depends(get_db),
):
    document = db.get(WarehouseDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="仓库单据不存在")
    if document.source_type != "manual":
        raise HTTPException(status_code=400, detail="联动生成的仓库单据不能申请删除，请修改对应来源单据")
    return deletion_service.queue_deletion(db, entity_type="warehouse_document", entity_id=document.id, entity_label=document.document_no, requester=user)
