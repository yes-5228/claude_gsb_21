"""保洁巡查记录模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import InspectionResult, Shift
from app.core.database import Base


class Inspection(Base):
    """一次保洁巡查的结果，包含各检查项打分。"""

    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restroom_id: Mapped[int] = mapped_column(
        ForeignKey("restrooms.id", ondelete="CASCADE"), index=True, comment="所属公厕"
    )
    inspector: Mapped[str] = mapped_column(String(60), index=True, comment="巡查人")
    inspect_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, index=True, comment="巡查时间"
    )
    shift: Mapped[str] = mapped_column(String(20), default=Shift.MORNING.value, comment="班次")
    items: Mapped[list[dict]] = mapped_column(JSON, default=list, comment="检查项打分明细")
    score: Mapped[float] = mapped_column(Float, default=0.0, comment="巡查得分")
    grade: Mapped[str] = mapped_column(String(20), default="", comment="评分等级")
    result: Mapped[str] = mapped_column(
        String(20), default=InspectionResult.NORMAL.value, index=True, comment="巡查结论"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="巡查备注")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 原始归属：记录最初属于哪座公厕；合并/拆分后 restroom_id 指向当前归属，原编号留此追溯
    origin_restroom_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="记录原始所属公厕ID（追溯用）"
    )
    origin_restroom_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="记录原始所属公厕编号（追溯用）"
    )

    restroom: Mapped["Restroom"] = relationship(  # noqa: F821
        back_populates="inspections", foreign_keys=[restroom_id]
    )
    issues: Mapped[list["Issue"]] = relationship(  # noqa: F821
        back_populates="inspection", foreign_keys="Issue.inspection_id"
    )
