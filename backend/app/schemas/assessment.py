"""月度考核结果相关数据结构。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.restroom import RestroomBrief


class AssessmentIssue(BaseModel):
    """出具月度考核。period 形如 2026-09；不传则取上一个自然月。"""

    period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="考核月份")
    remark: str | None = Field(default=None, max_length=500, description="考核说明")
    issued_by: str = Field(default="", max_length=60, description="出具人")


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restroom_id: int
    restroom: RestroomBrief | None = None
    period: str
    inspection_count: int
    avg_score: float
    issue_total: int
    issue_open: int
    grade: str
    remark: str | None = None
    issued_by: str = ""
    issued_at: datetime
    origin_restroom_id: int | None = None
    origin_restroom_code: str | None = None
