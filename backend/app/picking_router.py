from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission, verify_password
from app.config import settings
from app.database import get_db
from app.models import (
    Customer,
    LogisticsStaff,
    PickingOperationLog,
    PickingTask,
    PickingTaskItem,
    SalesOrder,
    SalesOrderItem,
    User,
)
from app.schemas import PickingGenerateIn, PickingScanIn, StaffMobileLoginIn
from app import warehouse_service


router = APIRouter(prefix="/api", tags=["扫码分拣"])
staff_bearer = HTTPBearer(auto_error=False)


def _create_staff_session(staff: LogisticsStaff) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({
        "sub": str(staff.id),
        "purpose": "staff_mobile",
        "version": staff.mobile_session_version or 1,
        "exp": expires,
    }, settings.JWT_SECRET_KEY, algorithm="HS256")


def current_mobile_staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(staff_bearer),
    db: Session = Depends(get_db),
) -> LogisticsStaff:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先验证工作密码")
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        if payload.get("purpose") != "staff_mobile":
            raise ValueError("wrong token purpose")
        staff = db.get(LogisticsStaff, int(payload["sub"]))
        version = int(payload.get("version", 0))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="手机登录已失效，请重新验证") from exc
    if not staff or not staff.active or version != (staff.mobile_session_version or 1):
        raise HTTPException(status_code=401, detail="手机登录已失效，请重新验证")
    return staff


def _task_query():
    return select(PickingTask).options(
        selectinload(PickingTask.customer),
        selectinload(PickingTask.sorter),
        selectinload(PickingTask.delivery),
        selectinload(PickingTask.sales_order),
        selectinload(PickingTask.items),
    )


def _task_output(task: PickingTask, current_code: str | None = None) -> dict:
    items = [{
        "id": item.id,
        "product_id": item.product_id,
        "product_name": item.product_name,
        "quantity": float(item.quantity),
        "unit_name": item.unit_name,
        "scan_code": item.scan_code if item.scan_code == current_code else None,
        "picked_at": item.picked_at,
        "loaded_at": item.loaded_at,
        "exception_note": item.exception_note,
        "is_current": item.scan_code == current_code,
    } for item in task.items]
    picked_count = sum(bool(item["picked_at"]) for item in items)
    loaded_count = sum(bool(item["loaded_at"]) for item in items)
    return {
        "id": task.id,
        "task_no": task.task_no,
        "sales_order_id": task.sales_order_id,
        "sales_order_no": task.sales_order.order_no,
        "customer_id": task.customer_id,
        "customer_name": task.customer.name,
        "customer_code": task.customer.customer_code,
        "sorter_id": task.sorter_id,
        "sorter_name": task.sorter.name if task.sorter else "未分配分拣员",
        "delivery_id": task.delivery_id,
        "delivery_name": task.delivery.name if task.delivery else "未分配配送员",
        "delivery_date": task.delivery_date,
        "status": task.status,
        "notes": task.notes,
        "created_at": task.created_at,
        "picked_count": picked_count,
        "loaded_count": loaded_count,
        "total_count": len(items),
        "items": items,
    }


def _seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds()))


def _monitor_task_output(task: PickingTask) -> dict:
    output = _task_output(task)
    picked_items = sorted((item for item in task.items if item.picked_at), key=lambda item: item.picked_at)
    loaded_items = sorted((item for item in task.items if item.loaded_at), key=lambda item: item.loaded_at)
    picked_previous = {item.id: (picked_items[index - 1].picked_at if index else None) for index, item in enumerate(picked_items)}
    loaded_previous = {item.id: (loaded_items[index - 1].loaded_at if index else None) for index, item in enumerate(loaded_items)}
    item_models = {item.id: item for item in task.items}
    for item in output["items"]:
        model = item_models[item["id"]]
        item["picked_interval_seconds"] = _seconds_between(picked_previous.get(model.id), model.picked_at)
        item["loaded_interval_seconds"] = _seconds_between(loaded_previous.get(model.id), model.loaded_at)
    picking_started = picked_items[0].picked_at if picked_items else None
    picking_finished = picked_items[-1].picked_at if len(picked_items) == len(task.items) and picked_items else None
    loading_started = loaded_items[0].loaded_at if loaded_items else None
    loading_finished = loaded_items[-1].loaded_at if len(loaded_items) == len(task.items) and loaded_items else None
    output.update({
        "picking_started_at": picking_started,
        "picking_finished_at": picking_finished,
        "picking_duration_seconds": _seconds_between(picking_started, picking_finished),
        "loading_started_at": loading_started,
        "loading_finished_at": loading_finished,
        "loading_duration_seconds": _seconds_between(loading_started, loading_finished),
        "waiting_seconds": _seconds_between(task.created_at, picking_started),
        "exception_count": sum(bool(item.exception_note) for item in task.items),
    })
    return output


def _apply_stage(task: PickingTask, item: PickingTaskItem, stage: str, note: str | None, db: Session):
    now = datetime.now()
    if stage == "picked":
        item.picked_at = item.picked_at or now
    elif stage == "loaded":
        if not item.picked_at:
            raise HTTPException(status_code=400, detail="该商品尚未完成分拣，不能确认装车")
        item.loaded_at = item.loaded_at or now
        item.sales_order_item.delivered_quantity = item.quantity
    elif stage == "exception":
        item.exception_note = (note or "现场异常").strip()[:255]
    else:
        raise HTTPException(status_code=400, detail="扫码操作类型不正确")
    db.flush()
    all_picked = all(row.picked_at for row in task.items)
    all_loaded = all(row.loaded_at for row in task.items)
    any_picked = any(row.picked_at for row in task.items)
    any_loaded = any(row.loaded_at for row in task.items)
    task.status = "completed" if all_loaded else "delivering" if any_loaded else "picked" if all_picked else "picking" if any_picked else "pending"
    warehouse_service.sync_picking_task(db, task)
    warehouse_service.rebuild_requisitions(db)


@router.get("/public/staff-entry/{mobile_token}")
def public_staff_entry(mobile_token: str, db: Session = Depends(get_db)):
    staff = db.scalar(select(LogisticsStaff).where(LogisticsStaff.mobile_token == mobile_token, LogisticsStaff.active.is_(True)))
    if not staff:
        raise HTTPException(status_code=404, detail="手机入口无效或该人员已停用")
    return {
        "name": staff.name,
        "staff_type": staff.staff_type,
        "pin_configured": bool(staff.work_pin_hash),
    }


@router.post("/public/staff-login/{mobile_token}")
def public_staff_login(mobile_token: str, data: StaffMobileLoginIn, db: Session = Depends(get_db)):
    staff = db.scalar(select(LogisticsStaff).where(LogisticsStaff.mobile_token == mobile_token, LogisticsStaff.active.is_(True)))
    if not staff:
        raise HTTPException(status_code=404, detail="手机入口无效或该人员已停用")
    now = datetime.now()
    if staff.pin_locked_until and staff.pin_locked_until > now:
        minutes = max(1, int((staff.pin_locked_until - now).total_seconds() / 60) + 1)
        raise HTTPException(status_code=429, detail=f"密码错误次数过多，请{minutes}分钟后再试")
    if not staff.work_pin_hash:
        raise HTTPException(status_code=403, detail="管理员尚未设置工作密码")
    if not verify_password(data.pin, staff.work_pin_hash):
        staff.pin_fail_count = (staff.pin_fail_count or 0) + 1
        remaining = max(0, 5 - staff.pin_fail_count)
        if staff.pin_fail_count >= 5:
            staff.pin_locked_until = now + timedelta(minutes=15)
            staff.pin_fail_count = 0
        db.commit()
        if remaining:
            raise HTTPException(status_code=401, detail=f"工作密码错误，还可尝试{remaining}次")
        raise HTTPException(status_code=429, detail="密码错误次数过多，已锁定15分钟")
    staff.pin_fail_count = 0
    staff.pin_locked_until = None
    db.commit()
    return {
        "staff_token": _create_staff_session(staff),
        "staff": {"id": staff.id, "name": staff.name, "staff_type": staff.staff_type},
        "expires_days": 7,
    }


@router.get("/public/staff-tasks")
def public_staff_tasks(
    scope: str = "today",
    staff: LogisticsStaff = Depends(current_mobile_staff),
    db: Session = Depends(get_db),
):
    statement = _task_query()
    if staff.staff_type == "sorter":
        statement = statement.where(PickingTask.sorter_id == staff.id)
    elif staff.staff_type == "delivery":
        statement = statement.where(PickingTask.delivery_id == staff.id)
    else:
        raise HTTPException(status_code=400, detail="该人员不是分拣员或配送员")
    today = date.today()
    if scope == "today":
        statement = statement.where(PickingTask.delivery_date == today)
    elif scope == "tomorrow":
        statement = statement.where(PickingTask.delivery_date == today + timedelta(days=1))
    elif scope == "unfinished":
        statement = statement.where(PickingTask.status != "completed")
    elif scope != "all":
        raise HTTPException(status_code=400, detail="任务日期范围不正确")
    tasks = db.scalars(statement.order_by(PickingTask.delivery_date, PickingTask.id)).all()
    output = [_task_output(task) for task in tasks]
    return {
        "staff": {"id": staff.id, "name": staff.name, "staff_type": staff.staff_type},
        "scope": scope,
        "task_count": len(output),
        "total_items": sum(row["total_count"] for row in output),
        "completed_items": sum(
            row["picked_count"] if staff.staff_type == "sorter" else row["loaded_count"] for row in output
        ),
        "tasks": output,
    }


@router.post("/public/staff-task-items/{item_id}/confirm")
def confirm_staff_task_item(
    item_id: int,
    data: PickingScanIn,
    request: Request,
    staff: LogisticsStaff = Depends(current_mobile_staff),
    db: Session = Depends(get_db),
):
    item = db.get(PickingTaskItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务或手机入口无效")
    task = db.scalar(_task_query().where(PickingTask.id == item.task_id))
    assigned = task.sorter_id == staff.id if staff.staff_type == "sorter" else task.delivery_id == staff.id
    expected_stage = "picked" if staff.staff_type == "sorter" else "loaded"
    if not assigned:
        raise HTTPException(status_code=403, detail="该商品不属于你的任务")
    if data.stage not in {expected_stage, "exception"}:
        raise HTTPException(status_code=400, detail="当前人员不能执行该操作")
    _apply_stage(task, item, data.stage, data.note, db)
    db.add(PickingOperationLog(
        task_id=task.id, item_id=item.id, staff_id=staff.id, action=data.stage,
        note=(data.note or "")[:255] or None,
        ip_address=(request.client.host if request.client else None),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    ))
    db.commit()
    return {"message": "操作成功"}


@router.get("/picking/options")
def picking_options(
    _: User = Depends(require_permission("picking_management")),
    db: Session = Depends(get_db),
):
    tasked_ids = set(db.scalars(select(PickingTask.sales_order_id)).all())
    orders = db.scalars(
        select(SalesOrder)
        .options(
            selectinload(SalesOrder.customer).selectinload(Customer.sorter),
            selectinload(SalesOrder.customer).selectinload(Customer.delivery),
            selectinload(SalesOrder.items),
        )
        .where(SalesOrder.status == "confirmed")
        .order_by(SalesOrder.delivery_date.desc(), SalesOrder.id.desc())
        .limit(500)
    ).all()
    return [{
        "id": row.id,
        "order_no": row.order_no,
        "customer_name": row.customer.name,
        "customer_code": row.customer.customer_code,
        "delivery_date": row.delivery_date,
        "sorter_name": row.customer.sorter.name if row.customer.sorter else "未分配",
        "delivery_name": row.customer.delivery.name if row.customer.delivery else "未分配",
        "item_count": len(row.items),
        "generated": row.id in tasked_ids,
    } for row in orders]


@router.get("/picking/tasks")
def list_picking_tasks(
    delivery_date: date | None = None,
    sorter_id: int | None = None,
    delivery_id: int | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("picking_management")),
    db: Session = Depends(get_db),
):
    statement = _task_query().order_by(PickingTask.delivery_date.desc(), PickingTask.id.desc())
    if delivery_date:
        statement = statement.where(PickingTask.delivery_date == delivery_date)
    if sorter_id:
        statement = statement.where(PickingTask.sorter_id == sorter_id)
    if delivery_id:
        statement = statement.where(PickingTask.delivery_id == delivery_id)
    if status:
        statement = statement.where(PickingTask.status == status)
    return [_task_output(row) for row in db.scalars(statement).all()]


@router.get("/picking/monitor")
def picking_monitor(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_permission("picking_monitor")),
    db: Session = Depends(get_db),
):
    start = date_from or date.today()
    end = date_to or start
    if end < start:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail="单次最多查看90天数据")
    tasks = db.scalars(
        _task_query()
        .where(PickingTask.delivery_date >= start, PickingTask.delivery_date <= end)
        .order_by(PickingTask.delivery_date.desc(), PickingTask.id.desc())
        .limit(2000)
    ).all()
    task_rows = [_monitor_task_output(task) for task in tasks]
    staff_rows = db.scalars(
        select(LogisticsStaff)
        .where(LogisticsStaff.active.is_(True), LogisticsStaff.staff_type.in_({"sorter", "delivery"}))
        .order_by(LogisticsStaff.staff_type, LogisticsStaff.name)
    ).all()
    workload = []
    for staff in staff_rows:
        assigned = [row for row in task_rows if row["sorter_id" if staff.staff_type == "sorter" else "delivery_id"] == staff.id]
        done_key = "picked_count" if staff.staff_type == "sorter" else "loaded_count"
        duration_key = "picking_duration_seconds" if staff.staff_type == "sorter" else "loading_duration_seconds"
        time_key = "picked_at" if staff.staff_type == "sorter" else "loaded_at"
        total_items = sum(row["total_count"] for row in assigned)
        completed_items = sum(row[done_key] for row in assigned)
        completed_tasks = [row for row in assigned if row["total_count"] and row[done_key] == row["total_count"]]
        durations = [row[duration_key] for row in completed_tasks if row[duration_key] is not None]
        action_times = [item[time_key] for row in assigned for item in row["items"] if item[time_key]]
        pending_products = []
        for row in assigned:
            for item in row["items"]:
                if not item[time_key] and item["product_name"] not in pending_products:
                    pending_products.append(item["product_name"])
        workload.append({
            "staff_id": staff.id,
            "staff_name": staff.name,
            "staff_type": staff.staff_type,
            "task_count": len(assigned),
            "completed_task_count": len(completed_tasks),
            "in_progress_task_count": sum(0 < row[done_key] < row["total_count"] for row in assigned),
            "customer_count": len({row["customer_id"] for row in assigned}),
            "total_items": total_items,
            "completed_items": completed_items,
            "pending_items": max(0, total_items - completed_items),
            "progress": round(completed_items / total_items * 100) if total_items else 0,
            "exception_count": sum(row["exception_count"] for row in assigned),
            "average_customer_seconds": round(sum(durations) / len(durations)) if durations else None,
            "last_action_at": max(action_times) if action_times else None,
            "customers": [row["customer_name"] for row in assigned],
            "pending_products": pending_products[:12],
        })
    return {
        "date_from": start,
        "date_to": end,
        "overview": {
            "task_count": len(task_rows),
            "completed_task_count": sum(row["status"] == "completed" for row in task_rows),
            "total_items": sum(row["total_count"] for row in task_rows),
            "picked_items": sum(row["picked_count"] for row in task_rows),
            "loaded_items": sum(row["loaded_count"] for row in task_rows),
            "exception_count": sum(row["exception_count"] for row in task_rows),
            "working_staff_count": sum(bool(row["completed_items"]) for row in workload),
        },
        "staff": workload,
        "tasks": task_rows,
    }


@router.post("/picking/tasks/generate")
def generate_picking_tasks(
    data: PickingGenerateIn,
    _: User = Depends(require_permission("picking_management")),
    db: Session = Depends(get_db),
):
    created = skipped = 0
    for order_id in dict.fromkeys(data.sales_order_ids):
        if db.scalar(select(PickingTask.id).where(PickingTask.sales_order_id == order_id)):
            skipped += 1
            continue
        order = db.scalar(
            select(SalesOrder)
            .options(
                selectinload(SalesOrder.customer),
                selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
                selectinload(SalesOrder.items).selectinload(SalesOrderItem.unit),
            )
            .where(SalesOrder.id == order_id)
        )
        if not order or order.status != "confirmed":
            skipped += 1
            continue
        task = PickingTask(
            task_no=f"FJ{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
            sales_order_id=order.id,
            customer_id=order.customer_id,
            sorter_id=order.customer.sorter_id,
            delivery_id=order.customer.delivery_id,
            delivery_date=order.delivery_date,
            public_token=uuid4().hex + uuid4().hex,
            status="pending",
        )
        task.items = [PickingTaskItem(
            sales_order_item_id=item.id,
            product_id=item.product_id,
            product_name=item.display_name or item.product.name,
            quantity=item.quantity,
            unit_name=item.unit.name,
            scan_code=uuid4().hex + uuid4().hex[:8],
        ) for item in order.items]
        db.add(task)
        db.flush()
        warehouse_service.sync_picking_task(db, task)
        created += 1
    warehouse_service.rebuild_requisitions(db)
    db.commit()
    return {"message": f"已生成 {created} 个客户分拣任务，跳过 {skipped} 个已有或无效订单", "created": created, "skipped": skipped}


@router.get("/public/picking/{scan_code}")
def public_picking(scan_code: str, db: Session = Depends(get_db)):
    item = db.scalar(select(PickingTaskItem).where(PickingTaskItem.scan_code == scan_code))
    if not item:
        raise HTTPException(status_code=404, detail="分拣标签无效或已作废")
    task = db.scalar(_task_query().where(PickingTask.id == item.task_id))
    return _task_output(task, scan_code)


@router.post("/public/picking/{scan_code}")
def confirm_public_scan(
    scan_code: str,
    data: PickingScanIn,
    request: Request,
    staff: LogisticsStaff = Depends(current_mobile_staff),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(PickingTaskItem).where(PickingTaskItem.scan_code == scan_code))
    if not item:
        raise HTTPException(status_code=404, detail="分拣标签无效或已作废")
    task = db.scalar(_task_query().where(PickingTask.id == item.task_id))
    assigned = task.sorter_id == staff.id if staff.staff_type == "sorter" else task.delivery_id == staff.id
    expected_stage = "picked" if staff.staff_type == "sorter" else "loaded"
    if not assigned:
        raise HTTPException(status_code=403, detail="该商品不属于你的任务")
    if data.stage not in {expected_stage, "exception"}:
        raise HTTPException(status_code=400, detail="当前人员不能执行该操作")
    _apply_stage(task, item, data.stage, data.note, db)
    db.add(PickingOperationLog(
        task_id=task.id, item_id=item.id, staff_id=staff.id, action=data.stage,
        note=(data.note or "")[:255] or None,
        ip_address=(request.client.host if request.client else None),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    ))
    db.commit()
    task = db.scalar(_task_query().where(PickingTask.id == task.id))
    return _task_output(task, scan_code)
