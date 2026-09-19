"""公厕合并 / 拆分变更单与审批执行。

关键约束：

1. 审批通过时在**单个数据库事务**内完成全部归属改写，任何一步失败都整体回滚，
   变更单回到「待审批」，绝不会出现记录只迁移一半的中间状态。
2. 执行时对相关公厕行加锁（PostgreSQL 为 SELECT ... FOR UPDATE），与巡查/问题
   提交在同一把行锁上排队：要么提交先落库再被本次变更整体带走，要么变更先生效、
   提交因公厕已撤并被拒绝并引导到承接方，记录必然落在确定的一方。
3. 巡查/问题/考核迁移当前归属 restroom_id 的同时，用 origin_restroom_* 保留原编号；
   已经有原编号的（二次撤并）保留最早的来源。
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import (
    OPEN_ISSUE_STATUSES,
    ChangeOrderStatus,
    ChangeType,
    RestroomStatus,
)
from app.core.exceptions import ConflictError, DomainError, NotFoundError
from app.models import (
    Inspection,
    Issue,
    MonthlyAssessment,
    RectificationRecord,
    Restroom,
    RestroomChangeOrder,
)
from app.schemas.change_order import (
    ApprovalAction,
    ChangeOrderOut,
    ChangePreview,
    MergeOrderCreate,
    SplitOrderCreate,
)
from app.schemas.restroom import RestroomBrief
from app.services import restroom_service

# 仍在审批流程中、尚未执行的变更单状态
_PENDING_STATUS = ChangeOrderStatus.PENDING.value


def _next_code(db: Session) -> str:
    """生成形如 BG-20260918-001 的变更单编号。"""
    prefix = datetime.now().strftime("BG-%Y%m%d")
    seq = (
        db.scalar(
            select(func.count())
            .select_from(RestroomChangeOrder)
            .where(RestroomChangeOrder.code.like(f"{prefix}-%"))
        )
        or 0
    ) + 1
    while True:
        code = f"{prefix}-{seq:03d}"
        if not db.scalar(select(RestroomChangeOrder.id).where(RestroomChangeOrder.code == code)):
            return code
        seq += 1


def get_order(db: Session, order_id: int) -> RestroomChangeOrder:
    order = db.get(RestroomChangeOrder, order_id)
    if order is None:
        raise NotFoundError(f"变更单 {order_id} 不存在")
    return order


def to_out(order: RestroomChangeOrder) -> ChangeOrderOut:
    return ChangeOrderOut.model_validate(order)


def list_orders(
    db: Session,
    *,
    status: str | None = None,
    type_: str | None = None,
    restroom_id: int | None = None,
) -> list[RestroomChangeOrder]:
    stmt = select(RestroomChangeOrder)
    if status:
        stmt = stmt.where(RestroomChangeOrder.status == status)
    if type_:
        stmt = stmt.where(RestroomChangeOrder.type == type_)
    if restroom_id:
        stmt = stmt.where(
            (RestroomChangeOrder.source_restroom_id == restroom_id)
            | (RestroomChangeOrder.target_restroom_id == restroom_id)
            | (RestroomChangeOrder.new_restroom_id == restroom_id)
        )
    stmt = stmt.order_by(RestroomChangeOrder.id.desc())
    return list(db.scalars(stmt))


def _ensure_no_active_order(db: Session, restroom_id: int, *, exclude_id: int | None = None) -> None:
    stmt = select(RestroomChangeOrder).where(
        RestroomChangeOrder.status == _PENDING_STATUS,
        (RestroomChangeOrder.source_restroom_id == restroom_id)
        | (RestroomChangeOrder.target_restroom_id == restroom_id),
    )
    if exclude_id is not None:
        stmt = stmt.where(RestroomChangeOrder.id != exclude_id)
    existing = db.scalars(stmt).first()
    if existing is not None:
        raise ConflictError(
            f"该公厕已有进行中的变更单 {existing.code}，需先完成或撤销后再发起"
        )


def _count(db: Session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return db.scalar(stmt) or 0


def _open_issues(db: Session, restroom_id: int) -> list[Issue]:
    return list(
        db.scalars(
            select(Issue)
            .where(
                Issue.restroom_id == restroom_id,
                Issue.status.in_(OPEN_ISSUE_STATUSES),
            )
            .order_by(Issue.id)
        )
    )


def build_preview(
    db: Session, *, type_: str, source_id: int, target_id: int | None = None
) -> ChangePreview:
    """预估变更影响面，供申请前确认。"""
    source = restroom_service.get_restroom(db, source_id)
    target = restroom_service.get_restroom(db, target_id) if target_id else None
    open_issues = _open_issues(db, source_id)
    return ChangePreview(
        type=type_,
        source_restroom=RestroomBrief.model_validate(source),
        target_restroom=RestroomBrief.model_validate(target) if target else None,
        inspection_count=_count(db, Inspection, Inspection.restroom_id == source_id),
        issue_open_count=len(open_issues),
        issue_closed_count=_count(
            db,
            Issue,
            Issue.restroom_id == source_id,
            Issue.status.notin_(OPEN_ISSUE_STATUSES),
        ),
        assessment_count=_count(
            db, MonthlyAssessment, MonthlyAssessment.restroom_id == source_id
        ),
        open_issues=[
            {
                "issue_id": issue.id,
                "code": issue.code,
                "title": issue.title,
                "status": issue.status,
                "assignee": issue.assignee,
            }
            for issue in open_issues
        ],
    )


def create_merge(db: Session, payload: MergeOrderCreate) -> RestroomChangeOrder:
    if payload.source_restroom_id == payload.target_restroom_id:
        raise DomainError("被撤并公厕与承接公厕不能是同一座")
    source = restroom_service.get_restroom(db, payload.source_restroom_id)
    target = restroom_service.get_restroom(db, payload.target_restroom_id)
    if source.status == RestroomStatus.MERGED.value:
        raise DomainError(f"公厕「{source.name}」已撤并，不能再次撤并")
    if target.status == RestroomStatus.MERGED.value:
        raise DomainError(f"承接公厕「{target.name}」已撤并，不能作为承接方")
    _ensure_no_active_order(db, source.id)
    _ensure_no_active_order(db, target.id)

    order = RestroomChangeOrder(
        code=_next_code(db),
        type=ChangeType.MERGE.value,
        status=_PENDING_STATUS,
        source_restroom_id=source.id,
        target_restroom_id=target.id,
        reason=payload.reason.strip(),
        applicant=payload.applicant.strip(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def create_split(db: Session, payload: SplitOrderCreate) -> RestroomChangeOrder:
    source = restroom_service.get_restroom(db, payload.source_restroom_id)
    if source.status == RestroomStatus.MERGED.value:
        raise DomainError(f"公厕「{source.name}」已撤并，不能拆分")
    _ensure_no_active_order(db, source.id)

    open_issues = _open_issues(db, source.id)
    open_ids = {issue.id for issue in open_issues}
    assigned_ids = {item.issue_id for item in payload.issue_assignments}
    unknown = assigned_ids - open_ids
    if unknown:
        raise DomainError(
            f"划归明细包含不属于该公厕在办问题的编号：{sorted(unknown)}"
        )
    missing = open_ids - assigned_ids
    if missing:
        raise DomainError(
            "存在未明确划归去向的在办问题，需逐条指定新点位或原公厕，"
            f"未覆盖问题ID：{sorted(missing)}"
        )

    order = RestroomChangeOrder(
        code=_next_code(db),
        type=ChangeType.SPLIT.value,
        status=_PENDING_STATUS,
        source_restroom_id=source.id,
        new_restroom_payload=payload.new_restroom.model_dump(mode="json"),
        issue_assignments=[item.model_dump() for item in payload.issue_assignments],
        reason=payload.reason.strip(),
        applicant=payload.applicant.strip(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def reject_order(db: Session, order_id: int, payload: ApprovalAction) -> RestroomChangeOrder:
    order = get_order(db, order_id)
    if order.status != _PENDING_STATUS:
        raise ConflictError(f"变更单当前状态为「{order.status}」，不能审批驳回")
    order.status = ChangeOrderStatus.REJECTED.value
    order.approver = payload.approver.strip()
    order.approve_remark = payload.remark
    order.rejected_at = datetime.now()
    db.commit()
    db.refresh(order)
    return order


def revoke_order(db: Session, order_id: int) -> RestroomChangeOrder:
    order = get_order(db, order_id)
    if order.status != _PENDING_STATUS:
        raise ConflictError(f"变更单当前状态为「{order.status}」，只有待审批单据可撤销")
    order.status = ChangeOrderStatus.REVOKED.value
    order.revoked_at = datetime.now()
    db.commit()
    db.refresh(order)
    return order


def delete_order(db: Session, order_id: int) -> None:
    order = get_order(db, order_id)
    if order.status == _PENDING_STATUS:
        raise ConflictError("待审批变更单不能删除，请先驳回或撤销")
    db.delete(order)
    db.commit()


def _lock_in_order(db: Session, ids: list[int]) -> list[Restroom]:
    """按固定顺序（id 升序）加行锁，避免多单据并发时互相等待形成死锁。"""
    rows = []
    for restroom_id in sorted(set(ids)):
        rows.append(restroom_service.lock_restroom(db, restroom_id))
    return rows


def approve_order(db: Session, order_id: int, payload: ApprovalAction) -> RestroomChangeOrder:
    """审批通过并整体执行；失败整体回滚，单据仍是「待审批」。"""
    order = get_order(db, order_id)
    if order.status != _PENDING_STATUS:
        raise ConflictError(f"变更单当前状态为「{order.status}」，不能审批通过")

    try:
        if order.is_merge:
            snapshot = _execute_merge(db, order)
        else:
            snapshot = _execute_split(db, order)

        order.status = ChangeOrderStatus.APPROVED.value
        order.approver = payload.approver.strip()
        order.approve_remark = payload.remark
        order.approved_at = datetime.now()
        order.result_snapshot = snapshot
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order


def _execute_merge(db: Session, order: RestroomChangeOrder) -> dict:
    source_id = order.source_restroom_id
    target_id = order.target_restroom_id
    assert target_id is not None
    locked = {r.id: r for r in _lock_in_order(db, [source_id, target_id])}
    source = locked[source_id]
    target = locked[target_id]
    if source.status == RestroomStatus.MERGED.value:
        raise DomainError(f"公厕「{source.name}」已被撤并，变更无法执行")
    if target.status == RestroomStatus.MERGED.value:
        raise DomainError(f"承接公厕「{target.name}」已撤并，变更无法执行")

    inspection_count = _count(db, Inspection, Inspection.restroom_id == source_id)
    issue_count = _count(db, Issue, Issue.restroom_id == source_id)
    assessment_count = _count(
        db, MonthlyAssessment, MonthlyAssessment.restroom_id == source_id
    )

    moved_issues = list(db.scalars(select(Issue).where(Issue.restroom_id == source_id)))
    db.execute(
        Inspection.__table__.update()
        .where(Inspection.restroom_id == source_id)
        .values(
            restroom_id=target_id,
            origin_restroom_id=func.coalesce(Inspection.origin_restroom_id, source_id),
            origin_restroom_code=func.coalesce(Inspection.origin_restroom_code, source.code),
        )
    )
    db.execute(
        Issue.__table__.update()
        .where(Issue.restroom_id == source_id)
        .values(
            restroom_id=target_id,
            origin_restroom_id=func.coalesce(Issue.origin_restroom_id, source_id),
            origin_restroom_code=func.coalesce(Issue.origin_restroom_code, source.code),
        )
    )
    db.execute(
        MonthlyAssessment.__table__.update()
        .where(MonthlyAssessment.restroom_id == source_id)
        .values(
            restroom_id=target_id,
            origin_restroom_id=func.coalesce(MonthlyAssessment.origin_restroom_id, source_id),
            origin_restroom_code=func.coalesce(
                MonthlyAssessment.origin_restroom_code, source.code
            ),
        )
    )

    now = datetime.now()
    for issue in moved_issues:
        db.add(
            RectificationRecord(
                issue_id=issue.id,
                action="归属变更",
                from_status=issue.status,
                to_status=issue.status,
                operator=order.applicant or "系统",
                remark=(
                    f"依据变更单 {order.code}，原公厕「{source.name}」（{source.code}）"
                    f"撤并进承接方「{target.name}」（{target.code}），本问题随之归并"
                ),
                created_at=now,
            )
        )

    source.status = RestroomStatus.MERGED.value
    source.merged_into_id = target_id
    source.merged_at = now

    return {
        "type": ChangeType.MERGE.value,
        "source_restroom_id": source_id,
        "source_restroom_code": source.code,
        "target_restroom_id": target_id,
        "target_restroom_code": target.code,
        "moved_inspection_count": inspection_count,
        "moved_issue_count": issue_count,
        "moved_assessment_count": assessment_count,
    }


def _execute_split(db: Session, order: RestroomChangeOrder) -> dict:
    source_id = order.source_restroom_id
    source = _lock_in_order(db, [source_id])[0]
    if source.status == RestroomStatus.MERGED.value:
        raise DomainError(f"公厕「{source.name}」已撤并，变更无法执行")

    payload = order.new_restroom_payload or {}
    new_code = restroom_service.next_available_code(db)
    new_restroom = Restroom(
        code=new_code,
        name=payload.get("name", ""),
        district=payload.get("district", ""),
        address=payload.get("address", ""),
        grade=payload.get("grade", ""),
        status=payload.get("status", RestroomStatus.NORMAL.value),
        manager=payload.get("manager", ""),
        manager_phone=payload.get("manager_phone", ""),
        open_hours=payload.get("open_hours", "06:00-22:00"),
        stall_count=payload.get("stall_count", 0),
        basin_count=payload.get("basin_count", 0),
        has_accessible=payload.get("has_accessible", True),
        longitude=payload.get("longitude"),
        latitude=payload.get("latitude"),
        remark=payload.get("remark"),
    )
    db.add(new_restroom)
    db.flush()  # 取得新点位主键

    # 执行前重新核对在办问题，防止申请后又新增了问题却没有划归去向
    open_issues = _open_issues(db, source_id)
    assignment_map = {
        int(item["issue_id"]): item["destination"] for item in (order.issue_assignments or [])
    }
    open_ids = {issue.id for issue in open_issues}
    if set(assignment_map) != open_ids:
        raise DomainError(
            "在办问题与申请时的划归明细不一致（可能申请后又有新问题），"
            "请撤销后重新发起拆分"
        )

    now = datetime.now()
    moved_ids: list[int] = []
    retained_ids: list[int] = []
    for issue in open_issues:
        destination = assignment_map[issue.id]
        if destination == "new":
            issue.restroom_id = new_restroom.id
            issue.origin_restroom_id = issue.origin_restroom_id or source_id
            issue.origin_restroom_code = issue.origin_restroom_code or source.code
            moved_ids.append(issue.id)
            db.add(
                RectificationRecord(
                    issue_id=issue.id,
                    action="归属变更",
                    from_status=issue.status,
                    to_status=issue.status,
                    operator=order.applicant or "系统",
                    remark=(
                        f"依据变更单 {order.code}，本问题由原公厕「{source.name}」"
                        f"（{source.code}）拆分到新点位「{new_restroom.name}」（{new_restroom.code}）"
                    ),
                    created_at=now,
                )
            )
        else:
            retained_ids.append(issue.id)

    order.new_restroom_id = new_restroom.id
    return {
        "type": ChangeType.SPLIT.value,
        "source_restroom_id": source_id,
        "source_restroom_code": source.code,
        "new_restroom_id": new_restroom.id,
        "new_restroom_code": new_restroom.code,
        "moved_issue_ids": moved_ids,
        "retained_issue_ids": retained_ids,
        "moved_issue_count": len(moved_ids),
        "retained_issue_count": len(retained_ids),
        "frozen_assessment_count": _count(
            db, MonthlyAssessment, MonthlyAssessment.restroom_id == source_id
        ),
    }
