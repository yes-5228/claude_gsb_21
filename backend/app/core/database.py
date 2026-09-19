"""数据库引擎、会话与初始化。"""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# 已有表上新增的可空列（项目未引入 Alembic，用幂等 ADD COLUMN 兼容旧库）。
# 新表由 Base.metadata.create_all 自动创建。
_ADDED_COLUMNS: dict[str, dict[str, object]] = {
    "restrooms": {
        "merged_into_id": "INTEGER",
        "merged_at": "TIMESTAMP",
    },
    "inspections": {
        "origin_restroom_id": "INTEGER",
        "origin_restroom_code": "VARCHAR(32)",
    },
    "issues": {
        "origin_restroom_id": "INTEGER",
        "origin_restroom_code": "VARCHAR(32)",
    },
    "monthly_assessments": {
        "origin_restroom_id": "INTEGER",
        "origin_restroom_code": "VARCHAR(32)",
    },
}


def _ensure_added_columns() -> None:
    """为旧库幂等补列；新列均可空，不影响存量数据。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # 新表由 create_all 建立，列已齐全
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _prepare_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    path = url.replace("sqlite:///", "", 1)
    if path.startswith(":memory:"):
        return
    directory = Path(path).parent
    if str(directory) not in ("", "."):
        os.makedirs(directory, exist_ok=True)


_prepare_sqlite_dir(settings.database_url)

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。"""


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401  确保模型完成注册

    Base.metadata.create_all(bind=engine)
    _ensure_added_columns()
