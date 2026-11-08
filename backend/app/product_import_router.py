import json
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import get_db
from app.models import Category, Product, ProductSupplier, ProductUnit, Supplier, User

router = APIRouter(prefix="/api/product-import", tags=["商品Excel导入"])

def _style(ws):
    for cell in ws[1]: cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="3B78B5")
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions

@router.get("/template")
def template(_:User=Depends(require_permission("product_management"))):
    wb=Workbook(); ws=wb.active; ws.title="商品基础资料"
    ws.append(["商品编码SKU*","商品名称*","分类*","基础单位*","通用别名(逗号分隔)","ABC等级(A/B/C)","启用批次管理(是/否)","默认库位","保质期(天)","最低温度℃","最高温度℃","标准损耗率%","商品说明","小程序上架(是/否)"])
    ws.append(["TD001","土豆","蔬菜","斤","马铃薯,洋芋","A","是","A-01",7,0,8,3,"冷藏保存","是"]); _style(ws)
    ws=wb.create_sheet("多单位与价格"); ws.append(["商品编码SKU*","单位名称*","换算率*","销售价","参考进价"]);ws.append(["TD001","件",20,80,50]);_style(ws)
    ws=wb.create_sheet("供应商绑定");ws.append(["商品编码SKU*","供应商名称*","启用拆单(是/否)","优先级","日最大供货量","单订单最大量","固定配额比例%"]);ws.append(["TD001","示例供应商","是",1,500,300,60]);_style(ws)
    ws=wb.create_sheet("填写说明");ws.append(["场景","填写工作表"]);ws.append(["基础建档","商品基础资料"]);ws.append(["多规格价格","基础资料+多单位与价格"]);ws.append(["采购拆单","再填写供应商绑定；供应商须已存在"]);ws.append(["更新","SKU已存在时更新，不删除历史单位"])
    stream=BytesIO();wb.save(stream);stream.seek(0)
    return StreamingResponse(stream,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="product-import-template.xlsx"'})

def _yes(v): return str(v or "").strip().lower() in {"是","yes","y","1","true"}
def _decimal(v,default=None): return default if v in (None,"") else Decimal(str(v))

@router.post("")
async def import_products(file:UploadFile=File(...),user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    if not (file.filename or "").lower().endswith(".xlsx"): raise HTTPException(400,"请上传.xlsx格式模板")
    try: wb=load_workbook(BytesIO(await file.read()),data_only=True)
    except Exception as exc: raise HTTPException(400,"Excel文件无法读取") from exc
    if "商品基础资料" not in wb.sheetnames: raise HTTPException(400,"缺少商品基础资料工作表")
    created=updated=0; errors=[]; products={}
    for index,row in enumerate(wb["商品基础资料"].iter_rows(min_row=2,values_only=True),2):
        if not any(v is not None for v in row): continue
        try:
            sku,name,category_name,base_name=[str(row[i] or "").strip() for i in range(4)]
            if not all([sku,name,category_name,base_name]): raise ValueError("SKU、名称、分类和基础单位必填")
            category=db.scalar(select(Category).where(Category.name==category_name))
            if not category: category=Category(name=category_name,active=True);db.add(category);db.flush()
            product=db.scalar(select(Product).options(selectinload(Product.units)).where(Product.sku==sku)); is_new=product is None
            if is_new:
                if db.scalar(select(Product).where(Product.name==name)): raise ValueError("商品名称已存在且SKU不同")
                product=Product(sku=sku,name=name,category=category.name,category_id=category.id);db.add(product);db.flush();product.units.append(ProductUnit(name=base_name,conversion_rate=1,is_base=True))
            product.name=name;product.category=category.name;product.category_id=category.id
            product.aliases_json=json.dumps([v.strip() for v in str(row[4] or "").replace("，",",").split(",") if v.strip()],ensure_ascii=False)
            level=str(row[5] or "B").strip().upper();product.abc_level=level if level in {"A","B","C"} else "B"
            product.batch_management=_yes(row[6]);product.default_location=str(row[7] or "").strip() or None;product.shelf_life_days=int(row[8]) if row[8] not in (None,"") else None
            product.storage_temperature_min=_decimal(row[9]);product.storage_temperature_max=_decimal(row[10]);product.loss_rate=_decimal(row[11],Decimal("0"));product.description=str(row[12] or "").strip() or None;product.mini_visible=_yes(row[13]);product.active=True
            products[sku]=product;created+=int(is_new);updated+=int(not is_new)
        except Exception as exc: errors.append(f"基础资料第{index}行：{exc}")
    db.flush()
    if "多单位与价格" in wb.sheetnames:
        for index,row in enumerate(wb["多单位与价格"].iter_rows(min_row=2,values_only=True),2):
            if not any(v is not None for v in row): continue
            try:
                sku=str(row[0] or "").strip();product=products.get(sku) or db.scalar(select(Product).options(selectinload(Product.units)).where(Product.sku==sku));name=str(row[1] or "").strip();rate=_decimal(row[2])
                if not product or not name or not rate or rate<=0: raise ValueError("SKU、单位和正数换算率必填")
                unit=next((u for u in product.units if u.name==name),None)
                if not unit: unit=ProductUnit(product_id=product.id,name=name,conversion_rate=rate,is_base=False);db.add(unit)
                unit.sales_price=_decimal(row[3]);unit.reference_purchase_price=_decimal(row[4])
            except Exception as exc: errors.append(f"多单位第{index}行：{exc}")
    if "供应商绑定" in wb.sheetnames:
        for index,row in enumerate(wb["供应商绑定"].iter_rows(min_row=2,values_only=True),2):
            if not any(v is not None for v in row): continue
            try:
                product=products.get(str(row[0] or "").strip()) or db.scalar(select(Product).where(Product.sku==str(row[0] or "").strip()));supplier=db.scalar(select(Supplier).where(Supplier.name==str(row[1] or "").strip()))
                if not product or not supplier: raise ValueError("商品SKU或供应商不存在")
                link=db.scalar(select(ProductSupplier).where(ProductSupplier.product_id==product.id,ProductSupplier.supplier_id==supplier.id))
                if not link: link=ProductSupplier(product_id=product.id,supplier_id=supplier.id,assigned_by=user.id);db.add(link)
                link.active=True;link.split_enabled=_yes(row[2]);link.priority=int(row[3] or 100);link.daily_capacity_base=_decimal(row[4]);link.order_capacity_base=_decimal(row[5]);link.quota_percent=_decimal(row[6],Decimal("0"))
            except Exception as exc: errors.append(f"供应商绑定第{index}行：{exc}")
    if errors: db.rollback();raise HTTPException(400,"；".join(errors[:20]))
    db.commit();return {"message":f"导入完成：新增{created}个，更新{updated}个","created":created,"updated":updated}
