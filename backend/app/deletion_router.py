from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_permission
from app.database import get_db
from app.deletion_service import ENTITY_NAMES, execute_deletion
from app.models import DeletionRequest, User


router = APIRouter(prefix="/api/deletion-requests", tags=["deletion-approval"])


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=255)


def _admin(user: User = Depends(require_permission("deletion_approval"))) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以审核删除申请")
    return user


def output(row: DeletionRequest) -> dict:
    return {
        "id": row.id,
        "entity_type": row.entity_type,
        "entity_type_name": ENTITY_NAMES.get(row.entity_type, row.entity_type),
        "entity_id": row.entity_id,
        "entity_label": row.entity_label,
        "requester_name": row.requester.name,
        "status": row.status,
        "reviewer_name": row.reviewer.name if row.reviewer else None,
        "review_note": row.review_note,
        "execution_result": row.execution_result,
        "created_at": row.created_at,
        "reviewed_at": row.reviewed_at,
    }


@router.get("")
def list_requests(
    status: str | None = None,
    _: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    statement = select(DeletionRequest).options(
        selectinload(DeletionRequest.requester), selectinload(DeletionRequest.reviewer)
    ).order_by(DeletionRequest.id.desc())
    if status in {"pending", "approved", "rejected"}:
        statement = statement.where(DeletionRequest.status == status)
    return [output(row) for row in db.scalars(statement).all()]


@router.post("/{request_id}/approve")
def approve_request(
    request_id: int,
    data: ReviewIn,
    reviewer: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    request = db.get(DeletionRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="删除申请不存在")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已经处理")
    result = execute_deletion(db, request, reviewer)
    request.review_note = (data.note or "").strip() or None
    db.commit()
    return {"message": result}


@router.post("/{request_id}/reject")
def reject_request(
    request_id: int,
    data: ReviewIn,
    reviewer: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    request = db.get(DeletionRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="删除申请不存在")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已经处理")
    request.status = "rejected"
    request.reviewed_by = reviewer.id
    request.reviewed_at = datetime.now()
    request.review_note = (data.note or "").strip() or "管理员驳回"
    request.execution_result = "未删除，原数据继续保留"
    db.commit()
    return {"message": "删除申请已驳回，原数据未发生变化"}
