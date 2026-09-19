"""月度考核结果业务逻辑。

考核结果是按月出具后即冻结的凭证：出具时按当时的记录归属汇总一次，之后即便
公厕被撤并或拆分，已出具月份的结果也不重算、不迁移（拆分场景）；实时看板统计
始终按记录当前归属现算，与考核凭证口径分离。
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import OPEN_ISSUE_STATUSES
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Inspection, Issue, MonthlyAssessment
from app.schemas.assessment import AssessmentIssue
from app.services import restroom_service


def previous_period(now: datetime | None = None) -> str:
    """上一个自然月，形如 2026-08。"""
    now = now or datetime.now()
    year, month = now.year, now.month
    if month == 1:
        year -= 1
        month = 12
    else:
        month -= 1
    return f"{year:04d}-{month:02d}"


def _period_bounds(period: str) -> tuple[datetime, datetime]:
    year, month = (int(part) for part in period.split("-"))
    start = datetime(year, month, 1)
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, datetime(end_year, end_month, 1)


def get_assessment(db: Session, assessment_id: int) -> MonthlyAssessment:
    row = db.get(MonthlyAssessment, assessment_id)
    if row is None:
        raise NotFoundError(f"考核结果 {assessment_id} 不存在")
    return row


def list_assessments(
    db: Session, *, restroom_id: int | None = None, period: str | None = None
) -> list[MonthlyAssessment]:
    stmt = select(MonthlyAssessment)
    if restroom_id:
        stmt = stmt.where(MonthlyAssessment.restroom_id == restroom_id)
    if period:
        stmt = stmt.where(MonthlyAssessment.period == period)
    stmt = stmt.order_by(MonthlyAssessment.period.desc(), MonthlyAssessment.id.desc())
    return list(db.scalars(stmt))


def issue_assessment(
    db: Session, restroom_id: int, payload: AssessmentIssue
) -> MonthlyAssessment:
    """出具某公厕某月考核：按当前归属的当月记录汇总一次并冻结。"""
    restroom = restroom_service.require_active_restroom(db, restroom_id)
    period = payload.period or previous_period()
    start, end = _period_bounds(period)

    duplicate = db.scalar(
        select(func.count())
        .select_from(MonthlyAssessment)
        .where(
            MonthlyAssessment.restroom_id == restroom_id,
            MonthlyAssessment.period == period,
            MonthlyAssessment.origin_restroom_id.is_(None),
        )
    )
    if duplicate:
        raise ConflictError(f"{restroom.name} {period} 的月度考核已出具，不能重复出具")

    inspection_count = db.scalar(
        select(func.count())
        .select_from(Inspection)
        .where(
            Inspection.restroom_id == restroom_id,
            Inspection.inspect_time >= start,
            Inspection.inspect_time < end,
        )
    ) or 0
    avg_score = db.scalar(
        select(func.avg(Inspection.score)).where(
            Inspection.restroom_id == restroom_id,
            Inspection.inspect_time >= start,
            Inspection.inspect_time < end,
        )
    )
    issue_total = db.scalar(
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.restroom_id == restroom_id,
            Issue.report_time >= start,
            Issue.report_time < end,
        )
    ) or 0
    issue_open = db.scalar(
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.restroom_id == restroom_id,
            Issue.report_time >= start,
            Issue.report_time < end,
            Issue.status.in_(OPEN_ISSUE_STATUSES),
        )
    ) or 0

    if inspection_count == 0:
        grade = "无巡查数据"
    else:
        score = float(avg_score or 0)
        grade = (
            "优秀" if score >= 90 else "良好" if score >= 80 else "合格" if score >= 70 else "不合格"
        )

    assessment = MonthlyAssessment(
        restroom_id=restroom_id,
        period=period,
        inspection_count=inspection_count,
        avg_score=round(float(avg_score or 0), 1),
        issue_total=issue_total,
        issue_open=issue_open,
        grade=grade,
        remark=payload.remark,
        issued_by=payload.issued_by,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment
