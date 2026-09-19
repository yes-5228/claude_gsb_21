"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    adjustments,
    assessments,
    inspections,
    issues,
    meta,
    restrooms,
    stats,
)

api_router = APIRouter()
# adjustments 必须在 restrooms 之前：其 /restrooms/adjustments/* 路径
# 不能被 /restrooms/{restroom_id} 抢先匹配。
api_router.include_router(adjustments.router)
api_router.include_router(assessments.router)
api_router.include_router(restrooms.router)
api_router.include_router(inspections.router)
api_router.include_router(issues.router)
api_router.include_router(stats.router)
api_router.include_router(meta.router)

__all__ = ["api_router"]
