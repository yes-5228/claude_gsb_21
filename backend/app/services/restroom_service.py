"""公厕台账业务逻辑。"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.constants import OPEN_ISSUE_STATUSES, RestroomStatus
from app.core.exceptions import ConflictError, DomainError, NotFoundError
from app.models import Inspection, Issue, Restroom, RestroomLineage
from app.schemas.restroom import (
    RestroomBrief,
    RestroomCreate,
    RestroomDetail,
    RestroomOut,
    RestroomUpdate,
)

SORTABLE_FIELDS = {
    "code": Restroom.code,
    "name": Restroom.name,
    "district": Restroom.district,
    "created_at": Restroom.created_at,
    "updated_at": Restroom.updated_at,
}


def next_code(db: Session) -> str:
    """生成形如 WC-0007 的公厕编号。"""
    seq = (db.scalar(select(func.count()).select_from(Restroom)) or 0) + 1
    while True:
        code = f"WC-{seq:04d}"
        if not db.scalar(select(Restroom.id).where(Restroom.code == code)):
            return code
        seq += 1


# 向后兼容的内部别名
_next_code = next_code


def get_restroom(db: Session, restroom_id: int) -> Restroom:
    restroom = db.get(Restroom, restroom_id)
    if restroom is None:
        raise NotFoundError(f"公厕 {restroom_id} 不存在")
    return restroom


def list_restrooms(
    db: Session,
    *,
    keyword: str | None = None,
    district: str | None = None,
    status: str | None = None,
    grade: str | None = None,
    page: int = 1,
    page_size: int = 10,
    sort_by: str = "created_at",
    order: str = "desc",
) -> tuple[list[Restroom], int]:
    stmt = select(Restroom)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                Restroom.name.like(like),
                Restroom.code.like(like),
                Restroom.address.like(like),
                Restroom.manager.like(like),
            )
        )
    if district:
        stmt = stmt.where(Restroom.district == district)
    if status:
        stmt = stmt.where(Restroom.status == status)
    if grade:
        stmt = stmt.where(Restroom.grade == grade)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = SORTABLE_FIELDS.get(sort_by, Restroom.created_at)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc(), Restroom.id.desc())
    rows = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return rows, total


def list_districts(db: Session) -> list[str]:
    return list(db.scalars(select(Restroom.district).distinct().order_by(Restroom.district)))


def create_restroom(db: Session, payload: RestroomCreate) -> Restroom:
    data = payload.model_dump()
    code = (data.pop("code") or "").strip() or next_code(db)
    if db.scalar(select(Restroom.id).where(Restroom.code == code)):
        raise DomainError(f"公厕编号 {code} 已存在")
    data = {key: (value.value if hasattr(value, "value") else value) for key, value in data.items()}
    restroom = Restroom(code=code, **data)
    db.add(restroom)
    db.commit()
    db.refresh(restroom)
    return restroom


def update_restroom(db: Session, restroom_id: int, payload: RestroomUpdate) -> Restroom:
    restroom = get_restroom(db, restroom_id)
    data = payload.model_dump(exclude_unset=True)
    new_status = data.get("status")
    new_status_value = new_status.value if hasattr(new_status, "value") else new_status
    if new_status_value == RestroomStatus.MERGED.value:
        raise DomainError("「已撤并」状态只能通过合并审批自动产生，不能手工设置")
    for key, value in data.items():
        setattr(restroom, key, value.value if hasattr(value, "value") else value)
    db.commit()
    db.refresh(restroom)
    return restroom


def delete_restroom(db: Session, restroom_id: int, *, force: bool = False) -> None:
    from app.services import adjustment_service

    restroom = get_restroom(db, restroom_id)
    pending = adjustment_service.pending_adjustment(db, restroom_id)
    if pending is not None:
        raise ConflictError(
            f"该公厕存在进行中的调整单 {pending.code}（{pending.type}），"
            "审批结案前不能删除档案"
        )
    if restroom.status == RestroomStatus.MERGED.value:
        raise ConflictError("该公厕已撤并并入承接方，档案保留用于追溯，不能删除")

    # 承接过撤并或被拆出的点位承载谱系记录，档案需永久保留用于追溯
    lineage_count = db.scalar(
        select(func.count())
        .select_from(RestroomLineage)
        .where(
            (RestroomLineage.current_restroom_id == restroom_id)
            | (RestroomLineage.original_restroom_id == restroom_id)
        )
    ) or 0
    if lineage_count:
        raise ConflictError(
            f"该公厕存在 {lineage_count} 条合并/拆分谱系记录，档案须保留用于原编号追溯，不能删除"
        )
    inspection_count = db.scalar(
        select(func.count()).select_from(Inspection).where(Inspection.restroom_id == restroom_id)
    ) or 0
    issue_count = db.scalar(
        select(func.count()).select_from(Issue).where(Issue.restroom_id == restroom_id)
    ) or 0
    if (inspection_count or issue_count) and not force:
        raise ConflictError(
            f"该公厕已有 {inspection_count} 条巡查记录、{issue_count} 条问题记录，"
            "确需删除请使用 force=true"
        )
    db.delete(restroom)
    db.commit()


def get_restroom_detail(db: Session, restroom_id: int) -> RestroomDetail:
    restroom = get_restroom(db, restroom_id)
    inspection_count = db.scalar(
        select(func.count()).select_from(Inspection).where(Inspection.restroom_id == restroom_id)
    ) or 0
    avg_score = db.scalar(
        select(func.avg(Inspection.score)).where(Inspection.restroom_id == restroom_id)
    )
    latest = db.scalars(
        select(Inspection)
        .where(Inspection.restroom_id == restroom_id)
        .order_by(Inspection.inspect_time.desc(), Inspection.id.desc())
        .limit(1)
    ).first()
    open_issue_count = db.scalar(
        select(func.count())
        .select_from(Issue)
        .where(Issue.restroom_id == restroom_id, Issue.status.in_(OPEN_ISSUE_STATUSES))
    ) or 0
    total_issue_count = db.scalar(
        select(func.count()).select_from(Issue).where(Issue.restroom_id == restroom_id)
    ) or 0

    base = RestroomOut.model_validate(restroom).model_dump()

    # 撤并点位的当前承接方 + 完整谱系（原编号留痕）
    current_restroom = None
    lineage: list[dict] = []
    from app.schemas.adjustment import LineageOut
    from app.services import adjustment_service

    links = adjustment_service.lineage_of(db, restroom_id)
    lineage = [LineageOut.model_validate(link).model_dump() for link in links]
    if restroom.status == RestroomStatus.MERGED.value:
        resolved = adjustment_service.resolve_restroom(db, restroom_id)
        if resolved.id != restroom_id:
            current_restroom = RestroomBrief.model_validate(resolved)

    return RestroomDetail(
        **base,
        inspection_count=inspection_count,
        latest_inspection_time=latest.inspect_time if latest else None,
        latest_inspection_score=latest.score if latest else None,
        avg_score=round(float(avg_score), 1) if avg_score is not None else None,
        open_issue_count=open_issue_count,
        total_issue_count=total_issue_count,
        current_restroom=current_restroom,
        lineage=lineage,
    )


def touch(db: Session, restroom_id: int) -> None:
    """巡查或问题变更后刷新台账更新时间。"""
    restroom = db.get(Restroom, restroom_id)
    if restroom is not None:
        restroom.updated_at = datetime.now()
        db.commit()
