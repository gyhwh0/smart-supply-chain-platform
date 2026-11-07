from datetime import date, datetime, time, timedelta
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import SessionLocal, get_db
from app.models import (
    Complaint,
    Customer,
    SalesOrder,
    User,
    WeComCustomerBinding,
    WeComMessage,
    WeComOrderDraft,
    WeComOrderDraftItem,
)
from app.schemas import ComplaintCreate, ComplaintUpdate, WeComBindingCreate, WeComSimulateMessage
from app import deletion_service, wecom_service


router = APIRouter(prefix="/api", tags=["企业微信"])


def _datetime_range(date_from: date | None, date_to: date | None):
    start = datetime.combine(date_from, time.min) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None
    return start, end


def _run_sync_event(event: dict):
    with SessionLocal() as db:
        wecom_service.process_sync_event(db, event)


@router.get("/wecom/callback")
def verify_wecom_callback(
    msg_signature: str = Query(alias="msg_signature"),
    timestamp: str = Query(),
    nonce: str = Query(),
    echostr: str = Query(),
):
    try:
        return Response(
            content=wecom_service.verify_callback(msg_signature, timestamp, nonce, echostr),
            media_type="text/plain",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wecom/callback")
async def receive_wecom_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(alias="msg_signature"),
    timestamp: str = Query(),
    nonce: str = Query(),
):
    try:
        event = wecom_service.parse_callback(await request.body(), msg_signature, timestamp, nonce)
        background_tasks.add_task(_run_sync_event, event)
        return Response(content="success", media_type="text/plain")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wecom/status")
def wecom_status(
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    status = wecom_service.wecom_config_status()
    draft_msgids = set(db.scalars(select(WeComOrderDraft.source_msgid)).all())
    pending_messages = db.scalars(
        select(WeComMessage).where(WeComMessage.status.in_({"needs_binding", "needs_review", "failed"}))
    ).all()
    status.update(
        binding_count=len(db.scalars(select(WeComCustomerBinding)).all()),
        pending_message_count=len([row for row in pending_messages if row.msgid not in draft_msgids]),
        pending_draft_count=len(
            db.scalars(
                select(WeComOrderDraft).where(WeComOrderDraft.status.in_({"needs_review", "awaiting_confirmation"}))
            ).all()
        ),
    )
    return status


@router.get("/wecom/attention")
def wecom_attention(
    user: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    complaint_statement = select(Complaint).where(
        Complaint.severity == "P0",
        Complaint.status.notin_({"resolved", "closed"}),
    )
    draft_statement = select(WeComOrderDraft).where(WeComOrderDraft.status == "needs_review")
    message_statement = select(WeComMessage).where(
        WeComMessage.status.in_({"needs_binding", "needs_review", "failed"})
    )
    if user.role == "order_clerk":
        complaint_statement = complaint_statement.where(Complaint.assigned_to == user.id)
        draft_statement = draft_statement.where(WeComOrderDraft.assigned_to == user.id)
        message_statement = message_statement.join(
            Customer, WeComMessage.customer_id == Customer.id
        ).where(Customer.order_clerk_id == user.id)
    complaints = db.scalars(complaint_statement.order_by(Complaint.id.desc())).all()
    drafts = db.scalars(draft_statement.order_by(WeComOrderDraft.id.desc())).all()
    messages = db.scalars(message_statement.order_by(WeComMessage.id.desc())).all()
    draft_msgids = set(db.scalars(select(WeComOrderDraft.source_msgid)).all())
    standalone_messages = [row for row in messages if row.msgid not in draft_msgids]
    return {
        "urgent_complaints": len(complaints),
        "review_items": len(drafts) + len(standalone_messages),
        "review_drafts": len(drafts),
        "review_messages": len(standalone_messages),
        "latest_complaint": (
            {
                "id": complaints[0].id,
                "complaint_no": complaints[0].complaint_no,
                "content": complaints[0].content,
            }
            if complaints
            else None
        ),
    }


@router.get("/wecom/bindings")
def list_bindings(
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(WeComCustomerBinding)
        .options(selectinload(WeComCustomerBinding.customer))
        .order_by(WeComCustomerBinding.id.desc())
    ).all()
    return [
        {
            "id": row.id,
            "customer_id": row.customer_id,
            "customer_name": row.customer.name,
            "customer_code": row.customer.customer_code,
            "external_userid": row.external_userid,
            "open_kfid": row.open_kfid,
            "verified": row.verified,
            "bind_method": row.bind_method,
            "wechat_name": row.wechat_name,
            "wechat_remark": row.wechat_remark,
            "display_name": row.wechat_remark or row.wechat_name or row.customer.contact_name or row.customer.name,
            "last_seen_at": row.last_seen_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/wecom/options")
def wecom_options(
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    customers = db.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.name)).all()
    clerks = db.scalars(
        select(User)
        .where(User.active.is_(True), User.role == "order_clerk")
        .order_by(User.name)
    ).all()
    return {
        "customers": [
            {
                "id": row.id,
                "name": row.name,
                "customer_code": row.customer_code,
                "order_clerk_id": row.order_clerk_id,
            }
            for row in customers
        ],
        "clerks": [{"id": row.id, "name": row.name, "role": row.role} for row in clerks],
    }


@router.post("/wecom/bindings")
def save_binding(
    data: WeComBindingCreate,
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, data.customer_id)
    if not customer or not customer.active:
        raise HTTPException(status_code=400, detail="请选择有效客户")
    external_userid = data.external_userid.strip()
    open_kfid = data.open_kfid.strip()
    if not external_userid:
        raise HTTPException(status_code=400, detail="企业微信客户ID不能为空")
    binding = db.scalar(
        select(WeComCustomerBinding).where(
            WeComCustomerBinding.external_userid == external_userid,
            WeComCustomerBinding.open_kfid == open_kfid,
        )
    )
    if binding:
        binding.customer_id = customer.id
        binding.verified = data.verified
        binding.bind_method = "manual"
        if data.wechat_remark is not None:
            binding.wechat_remark = data.wechat_remark.strip() or None
    else:
        binding = WeComCustomerBinding(
            customer_id=customer.id,
            external_userid=external_userid,
            open_kfid=open_kfid,
            verified=data.verified,
            bind_method="manual",
            wechat_remark=(data.wechat_remark or "").strip() or None,
        )
        db.add(binding)
    db.commit()
    return {"message": "微信客户绑定已保存"}


@router.delete("/wecom/bindings/{binding_id}")
def delete_binding(
    binding_id: int,
    user: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    binding = db.get(WeComCustomerBinding, binding_id)
    if not binding:
        raise HTTPException(status_code=404, detail="绑定记录不存在")
    return deletion_service.queue_deletion(db, entity_type="wecom_binding", entity_id=binding.id, entity_label=f"微信客户 {binding.external_userid}", requester=user)


@router.get("/wecom/messages")
def list_wecom_messages(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    statement = (
        select(WeComMessage)
        .options(selectinload(WeComMessage.customer))
        .order_by(WeComMessage.occurred_at.desc(), WeComMessage.id.desc())
        .limit(min(max(limit, 1), 500))
    )
    if status:
        statement = statement.where(WeComMessage.status == status)
    start, end = _datetime_range(date_from, date_to)
    if start:
        statement = statement.where(WeComMessage.occurred_at >= start)
    if end:
        statement = statement.where(WeComMessage.occurred_at < end)
    return [
        {
            "id": row.id,
            "msgid": row.msgid,
            "external_userid": row.external_userid,
            "open_kfid": row.open_kfid,
            "customer_name": row.customer.name if row.customer else "未绑定客户",
            "direction": row.direction,
            "msg_type": row.msg_type,
            "content": row.content,
            "intent": row.intent,
            "status": row.status,
            "occurred_at": row.occurred_at,
        }
        for row in db.scalars(statement).all()
    ]


@router.put("/wecom/messages/{message_id}/resolve")
def resolve_wecom_message(
    message_id: int,
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    message = db.get(WeComMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="微信消息不存在")
    if message.status not in {"needs_binding", "needs_review", "failed"}:
        return {"message": "该消息已经处理"}
    message.status = "resolved"
    db.commit()
    return {"message": "已标记为处理完成"}


def draft_output(row: WeComOrderDraft):
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "customer_name": row.customer.name,
        "assigned_to": row.assigned_to,
        "assignee_name": row.assignee.name if row.assignee else "未分配订单员",
        "raw_message": row.raw_message,
        "delivery_date": row.delivery_date,
        "status": row.status,
        "confidence": float(row.confidence),
        "parse_notes": row.parse_notes,
        "sales_order_id": row.sales_order_id,
        "created_at": row.created_at,
        "items": [
            {
                "id": item.id,
                "requested_name": item.requested_name,
                "product_name": (
                    next(
                        (
                            str(alias.get("alias"))
                            for alias in item.product.customer_aliases
                            if int(alias.get("customer_id", 0)) == row.customer_id
                        ),
                        item.product.name,
                    )
                    if item.product
                    else None
                ),
                "canonical_product_name": item.product.name if item.product else None,
                "unit_name": item.unit.name if item.unit else None,
                "quantity": float(item.quantity),
                "unit_price": float(item.unit_price) if item.unit_price is not None else None,
                "matched": item.matched,
                "specification": item.specification,
                "remark": item.remark,
            }
            for item in row.items
        ],
    }


@router.get("/wecom/order-drafts")
def list_order_drafts(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    statement = (
        select(WeComOrderDraft)
        .options(
            selectinload(WeComOrderDraft.customer),
            selectinload(WeComOrderDraft.assignee),
            selectinload(WeComOrderDraft.items).selectinload(WeComOrderDraftItem.product),
            selectinload(WeComOrderDraft.items).selectinload(WeComOrderDraftItem.unit),
        )
        .order_by(WeComOrderDraft.id.desc())
    )
    if status:
        statement = statement.where(WeComOrderDraft.status == status)
    start, end = _datetime_range(date_from, date_to)
    if start:
        statement = statement.where(WeComOrderDraft.created_at >= start)
    if end:
        statement = statement.where(WeComOrderDraft.created_at < end)
    return [draft_output(row) for row in db.scalars(statement).unique().all()]


@router.post("/wecom/order-drafts/{draft_id}/confirm")
def confirm_order_draft(
    draft_id: int,
    user: User = Depends(require_permission("sales_order_management")),
    db: Session = Depends(get_db),
):
    draft = db.scalar(
        select(WeComOrderDraft)
        .options(selectinload(WeComOrderDraft.items), selectinload(WeComOrderDraft.customer))
        .where(WeComOrderDraft.id == draft_id)
    )
    if not draft:
        raise HTTPException(status_code=404, detail="微信订单草稿不存在")
    if draft.status == "confirmed":
        return {"message": "该订单已经生成销售单", "sales_order_id": draft.sales_order_id}
    if not draft.assigned_to:
        draft.assigned_to = draft.customer.order_clerk_id or user.id
    try:
        order = wecom_service._confirm_draft(db, draft)
        source_message = db.scalar(select(WeComMessage).where(WeComMessage.msgid == draft.source_msgid))
        if source_message:
            source_message.status = "processed"
        db.commit()
        return {"message": "已生成并确认销售单", "sales_order_id": order.id, "order_no": order.order_no}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wecom/simulate-message")
def simulate_message(
    data: WeComSimulateMessage,
    _: User = Depends(require_permission("wecom_management")),
    db: Session = Depends(get_db),
):
    return wecom_service.process_inbound_message(
        db,
        msgid=f"SIM-{uuid4().hex}",
        external_userid=data.external_userid.strip(),
        open_kfid=data.open_kfid.strip() or "test-kf",
        content=data.content.strip(),
        payload={"msgtype": "text", "source": "simulation"},
    )


@router.get("/complaints")
def list_complaints(
    status: str | None = None,
    severity: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_permission("complaint_management")),
    db: Session = Depends(get_db),
):
    statement = (
        select(Complaint)
        .options(selectinload(Complaint.customer), selectinload(Complaint.assignee))
        .order_by(Complaint.id.desc())
    )
    if status:
        statement = statement.where(Complaint.status == status)
    if severity:
        statement = statement.where(Complaint.severity == severity)
    start, end = _datetime_range(date_from, date_to)
    if start:
        statement = statement.where(Complaint.created_at >= start)
    if end:
        statement = statement.where(Complaint.created_at < end)
    return [
        {
            "id": row.id,
            "complaint_no": row.complaint_no,
            "customer_id": row.customer_id,
            "customer_name": row.customer.name,
            "assigned_to": row.assigned_to,
            "assignee_name": row.assignee.name if row.assignee else "未分配",
            "sales_order_id": row.sales_order_id,
            "category": row.category,
            "severity": row.severity,
            "content": row.content,
            "status": row.status,
            "due_at": row.due_at,
            "resolution": row.resolution,
            "created_at": row.created_at,
            "overdue": bool(row.due_at and row.due_at < datetime.now() and row.status not in {"resolved", "closed"}),
        }
        for row in db.scalars(statement).all()
    ]


@router.get("/complaints/summary")
def complaint_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_permission("complaint_management")),
    db: Session = Depends(get_db),
):
    complaint_statement = select(func.count()).select_from(Complaint)
    start, end = _datetime_range(date_from, date_to)
    if start:
        complaint_statement = complaint_statement.where(Complaint.created_at >= start)
    if end:
        complaint_statement = complaint_statement.where(Complaint.created_at < end)
    order_statement = select(func.count()).select_from(SalesOrder)
    if date_from:
        order_statement = order_statement.where(SalesOrder.order_date >= date_from)
    if date_to:
        order_statement = order_statement.where(SalesOrder.order_date <= date_to)
    complaint_count = db.scalar(complaint_statement) or 0
    order_count = db.scalar(order_statement) or 0
    return {
        "complaint_count": complaint_count,
        "order_count": order_count,
        "complaint_rate": round(complaint_count / order_count * 100, 2) if order_count else 0,
    }


@router.post("/complaints")
def create_complaint(
    data: ComplaintCreate,
    _: User = Depends(require_permission("complaint_management")),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, data.customer_id)
    if not customer or not customer.active:
        raise HTTPException(status_code=400, detail="请选择有效客户")
    if data.severity not in {"P0", "P1", "P2"}:
        raise HTTPException(status_code=400, detail="投诉等级不正确")
    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="请填写投诉内容")
    assigned_to = data.assigned_to or customer.order_clerk_id
    if assigned_to:
        assignee = db.get(User, assigned_to)
        if not assignee or not assignee.active:
            raise HTTPException(status_code=400, detail="请选择有效处理人")
    if data.sales_order_id:
        order = db.get(SalesOrder, data.sales_order_id)
        if not order or order.customer_id != customer.id:
            raise HTTPException(status_code=400, detail="关联销售单与所选客户不一致")
    now = datetime.now()
    complaint = Complaint(
        complaint_no=f"CP{now:%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
        customer_id=customer.id,
        assigned_to=assigned_to,
        sales_order_id=data.sales_order_id,
        category=data.category.strip() or "其他",
        severity=data.severity,
        content=content,
        status="new",
        due_at=now + timedelta(hours=1 if data.severity == "P0" else 4 if data.severity == "P1" else 24),
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return {"message": "投诉已登记", "id": complaint.id, "complaint_no": complaint.complaint_no}


@router.put("/complaints/{complaint_id}")
def update_complaint(
    complaint_id: int,
    data: ComplaintUpdate,
    _: User = Depends(require_permission("complaint_management")),
    db: Session = Depends(get_db),
):
    if data.status not in {"new", "processing", "waiting_customer", "resolved", "closed"}:
        raise HTTPException(status_code=400, detail="投诉状态不正确")
    complaint = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="投诉记录不存在")
    if data.customer_id is not None:
        customer = db.get(Customer, data.customer_id)
        if not customer or not customer.active:
            raise HTTPException(status_code=400, detail="请选择有效客户")
        complaint.customer_id = customer.id
    if data.severity is not None:
        if data.severity not in {"P0", "P1", "P2"}:
            raise HTTPException(status_code=400, detail="投诉等级不正确")
        if complaint.severity != data.severity:
            complaint.due_at = datetime.now() + timedelta(
                hours=1 if data.severity == "P0" else 4 if data.severity == "P1" else 24
            )
        complaint.severity = data.severity
    if data.category is not None:
        complaint.category = data.category.strip() or "其他"
    if data.content is not None:
        content = data.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="投诉内容不能为空")
        complaint.content = content
    if data.assigned_to:
        assignee = db.get(User, data.assigned_to)
        if not assignee or not assignee.active:
            raise HTTPException(status_code=400, detail="请选择有效处理人")
    complaint.status = data.status
    complaint.assigned_to = data.assigned_to
    complaint.resolution = (data.resolution or "").strip() or None
    db.commit()
    return {"message": "投诉处理信息已更新"}


@router.delete("/complaints/{complaint_id}")
def delete_complaint(
    complaint_id: int,
    user: User = Depends(require_permission("complaint_management")),
    db: Session = Depends(get_db),
):
    complaint = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="投诉记录不存在")
    return deletion_service.queue_deletion(db, entity_type="complaint", entity_id=complaint.id, entity_label=complaint.complaint_no, requester=user)
