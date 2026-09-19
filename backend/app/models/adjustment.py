"""公厕台账合并/拆分模型。

设计要点：

- ``RestroomAdjustment`` 是一张带审批流的调整单（合并或拆分），
  申请 → 审批通过 → 同事务原子执行；驳回/撤销不产生任何归属变更。
- ``RestroomLineage`` 记录点位谱系：合并时被撤并点位的原编号、
  原名称指向承接方；拆分时新点位指向来源点位。原编号永久保留用于追溯。
- ``MonthlyAssessment`` 是月度考核结果快照，一经生成不再随后续
  合并/拆分重算；统计看板的实时指标始终按当前归属查询。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RestroomAdjustment(Base):
    """公厕合并/拆分审批单。"""

    __tablename__ = "restroom_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="调整单编号")
    type: Mapped[str] = mapped_column(String(20), index=True, comment="调整类型：合并/拆分")
    status: Mapped[str] = mapped_column(
        String(20), default="待审批", index=True, comment="审批单状态"
    )

    # 合并：source_id 为被撤并点位，target_id 为承接方（已存在）。
    # 拆分：source_id 为原点位（保留），target_id 为审批通过后新建的点位。
    source_restroom_id: Mapped[int] = mapped_column(
        ForeignKey("restrooms.id"), index=True, comment="来源（被撤并/被拆分）点位"
    )
    target_restroom_id: Mapped[int | None] = mapped_column(
        ForeignKey("restrooms.id"), nullable=True, index=True, comment="承接方/拆出的新点位"
    )

    # 拆分时新点位的建档信息（审批通过后据此创建）
    new_restroom_payload: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="拆分新点位档案"
    )

    reason: Mapped[str] = mapped_column(Text, comment="调整依据与说明")
    applicant: Mapped[str] = mapped_column(String(60), default="", comment="申请人")
    approver: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="审批人")
    approval_remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审批意见")
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="审批时间"
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="执行完成时间"
    )
    fail_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="执行失败原因")

    # 拆分时明确划归新点位的未闭环问题/在办任务（问题 id 列表）；
    # 合并时为空——全部记录整体归到承接方。
    move_issue_ids: Mapped[list[int]] = mapped_column(
        JSON, default=list, comment="划归新点位的问题 ID 清单"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    source_restroom: Mapped["Restroom"] = relationship(  # noqa: F821
        foreign_keys=[source_restroom_id]
    )
    target_restroom: Mapped["Restroom | None"] = relationship(  # noqa: F821
        foreign_keys=[target_restroom_id]
    )
    logs: Mapped[list["RestroomAdjustmentLog"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="RestroomAdjustmentLog.id",
    )


class RestroomAdjustmentLog(Base):
    """调整单审批/执行轨迹。"""

    __tablename__ = "restroom_adjustment_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(
        ForeignKey("restroom_adjustments.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(30), comment="动作：提交/审批通过/驳回/撤销/执行")
    operator: Mapped[str] = mapped_column(String(60), default="", comment="操作人")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="说明")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    adjustment: Mapped["RestroomAdjustment"] = relationship(back_populates="logs")


class RestroomLineage(Base):
    """点位谱系链接：原编号 → 当前承接点位，支持按原编号追溯。"""

    __tablename__ = "restroom_lineage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    relation: Mapped[str] = mapped_column(
        String(20), index=True, comment="关系：merged_into（并入）/split_from（拆出）"
    )
    original_restroom_id: Mapped[int | None] = mapped_column(
        ForeignKey("restrooms.id"), nullable=True, index=True,
        comment="原点位 ID（已撤并点位保留行时仍可关联）",
    )
    original_code: Mapped[str] = mapped_column(String(32), index=True, comment="原编号")
    original_name: Mapped[str] = mapped_column(String(120), default="", comment="原名称")
    current_restroom_id: Mapped[int] = mapped_column(
        ForeignKey("restrooms.id"), index=True, comment="当前承接点位"
    )
    adjustment_id: Mapped[int] = mapped_column(
        ForeignKey("restroom_adjustments.id"), comment="来源调整单"
    )
    moved_inspection_count: Mapped[int] = mapped_column(Integer, default=0, comment="归入巡查数")
    moved_issue_count: Mapped[int] = mapped_column(Integer, default=0, comment="归入问题数")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    current_restroom: Mapped["Restroom"] = relationship(  # noqa: F821
        foreign_keys=[current_restroom_id]
    )
    adjustment: Mapped["RestroomAdjustment"] = relationship()


class MonthlyAssessment(Base):
    """月度考核结果快照。

    按「点位 + 考核月份」冻结生成时的统计口径；点位后续被合并/拆分，
    历史快照保持不动。统计看板等实时分析按记录当前归属即时计算。
    """

    __tablename__ = "monthly_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True, comment="考核月份 YYYY-MM")
    restroom_id: Mapped[int] = mapped_column(
        ForeignKey("restrooms.id"), index=True, comment="考核时点归属点位"
    )
    restroom_code: Mapped[str] = mapped_column(String(32), comment="考核时点编号（冗余留痕）")
    restroom_name: Mapped[str] = mapped_column(String(120), comment="考核时点名称（冗余留痕）")
    inspection_count: Mapped[int] = mapped_column(Integer, default=0, comment="巡查次数")
    issue_count: Mapped[int] = mapped_column(Integer, default=0, comment="问题总数")
    open_issue_count: Mapped[int] = mapped_column(Integer, default=0, comment="未闭环问题数")
    avg_score: Mapped[float] = mapped_column(Float, default=0.0, comment="月均得分")
    grade: Mapped[str] = mapped_column(String(20), default="", comment="考核等级")
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, comment="完整考核明细快照")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
