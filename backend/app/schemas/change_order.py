"""公厕台账变更单（合并 / 拆分）相关数据结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.restroom import RestroomBase, RestroomBrief


class MergeOrderCreate(BaseModel):
    """发起合并：source 撤并进 target，记录整体归到承接方。"""

    source_restroom_id: int = Field(description="被撤并的公厕")
    target_restroom_id: int = Field(description="承接公厕")
    reason: str = Field(min_length=5, max_length=500, description="合并依据/原因说明")
    applicant: str = Field(default="", max_length=60, description="申请人")


class IssueAssignment(BaseModel):
    """拆分时一条未闭环问题的划归去向。"""

    issue_id: int = Field(description="问题ID")
    destination: Literal["new", "source"] = Field(
        description="new=划归新点位，source=留在原公厕"
    )


class SplitOrderCreate(BaseModel):
    """发起拆分：从 source 拆出新点位，并明确每条在办问题的归属。"""

    source_restroom_id: int = Field(description="被拆分的公厕")
    new_restroom: RestroomBase = Field(description="新点位档案")
    issue_assignments: list[IssueAssignment] = Field(
        default_factory=list, description="未闭环问题划归明细，必须覆盖全部在办问题"
    )
    reason: str = Field(min_length=5, max_length=500, description="拆分依据/原因说明")
    applicant: str = Field(default="", max_length=60, description="申请人")


class ApprovalAction(BaseModel):
    """审批操作：通过并执行 / 驳回。"""

    approver: str = Field(min_length=1, max_length=60, description="审批人")
    remark: str | None = Field(default=None, max_length=500, description="审批意见")


class ChangeOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    type: str
    status: str
    source_restroom_id: int
    target_restroom_id: int | None = None
    new_restroom_id: int | None = None
    source_restroom: RestroomBrief | None = None
    target_restroom: RestroomBrief | None = None
    new_restroom: RestroomBrief | None = None
    new_restroom_payload: dict | None = None
    issue_assignments: list[dict] = Field(default_factory=list)
    reason: str
    applicant: str = ""
    approver: str = ""
    approve_remark: str | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    revoked_at: datetime | None = None
    result_snapshot: dict | None = None
    created_at: datetime
    updated_at: datetime


class ChangePreview(BaseModel):
    """提交审批前的影响面预览。"""

    type: str
    source_restroom: RestroomBrief
    target_restroom: RestroomBrief | None = None
    inspection_count: int = 0
    issue_open_count: int = 0
    issue_closed_count: int = 0
    assessment_count: int = 0
    open_issues: list[dict] = Field(default_factory=list)
