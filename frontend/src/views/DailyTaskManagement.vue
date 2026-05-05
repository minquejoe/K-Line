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
          <el-time-picker
            v-model="configTime"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="选择时间"
            size="small"
            style="width:120px"
          />
          <el-button size="small" type="primary" @click="handleSaveConfig" :loading="savingConfig" style="margin-left:8px">保存</el-button>
        </div>
        <div class="config-item">
          <span class="label">优化周期</span>
          <span class="value">6 个月</span>
        </div>
        <div class="config-item">
          <span class="label">并行线程</span>
          <span class="value">自动</span>
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
      </el-card>

      <!-- 右栏上半：聚合优化 -->
      <el-card class="aggregation-card">
        <template #header>
          <div class="card-header"><el-icon><Connection /></el-icon><span>一键聚合优化</span></div>
        </template>
        <div class="kv-row">
          <span>目标股票</span>
          <el-select v-model="aggStockCode" placeholder="从收藏选择" filterable size="small" style="width:200px">
            <el-option v-for="c in watchlistCodes" :key="c.code" :label="`${c.code} ${c.name}`" :value="c.code" />
          </el-select>
        </div>
        <el-button type="success" :loading="aggRunning" :disabled="aggRunning" @click="handleAggOptimize" style="margin-top:8px;width:100%">
          <el-icon><VideoPlay /></el-icon> {{ aggRunning ? '聚合优化运行中...' : '运行聚合优化' }}
        </el-button>
        <div v-if="aggResult" class="agg-result" :class="aggResult.status">
          <template v-if="aggResult.status==='success'">
            ✅ Sharpe={{ aggResult.best_sharpe?.toFixed(3) }} · Buy={{ aggResult.buy_threshold }} · Sell={{ aggResult.sell_threshold }}
          </template>
          <template v-else>❌ {{ aggResult.error }}</template>
        </div>
      </el-card>

      <!-- 右栏下半：运行结果 -->
      <el-card class="result-card">
        <template #header>
          <div class="card-header"><el-icon><DataAnalysis /></el-icon><span>运行结果</span></div>
        </template>
        <el-tabs v-model="resultTab" size="small">
          <el-tab-pane label="自动运行" name="auto">
            <template v-if="taskStatus?.run_history?.length">
              <div v-for="r in taskStatus.run_history.slice(0,3)" :key="r.time" class="log-mini">
                <span>{{ r.time?.slice(0,19)?.replace('T',' ') }}</span>
                <el-tag :type="r.status==='success'?'success':'danger'" size="small">{{ r.status==='success'?'成功':'失败' }}</el-tag>
                <span class="hint">{{ r.elapsed_seconds?.toFixed(0) }}s · {{ r.stocks_scanned }}只 · {{ r.buy_signals || 0 }}信号</span>
              </div>
              <div class="log-mini" v-if="taskStatus.run_history.length > 3">
                <span class="hint">... 更多 见下方运行历史表</span>
              </div>
            </template>
            <div v-else class="hint">暂无自动运行记录</div>
          </el-tab-pane>
          <el-tab-pane label="手动运行" name="manual">
            <template v-if="taskStatus?.manual_history?.length">
              <div v-for="r in taskStatus.manual_history.slice(0,5)" :key="r.time" class="log-mini">
                <span>{{ r.time?.slice(0,19)?.replace('T',' ') }}</span>
                <el-tag :type="r.status==='success'?'success':'danger'" size="small">{{ r.status==='success'?'success':'fail' }}</el-tag>
                <span class="hint">{{ r.elapsed_seconds?.toFixed(0) }}s · {{ r.stocks_scanned }}只</span>
              </div>
            </template>
            <div v-else class="hint">暂无手动运行记录</div>
          </el-tab-pane>
          <el-tab-pane label="邮件" name="mail">
            <div class="log-mini"><span>状态</span><el-tag :type="emailEnabled?'success':'info'" size="small">{{ emailEnabled ? '已开启' : '已关闭' }}</el-tag></div>
            <div class="log-mini"><span>收件人 </span><span>{{ taskStatus?.email_info?.recipient || '-' }}</span></div>
            <div class="log-mini"><span>SMTP </span><span class="hint">{{ taskStatus?.email_info?.smtp_host }}:{{ taskStatus?.email_info?.smtp_port }}</span></div>
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <!-- 全宽：边界配置 -->
      <el-card class="bounds-card">
        <template #header>
          <div class="card-header"><el-icon><EditPen /></el-icon><span>参数边界配置</span></div>
        </template>
        <div class="bounds-header">
          <span>股票</span>
          <el-select v-model="boundsStock" placeholder="选股票" filterable size="small" style="width:200px" @change="loadBounds">
            <el-option v-for="c in watchlistCodes" :key="c.code" :label="`${c.code} ${c.name}`" :value="c.code" />
          </el-select>
          <template v-if="boundsStock">
            <el-button size="small" type="primary" :loading="savingBounds" @click="handleSaveBounds">保存</el-button>
            <el-button size="small" @click="handleResetBounds">重置默认</el-button>
          </template>
        </div>
        <el-tabs v-if="boundsStock" v-model="boundsTab" size="small" style="margin-top:4px">
          <el-tab-pane label="聚合参数" name="agg">
            <div class="bounds-grid">
              <div v-for="(v,k) in aggBounds" :key="k" class="bounds-item">
                <label>{{ k }}</label>
                <el-input-number v-model="aggBounds[k][0]" :min="0" :max="1" :step="0.05" :precision="2" size="small" controls-position="right" style="width:100px" />
                <span>~</span>
                <el-input-number v-model="aggBounds[k][1]" :min="0" :max="1" :step="0.05" :precision="2" size="small" controls-position="right" style="width:100px" />
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="单策略参数" name="strat">
            <el-select v-model="boundsStrategy" placeholder="选策略" size="small" style="width:220px;margin-bottom:8px" filterable clearable>
              <el-option v-for="s in strategyBoundsKeys" :key="s" :label="s" :value="s" />
            </el-select>
            <div v-if="boundsStrategy && strategyBounds[boundsStrategy]" class="bounds-grid">
              <div v-for="(v,k) in strategyBounds[boundsStrategy]" :key="k" class="bounds-item">
                <label>{{ k }}</label>
                <el-input-number v-model="strategyBounds[boundsStrategy][k][0]" :step="v[0] < 1 ? 0.05 : 1" :precision="v[0] < 1 ? 2 : 0" size="small" controls-position="right" style="width:100px" />
                <span>~</span>
                <el-input-number v-model="strategyBounds[boundsStrategy][k][1]" :step="v[1] < 1 ? 0.05 : 1" :precision="v[1] < 1 ? 2 : 0" size="small" controls-position="right" style="width:100px" />
              </div>
            </div>
            <el-empty v-else-if="boundsStrategy" description="该策略无参数" :image-size="40" />
          </el-tab-pane>
        </el-tabs>
        <el-empty v-if="!boundsStock" description="选择股票后编辑参数边界" :image-size="40" />
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
const configTime = ref('15:30')
const savingConfig = ref(false)
const resultTab = ref('auto')

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
    const h = String(data.config?.hour ?? 15).padStart(2, '0')
    const m = String(data.config?.minute ?? 30).padStart(2, '0')
    configTime.value = `${h}:${m}`

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

const handleSaveConfig = async () => {
  if (!configTime.value) return
  const [h, m] = configTime.value.split(':').map(Number)
  savingConfig.value = true
  try {
    await dailyTaskAPI.updateConfig(h, m)
    ElMessage.success(`每日任务时间已更新为 ${configTime.value}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally { savingConfig.value = false }
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
const aggBounds = ref<Record<string, number[]>>({ buy_threshold: [0.3, 0.7], sell_threshold: [0.2, 0.6], strategy_weight: [0.1, 2.0] })
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
  gap: 12px;
}

.status-banner {
  border-radius: 12px;
  padding: 16px 20px;
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
  grid-template-columns: 260px 1fr;
  gap: 12px;

  .config-card  { grid-row: 1 / 3; }
  .aggregation-card { grid-column: 2; grid-row: 1; }
  .result-card  { grid-column: 2; grid-row: 2; }
  .bounds-card  { grid-column: 1 / -1; }
  .history-card { grid-column: 1 / -1; }

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
    .config-card, .aggregation-card, .result-card, .bounds-card, .history-card { grid-column: 1; grid-row: auto; }
  }
}

// ── 实时进度卡 ──
.progress-card {
  border: 1px solid var(--el-color-primary-light-5);
  .progress-section { display: flex; flex-direction: column; gap: 8px; }
  .progress-row { display: flex; align-items: center; gap: 10px; }
  .prog-label { font-size: 13px; color: var(--el-text-color-secondary); flex-shrink: 0; white-space: nowrap; }
  .prog-value { font-size: 14px; }
  .prog-text { font-size: 13px; color: var(--el-text-color-secondary); white-space: nowrap; }
}

.config-item { display: flex; align-items: center; padding: 6px 0; gap: 8px;
  .label { color: var(--el-text-color-secondary); font-size: 13px; white-space: nowrap; min-width: 64px; }
  .value { font-weight: 600; font-size: 15px; }
  .hint { color: var(--el-text-color-placeholder); font-size: 12px; margin-left: 8px; }
}

.kv-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; font-size: 13px; color: var(--el-text-color-secondary);
  & > span:first-child { white-space: nowrap; min-width: 56px; }
  b { color: var(--el-text-color-primary); }
}

.strategy-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px; margin-top: 8px; font-size: 12px; }

.agg-result { margin-top: 8px; padding: 8px 10px; border-radius: 6px; font-size: 13px;
  &.success { background: #f0f9eb; color: #67c23a; }
  &.failed  { background: #fef0f0; color: #f56c6c; }
}

.result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 12px; }
.result-item { text-align: center; padding: 12px 8px; border-radius: 10px; background: var(--el-fill-color-light);
  &.active { background: #fef0f0; }
  .num { font-size: 24px; font-weight: 700; display: block; }
  .txt { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
}

.card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; }

// ── 边界配置 ──
.bounds-header { display: flex; align-items: center; gap: 10px; padding-bottom: 8px;
  & > span { font-size: 13px; color: var(--el-text-color-secondary); }
}
.bounds-grid { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.bounds-item { display: flex; align-items: center; gap: 6px; padding: 3px 0;
  label { font-size: 13px; color: var(--el-text-color-secondary); min-width: 130px; white-space: nowrap; }
}

// ── 结果Tab迷你日志 ──
.log-mini { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px;
  & > span:first-child { color: var(--el-text-color-secondary); white-space: nowrap; }
}
</style>
