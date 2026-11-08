import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import get_db
from app.models import Category, Product, ProductImportJob, ProductImportMapping, ProductSupplier, ProductUnit, Quote, Supplier, SupplierTierPrice, User, WarehouseDocument, WarehouseDocumentItem

router = APIRouter(prefix="/api/product-import", tags=["商品Excel导入"])
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads" / "product_imports"
IMAGE_DIR = Path(__file__).resolve().parent.parent / "uploads" / "product_images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True); IMAGE_DIR.mkdir(parents=True, exist_ok=True)

FIELD_DEFS = {
    "sku": ("商品编码", "text", True, ["sku", "货号", "商品编号", "物料编码", "产品编码"]),
    "barcode": ("条码", "text", False, ["商品条码", "国际条码", "barcode"]),
    "name": ("商品名称", "text", True, ["品名", "货品名称", "产品名称", "物料名称", "菜名"]),
    "category": ("商品分类", "text", True, ["分类", "品类", "类别", "所属分类"]),
    "base_unit": ("基础单位", "text", True, ["主单位", "基本单位", "计量单位", "单位"]),
    "aliases": ("通用别名", "text", False, ["别名", "商品别名", "搜索词"]),
    "brand": ("品牌", "text", False, ["品牌名称"]), "specification": ("规格型号", "text", False, ["规格", "型号"]),
    "origin": ("产地", "text", False, ["原产地", "产区"]), "grade": ("商品等级", "text", False, ["等级", "品质等级"]),
    "abc_level": ("ABC等级", "text", False, ["abc", "商品等级abc"]), "batch_management": ("启用批次管理", "bool", False, ["批次管理", "是否批次", "批号管理"]),
    "default_location": ("默认库位", "text", False, ["库位", "货位", "默认货位"]), "shelf_life_days": ("保质期天数", "integer", False, ["保质期", "保质期(天)", "质保期"]),
    "storage_temperature_min": ("最低保存温度", "number", False, ["最低温度", "储存温度下限"]), "storage_temperature_max": ("最高保存温度", "number", False, ["最高温度", "储存温度上限"]),
    "loss_rate": ("标准损耗率%", "number", False, ["损耗率", "损耗比例"]), "storage_notes": ("保存要求", "text", False, ["储存说明", "存储要求", "保管要求"]),
    "traceability_code": ("溯源码", "text", False, ["追溯码", "溯源编码"]), "fresh_attribute": ("生鲜属性", "text", False, ["鲜冻属性", "商品属性"]),
    "slaughter_batch": ("屠宰批次要求", "text", False, ["屠宰批次", "检疫批次"]), "aquatic_state": ("水产状态", "text", False, ["冰鲜冻品属性", "水产属性"]),
    "inventory_min": ("库存预警下限", "number", False, ["最低库存", "安全库存", "库存下限"]), "inventory_max": ("库存预警上限", "number", False, ["最高库存", "库存上限"]),
    "sales_price": ("普通销售价", "number", False, ["销售价", "售价", "普通客户价"]), "vip_sales_price": ("VIP销售价", "number", False, ["vip价", "会员价"]),
    "key_account_sales_price": ("大客户价", "number", False, ["协议价", "重点客户价"]), "min_sales_price": ("最低售价", "number", False, ["销售底价", "最低销售价"]),
    "max_sales_price": ("最高售价", "number", False, ["最高销售价"]), "reference_purchase_price": ("参考进价", "number", False, ["采购价", "成本价", "参考采购价"]),
    "unit2_name": ("辅助单位1", "text", False, ["副单位1", "销售单位1"]), "unit2_rate": ("辅助单位1换算率", "number", False, ["换算率1", "单位1比例"]),
    "unit2_sales_price": ("辅助单位1销售价", "number", False, ["单位1售价"]), "unit2_purchase_price": ("辅助单位1参考进价", "number", False, ["单位1进价"]),
    "unit3_name": ("辅助单位2", "text", False, ["副单位2", "销售单位2"]), "unit3_rate": ("辅助单位2换算率", "number", False, ["换算率2", "单位2比例"]),
    "unit3_sales_price": ("辅助单位2销售价", "number", False, ["单位2售价"]), "unit3_purchase_price": ("辅助单位2参考进价", "number", False, ["单位2进价"]),
    "unit4_name": ("辅助单位3", "text", False, ["副单位3", "销售单位3"]), "unit4_rate": ("辅助单位3换算率", "number", False, ["换算率3", "单位3比例"]),
    "unit4_sales_price": ("辅助单位3销售价", "number", False, ["单位3售价"]), "unit4_purchase_price": ("辅助单位3参考进价", "number", False, ["单位3进价"]),
    "unit5_name": ("辅助单位4", "text", False, ["副单位4", "销售单位4"]), "unit5_rate": ("辅助单位4换算率", "number", False, ["换算率4", "单位4比例"]),
    "unit5_sales_price": ("辅助单位4销售价", "number", False, ["单位4售价"]), "unit5_purchase_price": ("辅助单位4参考进价", "number", False, ["单位4进价"]),
    "unit6_name": ("辅助单位5", "text", False, ["副单位5", "销售单位5"]), "unit6_rate": ("辅助单位5换算率", "number", False, ["换算率5", "单位5比例"]),
    "unit6_sales_price": ("辅助单位5销售价", "number", False, ["单位5售价"]), "unit6_purchase_price": ("辅助单位5参考进价", "number", False, ["单位5进价"]),
    "supplier1": ("供应商1", "text", False, ["主供应商", "供应商"]), "supplier1_price": ("供应商1供货价", "number", False, ["主供应商报价", "供货价"]),
    "supplier1_moq": ("供应商1起订量", "number", False, ["起订量"]), "supplier1_daily_capacity": ("供应商1日最大供货量", "number", False, ["日最大供货量"]),
    "supplier1_order_capacity": ("供应商1单订单最大量", "number", False, ["单订单最大量"]), "supplier1_priority": ("供应商1优先级", "integer", False, ["供应商优先级"]),
    "supplier1_tiers": ("供应商1阶梯价", "text", False, ["采购阶梯价", "阶梯报价"]), "supplier2": ("供应商2", "text", False, []),
    "supplier2_price": ("供应商2供货价", "number", False, []), "supplier2_moq": ("供应商2起订量", "number", False, []),
    "supplier2_daily_capacity": ("供应商2日最大供货量", "number", False, []), "supplier2_order_capacity": ("供应商2单订单最大量", "number", False, []),
    "supplier2_priority": ("供应商2优先级", "integer", False, []), "supplier2_tiers": ("供应商2阶梯价", "text", False, []),
    "initial_quantity": ("期初库存数量", "number", False, ["初始库存", "期初数量"]), "initial_cost": ("期初单位成本", "number", False, ["期初成本", "初始成本"]),
    "initial_batch": ("期初批次号", "text", False, ["批次号", "批号"]), "production_date": ("生产日期", "date", False, ["生产日"]),
    "description": ("商品说明", "text", False, ["描述", "备注"]), "active": ("启用状态", "bool", False, ["是否启用", "状态"]), "mini_visible": ("小程序上架", "bool", False, ["是否上架", "商城上架"]),
}

def _norm(v): return re.sub(r"[\s_\-（）()/%℃]", "", str(v or "").strip().lower())
def _yes(v): return str(v or "").strip().lower() in {"是","yes","y","1","true","启用","上架"}
def _blank(v): return v is None or (isinstance(v,float) and pd.isna(v)) or str(v).strip()==""
def _value(v): return None if _blank(v) else v
def _decimal(v):
    if _blank(v): return None
    try: return Decimal(str(v).replace(",", "").replace("￥", "").strip())
    except (InvalidOperation, AttributeError) as exc: raise ValueError("必须是数字") from exc
def _integer(v):
    n=_decimal(v);return None if n is None else int(n)
def _json(v): return json.dumps(v,ensure_ascii=False,default=str)
def _aliases(v):
    result=[];seen=set()
    for item in re.split(r"[,，]",str(v or "")):
        item=item.strip();key=item.casefold()
        if item and key not in seen:seen.add(key);result.append(item)
    return result
def _signature(headers): return hashlib.sha256("|".join(_norm(h) for h in headers).encode()).hexdigest()
def _field_options(): return [{"key":k,"label":m[0],"type":m[1],"required":m[2]} for k,m in FIELD_DEFS.items()]

def _auto_mapping(headers):
    lookup={}
    for key,(label,_,__,aliases) in FIELD_DEFS.items():
        for name in [label,key,*aliases]:lookup[_norm(name)]=key
    return {str(h):lookup[_norm(h)] for h in headers if _norm(h) in lookup}

def _style(ws,widths=None):
    fill=PatternFill("solid",fgColor="2F6FB2")
    for cell in ws[1]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=fill;cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
    ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions;ws.row_dimensions[1].height=36
    for i in range(1,ws.max_column+1):ws.column_dimensions[ws.cell(1,i).column_letter].width=(widths or {}).get(i,18)

def _template(keys):
    wb=Workbook();ws=wb.active;ws.title="商品导入";ws.append([FIELD_DEFS[k][0]+("*" if FIELD_DEFS[k][2] else "") for k in keys])
    ex={"sku":"SP001","barcode":"690000000001","name":"金典有机纯牛奶梦幻盖","category":"乳制品类","base_unit":"盒","aliases":"金典牛奶，梦幻盖牛奶, 有机纯牛奶，金典牛奶","brand":"金典","specification":"250ml/盒","origin":"中国","grade":"一级","abc_level":"A","batch_management":"是","default_location":"A-01","shelf_life_days":180,"storage_temperature_min":0,"storage_temperature_max":25,"loss_rate":1,"traceability_code":"TRACE001","fresh_attribute":"常温","inventory_min":10,"inventory_max":500,"sales_price":7,"vip_sales_price":6.8,"key_account_sales_price":6.5,"min_sales_price":6,"max_sales_price":8,"reference_purchase_price":5.5,"unit2_name":"件","unit2_rate":10,"unit2_sales_price":68,"unit2_purchase_price":55,"unit3_name":"箱","unit3_rate":20,"unit3_sales_price":136,"unit3_purchase_price":110,"supplier1":"示例供应商","supplier1_price":5.5,"supplier1_moq":20,"supplier1_daily_capacity":500,"supplier1_order_capacity":300,"supplier1_priority":1,"supplier1_tiers":"100:5.3;300:5.1","initial_quantity":100,"initial_cost":5.5,"initial_batch":"QC20261108","production_date":date.today(),"active":"是","mini_visible":"否"}
    ws.append([ex.get(k) for k in keys]);_style(ws)
    info=wb.create_sheet("字段说明");info.append(["字段","必填","格式与业务规则","常见列名"])
    for k in keys:
        label,kind,required,aliases=FIELD_DEFS[k];rule={"number":"数值，不得为负数；换算率必须大于0","integer":"整数，不得为负数","bool":"是/否、启用/停用、1/0","date":"Excel日期或YYYY-MM-DD","text":"文本"}[kind]
        if k=="aliases":rule="多个别名用英文逗号或中文逗号分隔；导入自动去空格、去重"
        if k=="base_unit":rule="每个商品只能有一个基础单位；所有辅助单位均换算到此单位"
        info.append([label,"是" if required else "否",rule,"、".join(aliases)])
    _style(info,{1:24,2:10,3:52,4:42});guide=wb.create_sheet("导入说明");guide.append(["步骤","说明"]);guide.append([1,"一行代表一个商品；可在同一行填写基础单位和最多5个辅助单位。"]);guide.append([2,"换算率表示1个辅助单位包含多少个基础单位，例如基础单位=盒，1件=10盒，则填10。"]);guide.append([3,"别名支持中英文逗号混用，系统自动去空格、去重；导入后可用于商品搜索和下单匹配。"]);guide.append([4,"上传后先检查字段映射和三级校验结果，确认预览后才会写入数据库。"]);guide.append([5,"供应商阶梯价格式：100:5.8;300:5.5。"]);_style(guide,{1:12,2:100})
    stream=BytesIO();wb.save(stream);stream.seek(0);return stream

def _read(path):
    issues=[]
    if path.suffix.lower()==".xlsx":
        wb=load_workbook(path,data_only=True);ws=wb.active
        if len(wb.sheetnames)>1:issues.append({"level":"file","message":f"检测到{len(wb.sheetnames)}个Sheet，读取第一个：{ws.title}","suggestion":"确认数据位于第一个Sheet"})
        if ws.merged_cells.ranges:issues.append({"level":"file","message":"检测到合并单元格","suggestion":"数据区域不要使用合并单元格"})
        hidden=[c.column_letter for c in ws[1] if ws.column_dimensions[c.column_letter].hidden]
        if hidden:issues.append({"level":"file","message":f"检测到隐藏列：{','.join(hidden)}","suggestion":"展开并确认隐藏列"})
        values=list(ws.iter_rows(values_only=True))
        if not values:raise ValueError("Excel没有数据")
        headers=[str(v or "").strip().rstrip("*") for v in values[0]];rows=[dict(zip(headers,row))|{"__row__":i} for i,row in enumerate(values[1:],2) if any(not _blank(v) for v in row)]
        return headers,rows,issues,ws.title
    if path.suffix.lower()==".xls":
        frame=pd.read_excel(path,dtype=object);headers=[str(c).strip().rstrip("*") for c in frame.columns];rows=[{**{h:r.get(h) for h in headers},"__row__":i+2} for i,r in frame.iterrows() if any(not _blank(r.get(h)) for h in headers)];return headers,rows,issues,"Sheet1"
    raise ValueError("仅支持.xlsx或.xls文件")

def _mapped(raw,mapping):return [{"__row__":r["__row__"],**{k:_value(r.get(h)) for h,k in mapping.items() if k in FIELD_DEFS}} for r in raw]
def _err(row,col,level,msg,fix):return {"row":row,"column":col,"level":level,"message":msg,"suggestion":fix}

def _validate(rows,mode,db):
    errors=[];valid=[];skipped=[];seen_sku={};seen_barcode={};seen_name={};categories={x.name for x in db.scalars(select(Category).where(Category.active.is_(True))).all()};suppliers={x.name for x in db.scalars(select(Supplier).where(Supplier.active.is_(True))).all()};existing_skus=set(db.scalars(select(Product.sku).where(Product.sku.is_not(None))).all());existing_barcodes=set(db.scalars(select(Product.barcode).where(Product.barcode.is_not(None))).all());existing_names={name:sku for name,sku in db.execute(select(Product.name,Product.sku)).all()};numeric=[k for k,m in FIELD_DEFS.items() if m[1] in {"number","integer"}]
    for row in rows:
        bad=[];line=row["__row__"];sku=str(row.get("sku") or "").strip();existing=sku in existing_skus
        if not sku:bad.append(_err(line,"商品编码","field","商品编码不能为空","填写唯一SKU编码"))
        if sku in seen_sku:bad.append(_err(line,"商品编码","field",f"与第{seen_sku[sku]}行重复","每个SKU只保留一行"))
        elif sku:seen_sku[sku]=line
        if not existing or mode in {"create","overwrite"}:
            for k in ["name","category","base_unit"]:
                if _blank(row.get(k)):bad.append(_err(line,FIELD_DEFS[k][0],"field","必填字段为空","补充该字段"))
        name=str(row.get("name") or "").strip()
        if name:
            if name in seen_name and seen_name[name] != sku:bad.append(_err(line,"商品名称","field",f"与其他SKU使用了相同商品名称：{name}","商品名称必须唯一，或合并为同一SKU"))
            else:seen_name[name]=sku
            if name in existing_names and existing_names[name] != sku:bad.append(_err(line,"商品名称","business","商品名称已被其他SKU使用","修改名称，或使用原商品编码更新"))
        barcode=str(row.get("barcode") or "").strip()
        if barcode:
            if barcode in seen_barcode:bad.append(_err(line,"条码","field",f"与第{seen_barcode[barcode]}行重复","条码必须唯一"))
            else:seen_barcode[barcode]=line
            if barcode in existing_barcodes and not existing:bad.append(_err(line,"条码","business","条码已被其他商品使用","修改为唯一条码"))
        if mode=="create" and existing:skipped.append({"row":line,"sku":sku,"reason":"纯新增模式：编码已存在"});continue
        if row.get("category") and str(row["category"]).strip() not in categories:bad.append(_err(line,"商品分类","business","分类不存在","先在分类管理中新增"))
        for k in numeric:
            if _blank(row.get(k)):continue
            try:
                n=_decimal(row[k])
                if n<0:raise ValueError("不能为负数")
                row[k]=int(n) if FIELD_DEFS[k][1]=="integer" else str(n)
            except Exception as exc:bad.append(_err(line,FIELD_DEFS[k][0],"field",str(exc),"填写大于或等于0的数字"))
        unit_names=[str(row.get("base_unit") or "").strip().casefold()]
        for index in range(2,7):
            name,rate=f"unit{index}_name",f"unit{index}_rate"
            if row.get(name) and (_blank(row.get(rate)) or Decimal(str(row.get(rate) or 0))<=0):bad.append(_err(line,FIELD_DEFS[rate][0],"business","辅助单位换算率必须大于0","填写正确换算比例"))
            if row.get(name):unit_names.append(str(row[name]).strip().casefold())
        populated=[value for value in unit_names if value]
        if len(populated)!=len(set(populated)):bad.append(_err(line,"单位","business","基础单位与辅助单位存在重复","每个商品只能有一个基础单位，且单位名称不能重复"))
        if row.get("min_sales_price") is not None and row.get("max_sales_price") is not None and Decimal(str(row["min_sales_price"]))>Decimal(str(row["max_sales_price"])):bad.append(_err(line,"最低/最高售价","business","最低售价高于最高售价","调整价格区间"))
        if row.get("inventory_min") is not None and row.get("inventory_max") is not None and Decimal(str(row["inventory_min"]))>Decimal(str(row["inventory_max"])):bad.append(_err(line,"库存上下限","business","库存下限高于上限","调整库存区间"))
        if _yes(row.get("batch_management")) and _blank(row.get("shelf_life_days")):bad.append(_err(line,"保质期天数","business","批次商品未填写保质期","补充效期参数"))
        for k in ["supplier1","supplier2"]:
            if row.get(k) and str(row[k]).strip() not in suppliers:bad.append(_err(line,FIELD_DEFS[k][0],"business","供应商不存在","先新增并启用供应商"))
        if bad:errors.extend(bad)
        else:valid.append(row)
    return valid,errors,skipped

def _job(job):return {"id":job.id,"job_no":job.job_no,"filename":job.filename,"mode":job.import_mode,"status":job.status,"summary":json.loads(job.summary_json or "{}"),"created_at":job.created_at,"operator":job.creator.name if job.creator else "—","has_error_report":bool(job.error_report_path)}

@router.get("/config")
def config(_:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    mappings=db.scalars(select(ProductImportMapping).where(ProductImportMapping.active.is_(True)).order_by(ProductImportMapping.id.desc())).all();return {"fields":_field_options(),"mappings":[{"id":m.id,"name":m.name,"signature":m.header_signature,"mapping":json.loads(m.mapping_json)} for m in mappings]}

@router.get("/template")
def template(_:User=Depends(require_permission("product_management"))):
    return StreamingResponse(_template(list(FIELD_DEFS)),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="product-import-template.xlsx"'})

@router.get("/export")
def export_products(_:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    products=db.scalars(select(Product).options(selectinload(Product.units),selectinload(Product.assignments).selectinload(ProductSupplier.supplier),selectinload(Product.assignments).selectinload(ProductSupplier.quotes),selectinload(Product.assignments).selectinload(ProductSupplier.tier_prices)).order_by(Product.id)).unique().all();keys=list(FIELD_DEFS);wb=load_workbook(_template(keys));ws=wb["商品导入"];ws.delete_rows(2,ws.max_row)
    for p in products:
        base=next((u for u in p.units if u.is_base),p.units[0] if p.units else None);extras=[u for u in p.units if not u.is_base];links=[a for a in p.assignments if a.active]
        v={"sku":p.sku,"barcode":p.barcode,"name":p.name,"category":p.category,"base_unit":base.name if base else None,"aliases":",".join(p.aliases),"brand":p.brand,"specification":p.specification,"origin":p.origin,"grade":p.grade,"abc_level":p.abc_level,"batch_management":"是" if p.batch_management else "否","default_location":p.default_location,"shelf_life_days":p.shelf_life_days,"storage_temperature_min":p.storage_temperature_min,"storage_temperature_max":p.storage_temperature_max,"loss_rate":p.loss_rate,"storage_notes":p.storage_notes,"traceability_code":p.traceability_code,"fresh_attribute":p.fresh_attribute,"slaughter_batch":p.slaughter_batch,"aquatic_state":p.aquatic_state,"inventory_min":p.inventory_min,"inventory_max":p.inventory_max,"sales_price":base.sales_price if base else None,"vip_sales_price":base.vip_sales_price if base else None,"key_account_sales_price":base.key_account_sales_price if base else None,"min_sales_price":base.min_sales_price if base else None,"max_sales_price":base.max_sales_price if base else None,"reference_purchase_price":base.reference_purchase_price if base else None,"description":p.description,"active":"是" if p.active else "否","mini_visible":"是" if p.mini_visible else "否"}
        for i,u in enumerate(extras[:5],2):v.update({f"unit{i}_name":u.name,f"unit{i}_rate":u.conversion_rate,f"unit{i}_sales_price":u.sales_price,f"unit{i}_purchase_price":u.reference_purchase_price})
        for i,a in enumerate(links[:2],1):
            quote=next((q for q in a.quotes if base and q.unit_id==base.id),None);tiers=";".join(f"{tier.min_base_quantity}:{tier.base_unit_price}" for tier in a.tier_prices)
            v.update({f"supplier{i}":a.supplier.name,f"supplier{i}_price":quote.price if quote else None,f"supplier{i}_moq":a.min_order_base,f"supplier{i}_daily_capacity":a.daily_capacity_base,f"supplier{i}_order_capacity":a.order_capacity_base,f"supplier{i}_priority":a.priority,f"supplier{i}_tiers":tiers})
        ws.append([v.get(k) for k in keys])
    stream=BytesIO();wb.save(stream);stream.seek(0);return StreamingResponse(stream,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="products-export.xlsx"'})

@router.post("/preview")
async def preview(file:UploadFile=File(...),mode:str=Form("incremental"),user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx",".xls"}:raise HTTPException(400,"仅支持.xlsx或.xls文件")
    content=await file.read()
    if len(content)>20*1024*1024:raise HTTPException(400,"文件不能超过20MB")
    stored=f"{datetime.now():%Y%m%d%H%M%S}_{uuid4().hex}{suffix}";path=UPLOAD_DIR/stored;path.write_bytes(content)
    try:headers,rows,issues,sheet=_read(path)
    except Exception as exc:path.unlink(missing_ok=True);raise HTTPException(400,str(exc)) from exc
    sig=_signature(headers);mapping=_auto_mapping(headers);saved=db.scalar(select(ProductImportMapping).where(ProductImportMapping.header_signature==sig,ProductImportMapping.active.is_(True)).order_by(ProductImportMapping.id.desc()))
    if saved:mapping=json.loads(saved.mapping_json)
    job=ProductImportJob(job_no=f"DR{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",filename=(file.filename or "商品导入")[:255],file_path=stored,import_mode=mode,status="uploaded",header_signature=sig,mapping_json=_json(mapping),created_by=user.id,summary_json=_json({"sheet":sheet,"raw_rows":len(rows),"file_issues":issues,"headers":headers}));db.add(job);db.commit();db.refresh(job)
    return {"job_id":job.id,"job_no":job.job_no,"headers":headers,"mapping":mapping,"fields":_field_options(),"saved_mapping_name":saved.name if saved else None,"file_issues":issues,"raw_rows":len(rows),"preview":[{k:v for k,v in r.items() if k!="__row__"} for r in rows[:10]]}

def _error_report(errors,raw,headers):
    wb=Workbook();ws=wb.active;ws.title="错误明细";ws.append(["Excel行号","字段","错误层级","错误原因","修正建议"])
    for e in errors:ws.append([e["row"],e["column"],e["level"],e["message"],e["suggestion"]])
    _style(ws,{1:12,2:22,3:12,4:42,5:42});source=wb.create_sheet("错误原始行");source.append(["Excel行号",*headers]);bad={e["row"] for e in errors}
    for r in raw:
        if r["__row__"] in bad:source.append([r["__row__"],*[r.get(h) for h in headers]])
    _style(source);stream=BytesIO();wb.save(stream);stream.seek(0);return stream

@router.post("/validate/{job_id}")
def validate(job_id:int,payload:dict,user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    job=db.get(ProductImportJob,job_id)
    if not job:raise HTTPException(404,"导入任务不存在")
    mode=payload.get("mode") or job.import_mode
    if mode not in {"create","overwrite","incremental"}:raise HTTPException(400,"导入模式不正确")
    mapping=payload.get("mapping") or json.loads(job.mapping_json or "{}");headers,raw,issues,_=_read(UPLOAD_DIR/job.file_path);targets=[v for v in mapping.values() if v]
    if len(targets)!=len(set(targets)):raise HTTPException(400,"多个Excel列不能映射同一字段")
    if "sku" not in targets:raise HTTPException(400,"必须映射商品编码")
    rows=_mapped(raw,mapping);valid,errors,skipped=_validate(rows,mode,db);skip=bool(payload.get("skip_errors"));categories=Counter(str(r.get("category") or "未分类") for r in valid);prices=[float(r["sales_price"]) for r in valid if r.get("sales_price") is not None];summary={"raw_rows":len(rows),"valid_rows":len(valid),"error_rows":len({e["row"] for e in errors}),"error_count":len(errors),"skipped_rows":len(skipped),"categories":dict(categories),"price_min":min(prices) if prices else None,"price_max":max(prices) if prices else None,"can_commit":bool(valid) and (not errors or skip),"file_issues":issues}
    job.import_mode=mode;job.mapping_json=_json(mapping);job.preview_json=_json(valid);job.errors_json=_json(errors);job.summary_json=_json(summary);job.status="validated" if summary["can_commit"] else "validation_failed"
    name=str(payload.get("save_mapping_name") or "").strip()
    if name:
        scheme=db.scalar(select(ProductImportMapping).where(ProductImportMapping.name==name))
        if not scheme:scheme=ProductImportMapping(name=name,header_signature=job.header_signature,mapping_json=_json(mapping),created_by=user.id);db.add(scheme)
        else:scheme.header_signature=job.header_signature;scheme.mapping_json=_json(mapping);scheme.active=True
    if errors:
        report=_error_report(errors,raw,headers);filename=f"errors_{job.job_no}.xlsx";(UPLOAD_DIR/filename).write_bytes(report.getvalue());job.error_report_path=filename
    db.commit();return {"job_id":job.id,"summary":summary,"errors":errors[:200],"skipped":skipped[:200],"preview":valid[:20]}

def _set(obj,key,value,mode):
    if mode=="incremental" and _blank(value):return
    setattr(obj,key,value)
def _tiers(text):
    out=[]
    for part in str(text or "").replace("，",",").replace("；",";").split(";"):
        if not part.strip():continue
        bits=re.split(r"[:：,]",part)
        if len(bits)!=2:raise ValueError(f"阶梯价格式错误：{part}")
        out.append((_decimal(bits[0]),_decimal(bits[1])))
    return out

@router.post("/commit/{job_id}")
def commit(job_id:int,user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    job=db.scalar(select(ProductImportJob).where(ProductImportJob.id==job_id).with_for_update())
    if not job or job.status!="validated":raise HTTPException(400,"请先完成校验")
    rows=json.loads(job.preview_json or "[]");mode=job.import_mode;created=updated=0;initial=[];product_ids=[]
    try:
        categories={x.name:x for x in db.scalars(select(Category).where(Category.active.is_(True))).all()};suppliers={x.name:x for x in db.scalars(select(Supplier).where(Supplier.active.is_(True))).all()}
        for row in rows:
            sku=str(row["sku"]).strip();p=db.scalar(select(Product).options(selectinload(Product.units),selectinload(Product.assignments).selectinload(ProductSupplier.tier_prices)).where(Product.sku==sku));new=p is None
            if new:p=Product(sku=sku,name=str(row["name"]).strip(),category=str(row["category"]).strip(),category_id=categories[str(row["category"]).strip()].id);db.add(p);db.flush();created+=1
            else:updated+=1
            product_ids.append(p.id)
            for k in ["barcode","brand","specification","origin","grade","traceability_code","fresh_attribute","slaughter_batch","aquatic_state","default_location","storage_notes","description"]:
                if k in row:_set(p,k,str(row[k]).strip() if not _blank(row[k]) else None,mode)
            if "name" in row and not _blank(row["name"]):p.name=str(row["name"]).strip()
            if "category" in row and not _blank(row["category"]):c=categories[str(row["category"]).strip()];p.category=c.name;p.category_id=c.id
            if "aliases" in row:_set(p,"aliases_json",_json(_aliases(row.get("aliases"))),mode)
            if row.get("abc_level"):p.abc_level=str(row["abc_level"]).strip().upper()
            for k in ["shelf_life_days","storage_temperature_min","storage_temperature_max","loss_rate","inventory_min","inventory_max"]:
                if k in row:_set(p,k,_integer(row[k]) if k=="shelf_life_days" else _decimal(row[k]),mode)
            for k in ["batch_management","active","mini_visible"]:
                if k in row and not _blank(row[k]):setattr(p,k,_yes(row[k]))
            base_name=str(row.get("base_unit") or "").strip();base=next((u for u in p.units if u.is_base),None)
            if not base and base_name:base=ProductUnit(product_id=p.id,name=base_name,conversion_rate=1,is_base=True);db.add(base);p.units.append(base)
            if base:
                if new and base_name:base.name=base_name
                for k in ["sales_price","vip_sales_price","key_account_sales_price","min_sales_price","max_sales_price","reference_purchase_price"]:
                    if k in row:_set(base,k,_decimal(row[k]),mode)
            for i in range(2,7):
                name=str(row.get(f"unit{i}_name") or "").strip()
                if not name:continue
                unit=next((u for u in p.units if u.name==name),None)
                if not unit:unit=ProductUnit(product_id=p.id,name=name,conversion_rate=_decimal(row.get(f"unit{i}_rate")) or 1,is_base=False);db.add(unit);p.units.append(unit)
                if row.get(f"unit{i}_sales_price") is not None:unit.sales_price=_decimal(row[f"unit{i}_sales_price"])
                if row.get(f"unit{i}_purchase_price") is not None:unit.reference_purchase_price=_decimal(row[f"unit{i}_purchase_price"])
            db.flush()
            for i in [1,2]:
                supplier_name=str(row.get(f"supplier{i}") or "").strip()
                if not supplier_name:continue
                supplier=suppliers[supplier_name];link=next((a for a in p.assignments if a.supplier_id==supplier.id),None)
                if not link:link=ProductSupplier(product_id=p.id,supplier_id=supplier.id,assigned_by=user.id);db.add(link);p.assignments.append(link)
                link.active=True;link.split_enabled=True
                for suffix,attr in [("moq","min_order_base"),("daily_capacity","daily_capacity_base"),("order_capacity","order_capacity_base")]:
                    if row.get(f"supplier{i}_{suffix}") is not None:setattr(link,attr,_decimal(row[f"supplier{i}_{suffix}"]))
                if row.get(f"supplier{i}_priority") is not None:link.priority=_integer(row[f"supplier{i}_priority"])
                db.flush()
                if row.get(f"supplier{i}_price") is not None and base:
                    quote=db.scalar(select(Quote).where(Quote.assignment_id==link.id,Quote.unit_id==base.id))
                    if not quote:quote=Quote(assignment_id=link.id,unit_id=base.id,price=_decimal(row[f"supplier{i}_price"]));db.add(quote)
                    else:quote.price=_decimal(row[f"supplier{i}_price"])
                if row.get(f"supplier{i}_tiers"):
                    link.tier_prices.clear();db.flush()
                    for qty,price in _tiers(row[f"supplier{i}_tiers"]):link.tier_prices.append(SupplierTierPrice(min_base_quantity=qty,base_unit_price=price))
            if row.get("initial_quantity") is not None and _decimal(row["initial_quantity"])>0 and base:initial.append((p,base,row))
        if initial:
            doc=WarehouseDocument(document_no=f"QC{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",document_type="inbound",business_date=date.today(),warehouse="主仓库",target_name="商品导入期初库存",source_type="product_import",source_id=job.id,source_no=job.job_no,status="confirmed",notes="商品导入中心生成期初库存",created_by=user.id);db.add(doc);db.flush()
            for p,unit,row in initial:
                qty=_decimal(row["initial_quantity"]);cost=_decimal(row.get("initial_cost")) or _decimal(row.get("reference_purchase_price")) or Decimal("0");production=pd.to_datetime(row.get("production_date")).date() if row.get("production_date") else None;doc.items.append(WarehouseDocumentItem(product_id=p.id,unit_id=unit.id,quantity=qty,base_quantity=qty,batch_no=str(row.get("initial_batch") or "").strip() or None,location=p.default_location,production_date=production,shelf_life_days=p.shelf_life_days,unit_cost_base=cost,remark="期初库存导入"))
        job.status="committed";job.committed_at=datetime.now();summary=json.loads(job.summary_json or "{}");summary.update({"created":created,"updated":updated,"initial_stock_items":len(initial),"product_ids":product_ids});job.summary_json=_json(summary);db.commit()
    except Exception as exc:db.rollback();raise HTTPException(400,f"导入事务已回滚：{exc}") from exc
    return {"message":f"导入完成：新增{created}个，更新{updated}个，期初库存{len(initial)}项","created":created,"updated":updated,"initial_stock_items":len(initial)}

@router.post("/jobs/{job_id}/batch-adjust")
def batch_adjust(job_id:int,payload:dict,user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    job=db.get(ProductImportJob,job_id)
    if not job or job.status!="committed":raise HTTPException(400,"仅已完成的导入任务可以批量整理")
    summary=json.loads(job.summary_json or "{}");product_ids=summary.get("product_ids") or []
    if not product_ids:raise HTTPException(400,"该历史任务没有可批量处理的商品范围")
    products=db.scalars(select(Product).options(selectinload(Product.units),selectinload(Product.assignments)).where(Product.id.in_(product_ids))).unique().all()
    category_id=payload.get("category_id");category=db.get(Category,category_id) if category_id else None
    if category_id and (not category or not category.active):raise HTTPException(400,"指定分类不存在或已停用")
    supplier_ids=[int(v) for v in payload.get("supplier_ids") or []]
    suppliers=db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids),Supplier.active.is_(True))).all() if supplier_ids else []
    if len(suppliers)!=len(set(supplier_ids)):raise HTTPException(400,"供应商不存在或已停用")
    percent=_decimal(payload.get("sales_price_percent"))
    if percent is not None and percent<=0:raise HTTPException(400,"调价百分比必须大于0")
    category_rules=[]
    for rule in payload.get("category_rules") or []:
        keyword=str(rule.get("keyword") or "").strip().lower();target=db.get(Category,rule.get("category_id")) if rule.get("category_id") else None
        if keyword and (not target or not target.active):raise HTTPException(400,f"关键词“{keyword}”对应的分类不存在或已停用")
        if keyword:category_rules.append((keyword,target))
    changed=0
    for product in products:
        if category:product.category_id=category.id;product.category=category.name
        else:
            searchable=" ".join([product.name,product.sku or "",*product.aliases]).lower()
            matched=next((target for keyword,target in category_rules if keyword in searchable),None)
            if matched:product.category_id=matched.id;product.category=matched.name
        if payload.get("active") is not None:product.active=bool(payload["active"])
        if payload.get("inventory_min") is not None:product.inventory_min=_decimal(payload["inventory_min"])
        if payload.get("inventory_max") is not None:product.inventory_max=_decimal(payload["inventory_max"])
        if product.inventory_min is not None and product.inventory_max is not None and product.inventory_min>product.inventory_max:raise HTTPException(400,f"{product.name}库存下限不能高于上限")
        if percent is not None:
            factor=percent/Decimal("100")
            for unit in product.units:
                for field in ["sales_price","vip_sales_price","key_account_sales_price","min_sales_price","max_sales_price"]:
                    value=getattr(unit,field)
                    if value is not None:setattr(unit,field,(Decimal(value)*factor).quantize(Decimal("0.0001")))
        current={item.supplier_id for item in product.assignments}
        for supplier in suppliers:
            if supplier.id not in current:product.assignments.append(ProductSupplier(supplier_id=supplier.id,assigned_by=user.id,active=True,split_enabled=True))
        changed+=1
    adjustments=summary.get("batch_adjustments") or [];adjustments.append({"at":datetime.now().isoformat(),"operator":user.name,"count":changed,"category_id":category_id,"category_rules":[{"keyword":k,"category_id":c.id} for k,c in category_rules],"supplier_ids":supplier_ids,"sales_price_percent":str(percent) if percent is not None else None});summary["batch_adjustments"]=adjustments[-20:];job.summary_json=_json(summary);db.commit()
    return {"message":f"已批量整理 {changed} 个商品","changed":changed}

@router.get("/jobs")
def jobs(_:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    rows=db.scalars(select(ProductImportJob).options(selectinload(ProductImportJob.creator)).order_by(ProductImportJob.id.desc()).limit(200)).all();return [_job(r) for r in rows]
@router.get("/jobs/{job_id}/original")
def original(job_id:int,_:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    job=db.get(ProductImportJob,job_id);path=UPLOAD_DIR/(job.file_path if job else "")
    if not job or not path.exists():raise HTTPException(404,"原始文件不存在")
    return FileResponse(path,filename=job.filename)
@router.get("/jobs/{job_id}/errors")
def errors(job_id:int,_:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    job=db.get(ProductImportJob,job_id);path=UPLOAD_DIR/(job.error_report_path if job and job.error_report_path else "")
    if not job or not job.error_report_path or not path.exists():raise HTTPException(404,"错误报告不存在")
    return FileResponse(path,filename=f"{job.job_no}-错误明细.xlsx",media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@router.post("/images")
async def import_images(file:UploadFile=File(...),user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    if not (file.filename or "").lower().endswith(".zip"):raise HTTPException(400,"请上传ZIP图片包")
    content=await file.read()
    if len(content)>100*1024*1024:raise HTTPException(400,"图片包不能超过100MB")
    matched=0;unmatched=[]
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            members=[m for m in archive.infolist() if not m.is_dir() and Path(m.filename).suffix.lower() in {".jpg",".jpeg",".png",".webp"}]
            if sum(m.file_size for m in members)>200*1024*1024:raise ValueError("解压后图片不能超过200MB")
            for member in members:
                stem=Path(member.filename).stem;sku=re.split(r"[_-](?:详情|detail|主图|main)",stem,flags=re.I)[0];p=db.scalar(select(Product).where(Product.sku==sku))
                if not p:unmatched.append(Path(member.filename).name);continue
                suffix=Path(member.filename).suffix.lower();stored=f"{uuid4().hex}{suffix}";(IMAGE_DIR/stored).write_bytes(archive.read(member));detail=bool(re.search(r"(?:详情|detail)",stem,re.I))
                if detail:images=json.loads(p.detail_images_json or "[]");images.append(stored);p.detail_images_json=_json(images[-8:])
                else:p.image_path=stored;p.image_name=Path(member.filename).name;p.image_content_type=f"image/{suffix.lstrip('.').replace('jpg','jpeg')}"
                matched+=1
    except (zipfile.BadZipFile,ValueError) as exc:raise HTTPException(400,str(exc)) from exc
    db.commit();return {"message":f"成功关联{matched}张图片，未匹配{len(unmatched)}张","matched":matched,"unmatched":unmatched[:100]}

@router.post("")
async def legacy_import(file:UploadFile=File(...),user:User=Depends(require_permission("product_management")),db:Session=Depends(get_db)):
    raise HTTPException(400,"导入流程已升级，请进入商品导入中心完成字段映射、校验预览和确认导入")
