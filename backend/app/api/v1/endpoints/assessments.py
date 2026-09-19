"""月度考核结果接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.assessment import AssessmentIssue, AssessmentOut
from app.schemas.restroom import RestroomBrief
from app.services import assessment_service

router = APIRouter(prefix="/assessments", tags=["月度考核"])


@router.get("", response_model=list[AssessmentOut], summary="月度考核结果列表")
def list_assessments(
    db: Annotated[Session, Depends(get_db)],
    restroom_id: Annotated[int | None, Query(description="按公厕过滤")] = None,
    period: Annotated[str | None, Query(description="按月份过滤，如 2026-09")] = None,
) -> list[AssessmentOut]:
    rows = assessment_service.list_assessments(
        db, restroom_id=restroom_id, period=period
    )
    result = []
    for row in rows:
        out = AssessmentOut.model_validate(row)
        restroom = row.restroom
        if restroom:
            out.restroom = RestroomBrief.model_validate(restroom)
        result.append(out)
    return result


@router.post(
    "/restrooms/{restroom_id}", response_model=AssessmentOut, status_code=201,
    summary="出具某公厕月度考核（结果冻结）",
)
def issue_assessment(
    restroom_id: int, payload: AssessmentIssue, db: Annotated[Session, Depends(get_db)]
) -> AssessmentOut:
    row = assessment_service.issue_assessment(db, restroom_id, payload)
    out = AssessmentOut.model_validate(row)
    out.restroom = RestroomBrief.model_validate(row.restroom)
    return out
