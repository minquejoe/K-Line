"""每日自动优化任务服务

每日收盘后自动执行：
  1. 获取所有用户自选股（去重）
  2. 批量参数优化 + 权重优化
  3. 检测买入信号
  4. 邮件推送
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.app.config import settings
from backend.app.dependencies import get_storage
from backend.app.services.batch_optimization import BatchOptimizer, BatchResult
from backend.app.services.notification_service import NotificationService
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DailyTaskService:
    """每日自动任务服务"""

    def __init__(self):
        self.storage = get_storage()
        self.batch_optimizer = BatchOptimizer()
        self.notification = NotificationService()
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._last_run: Dict[str, Any] = {}
        self._run_history: List[Dict[str, Any]] = []  # 最近运行历史
        self._last_buy_signals: List[Dict[str, Any]] = []  # 最近买入信号
        self._is_running = False
        self._max_history = 30  # 保留最近30条记录
        self._enable_email = os.getenv("ENABLE_EMAIL_NOTIFY", "true").lower() == "true"

    # ────────── 定时任务注册 ──────────

    def start(self):
        """启动定时任务"""
        hour = int(os.getenv("DAILY_TASK_HOUR", "15"))
        minute = int(os.getenv("DAILY_TASK_MINUTE", "30"))

        self.scheduler.add_job(
            self.run_daily,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai"),
            id="daily_optimization",
            name="每日策略优化与信号推送",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info(f"每日任务已注册: {hour:02d}:{minute:02d} 执行")

    def stop(self):
        """停止定时任务"""
        self.scheduler.shutdown(wait=False)

    # ────────── 主流程 ──────────

    async def run_daily(self) -> Dict[str, Any]:
        """执行每日完整流程"""
        if self._is_running:
            logger.warning("上一轮任务尚未完成，跳过本次执行")
            return {"status": "skipped", "reason": "already_running"}

        self._is_running = True
        start_time = datetime.now()
        logger.info("========== 每日任务开始 ==========")

        try:
            # 1. 获取自选股列表（去重）
            stock_codes = self._get_watchlist_stocks()
            logger.info(f"步骤1: 获取自选股 {len(stock_codes)} 只")

            if not stock_codes:
                self._is_running = False
                return {"status": "no_stocks"}

            # 2. 批量优化（带进度上报）
            logger.info(f"步骤2: 开始批量优化...")
            results = self.batch_optimizer.run_batch(
                stock_codes,
                progress_callback=lambda p: None,  # progress 通过 self.batch_optimizer.progress 轮询
            )

            # 3. 收集买入信号

            # 3. 收集买入信号
            buy_signals = []
            errors = []
            for r in results:
                if r.errors:
                    errors.append(f"{r.stock_code}: {'; '.join(r.errors)}")
                for sig in r.buy_signals:
                    buy_signals.append({
                        "stock_code": r.stock_code,
                        "stock_name": r.stock_name,
                        "score": sig["score"],
                        "strategies": sig.get("triggering_strategies", []),
                    })

            logger.info(f"步骤3: 发现 {len(buy_signals)} 个买入信号")

            # 3.5 保存聚合方案
            logger.info("步骤3.5: 保存聚合方案...")
            saved_count = 0
            for r in results:
                if r.weight_result and not r.weight_result.error:
                    sid = self.batch_optimizer.save_aggregation_scheme(
                        stock_code=r.stock_code,
                        stock_name=r.stock_name,
                        param_results=r.param_results,
                        weight_result=r.weight_result,
                    )
                    if sid:
                        saved_count += 1
            logger.info(f"已保存 {saved_count} 个聚合方案")

            # 4. 发送邮件（受开关控制）
            if self._enable_email:
                logger.info("步骤4: 发送邮件...")
                self.notification.send_buy_signal_email(
                    buy_signals=buy_signals,
                    total_stocks=len(stock_codes),
                    errors=errors if errors else None,
                )
            else:
                logger.info("步骤4: 邮件通知已关闭")

            elapsed = (datetime.now() - start_time).total_seconds()
            self._last_run = {
                "time": start_time.isoformat(),
                "elapsed_seconds": elapsed,
                "stocks_scanned": len(stock_codes),
                "buy_signals": len(buy_signals),
                "errors": len(errors),
                "status": "success",
            }
            self._last_buy_signals = buy_signals
            self._run_history.insert(0, self._last_run.copy())
            if len(self._run_history) > self._max_history:
                self._run_history = self._run_history[: self._max_history]

            logger.info(f"========== 每日任务完成 ({elapsed:.0f}s) ==========")
            self._is_running = False
            return self._last_run

        except Exception as e:
            logger.error(f"每日任务失败: {e}", exc_info=True)
            elapsed = (datetime.now() - start_time).total_seconds()
            self._last_run = {
                "time": start_time.isoformat(),
                "elapsed_seconds": elapsed,
                "status": "failed",
                "error": str(e),
            }
            self._is_running = False
            return self._last_run

    # ────────── 辅助方法 ──────────

    def _get_watchlist_stocks(self) -> List[str]:
        """获取所有用户自选股（去重）"""
        try:
            users = self.storage.list_users() if hasattr(self.storage, 'list_users') else []
            codes_set = set()
            for user in users:
                watchlist = self.storage.get_watchlist(user.get("id", 0)) if hasattr(self.storage, 'get_watchlist') else []
                for item in watchlist:
                    codes_set.add(item.get("stock_code", ""))
            return sorted(codes_set)
        except Exception as e:
            logger.warning(f"获取自选股失败: {e}，尝试直接查表")
            return []

    def get_status(self) -> Dict[str, Any]:
        """获取最近运行状态（含进度和历史）"""
        hour = int(os.getenv("DAILY_TASK_HOUR", "15"))
        minute = int(os.getenv("DAILY_TASK_MINUTE", "30"))
        return {
            "last_run": self._last_run or None,
            "run_history": self._run_history,
            "last_buy_signals": self._last_buy_signals,
            "is_running": self._is_running,
            "config": {"hour": hour, "minute": minute},
            "email_enabled": self._enable_email,
            "progress": {
                "phase": self.batch_optimizer.progress.phase,
                "stock_index": self.batch_optimizer.progress.stock_index,
                "stock_total": self.batch_optimizer.progress.stock_total,
                "stock_code": self.batch_optimizer.progress.stock_code,
                "strategy_index": self.batch_optimizer.progress.strategy_index,
                "strategy_total": self.batch_optimizer.progress.strategy_total,
                "strategy_name": self.batch_optimizer.progress.strategy_name,
                "elapsed": self.batch_optimizer.progress.elapsed_seconds,
            },
        }

    async def trigger_manual(self) -> Dict[str, Any]:
        """手动触发每日完整任务"""
        return await self.run_daily()

    async def optimize_aggregation(
        self, stock_code: str, strategy_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        手动对单只股票跑聚合优化（参数+权重+阈值优化+保存方案）
        """
        self._is_running = True
        start_time = datetime.now()
        try:
            data = self.batch_optimizer.data_service.get_kline_data(
                stock_code,
                (datetime.now() - timedelta(days=186)).strftime("%Y%m%d"),
                datetime.now().strftime("%Y%m%d"),
            )
            if data.empty:
                self._is_running = False
                return {"status": "failed", "error": "无K线数据"}

            param_results = self.batch_optimizer._optimize_all_strategies(
                data, stock_code, strategy_names or self.batch_optimizer.strategy_manager.list_strategies()
            )
            active = [r for r in param_results if r.error is None]
            if len(active) < 2:
                self._is_running = False
                return {"status": "failed", "error": "有效策略不足2个"}

            weight_result = self.batch_optimizer._optimize_weights(data, active, stock_code)
            self.batch_optimizer._save_results(stock_code, param_results, weight_result)

            stock_name = self.batch_optimizer.data_service.get_stock_name(stock_code) or ""
            scheme_id = self.batch_optimizer.save_aggregation_scheme(
                stock_code, stock_name, param_results, weight_result
            )

            elapsed = (datetime.now() - start_time).total_seconds()
            self._is_running = False
            return {
                "status": "success", "stock_code": stock_code,
                "strategies_n": len(active), "weights": weight_result.weights,
                "buy_threshold": weight_result.buy_threshold,
                "sell_threshold": weight_result.sell_threshold,
                "best_sharpe": weight_result.best_sharpe,
                "scheme_id": scheme_id, "elapsed_seconds": elapsed,
            }
        except Exception as e:
            logger.error(f"手动聚合优化失败: {e}", exc_info=True)
            self._is_running = False
            return {"status": "failed", "error": str(e)}

    # ────────── 参数边界 ──────────

    def get_bounds(self, stock_code: str) -> dict:
        """获取某只股票的参数边界，无配置时返回系统默认"""
        stored = self.storage.get_bounds(stock_code)
        if stored:
            return stored

        # 系统默认值
        default_agg = {"buy_threshold": [0.3, 0.7], "sell_threshold": [0.2, 0.6]}
        default_strategies = {}
        for name in self.batch_optimizer.strategy_manager.list_strategies():
            s = self.batch_optimizer.strategy_manager.get_strategy(name)
            if s:
                bounds = s.get_param_bounds()
                if bounds:
                    default_strategies[name] = {k: list(v[:2]) for k, v in bounds.items()}
        return {
            "stock_code": stock_code,
            "aggregation_bounds": default_agg,
            "strategy_bounds": default_strategies,
            "updated_at": None,
        }

    def save_bounds(self, stock_code: str, aggregation_bounds: dict, strategy_bounds: dict) -> bool:
        """保存参数边界配置"""
        return self.storage.save_bounds(stock_code, aggregation_bounds, strategy_bounds)

    def _load_custom_bounds(self, stock_code: str) -> Optional[dict]:
        """加载自定义边界（内部使用），无配置返回None"""
        stored = self.storage.get_bounds(stock_code)
        if stored and stored.get("aggregation_bounds"):
            return stored
        return None


import os

# 全局单例
daily_task_service = DailyTaskService()
