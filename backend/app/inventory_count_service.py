import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    InventoryCount, InventoryCountItem, InventoryCountLog, Product, ProductUnit,
    User, WarehouseDocument, WarehouseDocumentItem,
)


REASONS = ["正常损耗", "分拣错发/漏发", "采购入库误差", "录单错误", "计量误差", "过期报损", "其他"]


def _loads(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def query():
    return select(InventoryCount).options(
        selectinload(InventoryCount.responsible), selectinload(InventoryCount.creator),
        selectinload(InventoryCount.items).selectinload(InventoryCountItem.product),
        selectinload(InventoryCount.items).selectinload(InventoryCountItem.unit),
        selectinload(InventoryCount.items).selectinload(InventoryCountItem.counter),
    )


def batch_balances(db: Session, warehouse: str) -> dict:
    documents = db.scalars(
        select(WarehouseDocument).options(
            selectinload(WarehouseDocument.items).selectinload(WarehouseDocumentItem.product),
            selectinload(WarehouseDocument.items).selectinload(WarehouseDocumentItem.unit),
        ).where(WarehouseDocument.warehouse == warehouse, WarehouseDocument.status == "confirmed")
        .order_by(WarehouseDocument.business_date, WarehouseDocument.id)
    ).unique().all()
    balances = defaultdict(lambda: {"quantity": Decimal("0"), "cost": Decimal("0"), "product": None, "unit": None,
                                    "production_date": None, "shelf_life_days": None, "supplier_id": None})
    product_cost = defaultdict(lambda: {"quantity": Decimal("0"), "amount": Decimal("0")})
    for document in documents:
        if document.document_type == "preparation":
            continue
        sign = Decimal("1") if document.document_type == "inbound" else Decimal("-1")
        for item in document.items:
            key = (item.product_id, item.batch_no or "", item.location or item.product.default_location or "")
            row = balances[key]; row["product"] = item.product
            row["unit"] = next((u for u in item.product.units if u.is_base), item.unit)
            if item.production_date: row["production_date"] = item.production_date
            if item.shelf_life_days: row["shelf_life_days"] = item.shelf_life_days
            if item.supplier_id: row["supplier_id"] = item.supplier_id
            qty = Decimal(item.base_quantity) * sign
            if sign > 0:
                cost = Decimal(item.unit_cost_base or 0)
                if not cost and item.unit.reference_purchase_price is not None:
                    cost = Decimal(item.unit.reference_purchase_price) / Decimal(item.unit.conversion_rate)
                product_cost[item.product_id]["quantity"] += Decimal(item.base_quantity)
                product_cost[item.product_id]["amount"] += Decimal(item.base_quantity) * cost
                row["cost"] = cost or row["cost"]
            else:
                product_cost[item.product_id]["quantity"] += qty
                avg = (product_cost[item.product_id]["amount"] / (product_cost[item.product_id]["quantity"] - qty)) if (product_cost[item.product_id]["quantity"] - qty) else Decimal("0")
                product_cost[item.product_id]["amount"] += qty * avg
            row["quantity"] += qty
    for key, row in balances.items():
        cost_state = product_cost[key[0]]
        row["avg_cost"] = cost_state["amount"] / cost_state["quantity"] if cost_state["quantity"] else row["cost"]
    return balances


def _batch_status(production_date, shelf_life_days, near_days=7):
    if not production_date or not shelf_life_days:
        return "missing_expiry"
    expiry = production_date + timedelta(days=shelf_life_days)
    if expiry < date.today(): return "expired"
    if expiry <= date.today() + timedelta(days=near_days): return "near_expiry"
    return "normal"


def create_count(db: Session, data: dict, user: User) -> InventoryCount:
    if data["planned_start"] >= data["planned_end"]:
        raise ValueError("计划结束时间必须晚于开始时间")
    scope = data.get("scope") or {}
    count = InventoryCount(
        count_no=f"PD{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
        warehouse=data["warehouse"].strip(), count_type=data.get("count_type", "full"),
        planned_start=data["planned_start"], planned_end=data["planned_end"],
        responsible_id=data["responsible_id"], participant_ids_json=json.dumps(data.get("participant_ids") or []),
        scope_json=json.dumps(scope, ensure_ascii=False), difference_threshold=Decimal(str(data.get("difference_threshold", 5))),
        created_by=user.id,
    )
    db.add(count); db.flush()
    balances = batch_balances(db, count.warehouse)
    near_days = int(scope.get("near_expiry_days") or 7)
    for (product_id, batch_no, location), row in balances.items():
        product = row["product"]
        if row["quantity"] == 0: continue
        if scope.get("categories") and product.category not in scope["categories"]: continue
        if scope.get("abc_levels") and product.abc_level not in scope["abc_levels"]: continue
        if scope.get("product_ids") and product_id not in scope["product_ids"]: continue
        if scope.get("skus") and product.sku not in scope["skus"]: continue
        if scope.get("locations") and location not in scope["locations"]: continue
        if scope.get("supplier_ids") and row["supplier_id"] not in scope["supplier_ids"]: continue
        status = _batch_status(row["production_date"], row["shelf_life_days"], near_days) if product.batch_management else "not_managed"
        if scope.get("near_expiry_only") and status not in {"near_expiry", "expired"}: continue
        count.items.append(InventoryCountItem(
            product_id=product_id, unit_id=row["unit"].id, batch_no=batch_no or None, location=location or None,
            production_date=row["production_date"], shelf_life_days=row["shelf_life_days"], batch_status=status,
            assigned_user_ids_json=json.dumps(data.get("participant_ids") or [data["responsible_id"]]),
            system_qty_base=row["quantity"], avg_cost_base=row["avg_cost"] or 0,
        ))
    db.add(InventoryCountLog(count_id=count.id, action="created", operator_id=user.id,
                             detail_json=json.dumps({"scope": scope, "items": len(count.items)}, ensure_ascii=False)))
    db.commit()
    return db.scalar(query().where(InventoryCount.id == count.id))


def _recalculate(item: InventoryCountItem):
    final = item.recount_qty_base if item.recount_qty_base is not None else item.first_count_qty_base
    item.final_qty_base = final
    if final is None: return
    item.difference_qty_base = Decimal(final) - Decimal(item.system_qty_base)
    item.difference_amount = item.difference_qty_base * Decimal(item.avg_cost_base or 0)
    divisor = abs(Decimal(item.system_qty_base))
    item.difference_rate = abs(item.difference_qty_base) / divisor * 100 if divisor else (Decimal("100") if item.difference_qty_base else Decimal("0"))


def save_items(db: Session, count_id: int, rows: list[dict], user: User):
    count = db.scalar(select(InventoryCount).where(InventoryCount.id == count_id).with_for_update())
    if not count or count.status in {"confirmed", "cancelled"}: raise ValueError("盘点单不存在或已结束")
    items = {item.id: item for item in db.scalars(select(InventoryCountItem).where(InventoryCountItem.count_id == count_id).with_for_update()).all()}
    for row in rows:
        item = items.get(row.get("id"))
        if not item: continue
        product = db.get(Product, item.product_id)
        batch_no = (row.get("batch_no") or "").strip() or None
        production_date = row.get("production_date")
        shelf_life_days = row.get("shelf_life_days")
        if product.batch_management and (not batch_no or not production_date or not shelf_life_days):
            raise ValueError(f"{product.name}已启用批次管理，必须填写批次号、生产日期和保质期")
        item.batch_no=batch_no; item.production_date=production_date; item.shelf_life_days=shelf_life_days
        item.batch_status=_batch_status(production_date, shelf_life_days)
        quantity = Decimal(str(row["actual_quantity"]))
        if quantity < 0: raise ValueError("实盘数量不能小于0")
        if item.status == "recounting": item.recount_qty_base=quantity
        else: item.first_count_qty_base=quantity
        item.difference_reason=(row.get("difference_reason") or "").strip() or None
        item.reason_note=(row.get("reason_note") or "").strip() or None
        item.counted_by=user.id; item.counted_at=datetime.now(); item.status="counted"
        _recalculate(item)
        if item.difference_rate > count.difference_threshold and item.recount_qty_base is None:
            item.recount_required=True
    count.status="counting"
    db.add(InventoryCountLog(count_id=count.id, action="count_saved", operator_id=user.id,
                             detail_json=json.dumps({"item_ids": [row.get("id") for row in rows]})))
    db.commit()
    return db.scalar(query().where(InventoryCount.id == count_id))


def start_recount(db: Session, count_id: int, item_ids: list[int], assigned_ids: list[int], user: User):
    count=db.get(InventoryCount,count_id)
    if not count or count.status in {"confirmed","cancelled"}: raise ValueError("盘点单不可复盘")
    rows=db.scalars(select(InventoryCountItem).where(InventoryCountItem.count_id==count_id,InventoryCountItem.id.in_(item_ids)).with_for_update()).all()
    for item in rows:
        item.status="recounting"; item.recount_required=True
        item.assigned_user_ids_json=json.dumps(assigned_ids or [count.responsible_id])
    count.status="recounting"
    db.add(InventoryCountLog(count_id=count.id,action="recount_created",operator_id=user.id,detail_json=json.dumps({"item_ids":item_ids,"assigned_ids":assigned_ids})))
    db.commit()


def confirm(db: Session, count_id: int, user: User):
    count=db.scalar(query().where(InventoryCount.id==count_id).with_for_update())
    if not count or count.status=="confirmed": raise ValueError("盘点单不存在或已确认")
    pending=[item for item in count.items if item.final_qty_base is None]
    if pending: raise ValueError(f"仍有{len(pending)}项未录入实盘数")
    recount=[item for item in count.items if item.recount_required and item.recount_qty_base is None]
    if recount: raise ValueError(f"仍有{len(recount)}项差异超阈值，必须完成复盘")
    missing_reason=[item for item in count.items if item.difference_qty_base and not item.difference_reason]
    if missing_reason: raise ValueError(f"仍有{len(missing_reason)}项差异未标注原因")
    current=batch_balances(db,count.warehouse)
    for item in count.items:
        key=(item.product_id,item.batch_no or "",item.location or "")
        current_qty=current.get(key,{}).get("quantity",Decimal("0"))
        if current_qty != item.system_qty_base:
            raise ValueError(f"{item.product.name}盘点期间发生库存异动，请重新生成盘点单以防覆盖真实流水")
    gains=[]; losses=[]
    for item in count.items:
        _recalculate(item)
        if item.difference_qty_base > 0: gains.append(item)
        elif item.difference_qty_base < 0: losses.append(item)
        item.status="confirmed"
    for document_type, rows, label in [("inbound",gains,"盘盈"),("outbound",losses,"盘亏")]:
        if not rows: continue
        document=WarehouseDocument(document_no=f"PD{label}{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",document_type=document_type,
            business_date=date.today(),warehouse=count.warehouse,target_name=f"{count.count_no}{label}",source_type="inventory_count",
            source_id=count.id,source_no=count.count_no,status="confirmed",notes=f"盘点差异自动生成{label}调整单",created_by=user.id)
        db.add(document); db.flush()
        for item in rows:
            document.items.append(WarehouseDocumentItem(product_id=item.product_id,unit_id=item.unit_id,
                quantity=abs(item.difference_qty_base),base_quantity=abs(item.difference_qty_base),batch_no=item.batch_no,
                location=item.location,production_date=item.production_date,shelf_life_days=item.shelf_life_days,
                unit_cost_base=item.avg_cost_base,remark=f"{item.difference_reason}{'：'+item.reason_note if item.reason_note else ''}"))
    count.status="confirmed"; count.completed_at=datetime.now()
    db.add(InventoryCountLog(count_id=count.id,action="confirmed",operator_id=user.id,
        detail_json=json.dumps({"gain_items":len(gains),"loss_items":len(losses)})))
    db.commit()
    return {"message":"盘点已确认，盘盈盘亏调整单已生成","gain_items":len(gains),"loss_items":len(losses)}


def output(count: InventoryCount, detail=False):
    items=[]
    if detail:
        for item in count.items:
            items.append({"id":item.id,"product_id":item.product_id,"product_name":item.product.name,"sku":item.product.sku,
                "category":item.product.category,"abc_level":item.product.abc_level,"batch_management":item.product.batch_management,
                "unit_name":item.unit.name,"batch_no":item.batch_no,"location":item.location,"production_date":item.production_date,
                "shelf_life_days":item.shelf_life_days,"batch_status":item.batch_status,"system_quantity":float(item.system_qty_base),
                "first_count_quantity":float(item.first_count_qty_base) if item.first_count_qty_base is not None else None,
                "recount_quantity":float(item.recount_qty_base) if item.recount_qty_base is not None else None,
                "final_quantity":float(item.final_qty_base) if item.final_qty_base is not None else None,
                "avg_cost":float(item.avg_cost_base),"difference_quantity":float(item.difference_qty_base),
                "difference_amount":float(item.difference_amount),"difference_rate":float(item.difference_rate),
                "difference_reason":item.difference_reason,"reason_note":item.reason_note,"recount_required":item.recount_required,
                "status":item.status,"counter_name":item.counter.name if item.counter else None})
    differences=[item for item in count.items if item.final_qty_base is not None and item.difference_qty_base]
    return {"id":count.id,"count_no":count.count_no,"warehouse":count.warehouse,"count_type":count.count_type,
        "planned_start":count.planned_start,"planned_end":count.planned_end,"responsible_id":count.responsible_id,
        "responsible_name":count.responsible.name,"participant_ids":_loads(count.participant_ids_json,[]),
        "scope":_loads(count.scope_json,{}),"difference_threshold":float(count.difference_threshold),"status":count.status,
        "item_count":len(count.items),"counted_count":sum(item.final_qty_base is not None for item in count.items),
        "difference_count":len(differences),"difference_amount":float(sum((abs(item.difference_amount) for item in differences),Decimal("0"))),
        "accuracy_rate":round((1-len(differences)/len(count.items))*100,2) if count.items else 100,"created_at":count.created_at,"items":items}


def excel_template(count: InventoryCount) -> BytesIO:
    wb=Workbook(); ws=wb.active; ws.title="盘点录入"
    headers=["盘点项ID*","商品编码","商品名称","分类","库位","批次号","生产日期","保质期(天)","账面数量(只读)","实盘数量*","差异原因","原因说明"]
    ws.append(headers)
    for item in count.items:
        ws.append([item.id,item.product.sku,item.product.name,item.product.category,item.location,item.batch_no,item.production_date,item.shelf_life_days,float(item.system_qty_base),None,item.difference_reason,item.reason_note])
    for cell in ws[1]: cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="3B78B5")
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    for column,width in {"A":12,"B":16,"C":22,"D":15,"E":15,"F":18,"G":14,"H":14,"I":16,"J":16,"K":20,"L":28}.items(): ws.column_dimensions[column].width=width
    guide=wb.create_sheet("填写说明"); guide.append(["说明"]); guide.append(["只填写实盘数量、差异原因和原因说明；带*列不得删除。"]); guide.append(["批次管理商品的批次号、生产日期、保质期必须完整。"]); guide.append(["差异原因可选："+"、".join(REASONS)])
    stream=BytesIO(); wb.save(stream); stream.seek(0); return stream


def import_excel(db:Session,count_id:int,content:bytes,user:User):
    wb=load_workbook(BytesIO(content),data_only=True); ws=wb["盘点录入"] if "盘点录入" in wb.sheetnames else wb.active
    rows=[]; errors=[]
    for index,values in enumerate(ws.iter_rows(min_row=2,values_only=True),2):
        if not any(value is not None for value in values): continue
        try:
            rows.append({"id":int(values[0]),"batch_no":values[5],"production_date":values[6],"shelf_life_days":values[7],
                         "actual_quantity":Decimal(str(values[9])),"difference_reason":values[10],"reason_note":values[11]})
        except Exception as exc: errors.append(f"第{index}行：{exc}")
    if errors: raise ValueError("；".join(errors[:10]))
    result=save_items(db,count_id,rows,user)
    return {"message":f"成功导入{len(rows)}条盘点结果","count":output(result,True)}


def report_excel(count:InventoryCount)->BytesIO:
    wb=Workbook(); ws=wb.active; ws.title="盘点差异"
    headers=["商品编码","商品","分类","ABC","库位","批次","账面数","初盘数","复盘数","最终数","差异数","单位成本","差异金额","差异率%","原因","状态"]
    ws.append(headers)
    for item in count.items:
        ws.append([item.product.sku,item.product.name,item.product.category,item.product.abc_level,item.location,item.batch_no,float(item.system_qty_base),
            float(item.first_count_qty_base) if item.first_count_qty_base is not None else None,float(item.recount_qty_base) if item.recount_qty_base is not None else None,
            float(item.final_qty_base) if item.final_qty_base is not None else None,float(item.difference_qty_base),float(item.avg_cost_base),float(item.difference_amount),float(item.difference_rate),item.difference_reason,item.status])
    for cell in ws[1]: cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="3B78B5")
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    stream=BytesIO(); wb.save(stream); stream.seek(0); return stream
