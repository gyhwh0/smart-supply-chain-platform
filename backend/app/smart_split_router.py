from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.database import get_db
from app.models import Category, User
from app import smart_split_service


router = APIRouter(prefix="/api/smart-split", tags=["smart-split"])


class TierPriceIn(BaseModel):
    min_base_quantity: Decimal = Field(gt=0)
    base_unit_price: Decimal = Field(gt=0)


class AssignmentRuleIn(BaseModel):
    split_enabled: bool = True
    priority: int = Field(default=100, ge=1, le=9999)
    daily_capacity_base: Decimal | None = Field(default=None, gt=0)
    order_capacity_base: Decimal | None = Field(default=None, gt=0)
    quota_percent: Decimal = Field(default=0, ge=0, le=100)
    tier_prices: list[TierPriceIn] = Field(default_factory=list)


class CategoryLossIn(BaseModel):
    purchase_loss_rate: Decimal = Field(ge=0, le=100)


class SupplierPerformanceIn(BaseModel):
    on_time_rate: Decimal = Field(ge=0, le=100)
    inspection_pass_rate: Decimal = Field(ge=0, le=100)
    return_rate: Decimal = Field(ge=0, le=100)
    payment_term_days: int = Field(default=0, ge=0, le=3650)


class QualityWeightsIn(BaseModel):
    on_time: Decimal = Field(ge=0)
    inspection: Decimal = Field(ge=0)
    return_: Decimal = Field(alias="return", ge=0)


class PreviewIn(BaseModel):
    source_type: str
    source_id: int
    strategy: str


class AllocationIn(BaseModel):
    assignment_id: int
    base_quantity: Decimal = Field(gt=0)


class SplitItemIn(BaseModel):
    product_id: int
    allocations: list[AllocationIn] = Field(min_length=1)


class GenerateIn(PreviewIn):
    reduction_strategy: str = "proportional"
    notes: str | None = None
    items: list[SplitItemIn] = Field(min_length=1)


@router.get("/config")
def get_config(
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.configuration(db)


@router.put("/assignments/{assignment_id}")
def save_assignment_rule(
    assignment_id: int,
    data: AssignmentRuleIn,
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.update_assignment(db, assignment_id, data.model_dump())


@router.put("/categories/{category_id}/loss")
def save_category_loss(
    category_id: int,
    data: CategoryLossIn,
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    category.purchase_loss_rate = data.purchase_loss_rate
    db.commit()
    return {"message": "品类采购损耗率已保存"}


@router.put("/suppliers/{supplier_id}/performance")
def save_supplier_performance(
    supplier_id: int,
    data: SupplierPerformanceIn,
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.update_supplier_performance(db, supplier_id, data.model_dump())


@router.put("/quality-weights")
def save_quality_weights(
    data: QualityWeightsIn,
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    values = data.model_dump(by_alias=True)
    return smart_split_service.update_weights(db, values)


@router.get("/sources")
def get_sources(
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.source_options(db)


@router.post("/preview")
def preview_split(
    data: PreviewIn,
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.preview(db, data.source_type, data.source_id, data.strategy)


@router.post("/generate")
def generate_split_orders(
    data: GenerateIn,
    user: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.generate(db, data.model_dump(), user)


@router.get("/plans")
def list_plans(
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.plans(db)


@router.post("/plans/{plan_id}/cancel")
def cancel_plan(
    plan_id: int,
    _: User = Depends(require_permission("smart_split_management")),
    db: Session = Depends(get_db),
):
    return smart_split_service.cancel_plan(db, plan_id)
