"""月度考核结果：一经出具即冻结，不因后续公厕拆分而改变。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonthlyAssessment(Base):
    """某座公厕某个月份的考核结果凭证。

    - 出具后即为冻结凭证：拆分公厕时，历史月份已出具的考核结果保留在原公厕、
      不重算、不迁移；实时统计仍按记录当前归属重新汇总，二者口径分离。
    - 合并时考核记录随巡查、问题一并归到承接方，同时用 origin_* 保留原公厕编号，
      因此承接方同一月份可能并存多条来源不同的历史考核，库层不再加唯一约束，
      出具时的「一座公厕一个月份一条」由业务层保证。
    """

    __tablename__ = "monthly_assessments"
    __table_args__ = (
        Index("ix_assessment_restroom_period", "restroom_id", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restroom_id: Mapped[int] = mapped_column(
        ForeignKey("restrooms.id", ondelete="CASCADE"), index=True, comment="当前归属公厕"
    )
    period: Mapped[str] = mapped_column(String(7), index=True, comment="考核月份，形如 2026-09")
    inspection_count: Mapped[int] = mapped_column(Integer, default=0, comment="当月巡查次数")
    avg_score: Mapped[float] = mapped_column(Float, default=0.0, comment="当月巡查均分")
    issue_total: Mapped[int] = mapped_column(Integer, default=0, comment="当月问题数")
    issue_open: Mapped[int] = mapped_column(Integer, default=0, comment="当月未闭环问题数")
    grade: Mapped[str] = mapped_column(String(20), default="", comment="考核等次")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="考核说明")
    issued_by: Mapped[str] = mapped_column(String(60), default="", comment="出具人")
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="出具时间")

    # 原始归属：合并归到承接方后保留原公厕编号，便于追溯
    origin_restroom_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="考核原始所属公厕ID（追溯用）"
    )
    origin_restroom_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="考核原始所属公厕编号（追溯用）"
    )

    restroom: Mapped["Restroom"] = relationship()  # noqa: F821
