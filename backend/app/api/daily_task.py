"""每日任务 API

查看/管理每日自动优化任务，含实时进度、邮件开关、参数边界配置。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from backend.app.api.auth import get_current_admin_user
from backend.app.services.daily_task_service import daily_task_service

router = APIRouter()


class EmailToggleRequest(BaseModel):
    enabled: bool

class AggregationOptimizeRequest(BaseModel):
    stock_code: str
    strategy_names: Optional[List[str]] = None

class BoundsRequest(BaseModel):
    aggregation_bounds: Dict[str, list] = {}
    strategy_bounds: Dict[str, Dict[str, list]] = {}

class TaskConfigRequest(BaseModel):
    hour: int = 15
    minute: int = 30
    notify_email: str = ""


@router.get("/daily-task/status")
async def get_daily_task_status(
    current_user=Depends(get_current_admin_user),
):
    """获取每日任务状态（含实时进度）"""
    return daily_task_service.get_status()


@router.post("/daily-task/run")
async def trigger_daily_task(
    current_user=Depends(get_current_admin_user),
):
    """手动触发每日任务"""
    result = await daily_task_service.trigger_manual()
    return result


@router.get("/daily-task/progress")
async def get_progress(
    current_user=Depends(get_current_admin_user),
):
    """获取实时优化进度（前端轮询用）"""
    return daily_task_service.batch_optimizer.progress


@router.post("/daily-task/toggle-email")
async def toggle_email(
    body: EmailToggleRequest,
    current_user=Depends(get_current_admin_user),
):
    """开关邮件通知"""
    import os
    daily_task_service._enable_email = body.enabled
    os.environ["ENABLE_EMAIL_NOTIFY"] = str(body.enabled).lower()
    return {"email_enabled": body.enabled}


@router.post("/daily-task/optimize-aggregation")
async def optimize_aggregation(
    body: AggregationOptimizeRequest,
    current_user=Depends(get_current_admin_user),
):
    """手动运行聚合优化（单股票）"""
    result = await daily_task_service.optimize_aggregation(
        stock_code=body.stock_code,
        strategy_names=body.strategy_names,
    )
    return result


@router.get("/daily-task/bounds/{stock_code}")
async def get_bounds(
    stock_code: str,
    current_user=Depends(get_current_admin_user),
):
    """获取某只股票的参数边界配置"""
    return daily_task_service.get_bounds(stock_code)


@router.put("/daily-task/bounds/{stock_code}")
async def save_bounds(
    stock_code: str,
    body: BoundsRequest,
    current_user=Depends(get_current_admin_user),
):
    """保存某只股票的参数边界配置"""
    ok = daily_task_service.save_bounds(
        stock_code=stock_code,
        aggregation_bounds=body.aggregation_bounds,
        strategy_bounds=body.strategy_bounds,
    )
    if ok:
        return {"status": "ok"}
    raise HTTPException(500, "保存失败")


@router.get("/daily-task/config")
async def get_config(current_user=Depends(get_current_admin_user)):
    """获取每日任务配置"""
    return daily_task_service.get_status()

@router.put("/daily-task/config")
async def update_config(
    body: TaskConfigRequest,
    current_user=Depends(get_current_admin_user),
):
    """更新运行时间和邮件收件人"""
    daily_task_service.update_config(body.hour, body.minute, body.notify_email)
    return {"status": "ok"}
