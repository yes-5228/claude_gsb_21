"""月度考核结果接口。

月度考核是冻结快照：一经生成，后续公厕合并/拆分不会改动已出结果；
实时看板统计始终按记录当前归属即时重算，二者互不影响。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.adjustment import MonthlyAssessmentOut
from app.services import adjustment_service

router = APIRouter(prefix="/assessments", tags=["月度考核"])


class AssessmentGenerateRequest(BaseModel):
    period: str | None = Field(default=None, description="考核月份 YYYY-MM，留空取上月")
    operator: str = Field(default="系统", max_length=60, description="操作人")


@router.get("", response_model=list[MonthlyAssessmentOut], summary="月度考核结果列表")
def list_assessments(
    db: Annotated[Session, Depends(get_db)],
    period: Annotated[str | None, Query(description="考核月份 YYYY-MM")] = None,
) -> list[MonthlyAssessmentOut]:
    return [
        MonthlyAssessmentOut.model_validate(row)
        for row in adjustment_service.list_assessments(db, period)
    ]


@router.post(
    "/generate",
    response_model=list[MonthlyAssessmentOut],
    summary="生成月度考核快照（已存在的月份/点位不会被覆盖或重算）",
)
def generate_assessments(
    payload: AssessmentGenerateRequest, db: Annotated[Session, Depends(get_db)]
) -> list[MonthlyAssessmentOut]:
    rows = adjustment_service.generate_monthly_assessment(
        db, payload.period, operator=payload.operator
    )
    return [MonthlyAssessmentOut.model_validate(row) for row in rows]
