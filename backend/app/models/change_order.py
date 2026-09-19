"""公厕台账变更单（合并 / 拆分）与审批留痕。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ChangeOrderStatus, ChangeType
from app.core.database import Base


class RestroomChangeOrder(Base):
    """一次公厕合并或拆分的审批单据。

    - merge：source_restroom_id 撤并进 target_restroom_id，承接方已存在。
    - split：从 source_restroom_id 拆出一座新公厕 new_restroom_id（执行时建档）。

    草稿/待审批阶段不改动任何业务数据；审批通过时在单个事务内整体执行，
    执行失败整体回滚，不会出现记录只迁移一半的中间状态。
    """

    __tablename__ = "restroom_change_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="变更单编号")
    type: Mapped[str] = mapped_column(String(10), index=True, comment="变更类型：merge/split")
    status: Mapped[str] = mapped_column(
        String(20),
        default=ChangeOrderStatus.PENDING.value,
        index=True,
        comment="审批状态",
    )

    source_restroom_id: Mapped[int] = mapped_column(
        ForeignKey("restrooms.id", ondelete="CASCADE"), index=True, comment="被撤并/被拆分的公厕"
    )
    target_restroom_id: Mapped[int | None] = mapped_column(
        ForeignKey("restrooms.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="合并承接方（仅合并）",
    )
    new_restroom_id: Mapped[int | None] = mapped_column(
        ForeignKey("restrooms.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="拆分新建公厕（执行后回填）",
    )

    # 拆分时新点位的建档参数
    new_restroom_payload: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="拆分新点位建档参数"
    )
    # 拆分时未闭环问题的划归明细：[{"issue_id":1,"to":"new"/"source"}, ...]
    issue_assignments: Mapped[list] = mapped_column(
        JSON, default=list, comment="在办问题划归明细（拆分）"
    )

    reason: Mapped[str] = mapped_column(Text, comment="变更依据/原因说明")
    applicant: Mapped[str] = mapped_column(String(60), default="", comment="申请人")
    approver: Mapped[str] = mapped_column(String(60), default="", comment="审批人")
    approve_remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审批意见")
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="审批/执行时间"
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="驳回时间"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="撤销时间"
    )

    # 执行完成后的归属变更快照，便于审计与页面回显
    result_snapshot: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="执行结果快照（迁移了哪些记录）"
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
    new_restroom: Mapped["Restroom | None"] = relationship(  # noqa: F821
        foreign_keys=[new_restroom_id]
    )

    @property
    def is_merge(self) -> bool:
        return self.type == ChangeType.MERGE.value

    @property
    def is_split(self) -> bool:
        return self.type == ChangeType.SPLIT.value
