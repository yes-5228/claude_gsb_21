"""公厕合并 / 拆分变更单接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.change_order import (
    ApprovalAction,
    ChangeOrderOut,
    ChangePreview,
    MergeOrderCreate,
    SplitOrderCreate,
)
from app.schemas.common import MessageOut
from app.services import change_order_service

router = APIRouter(prefix="/change-orders", tags=["台账合并拆分"])


@router.get("", response_model=list[ChangeOrderOut], summary="变更单列表")
def list_orders(
    db: Annotated[Session, Depends(get_db)],
    status: Annotated[str | None, Query(description="审批状态")] = None,
    type: Annotated[str | None, Query(description="merge / split")] = None,
    restroom_id: Annotated[int | None, Query(description="涉及的公厕ID")] = None,
) -> list[ChangeOrderOut]:
    rows = change_order_service.list_orders(
        db, status=status, type_=type, restroom_id=restroom_id
    )
    return [change_order_service.to_out(row) for row in rows]


@router.get("/preview", response_model=ChangePreview, summary="变更影响面预览")
def preview(
    db: Annotated[Session, Depends(get_db)],
    type: Annotated[str, Query(pattern="^(merge|split)$")],
    source_restroom_id: int,
    target_restroom_id: int | None = None,
) -> ChangePreview:
    return change_order_service.build_preview(
        db, type_=type, source_id=source_restroom_id, target_id=target_restroom_id
    )


@router.post("/merge", response_model=ChangeOrderOut, status_code=201, summary="发起合并申请")
def create_merge(payload: MergeOrderCreate, db: Annotated[Session, Depends(get_db)]) -> ChangeOrderOut:
    return change_order_service.to_out(change_order_service.create_merge(db, payload))


@router.post("/split", response_model=ChangeOrderOut, status_code=201, summary="发起拆分申请")
def create_split(payload: SplitOrderCreate, db: Annotated[Session, Depends(get_db)]) -> ChangeOrderOut:
    return change_order_service.to_out(change_order_service.create_split(db, payload))


@router.get("/{order_id}", response_model=ChangeOrderOut, summary="变更单详情")
def get_order(order_id: int, db: Annotated[Session, Depends(get_db)]) -> ChangeOrderOut:
    return change_order_service.to_out(change_order_service.get_order(db, order_id))


@router.post("/{order_id}/approve", response_model=ChangeOrderOut, summary="审批通过并执行")
def approve_order(
    order_id: int, payload: ApprovalAction, db: Annotated[Session, Depends(get_db)]
) -> ChangeOrderOut:
    return change_order_service.to_out(change_order_service.approve_order(db, order_id, payload))


@router.post("/{order_id}/reject", response_model=ChangeOrderOut, summary="审批驳回")
def reject_order(
    order_id: int, payload: ApprovalAction, db: Annotated[Session, Depends(get_db)]
) -> ChangeOrderOut:
    return change_order_service.to_out(change_order_service.reject_order(db, order_id, payload))


@router.post("/{order_id}/revoke", response_model=ChangeOrderOut, summary="撤销待审批变更单")
def revoke_order(order_id: int, db: Annotated[Session, Depends(get_db)]) -> ChangeOrderOut:
    return change_order_service.to_out(change_order_service.revoke_order(db, order_id))


@router.delete("/{order_id}", response_model=MessageOut, summary="删除变更单（仅已驳回/已撤销/已执行）")
def delete_order(order_id: int, db: Annotated[Session, Depends(get_db)]) -> MessageOut:
    change_order_service.delete_order(db, order_id)
    return MessageOut(message="删除成功")
