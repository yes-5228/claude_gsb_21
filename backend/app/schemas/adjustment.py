"""公厕合并/拆分相关数据结构。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.restroom import RestroomBase, RestroomBrief


class AdjustmentIssueItem(BaseModel):
    """拆分时可划归的未闭环问题。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    status: str
    severity: str
    assignee: str = ""


class MergeApplyRequest(BaseModel):
    """合并申请：source 并入 target。"""

    source_restroom_id: int = Field(description="被撤并点位 ID")
    target_restroom_id: int = Field(description="承接方点位 ID")
    reason: str = Field(min_length=5, max_length=1000, description="合并依据与说明")
    applicant: str = Field(default="", max_length=60, description="申请人")


class SplitApplyRequest(BaseModel):
    """拆分申请：从 source 拆出新点位。"""

    source_restroom_id: int = Field(description="原点位 ID（拆分后保留）")
    reason: str = Field(min_length=5, max_length=1000, description="拆分依据与说明")
    applicant: str = Field(default="", max_length=60, description="申请人")
    new_restroom: RestroomBase = Field(description="新点位档案")
    new_code: str | None = Field(default=None, max_length=32, description="新点位编号，留空自动生成")
    move_issue_ids: list[int] = Field(
        default_factory=list, description="划归新点位的未闭环问题 ID 清单"
    )


class ApprovalRequest(BaseModel):
    """审批操作。"""

    approver: str = Field(min_length=1, max_length=60, description="审批人")
    remark: str | None = Field(default=None, max_length=500, description="审批意见")


class AdjustmentLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    operator: str
    remark: str | None = None
    created_at: datetime


class LineageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    relation: str
    original_restroom_id: int | None = None
    original_code: str
    original_name: str = ""
    current_restroom_id: int
    moved_inspection_count: int = 0
    moved_issue_count: int = 0
    created_at: datetime
    current_restroom: RestroomBrief | None = None


class AdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    type: str
    status: str
    source_restroom_id: int
    target_restroom_id: int | None = None
    source_restroom: RestroomBrief | None = None
    target_restroom: RestroomBrief | None = None
    new_restroom_payload: dict | None = None
    reason: str
    applicant: str
    approver: str | None = None
    approval_remark: str | None = None
    move_issue_ids: list[int] = Field(default_factory=list)
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    fail_reason: str | None = None
    created_at: datetime
    logs: list[AdjustmentLogOut] = Field(default_factory=list)


class AdjustmentDetail(AdjustmentOut):
    """调整单详情，附带执行涉及的数量与谱系。"""

    source_inspection_count: int = 0
    source_issue_count: int = 0
    source_open_issue_count: int = 0
    movable_issues: list[AdjustmentIssueItem] = Field(default_factory=list)


class MonthlyAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    restroom_id: int
    restroom_code: str
    restroom_name: str
    inspection_count: int
    issue_count: int
    open_issue_count: int
    avg_score: float
    grade: str
    snapshot: dict = Field(default_factory=dict)
    created_at: datetime
