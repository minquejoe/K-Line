"""批量优化执行器

对自选股列表批量执行参数优化 + 权重优化，并行执行。
双层PSO架构：
  第1层 — 每个策略的参数优化（已有）
  第2层 — 多策略聚合权重优化（新增）
"""

from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np

from src.strategy.manager import StrategyManager
from src.strategy.optimization import Optimizer
from src.strategy.statistics import StrategyStatistics
from src.utils.logger import get_logger
from backend.app.dependencies import get_storage
from backend.app.services.data_service import DataService

logger = get_logger(__name__)


@dataclass
class OptimizationResult:
    """单策略优化结果"""
    strategy_name: str
    stock_code: str
    optimal_params: Dict[str, Any]
    best_score: float
    target_metric: str
    elapsed_seconds: float
    error: Optional[str] = None


@dataclass
class WeightOptimizationResult:
    """权重+阈值优化结果"""
    stock_code: str
    weights: Dict[str, float]  # strategy_name -> weight
    buy_threshold: float = 0.5
    sell_threshold: float = 0.4
    best_sharpe: float = 0
    elapsed_seconds: float = 0
    error: Optional[str] = None


@dataclass
class BatchResult:
    """批量优化总结果"""
    stock_code: str
    stock_name: str
    param_results: List[OptimizationResult] = field(default_factory=list)
    weight_result: Optional[WeightOptimizationResult] = None
    buy_signals: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class ProgressReport:
    """优化进度报告（供前端轮询）"""
    phase: str = "idle"  # idle | params | weights | signals | done
    stock_index: int = 0
    stock_total: int = 0
    stock_code: str = ""
    strategy_index: int = 0
    strategy_total: int = 0
    strategy_name: str = ""
    elapsed_seconds: float = 0


class BatchOptimizer:
    """批量优化执行器"""

    # PSO 参数
    PARAM_PSO_PARTICLES = 20
    PARAM_PSO_ITERATIONS = 50
    WEIGHT_PSO_PARTICLES = 10
    WEIGHT_PSO_ITERATIONS = 30

    # 并行度
    MAX_WORKERS = 3

    # 回溯窗口（月）
    LOOKBACK_MONTHS = 6

    def __init__(self):
        self.strategy_manager = StrategyManager()
        self.data_service = DataService()
        self.storage = get_storage()
        self.statistics = StrategyStatistics()
        self.progress = ProgressReport()
        self._progress_callback = None  # 可选的回调函数

    # ────────── 主入口 ──────────

    def run_batch(
        self,
        stock_codes: List[str],
        strategy_names: Optional[List[str]] = None,
        lookback_months: int = LOOKBACK_MONTHS,
        progress_callback=None,
    ) -> List[BatchResult]:
        """
        对股票列表批量执行优化

        Args:
            stock_codes: 股票代码列表
            strategy_names: 策略名称列表，None=全部
            lookback_months: 数据回溯月数
            progress_callback: 进度回调 fn(ProgressReport)

        Returns:
            每只股票的批量结果
        """
        if strategy_names is None:
            strategy_names = self.strategy_manager.list_strategies()

        self._progress_callback = progress_callback
        total = max(len(stock_codes), 1)

        logger.info(
            f"开始批量优化: {len(stock_codes)} 只股票, "
            f"{len(strategy_names)} 个策略, {self.MAX_WORKERS} 线程"
        )

        results: List[BatchResult] = []
        t_start = datetime.now()

        # 逐股票优化（保持 ThreadPool 并行在单股票内部做）
        for idx, code in enumerate(stock_codes):
            self._report_progress(
                phase="params", stock_index=idx + 1, stock_total=total,
                stock_code=code, strategy_total=len(strategy_names),
                elapsed=(datetime.now() - t_start).total_seconds(),
            )
            try:
                result = self._optimize_single_stock(code, strategy_names, lookback_months)
                results.append(result)
                n_params = len(result.param_results)
                n_buy = len(result.buy_signals)
                logger.info(f"[{code}] 完成: {n_params} 参数优化, {n_buy} 买入信号")
            except Exception as e:
                logger.error(f"[{code}] 批量优化失败: {e}")
                results.append(BatchResult(stock_code=code, stock_name="", errors=[str(e)]))

        self._report_progress(phase="done", stock_index=total, stock_total=total, elapsed=(datetime.now() - t_start).total_seconds())
        return results

    def _report_progress(self, **kwargs):
        """上报进度"""
        for k, v in kwargs.items():
            if hasattr(self.progress, k):
                setattr(self.progress, k, v)
        if self._progress_callback:
            self._progress_callback(self.progress)

    # ────────── 单股票优化 ──────────

    def _optimize_single_stock(
        self,
        stock_code: str,
        strategy_names: List[str],
        lookback_months: int,
    ) -> BatchResult:
        """对单只股票执行完整优化流程"""
        result = BatchResult(
            stock_code=stock_code,
            stock_name=self.data_service.get_stock_name(stock_code) or "",
        )

        # 1. 获取K线数据
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=lookback_months * 31)).strftime("%Y%m%d")
        data = self.data_service.get_kline_data(stock_code, start_date, end_date)

        if data.empty or len(data) < 60:
            result.errors.append(f"数据不足（{len(data)}行）")
            return result

        # 2. 第1层：逐策略参数优化
        param_results = self._optimize_all_strategies(data, stock_code, strategy_names)
        result.param_results = param_results

        # 筛选成功的策略（有信号生成的）
        active_strategies = [r for r in param_results if r.error is None]
        if len(active_strategies) < 2:
            result.errors.append("可用策略不足2个，跳过权重优化")
            return result

        # 3. 第2层：权重优化
        weight_result = self._optimize_weights(data, active_strategies, stock_code)
        result.weight_result = weight_result

        if weight_result and weight_result.error is None and weight_result.weights:
            # 4. 用最优权重 + 最优阈值跑聚合，检测买点
            buy_signals = self._detect_buy_signals(
                data, active_strategies, weight_result.weights, weight_result.buy_threshold
            )
            result.buy_signals = buy_signals

        # 5. 保存结果到数据库
        self._save_results(stock_code, param_results, weight_result)

        return result

    # ────────── 第1层：参数优化 ──────────

    def _optimize_all_strategies(
        self, data: pd.DataFrame, stock_code: str, strategy_names: List[str]
    ) -> List[OptimizationResult]:
        """对单只股票的所有策略执行参数优化"""
        results = []
        total = len(strategy_names)
        for idx, sname in enumerate(strategy_names):
            self.progress.strategy_index = idx + 1
            self.progress.strategy_name = sname
            if self._progress_callback:
                self._progress_callback(self.progress)

            try:
                strategy = self.strategy_manager.get_strategy(sname)
                if strategy is None:
                    continue

                bounds = strategy.get_param_bounds()
                if not bounds:
                    # 无参数策略，用默认参数跑一次即可
                    result_df = strategy.analyze(data)
                    stats = self.statistics.calculate_statistics(data, result_df)
                    results.append(OptimizationResult(
                        strategy_name=sname,
                        stock_code=stock_code,
                        optimal_params={},
                        best_score=stats.get("sharpe_ratio", 0) or 0,
                        target_metric="sharpe_ratio",
                        elapsed_seconds=0,
                    ))
                    continue

                # PSO 参数优化
                t0 = datetime.now()
                optimizer = Optimizer(sname, data)
                opt_result = optimizer.optimize_pso(
                    param_bounds=bounds,
                    num_particles=self.PARAM_PSO_PARTICLES,
                    max_iter=self.PARAM_PSO_ITERATIONS,
                    target_metric="sharpe_ratio",
                )
                elapsed = (datetime.now() - t0).total_seconds()

                results.append(OptimizationResult(
                    strategy_name=sname,
                    stock_code=stock_code,
                    optimal_params=opt_result.get("best_params", {}),
                    best_score=opt_result.get("best_score", 0) or 0,
                    target_metric="sharpe_ratio",
                    elapsed_seconds=elapsed,
                ))

            except Exception as e:
                logger.warning(f"[{stock_code}] 策略 {sname} 优化失败: {e}")
                results.append(OptimizationResult(
                    strategy_name=sname,
                    stock_code=stock_code,
                    optimal_params={},
                    best_score=0,
                    target_metric="sharpe_ratio",
                    elapsed_seconds=0,
                    error=str(e),
                ))

        return results

    # ────────── 第2层：权重优化 ──────────

    def _optimize_weights(
        self,
        data: pd.DataFrame,
        param_results: List[OptimizationResult],
        stock_code: str,
    ) -> WeightOptimizationResult:
        """
        三维 PSO 优化聚合权重 + 买入阈值 + 卖出阈值

        目标：最大化加权聚合信号的 Sharpe ratio
        搜索空间：
          - 权重:       w_i ∈ [0.1, 2.0]
          - buy_threshold:  ∈ [0.3, 0.7]
          - sell_threshold: ∈ [0.2, 0.6]
        约束: buy_threshold > sell_threshold
        """
        t0 = datetime.now()

        # 用最优参数生成每个策略的信号
        strategy_signals: Dict[str, pd.Series] = {}
        active_names = []

        for r in param_results:
            if r.error:
                continue
            try:
                strategy = self.strategy_manager.get_strategy(r.strategy_name)
                if strategy is None:
                    continue
                for k, v in r.optimal_params.items():
                    if hasattr(strategy, k):
                        setattr(strategy, k, v)
                result_df = strategy.analyze(data)
                if result_df is not None and "signal" in result_df.columns:
                    strategy_signals[r.strategy_name] = result_df["signal"].values
                    active_names.append(r.strategy_name)
            except Exception as e:
                logger.warning(f"[{stock_code}] 生成 {r.strategy_name} 信号失败: {e}")

        n_strategies = len(active_names)
        if n_strategies < 2:
            return WeightOptimizationResult(
                stock_code=stock_code,
                weights={},
                best_sharpe=0,
                elapsed_seconds=0,
                error="有效策略不足2个",
            )

        # PSO: 权重 + 阈值（共 n+2 个变量）
        from mealpy import FloatVar, PSO

        vars_bounds = [FloatVar(lb=0.1, ub=2.0, name=f"w_{name}") for name in active_names]
        vars_bounds += [
            FloatVar(lb=0.3, ub=0.7, name="buy_threshold"),
            FloatVar(lb=0.2, ub=0.6, name="sell_threshold"),
        ]

        # 计算最佳单策略 Sharpe 作为 baseline（聚合必须优于它）
        best_single_sharpe = max((r.best_score or 0 for r in param_results if r.error is None), default=0.0)

        def objective(solution):
            *w_vals, bt, st = [float(v) for v in solution]
            # 约束: buy > sell
            if bt <= st:
                return -10.0

            weights = dict(zip(active_names, w_vals))
            total_weight = sum(abs(w) for w in weights.values()) or 1.0

            aggregated = np.zeros(len(data))
            for name, signals in strategy_signals.items():
                w = weights.get(name, 0)
                aggregated += w * signals

            agg_signals = np.zeros(len(data), dtype=int)
            agg_signals[aggregated > bt * total_weight] = 1
            agg_signals[aggregated < -st * total_weight] = -1

            result_df = pd.DataFrame({
                "date": data["date"].values,
                "signal": agg_signals,
                "signal_type": [
                    "买入" if s == 1 else ("卖出" if s == -1 else "持有")
                    for s in agg_signals
                ],
            })

            try:
                stats = self.statistics.calculate_statistics(data, result_df)
                agg_sharpe = stats.get("sharpe_ratio", -10) or -10
                # 惩罚：聚合 Sharpe 必须比最佳单策略高至少 2%
                if agg_sharpe < best_single_sharpe * 1.02:
                    return agg_sharpe - (best_single_sharpe * 1.02 - agg_sharpe) * 5
                return agg_sharpe
            except Exception:
                return -10

        try:
            problem = {
                "obj_func": objective,
                "bounds": vars_bounds,
                "minmax": "max",
                "verbose": False,
            }
            model = PSO.OriginalPSO(
                epoch=self.WEIGHT_PSO_ITERATIONS,
                pop_size=self.WEIGHT_PSO_PARTICLES,
            )
            g_best = model.solve(problem)

            *w_best, bt_best, st_best = [float(v) for v in g_best.solution]
            best_weights = dict(zip(active_names, w_best))

            # 归一化权重到 [0.1, 2.0]
            max_w = max(w_best) or 1.0
            best_weights = {k: max(v / max_w * 2.0, 0.1) for k, v in best_weights.items()}

            elapsed = (datetime.now() - t0).total_seconds()
            return WeightOptimizationResult(
                stock_code=stock_code,
                weights=best_weights,
                buy_threshold=round(bt_best, 3),
                sell_threshold=round(st_best, 3),
                best_sharpe=g_best.target.fitness,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            logger.error(f"[{stock_code}] 权重优化失败: {e}")
            equal_weights = {name: 1.0 for name in active_names}
            return WeightOptimizationResult(
                stock_code=stock_code,
                weights=equal_weights,
                buy_threshold=0.5,
                sell_threshold=0.4,
                best_sharpe=0,
                elapsed_seconds=0,
                error=str(e),
            )

    # ────────── 买点检测 ──────────

    def _detect_buy_signals(
        self,
        data: pd.DataFrame,
        param_results: List[OptimizationResult],
        weights: Dict[str, float],
        buy_threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """使用最优权重和阈值检测买入信号"""
        total_weight = sum(weights.values())
        aggregated = np.zeros(len(data))

        for r in param_results:
            if r.error or r.strategy_name not in weights:
                continue
            try:
                strategy = self.strategy_manager.get_strategy(r.strategy_name)
                if strategy is None:
                    continue
                for k, v in r.optimal_params.items():
                    if hasattr(strategy, k):
                        setattr(strategy, k, v)
                result_df = strategy.analyze(data)
                if result_df is not None and "signal" in result_df.columns:
                    w = weights[r.strategy_name]
                    aggregated += w * result_df["signal"].values
            except Exception:
                continue

        buy_signals = []
        recent_n = min(5, len(data))
        for i in range(len(data) - recent_n, len(data)):
            if aggregated[i] >= buy_threshold * total_weight:
                buy_signals.append({
                    "date": str(data.iloc[i]["date"])[:10],
                    "score": round(float(aggregated[i]) / total_weight, 3),
                    "triggering_strategies": [
                        r.strategy_name for r in param_results
                        if r.strategy_name in weights and weights[r.strategy_name] > 0.5
                    ],
                })

        return buy_signals[-3:]

    # ────────── 结果持久化 ──────────

    def _save_results(
        self,
        stock_code: str,
        param_results: List[OptimizationResult],
        weight_result: Optional[WeightOptimizationResult],
    ):
        """保存优化结果到数据库"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for r in param_results:
            if r.error:
                continue
            try:
                self.storage.save_param_set(
                    stock_code=stock_code,
                    strategy_name=r.strategy_name,
                    name=f"auto_{now[:10]}_{now[11:19].replace(':','')}",
                    params=r.optimal_params,
                    description=f"每日自动优化 (Sharpe={r.best_score:.3f})",
                    target_metric=r.target_metric,
                    best_score=r.best_score,
                    optimization_method="PSO",
                    num_particles=self.PARAM_PSO_PARTICLES,
                    max_iter=self.PARAM_PSO_ITERATIONS,
                    date_range=f"{now[:10]}",
                    is_default=True,
                )
            except Exception as e:
                logger.warning(f"保存 {r.strategy_name} 参数失败: {e}")

        if weight_result and weight_result.weights and not weight_result.error:
            try:
                self.storage.save_param_set(
                    stock_code=stock_code,
                    strategy_name="__aggregation_weights__",
                    name=f"auto_{now[:10]}_{now[11:19].replace(':','')}",
                    params=weight_result.weights,
                    description=f"自动权重优化 (Sharpe={weight_result.best_sharpe:.3f})",
                    target_metric="sharpe_ratio",
                    best_score=weight_result.best_sharpe,
                    optimization_method="PSO_WEIGHTS",
                    num_particles=self.WEIGHT_PSO_PARTICLES,
                    max_iter=self.WEIGHT_PSO_ITERATIONS,
                    date_range=f"{now[:10]}",
                    is_default=True,
                )
            except Exception as e:
                logger.warning(f"保存权重失败: {e}")

    def save_aggregation_scheme(
        self,
        stock_code: str,
        stock_name: str,
        param_results: List[OptimizationResult],
        weight_result: WeightOptimizationResult,
    ) -> Optional[int]:
        """
        保存完整的聚合方案（可被前端加载）

        方案包含：股票代码、所有策略的最优参数、最优权重、最优阈值
        """
        if not weight_result or not weight_result.weights or weight_result.error:
            return None

        now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        strategies_list = []
        required_names = []

        for r in param_results:
            if r.error or r.strategy_name not in weight_result.weights:
                continue
            strategies_list.append({
                "name": r.strategy_name,
                "weight": round(weight_result.weights[r.strategy_name], 3),
                "params": r.optimal_params,
            })
            required_names.append(r.strategy_name)

        if len(strategies_list) < 2:
            return None

        try:
            scheme_id = self.storage.save_aggregation_scheme(
                name=f"auto_{stock_code}_{now}",
                description=f"自动优化聚合方案 (Sharpe={weight_result.best_sharpe:.3f}, buy={weight_result.buy_threshold}, sell={weight_result.sell_threshold})",
                stock_code=stock_code,
                strategies=strategies_list,
                buy_threshold=weight_result.buy_threshold,
                sell_threshold=weight_result.sell_threshold,
                required_strategies=required_names,
            )
            logger.info(f"[{stock_code}] 聚合方案已保存: ID={scheme_id}")
            return scheme_id
        except Exception as e:
            logger.error(f"[{stock_code}] 保存聚合方案失败: {e}")
            return None
