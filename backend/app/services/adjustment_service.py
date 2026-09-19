"""公厕台账合并/拆分业务逻辑。

核心规则
--------

1. **审批驱动**：调整单必须先申请（状态=待审批），审批通过即在同一事务内
   完成归属变更；驳回、撤销不产生任何数据变更。
2. **原子性**：执行全程使用一个事务，任一步骤失败全部回滚，
   不会出现记录只归了一半的情况；异常后审批单落为「执行失败」并留原因。
3. **合并归属规则**：源点位全部历史巡查、问题（含已闭环及整改流水）整体
   归到承接方，源点位置为「已撤并」并保留原编号与谱系链接用于追溯。
4. **拆分归属规则**：申请时从源点位当前未闭环问题/在办整改任务中勾选
   划归新点位；历史巡查与已闭环记录留在源点位，新点位从建档日起积累。
5. **考核冻结**：月度考核结果是快照，合并/拆分只影响实时统计（按当前归属
   即时计算），已出具的月度考核结果一律不动。
6. **提交确定性**：巡查/问题提交流程先锁定目标点位行，若点位已撤并，
   统一重定向到当前承接方；待审批的调整单不再受理第二张，保证归属唯一确定。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.constants import (
    OPEN_ISSUE_STATUSES,
    AdjustmentStatus,
    AdjustmentType,
    RestroomStatus,
)
from app.core.exceptions import ConflictError, DomainError, NotFoundError
from app.models import (
    Inspection,
    Issue,
    MonthlyAssessment,
    RectificationRecord,
    Restroom,
    RestroomAdjustment,
    RestroomAdjustmentLog,
    RestroomLineage,
)
from app.schemas.adjustment import AdjustmentIssueItem
from app.services import restroom_service, scoring

_ACTIVE_PENDING = AdjustmentStatus.PENDING.value
_MERGED = RestroomStatus.MERGED.value


# ---------------------------------------------------------------------------
# 应用级点位写锁（与数据库无关的串行化点）
# ---------------------------------------------------------------------------
#
# 为什么需要它，而不能只靠数据库行锁：
#
# 1. 本项目开发/默认库是 SQLite，不支持 ``SELECT ... FOR UPDATE``，行锁会被
#    静默忽略，归属变更与巡查提交可能交错（巡查在合并批量划转 *之后* 插入，
#    从而留在已撤并点位）。
# 2. PostgreSQL 的行锁在 Read Committed 下等待结束后，Session 已缓存的
#    对象属性不会自动刷新，必须在锁内重读，单纯加锁仍然不够。
#
# 因此：调整执行与巡查/问题提交都先抢同一组按点位 id 排序的应用锁，
# 在锁内解析最终归属、复核点位状态、完成写入与提交。合并撤并是低频管理
# 操作，单进程内有序加锁成本可忽略；多 worker 部署时再由 PG 行锁兜底。

_locks_guard = threading.Lock()
_point_locks: dict[int, threading.Lock] = {}


def _point_lock(restroom_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _point_locks.get(restroom_id)
        if lock is None:
            lock = threading.Lock()
            _point_locks[restroom_id] = lock
        return lock


@contextmanager
def ordered_point_locks(restroom_ids):
    """按点位 id 全局统一升序加锁，防止不同事务加锁顺序不一致造成死锁。"""

    ids = sorted(set(restroom_ids))
    acquired: list[threading.Lock] = []
    try:
        for restroom_id in ids:
            lock = _point_lock(restroom_id)
            lock.acquire()
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()


# ---------------------------------------------------------------------------
# 编号生成
# ---------------------------------------------------------------------------

def _next_adjustment_code(db: Session) -> str:
    prefix = datetime.now().strftime("ADJ-%Y%m%d")
    seq = (
        db.scalar(
            select(func.count())
            .select_from(RestroomAdjustment)
            .where(RestroomAdjustment.code.like(f"{prefix}-%"))
        )
        or 0
    ) + 1
    while True:
        code = f"{prefix}-{seq:03d}"
        if not db.scalar(select(RestroomAdjustment.id).where(RestroomAdjustment.code == code)):
            return code
        seq += 1


def _log(adjustment: RestroomAdjustment, action: str, operator: str, remark: str | None = None) -> None:
    adjustment.logs.append(
        RestroomAdjustmentLog(action=action, operator=operator or "系统", remark=remark)
    )


# ---------------------------------------------------------------------------
# 点位归属解析（提交确定性的核心）
# ---------------------------------------------------------------------------

def _lineage_chain(db: Session, restroom_id: int) -> list[int]:
    """沿 merged_into 谱系从起始点位走到当前承接方，返回整条链上的点位 id。"""

    chain: list[int] = []
    seen: set[int] = set()
    current_id = restroom_id
    while True:
        current = db.get(Restroom, current_id)
        if current is None:
            if not chain:
                raise NotFoundError(f"公厕 {restroom_id} 不存在")
            raise ConflictError("谱系中的承接点位不存在，无法确定归属")
        if current.status != _MERGED:
            chain.append(current.id)
            return chain
        if current.id in seen:
            raise ConflictError("点位谱系存在环，请联系管理员核查台账谱系数据")
        seen.add(current.id)
        chain.append(current.id)
        link = db.scalars(
            select(RestroomLineage)
            .where(
                RestroomLineage.original_restroom_id == current.id,
                RestroomLineage.relation == "merged_into",
            )
            .order_by(RestroomLineage.id.desc())
            .limit(1)
        ).first()
        if link is None:
            raise ConflictError(f"已撤并点位「{current.name}」缺少承接谱系，无法确定归属")
        current_id = link.current_restroom_id


def resolve_restroom(db: Session, restroom_id: int) -> Restroom:
    """只读解析：获取点位；若已撤并，沿谱系找到当前承接方。"""

    chain = _lineage_chain(db, restroom_id)
    return db.get(Restroom, chain[-1])


@contextmanager
def restroom_write_target(db: Session, restroom_id: int):
    """写路径：在持有归属锁的前提下产出最终归属点位。

    调用方必须在 ``with`` 块内完成记录写入与 ``commit``——
    锁一直持有到提交结束，封堵「解析完归属、插入完成前合并落地」的窗口。
    与合并执行共用同一组按点位 id 排序的应用锁，二者严格串行：

    - 提交在合并执行 *前* 拿到锁：归属为源点位，随后合并把记录整体带走；
    - 提交在合并执行 *后* 拿到锁：锁内读到源点位已撤并，直接落到承接方。
    """

    chain = _lineage_chain(db, restroom_id)
    with ordered_point_locks(chain):
        # 丢弃 identity map 的缓存，强制读取等锁结束后的最新状态
        db.expire_all()
        chain = _lineage_chain(db, restroom_id)
        final_id = chain[-1]
        # PostgreSQL 下行锁兜底多 worker 部署；SQLite 自动忽略
        db.execute(select(Restroom.id).where(Restroom.id.in_(chain)).with_for_update())
        yield db.get(Restroom, final_id)


def pending_adjustment(db: Session, restroom_id: int) -> RestroomAdjustment | None:
    """涉及某点位且尚未结案的调整单（合并/拆分申请期间禁止再申请、禁止删档）。"""

    return db.scalars(
        select(RestroomAdjustment)
        .where(
            RestroomAdjustment.status == _ACTIVE_PENDING,
            (RestroomAdjustment.source_restroom_id == restroom_id)
            | (RestroomAdjustment.target_restroom_id == restroom_id),
        )
        .order_by(RestroomAdjustment.id.desc())
        .limit(1)
    ).first()


def _get_active_restroom(db: Session, restroom_id: int, role: str) -> Restroom:
    restroom = db.get(Restroom, restroom_id)
    if restroom is None:
        raise NotFoundError(f"{role}点位 {restroom_id} 不存在")
    if restroom.status == _MERGED:
        raise DomainError(f"{role}点位「{restroom.name}」已撤并，不能参与调整")
    return restroom


def apply_merge(db: Session, payload: Any) -> RestroomAdjustment:
    if payload.source_restroom_id == payload.target_restroom_id:
        raise DomainError("被撤并点位与承接方不能是同一座公厕")

    source = _get_active_restroom(db, payload.source_restroom_id, "被撤并")
    target = _get_active_restroom(db, payload.target_restroom_id, "承接方")

    for restroom in (source, target):
        pending = pending_adjustment(db, restroom.id)
        if pending is not None:
            raise ConflictError(
                f"点位「{restroom.name}」存在进行中的调整单 {pending.code}，"
                "需审批结案后才能再次发起调整"
            )

    adjustment = RestroomAdjustment(
        code=_next_adjustment_code(db),
        type=AdjustmentType.MERGE.value,
        status=AdjustmentStatus.PENDING.value,
        source_restroom_id=source.id,
        target_restroom_id=target.id,
        reason=payload.reason.strip(),
        applicant=payload.applicant.strip(),
        move_issue_ids=[],
    )
    _log(adjustment, "提交申请", payload.applicant, f"申请将「{source.name}」并入「{target.name}」")
    db.add(adjustment)
    db.commit()
    db.refresh(adjustment)
    return adjustment


def apply_split(db: Session, payload: Any) -> RestroomAdjustment:
    source = _get_active_restroom(db, payload.source_restroom_id, "原")
    pending = pending_adjustment(db, source.id)
    if pending is not None:
        raise ConflictError(
            f"点位「{source.name}」存在进行中的调整单 {pending.code}，"
            "需审批结案后才能再次发起调整"
        )

    # 校验新点位编号
    new_code = (payload.new_code or "").strip() or restroom_service.next_code(db)
    if db.scalar(select(Restroom.id).where(Restroom.code == new_code)):
        raise DomainError(f"新点位编号 {new_code} 已存在")

    # 校验划归清单：必须是源点位当前未闭环的问题
    move_ids = list(dict.fromkeys(payload.move_issue_ids or []))
    if move_ids:
        rows = list(
            db.scalars(
                select(Issue).where(
                    Issue.id.in_(move_ids),
                    Issue.restroom_id == source.id,
                    Issue.status.in_(OPEN_ISSUE_STATUSES),
                )
            )
        )
        valid_ids = {row.id for row in rows}
        invalid = [issue_id for issue_id in move_ids if issue_id not in valid_ids]
        if invalid:
            raise DomainError(
                "以下问题不属于该点位的未闭环问题/在办任务，不能划归："
                + "、".join(str(i) for i in invalid)
            )

    new_payload = payload.new_restroom.model_dump()
    new_payload = {
        key: (value.value if hasattr(value, "value") else value)
        for key, value in new_payload.items()
    }
    new_payload["code"] = new_code

    adjustment = RestroomAdjustment(
        code=_next_adjustment_code(db),
        type=AdjustmentType.SPLIT.value,
        status=AdjustmentStatus.PENDING.value,
        source_restroom_id=source.id,
        target_restroom_id=None,
        new_restroom_payload=new_payload,
        reason=payload.reason.strip(),
        applicant=payload.applicant.strip(),
        move_issue_ids=move_ids,
    )
    _log(
        adjustment,
        "提交申请",
        payload.applicant,
        f"申请从「{source.name}」拆出新点位「{new_payload['name']}」，"
        f"划归 {len(move_ids)} 条未闭环问题/在办任务",
    )
    db.add(adjustment)
    db.commit()
    db.refresh(adjustment)
    return adjustment


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------

def get_adjustment(db: Session, adjustment_id: int) -> RestroomAdjustment:
    adjustment = db.get(RestroomAdjustment, adjustment_id)
    if adjustment is None:
        raise NotFoundError(f"调整单 {adjustment_id} 不存在")
    return adjustment


def approve(db: Session, adjustment_id: int, payload: Any) -> RestroomAdjustment:
    """审批通过 = 同事务原子执行。失败时整体回滚并标记执行失败。"""

    adjustment = get_adjustment(db, adjustment_id)
    if adjustment.status != AdjustmentStatus.PENDING.value:
        raise ConflictError(f"调整单当前状态为「{adjustment.status}」，不能审批")

    try:
        # 与巡查/问题提交共用有序点位锁，锁内完成全部归属变更并提交，
        # 保证并发提交要么先于撤并（随后被整体带走），要么后于撤并（直接重定向）。
        lock_ids = [adjustment.source_restroom_id]
        if (
            adjustment.type == AdjustmentType.MERGE.value
            and adjustment.target_restroom_id is not None
        ):
            lock_ids.append(adjustment.target_restroom_id)

        with ordered_point_locks(lock_ids):
            if adjustment.type == AdjustmentType.MERGE.value:
                _execute_merge(db, adjustment)
            else:
                _execute_split(db, adjustment)

            adjustment.status = AdjustmentStatus.COMPLETED.value
            adjustment.approver = payload.approver.strip()
            adjustment.approval_remark = (payload.remark or "").strip() or None
            adjustment.approved_at = datetime.now()
            adjustment.executed_at = adjustment.approved_at
            _log(
                adjustment,
                "审批通过并执行",
                payload.approver,
                (payload.remark or "").strip() or None,
            )
            db.commit()
    except Exception:
        db.rollback()
        # 执行失败：在独立事务中把单据标记为失败，原业务数据保持完全不动
        failed = db.get(RestroomAdjustment, adjustment_id)
        if failed is not None and failed.status == AdjustmentStatus.PENDING.value:
            failed.status = AdjustmentStatus.FAILED.value
            failed.fail_reason = "执行过程中发生异常，全部归属变更已回滚"
            failed.logs.append(
                RestroomAdjustmentLog(
                    action="执行失败",
                    operator=payload.approver.strip(),
                    remark="归属变更事务整体回滚，未产生任何数据变更",
                )
            )
            db.commit()
        raise
    db.refresh(adjustment)
    return adjustment


def reject(db: Session, adjustment_id: int, payload: Any) -> RestroomAdjustment:
    adjustment = get_adjustment(db, adjustment_id)
    if adjustment.status != AdjustmentStatus.PENDING.value:
        raise ConflictError(f"调整单当前状态为「{adjustment.status}」，不能驳回")
    adjustment.status = AdjustmentStatus.REJECTED.value
    adjustment.approver = payload.approver.strip()
    adjustment.approval_remark = (payload.remark or "").strip() or None
    adjustment.approved_at = datetime.now()
    _log(adjustment, "审批驳回", payload.approver, (payload.remark or "").strip() or None)
    db.commit()
    db.refresh(adjustment)
    return adjustment


def cancel(db: Session, adjustment_id: int, *, operator: str) -> RestroomAdjustment:
    adjustment = get_adjustment(db, adjustment_id)
    if adjustment.status != AdjustmentStatus.PENDING.value:
        raise ConflictError(f"调整单当前状态为「{adjustment.status}」，不能撤销")
    adjustment.status = AdjustmentStatus.CANCELLED.value
    _log(adjustment, "撤销申请", operator, "申请人撤回调整单")
    db.commit()
    db.refresh(adjustment)
    return adjustment


# ---------------------------------------------------------------------------
# 原子执行
# ---------------------------------------------------------------------------

def _execute_merge(db: Session, adjustment: RestroomAdjustment) -> None:
    """在持有源/承接方点位锁的前提下执行合并。"""

    source = db.get(Restroom, adjustment.source_restroom_id)
    target = db.get(Restroom, adjustment.target_restroom_id)
    if source is None or target is None:
        raise DomainError("来源或承接点位不存在，执行中止")
    if source.id == target.id:
        raise DomainError("来源点位与承接方相同，执行中止")
    if source.status == _MERGED or target.status == _MERGED:
        raise DomainError("来源或承接点位已撤并，执行中止")

    # PostgreSQL 下行锁兜底多 worker 部署（调用方已持有应用级有序锁）
    db.execute(
        select(Restroom.id)
        .where(Restroom.id.in_([source.id, target.id]))
        .order_by(Restroom.id)
        .with_for_update()
    )

    inspection_count = (
        db.scalar(
            select(func.count()).select_from(Inspection).where(Inspection.restroom_id == source.id)
        )
        or 0
    )
    issue_count = (
        db.scalar(select(func.count()).select_from(Issue).where(Issue.restroom_id == source.id))
        or 0
    )

    # 全部历史巡查、问题整体归到承接方（问题的整改流水随问题自然跟随）
    db.execute(
        update(Inspection)
        .where(Inspection.restroom_id == source.id)
        .values(restroom_id=target.id)
    )
    db.execute(
        update(Issue)
        .where(Issue.restroom_id == source.id)
        .values(restroom_id=target.id)
    )

    source.status = _MERGED
    source.updated_at = datetime.now()
    target.updated_at = datetime.now()

    db.add(
        RestroomLineage(
            relation="merged_into",
            original_restroom_id=source.id,
            original_code=source.code,
            original_name=source.name,
            current_restroom_id=target.id,
            adjustment_id=adjustment.id,
            moved_inspection_count=inspection_count,
            moved_issue_count=issue_count,
        )
    )
    _log(
        adjustment,
        "执行归属变更",
        "系统",
        f"「{source.name}（{source.code}）」整体并入「{target.name}（{target.code}）」："
        f"巡查 {inspection_count} 条、问题 {issue_count} 条已归到承接方，原编号保留可追溯",
    )


def _execute_split(db: Session, adjustment: RestroomAdjustment) -> None:
    """在持有原点位锁的前提下执行拆分。"""

    source = db.get(Restroom, adjustment.source_restroom_id)
    if source is None:
        raise DomainError("原点位不存在，执行中止")
    if source.status == _MERGED:
        raise DomainError("原点位已撤并，执行中止")

    db.execute(select(Restroom.id).where(Restroom.id == source.id).with_for_update())

    payload = dict(adjustment.new_restroom_payload or {})
    code = payload.pop("code")
    new_restroom = Restroom(code=code, **payload)
    db.add(new_restroom)
    db.flush()  # 取得新点位主键

    move_ids = list(adjustment.move_issue_ids or [])
    moved = 0
    if move_ids:
        # 执行时再次防御性校验：只划转仍处于未闭环、且仍归属源点位的问题
        rows = list(
            db.scalars(
                select(Issue)
                .where(
                    Issue.id.in_(move_ids),
                    Issue.restroom_id == source.id,
                    Issue.status.in_(OPEN_ISSUE_STATUSES),
                )
                .with_for_update()
            )
        )
        valid_ids = [row.id for row in rows]
        if valid_ids:
            moved = (
                db.execute(
                    update(Issue).where(Issue.id.in_(valid_ids)).values(restroom_id=new_restroom.id)
                ).rowcount
                or 0
            )
        # 在办任务在划转时追加一条轨迹说明，明确责任点位变化
        for issue in rows:
            issue.records.append(
                RectificationRecord(
                    action="点位拆分划转",
                    from_status=issue.status,
                    to_status=issue.status,
                    operator=adjustment.applicant or "系统",
                    remark=(
                        f"因台账拆分，该在办任务由「{source.name}（{source.code}）」"
                        f"划归新点位「{new_restroom.name}（{new_restroom.code}）」"
                    ),
                )
            )

    adjustment.target_restroom_id = new_restroom.id
    db.add(
        RestroomLineage(
            relation="split_from",
            original_restroom_id=source.id,
            original_code=source.code,
            original_name=source.name,
            current_restroom_id=new_restroom.id,
            adjustment_id=adjustment.id,
            moved_inspection_count=0,
            moved_issue_count=moved,
        )
    )
    _log(
        adjustment,
        "执行归属变更",
        "系统",
        f"从「{source.name}（{source.code}）」拆出新点位「{new_restroom.name}（{new_restroom.code}）」，"
        f"{moved} 条未闭环问题/在办任务划归新点位；历史巡查与已闭环记录保留在原点位",
    )


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def list_adjustments(
    db: Session,
    *,
    status: str | None = None,
    type_: str | None = None,
    restroom_id: int | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[RestroomAdjustment], int]:
    stmt = select(RestroomAdjustment)
    if status:
        stmt = stmt.where(RestroomAdjustment.status == status)
    if type_:
        stmt = stmt.where(RestroomAdjustment.type == type_)
    if restroom_id:
        stmt = stmt.where(
            (RestroomAdjustment.source_restroom_id == restroom_id)
            | (RestroomAdjustment.target_restroom_id == restroom_id)
        )
    stmt = stmt.order_by(RestroomAdjustment.id.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))
    )
    return rows, total


def movable_issues(db: Session, restroom_id: int) -> list[Issue]:
    """拆分候选：该点位未闭环问题/在办整改任务。"""

    return list(
        db.scalars(
            select(Issue)
            .where(Issue.restroom_id == restroom_id, Issue.status.in_(OPEN_ISSUE_STATUSES))
            .order_by(Issue.deadline.is_(None), Issue.deadline.asc(), Issue.id.desc())
        )
    )


def adjustment_detail_data(db: Session, adjustment: RestroomAdjustment) -> dict[str, Any]:
    source_id = adjustment.source_restroom_id
    source_inspection_count = (
        db.scalar(
            select(func.count()).select_from(Inspection).where(Inspection.restroom_id == source_id)
        )
        or 0
    )
    source_issue_count = (
        db.scalar(select(func.count()).select_from(Issue).where(Issue.restroom_id == source_id))
        or 0
    )
    source_open_issue_count = (
        db.scalar(
            select(func.count())
            .select_from(Issue)
            .where(Issue.restroom_id == source_id, Issue.status.in_(OPEN_ISSUE_STATUSES))
        )
        or 0
    )
    movable = [AdjustmentIssueItem.model_validate(row) for row in movable_issues(db, source_id)]
    return {
        "source_inspection_count": source_inspection_count,
        "source_issue_count": source_issue_count,
        "source_open_issue_count": source_open_issue_count,
        "movable_issues": movable,
    }


def lineage_of(db: Session, restroom_id: int) -> list[RestroomLineage]:
    """该点位承接/拆出的全部谱系链接（含被撤并点位的原编号）。"""

    return list(
        db.scalars(
            select(RestroomLineage)
            .where(
                (RestroomLineage.current_restroom_id == restroom_id)
                | (RestroomLineage.original_restroom_id == restroom_id)
            )
            .order_by(RestroomLineage.id.desc())
        )
    )


def find_by_original_code(db: Session, code: str) -> list[RestroomLineage]:
    """按原编号反查当前承接点位（追溯入口）。"""

    return list(
        db.scalars(
            select(RestroomLineage)
            .where(RestroomLineage.original_code == code.strip())
            .order_by(RestroomLineage.id.desc())
        )
    )


# ---------------------------------------------------------------------------
# 月度考核（快照冻结）
# ---------------------------------------------------------------------------

def assessment_grade(avg_score: float) -> str:
    return scoring.score_to_grade(avg_score)


def generate_monthly_assessment(
    db: Session, period: str | None = None, *, operator: str = "系统"
) -> list[MonthlyAssessment]:
    """生成指定月份（默认上月）的月度考核快照。

    - 同一「月份 + 点位」已存在快照时**永不覆盖**（已经出的月度考核结果不动）；
    - 统计口径为该月内点位名下的巡查与问题，按**生成时**的当前归属归集
      （合并点位的当月记录已在承接方名下）；
    - 快照写入后，后续再发生合并/拆分对其无任何影响。
    """

    if period is None:
        today = date.today()
        first_of_this = today.replace(day=1)
        last_prev = first_of_this - timedelta(days=1)
        period = last_prev.strftime("%Y-%m")

    try:
        year, month = (int(part) for part in period.split("-"))
        month_start = datetime.combine(date(year, month, 1), time.min)
    except (ValueError, TypeError) as exc:
        raise DomainError("月份格式应为 YYYY-MM") from exc
    if month == 12:
        next_month_start = datetime.combine(date(year + 1, 1, 1), time.min)
    else:
        next_month_start = datetime.combine(date(year, month + 1, 1), time.min)

    existing = {
        row.restroom_id
        for row in db.scalars(
            select(MonthlyAssessment).where(MonthlyAssessment.period == period)
        )
    }

    created: list[MonthlyAssessment] = []
    restrooms = list(db.scalars(select(Restroom).order_by(Restroom.id)))
    for restroom in restrooms:
        if restroom.id in existing:
            continue

        inspections = list(
            db.scalars(
                select(Inspection).where(
                    Inspection.restroom_id == restroom.id,
                    Inspection.inspect_time >= month_start,
                    Inspection.inspect_time < next_month_start,
                )
            )
        )
        issues = list(
            db.scalars(
                select(Issue).where(
                    Issue.restroom_id == restroom.id,
                    Issue.report_time >= month_start,
                    Issue.report_time < next_month_start,
                )
            )
        )
        # 当月既无巡查也无问题的点位不出考核单；已撤并点位若当月有数据仍出单留痕
        if not inspections and not issues:
            continue

        avg_score = (
            round(sum(float(item.score or 0) for item in inspections) / len(inspections), 1)
            if inspections
            else 0.0
        )
        open_count = sum(1 for item in issues if item.status in OPEN_ISSUE_STATUSES)
        snapshot = {
            "generated_by": operator,
            "generated_at": datetime.now().isoformat(),
            "inspection_scores": [float(item.score or 0) for item in inspections],
            "issue_codes": [item.code for item in issues],
            "restroom_status_at_generation": restroom.status,
        }
        assessment = MonthlyAssessment(
            period=period,
            restroom_id=restroom.id,
            restroom_code=restroom.code,
            restroom_name=restroom.name,
            inspection_count=len(inspections),
            issue_count=len(issues),
            open_issue_count=open_count,
            avg_score=avg_score,
            grade=assessment_grade(avg_score),
            snapshot=snapshot,
        )
        db.add(assessment)
        created.append(assessment)

    db.commit()
    for item in created:
        db.refresh(item)
    return created


def list_assessments(db: Session, period: str | None = None) -> list[MonthlyAssessment]:
    stmt = select(MonthlyAssessment)
    if period:
        stmt = stmt.where(MonthlyAssessment.period == period)
    return list(
        db.scalars(stmt.order_by(MonthlyAssessment.period.desc(), MonthlyAssessment.id))
    )
