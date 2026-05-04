<template>
  <div class="daily-task-page">
    <!-- 状态横幅 -->
    <div class="status-banner" :class="bannerClass">
      <div class="banner-left">
        <el-icon :size="28">
          <Loading v-if="taskStatus?.is_running" class="is-loading" />
          <CircleCheckFilled v-else-if="lastSuccess" />
          <WarningFilled v-else-if="lastFailed" />
          <Clock v-else />
        </el-icon>
        <div>
          <h3>{{ bannerTitle }}</h3>
          <p>{{ bannerDesc }}</p>
        </div>
      </div>
      <div class="banner-right" v-if="!taskStatus?.is_running">
        <el-button type="primary" :icon="VideoPlay" :loading="triggering" @click="handleTrigger">
          立即执行
        </el-button>
      </div>
    </div>

    <!-- 运行中：实时进度 -->
    <el-card v-if="taskStatus?.is_running" class="progress-card">
      <template #header>
        <div class="card-header"><el-icon><Loading class="is-loading" /></el-icon><span>优化进行中…</span></div>
      </template>
      <div class="progress-section">
        <div class="progress-row">
          <span class="prog-label">股票进度</span>
          <el-progress
            :percentage="stockPercent"
            :stroke-width="16"
            :text-inside="true"
            :color="'#409eff'"
            style="flex:1"
          />
          <span class="prog-text">{{ taskStatus.progress.stock_index }}/{{ taskStatus.progress.stock_total }}</span>
        </div>
        <div class="progress-row">
          <span class="prog-label">当前股票</span>
          <span class="prog-value" style="font-weight:600;min-width:80px">{{ taskStatus.progress.stock_code || '-' }}</span>
        </div>
        <div class="progress-row">
          <span class="prog-label">策略进度</span>
          <el-progress
            :percentage="strategyPercent"
            :stroke-width="12"
            :text-inside="true"
            :color="'#67c23a'"
            style="flex:1"
          />
          <span class="prog-text">{{ taskStatus.progress.strategy_index }}/{{ taskStatus.progress.strategy_total }}</span>
        </div>
        <div class="progress-row">
          <span class="prog-label">当前策略</span>
          <span class="prog-value">{{ taskStatus.progress.strategy_name || '-' }}</span>
        </div>
        <div class="progress-row" style="color:var(--el-text-color-secondary);font-size:12px">
          <el-icon><Timer /></el-icon>
          <span>已运行 {{ fmtProgressElapsed }}</span>
        </div>
      </div>
    </el-card>

    <div class="page-grid">
      <!-- 左侧：配置 -->
      <el-card class="config-card">
        <template #header>
          <div class="card-header"><el-icon><Setting /></el-icon><span>任务配置</span></div>
        </template>
        <div class="config-item">
          <span class="label">定时执行</span>
          <span class="value">{{ fmtTime }}</span>
        </div>
        <div class="config-item">
          <span class="label">优化周期</span>
          <span class="value">6 个月</span>
        </div>
        <div class="config-item">
          <span class="label">并行线程</span>
          <span class="value">3</span>
        </div>
        <el-divider />
        <div class="config-item">
          <span class="label">邮件通知</span>
          <el-switch
            v-model="emailEnabled"
            :loading="emailToggling"
            @change="handleEmailToggle"
            inline-prompt
            active-text="开"
            inactive-text="关"
          />
        </div>
        <el-divider />
        <div class="config-item" style="flex-direction:column;align-items:flex-start;gap:6px">
          <span class="label" style="width:auto">聚合策略选择</span>
          <div class="strategy-checkboxes">
            <el-checkbox
              v-for="s in allStrategies" :key="s"
              :model-value="selectedStrategies.includes(s)"
              @change="(v:boolean) => toggleStrategy(s,v)"
              size="small"
            >{{ s }}</el-checkbox>
          </div>
        </div>
      </el-card>

      <!-- 📐 参数边界配置 -->
      <el-card class="bounds-card">
        <template #header>
          <div class="card-header"><el-icon><EditPen /></el-icon><span>参数边界配置（每股票独立）</span></div>
        </template>
        <div class="config-item">
          <span class="label">股票</span>
          <el-select v-model="boundsStock" placeholder="选股票" filterable size="small" style="width:220px" @change="loadBounds">
            <el-option v-for="c in watchlistCodes" :key="c.code" :label="`${c.code} ${c.name}`" :value="c.code" />
          </el-select>
        </div>
        <template v-if="boundsStock">
          <el-tabs v-model="boundsTab" size="small" style="margin-top:8px">
            <el-tab-pane label="聚合参数" name="agg">
              <div v-for="(v, k) in aggBounds" :key="k" class="bounds-row">
                <span class="bound-label">{{ k }}</span>
                <el-input-number v-model="aggBounds[k][0]" :min="0" :max="1" :step="0.05" :precision="2" size="small" controls-position="right" style="width:110px" />
                <span class="bound-sep">~</span>
                <el-input-number v-model="aggBounds[k][1]" :min="0" :max="1" :step="0.05" :precision="2" size="small" controls-position="right" style="width:110px" />
              </div>
            </el-tab-pane>
            <el-tab-pane label="单策略参数" name="strat">
              <div class="config-item" style="margin-bottom:6px">
                <span class="label">策略</span>
                <el-select v-model="boundsStrategy" placeholder="选策略" size="small" style="width:200px" filterable>
                  <el-option v-for="s in strategyBoundsKeys" :key="s" :label="s" :value="s" />
                </el-select>
              </div>
              <template v-if="boundsStrategy && strategyBounds[boundsStrategy]">
                <div v-for="(v, k) in strategyBounds[boundsStrategy]" :key="k" class="bounds-row">
                  <span class="bound-label">{{ k }}</span>
                  <el-input-number v-model="strategyBounds[boundsStrategy][k][0]" :step="v[0] < 1 ? 0.05 : 1" :precision="v[0] < 1 ? 2 : 0" size="small" controls-position="right" style="width:100px" />
                  <span class="bound-sep">~</span>
                  <el-input-number v-model="strategyBounds[boundsStrategy][k][1]" :step="v[1] < 1 ? 0.05 : 1" :precision="v[1] < 1 ? 2 : 0" size="small" controls-position="right" style="width:100px" />
                </div>
              </template>
              <el-empty v-else-if="boundsStrategy" description="该策略无参数" :image-size="40" />
            </el-tab-pane>
          </el-tabs>
          <div style="margin-top:8px;display:flex;gap:8px">
            <el-button size="small" type="primary" :loading="savingBounds" @click="handleSaveBounds">保存边界</el-button>
            <el-button size="small" @click="handleResetBounds">重置为系统默认</el-button>
          </div>
        </template>
        <el-empty v-else description="请先选择股票" :image-size="40" />
      </el-card>

      <!-- 手动聚合优化 -->
      <el-card class="aggregation-card">
        <template #header>
          <div class="card-header"><el-icon><Connection /></el-icon><span>聚合优化</span></div>
        </template>
        <div class="config-item">
          <span class="label">目标股票</span>
          <el-input v-model="aggStockCode" placeholder="如 000001" size="small" style="width:120px" />
        </div>
        <el-button type="success" :loading="aggRunning" @click="handleAggOptimize" style="margin-top:10px;width:100%">
          <el-icon><VideoPlay /></el-icon> 运行聚合优化
        </el-button>
        <div v-if="aggResult" style="margin-top:8px;font-size:13px;color:var(--el-text-color-secondary)">
          <span v-if="aggResult.status==='success'">
            ✅ Sharpe={{ aggResult.best_sharpe?.toFixed(3) }}
            Buy={{ aggResult.buy_threshold }} Sell={{ aggResult.sell_threshold }}
          </span>
          <span v-else style="color:#f56c6c">❌ {{ aggResult.error }}</span>
        </div>
      </el-card>

      <!-- 右侧：上次运行 -->
      <el-card v-if="taskStatus?.last_run" class="result-card">
        <template #header>
          <div class="card-header"><el-icon><DataAnalysis /></el-icon><span>上次运行结果</span></div>
        </template>
        <div class="result-grid">
          <div class="result-item stock">
            <span class="num">{{ taskStatus.last_run.stocks_scanned }}</span>
            <span class="txt">扫描股票</span>
          </div>
          <div class="result-item signal" :class="{ active: (taskStatus.last_run.buy_signals || 0) > 0 }">
            <span class="num">{{ taskStatus.last_run.buy_signals || 0 }}</span>
            <span class="txt">买入信号</span>
          </div>
          <div class="result-item time">
            <span class="num">{{ fmtElapsed }}</span>
            <span class="txt">耗时</span>
          </div>
          <div class="result-item error" v-if="(taskStatus.last_run.errors || 0) > 0">
            <span class="num">{{ taskStatus.last_run.errors }}</span>
            <span class="txt">异常</span>
          </div>
        </div>

        <div v-if="taskStatus.last_buy_signals?.length" class="signals-section">
          <el-divider />
          <h4>📊 触发信号</h4>
          <div class="signal-list">
            <div v-for="(s, i) in taskStatus.last_buy_signals" :key="i" class="signal-item">
              <span class="sig-code">{{ s.stock_code }}</span>
              <span class="sig-name">{{ s.stock_name }}</span>
              <el-tag :type="s.score >= 0.7 ? 'success' : 'warning'" size="small" effect="dark">
                {{ (s.score * 100).toFixed(0) }}%
              </el-tag>
              <span class="sig-strategies">{{ (s.strategies || []).slice(0, 4).join(', ') }}</span>
            </div>
          </div>
        </div>
      </el-card>

      <el-card v-else class="result-card">
        <template #header>
          <div class="card-header"><el-icon><DataAnalysis /></el-icon><span>运行结果</span></div>
        </template>
        <el-empty description="尚未执行过每日优化任务" :image-size="80" />
      </el-card>

      <!-- 运行历史 -->
      <el-card v-if="taskStatus?.run_history?.length" class="history-card">
        <template #header>
          <div class="card-header"><el-icon><Timer /></el-icon><span>运行历史 ({{ taskStatus.run_history.length }})</span></div>
        </template>
        <el-table :data="taskStatus.run_history" size="small" stripe>
          <el-table-column prop="time" label="时间" width="180">
            <template #default="{ row }">{{ row.time?.slice(0, 19)?.replace('T', ' ') }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                {{ row.status === 'success' ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="elapsed_seconds" label="耗时" width="80">
            <template #default="{ row }">{{ row.elapsed_seconds?.toFixed(0) }}s</template>
          </el-table-column>
          <el-table-column prop="stocks_scanned" label="股票" width="70" />
          <el-table-column prop="buy_signals" label="信号" width="70" />
          <el-table-column prop="error" label="错误信息" min-width="200">
            <template #default="{ row }">
              <span v-if="row.error" style="color:#f56c6c">{{ row.error }}</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 快捷链接 -->
      <el-card class="links-card">
        <template #header>
          <div class="card-header"><el-icon><Link /></el-icon><span>快捷操作</span></div>
        </template>
        <div class="links-grid">
          <el-button text type="primary" @click="$router.push('/strategy/aggregation')">
            策略聚合 → 加载最优参数
          </el-button>
          <el-button text type="success" @click="$router.push('/data/manage')">
            数据管理 → 更新行情
          </el-button>
          <el-button text type="warning" @click="$router.push('/strategy/analysis')">
            单策略分析 → 手动验证
          </el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Loading, CircleCheckFilled, WarningFilled, Clock, VideoPlay,
  Setting, DataAnalysis, Timer, Link, Connection, EditPen,
} from '@element-plus/icons-vue'
import { dailyTaskAPI, type DailyTaskStatus } from '@/api/dailyTask'
import { strategyAPI } from '@/api/strategy'

const taskStatus = ref<DailyTaskStatus | null>(null)
const triggering = ref(false)
const emailEnabled = ref(true)
const emailToggling = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// 聚合策略选择 + 手动优化
const allStrategies = ref<string[]>([])
const selectedStrategies = ref<string[]>([])
const aggStockCode = ref('')
const aggRunning = ref(false)
const aggResult = ref<any>(null)

const bannerClass = computed(() => {
  if (taskStatus.value?.is_running) return 'running'
  if (taskStatus.value?.last_run?.status === 'success') return 'success'
  if (taskStatus.value?.last_run?.status === 'failed') return 'failed'
  return 'idle'
})

const lastSuccess = computed(() => taskStatus.value?.last_run?.status === 'success')
const lastFailed = computed(() => taskStatus.value?.last_run?.status === 'failed')

const bannerTitle = computed(() => {
  if (taskStatus.value?.is_running) return '任务执行中...'
  if (lastSuccess.value) return '上次运行成功'
  if (lastFailed.value) return '上次运行失败'
  return '等待首次运行'
})

const bannerDesc = computed(() => {
  if (taskStatus.value?.is_running) {
    const p = taskStatus.value.progress
    return `正在优化 ${p.stock_code || '...'} · ${p.strategy_name || ''}`
  }
  const lr = taskStatus.value?.last_run
  if (lr) return `${lr.time?.slice(0, 19)?.replace('T', ' ')} · 耗时 ${lr.elapsed_seconds?.toFixed(0)}s`
  return `定时 ${fmtTime.value} 每日自动执行`
})

const fmtTime = computed(() => {
  const h = taskStatus.value?.config?.hour ?? 15
  const m = taskStatus.value?.config?.minute ?? 30
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
})

const fmtElapsed = computed(() => {
  const s = taskStatus.value?.last_run?.elapsed_seconds ?? 0
  return s >= 60 ? `${(s / 60).toFixed(1)}min` : `${s.toFixed(0)}s`
})

const fmtProgressElapsed = computed(() => {
  const s = taskStatus.value?.progress?.elapsed ?? 0
  return s >= 60 ? `${(s / 60).toFixed(1)} min` : `${s.toFixed(0)}s`
})

const stockPercent = computed(() => {
  const p = taskStatus.value?.progress
  if (!p || p.stock_total === 0) return 0
  return Math.round((p.stock_index / p.stock_total) * 100)
})

const strategyPercent = computed(() => {
  const p = taskStatus.value?.progress
  if (!p || p.strategy_total === 0) return 0
  return Math.round((p.strategy_index / p.strategy_total) * 100)
})

const loadStatus = async () => {
  try {
    const data = await dailyTaskAPI.getStatus()
    taskStatus.value = data
    emailEnabled.value = data.email_enabled

    // 运行中则启动轮询
    if (data.is_running && !pollTimer) {
      pollTimer = setInterval(loadStatus, 1500)
    } else if (!data.is_running && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch { /* silent */ }
}

const handleTrigger = async () => {
  triggering.value = true
  try {
    await dailyTaskAPI.triggerRun()
    ElMessage.success('优化任务已启动')
    // 立即开始轮询
    setTimeout(loadStatus, 500)
  } catch (e: any) {
    ElMessage.error(e?.message || '触发失败')
  } finally { triggering.value = false }
}

const handleEmailToggle = async (val: boolean) => {
  emailToggling.value = true
  try {
    await dailyTaskAPI.toggleEmail(val)
    ElMessage.success(val ? '邮件通知已开启' : '邮件通知已关闭')
  } catch {
    emailEnabled.value = !val
  } finally { emailToggling.value = false }
}

const loadStrategies = async () => {
  try {
    const res = await strategyAPI.listStrategies()
    allStrategies.value = (res.strategies || []).map((s: any) => s.name)
    const saved = localStorage.getItem('aggregation_selected_strategies')
    selectedStrategies.value = saved ? JSON.parse(saved) : [...allStrategies.value]
  } catch { /* will retry */ }
}

const toggleStrategy = (name: string, val: boolean) => {
  if (val) selectedStrategies.value.push(name)
  else selectedStrategies.value = selectedStrategies.value.filter(s => s !== name)
  localStorage.setItem('aggregation_selected_strategies', JSON.stringify(selectedStrategies.value))
}

const handleAggOptimize = async () => {
  if (!aggStockCode.value) { ElMessage.warning('请输入股票代码'); return }
  aggRunning.value = true; aggResult.value = null
  try {
    aggResult.value = await dailyTaskAPI.optimizeAggregation(
      aggStockCode.value,
      selectedStrategies.value.length ? selectedStrategies.value : undefined,
    )
    ElMessage.success('聚合优化完成，方案已保存')
  } catch (e: any) {
    aggResult.value = { status: 'failed', error: e?.message || '请求失败' }
  } finally { aggRunning.value = false }
}

// ── 参数边界 ──
import { watchlistAPI } from '@/api/watchlist'
const boundsStock = ref('')
const boundsTab = ref('agg')
const boundsStrategy = ref('')
const aggBounds = ref<Record<string, number[]>>({ buy_threshold: [0.3, 0.7], sell_threshold: [0.2, 0.6] })
const strategyBounds = ref<Record<string, Record<string, number[]>>>({})
const savingBounds = ref(false)
const watchlistCodes = ref<Array<{code:string;name:string}>>([])
const strategyBoundsKeys = computed(() => Object.keys(strategyBounds.value))

const loadWatchlist = async () => {
  try {
    const list = await watchlistAPI.getWatchlist()
    watchlistCodes.value = (list || []).map((w:any) => ({ code:w.stock_code||w.code, name:w.stock_name||w.name||'' }))
  } catch { /* silent */ }
}

const loadBounds = async (code: string) => {
  try {
    const data = await dailyTaskAPI.getBounds(code)
    aggBounds.value = data.aggregation_bounds || { buy_threshold: [0.3, 0.7], sell_threshold: [0.2, 0.6] }
    strategyBounds.value = data.strategy_bounds || {}
    boundsStrategy.value = ''
  } catch { /* silent */ }
}

const handleSaveBounds = async () => {
  if (!boundsStock.value) return
  savingBounds.value = true
  try {
    const clean: Record<string, Record<string, number[]>> = {}
    for (const [sn, ps] of Object.entries(strategyBounds.value)) {
      clean[sn] = {}
      for (const [pn, vs] of Object.entries(ps)) {
        clean[sn][pn] = [vs[0], vs[1]]
      }
    }
    await dailyTaskAPI.saveBounds(boundsStock.value, aggBounds.value, clean)
    ElMessage.success('参数边界已保存')
  } catch (e: any) { ElMessage.error(e?.message || '保存失败')
  } finally { savingBounds.value = false }
}

const handleResetBounds = async () => {
  if (!boundsStock.value) return
  try { await dailyTaskAPI.saveBounds(boundsStock.value, {}, {}); loadBounds(boundsStock.value); ElMessage.success('已重置') }
  catch { /* silent */ }
}

onMounted(() => {
  loadStatus()
  loadStrategies()
  loadWatchlist()
})

onUnmounted(() => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})
</script>

<style scoped lang="scss">
.daily-task-page {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.status-banner {
  border-radius: 12px;
  padding: 20px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #fff;

  &.running { background: linear-gradient(135deg, #e6a23c, #d48806); }
  &.success { background: linear-gradient(135deg, #67c23a, #529b2e); }
  &.failed  { background: linear-gradient(135deg, #f56c6c, #c0392b); }
  &.idle    { background: linear-gradient(135deg, #909399, #63666e); }

  .banner-left { display: flex; align-items: center; gap: 14px;
    h3 { margin: 0; font-size: 18px; }
    p { margin: 4px 0 0; font-size: 13px; opacity: .85; }
  }
}

.page-grid {
  display: grid;
  grid-template-columns: 240px 1fr;
  grid-template-rows: auto auto;
  gap: 16px;

  .config-card  { grid-row: 1 / 3; }
  .result-card  { grid-column: 2; }
  .history-card { grid-column: 2; }
  .links-card   { grid-column: 1 / -1; }
  .bounds-card   { grid-column: 1 / -1; }
  .aggregation-card { grid-column: 1 / -1; }

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
    .config-card, .result-card, .history-card, .links-card, .bounds-card, .aggregation-card { grid-column: 1; grid-row: auto; }
  }
}

// ── 实时进度卡 ──
.progress-card {
  border: 1px solid var(--el-color-primary-light-5);
  .progress-section { display: flex; flex-direction: column; gap: 10px; }
  .progress-row { display: flex; align-items: center; gap: 10px; }
  .prog-label { width: 64px; font-size: 13px; color: var(--el-text-color-secondary); flex-shrink: 0; }
  .prog-value { font-size: 14px; }
  .prog-text { font-size: 13px; color: var(--el-text-color-secondary); white-space: nowrap; }
}

.config-item {
  display: flex;
  align-items: center;
  padding: 8px 0;
  .label { color: var(--el-text-color-secondary); width: 64px; font-size: 13px; }
  .value { font-weight: 600; font-size: 15px; }
  .hint { color: var(--el-text-color-placeholder); font-size: 12px; margin-left: 8px; }
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
  gap: 12px;
}

.result-item {
  text-align: center; padding: 12px 8px; border-radius: 10px; background: var(--el-fill-color-light);
  &.signal.active { background: #fef0f0; }
  .num { font-size: 24px; font-weight: 700; display: block; }
  .txt { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
}

.signals-section h4 { margin: 4px 0 8px; font-size: 14px; }

.signal-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--el-border-color-lighter);
  .sig-code { font-weight: 600; width: 70px; }
  .sig-name { color: var(--el-text-color-secondary); font-size: 13px; flex: 1; }
  .sig-strategies { color: var(--el-text-color-placeholder); font-size: 12px; }
}

.card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; }

.strategy-checkboxes {
  display: flex; flex-wrap: wrap; gap: 4px; max-height: 200px; overflow-y: auto;
  :deep(.el-checkbox) { margin-right: 0; }
}

.aggregation-card {
  grid-column: 2;
  @media (max-width: 768px) { grid-column: 1; }
}

.links-grid { display: flex; flex-wrap: wrap; gap: 16px; }

// ── 边界配置 ──
.bounds-card { .config-item { padding: 4px 0; } }

.bounds-row {
  display: flex; align-items: center; gap: 6px; padding: 4px 0;
  .bound-label { width: 120px; font-size: 13px; color: var(--el-text-color-secondary); }
  .bound-sep { color: var(--el-text-color-placeholder); }
}
</style>
