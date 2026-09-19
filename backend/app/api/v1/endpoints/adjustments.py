"""公厕合并/拆分审批接口。

路由需先于 ``restrooms`` 模块注册，避免 ``/restrooms/adjustments``
被 ``/restrooms/{restroom_id}`` 抢先匹配。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import PaginationDep, build_meta
from app.core.database import get_db
from app.schemas.adjustment import (
    AdjustmentDetail,
    AdjustmentIssueItem,
    AdjustmentOut,
    LineageOut,
    MergeApplyRequest,
    SplitApplyRequest,
    ApprovalRequest,
)
from app.schemas.common import Page
from app.services import adjustment_service

router = APIRouter(prefix="/restrooms", tags=["台账合并拆分"])


@router.get(
    "/adjustments/movable-issues",
    response_model=list[AdjustmentIssueItem],
    summary="拆分候选：未闭环问题/在办任务",
)
def movable_issues(
    db: Annotated[Session, Depends(get_db)],
    restroom_id: Annotated[int, Query(description="原点位 ID")],
) -> list[AdjustmentIssueItem]:
    return [
        AdjustmentIssueItem.model_validate(row)
        for row in adjustment_service.movable_issues(db, restroom_id)
    ]


@router.get(
    "/adjustments/lineage",
    response_model=list[LineageOut],
    summary="按原编号追溯当前承接点位",
)
def trace_lineage(
    db: Annotated[Session, Depends(get_db)],
    code: Annotated[str, Query(description="原公厕编号，如 WC-0003")],
) -> list[LineageOut]:
    return [LineageOut.model_validate(row) for row in adjustment_service.find_by_original_code(db, code)]


@router.get("/adjustments", response_model=Page[AdjustmentOut], summary="合并/拆分审批单列表")
def list_adjustments(
    db: Annotated[Session, Depends(get_db)],
    pagination: PaginationDep,
    status: Annotated[str | None, Query(description="审批状态")] = None,
    type: Annotated[str | None, Query(description="调整类型：合并/拆分")] = None,
    restroom_id: Annotated[int | None, Query(description="涉及的点位 ID")] = None,
) -> Page[AdjustmentOut]:
    rows, total = adjustment_service.list_adjustments(
        db,
        status=status,
        type_=type,
        restroom_id=restroom_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return Page[AdjustmentOut](
        items=[AdjustmentOut.model_validate(row) for row in rows],
        meta=build_meta(total, pagination),
    )


@router.post(
    "/adjustments/merge",
    response_model=AdjustmentOut,
    status_code=201,
    summary="发起合并申请（一座并入另一座）",
)
def apply_merge(
    payload: MergeApplyRequest, db: Annotated[Session, Depends(get_db)]
) -> AdjustmentOut:
    return AdjustmentOut.model_validate(adjustment_service.apply_merge(db, payload))


@router.post(
    "/adjustments/split",
    response_model=AdjustmentOut,
    status_code=201,
    summary="发起拆分申请（从一座拆出新点位）",
)
def apply_split(
    payload: SplitApplyRequest, db: Annotated[Session, Depends(get_db)]
) -> AdjustmentOut:
    return AdjustmentOut.model_validate(adjustment_service.apply_split(db, payload))


@router.get(
    "/adjustments/{adjustment_id}",
    response_model=AdjustmentDetail,
    summary="调整单详情（含来源点位数量与可划归问题）",
)
def get_adjustment(
    adjustment_id: int, db: Annotated[Session, Depends(get_db)]
) -> AdjustmentDetail:
    adjustment = adjustment_service.get_adjustment(db, adjustment_id)
    base = AdjustmentOut.model_validate(adjustment).model_dump()
    extra = adjustment_service.adjustment_detail_data(db, adjustment)
    return AdjustmentDetail(**base, **extra)


@router.post(
    "/adjustments/{adjustment_id}/approve",
    response_model=AdjustmentOut,
    summary="审批通过并原子执行归属变更",
)
def approve_adjustment(
    adjustment_id: int,
    payload: ApprovalRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentOut:
    return AdjustmentOut.model_validate(adjustment_service.approve(db, adjustment_id, payload))


@router.post(
    "/adjustments/{adjustment_id}/reject",
    response_model=AdjustmentOut,
    summary="审批驳回（不产生任何归属变更）",
)
def reject_adjustment(
    adjustment_id: int,
    payload: ApprovalRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentOut:
    return AdjustmentOut.model_validate(adjustment_service.reject(db, adjustment_id, payload))


@router.post(
    "/adjustments/{adjustment_id}/cancel",
    response_model=AdjustmentOut,
    summary="撤销调整申请",
)
def cancel_adjustment(
    adjustment_id: int,
    payload: ApprovalRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentOut:
    return AdjustmentOut.model_validate(
        adjustment_service.cancel(db, adjustment_id, operator=payload.approver)
    )


@router.get(
    "/{restroom_id}/lineage",
    response_model=list[LineageOut],
    summary="点位谱系（原编号留痕与承接关系）",
)
def restroom_lineage(
    restroom_id: int, db: Annotated[Session, Depends(get_db)]
) -> list[LineageOut]:
    return [
        LineageOut.model_validate(row)
        for row in adjustment_service.lineage_of(db, restroom_id)
    ]
