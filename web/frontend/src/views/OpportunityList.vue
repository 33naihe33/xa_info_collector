<!-- web/frontend/src/views/OpportunityList.vue -->
<template>
  <div>
    <!-- 条线入口卡片视图 -->
    <transition name="fade" mode="out-in">
      <div v-if="!selectedLine" key="overview">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <div>
            <h2 style="margin: 0; display: inline-block;">商机总览</h2>
            <el-tag v-if="stats" style="margin-left: 12px;" type="info">
              共 {{ stats.total }} 条
            </el-tag>
          </div>
          <el-button type="warning" :icon="MagicStick" :loading="analyzing" @click="handleAnalyze">
            LLM 分析
          </el-button>
        </div>

        <div class="line-grid">
          <!-- 领导调研入口（放在最前面）-->
          <el-card
            shadow="hover"
            class="line-card"
            :body-style="{ padding: '20px' }"
            :style="{ borderLeftColor: '#9b59b6', borderLeftWidth: '4px', borderLeftStyle: 'solid' }"
            @click="goLeadership"
          >
            <div class="line-card-body">
              <el-icon :size="32" :color="'#9b59b6'" class="line-icon">
                <Star />
              </el-icon>
              <div class="line-info">
                <div class="line-name">领导调研</div>
                <el-tag size="small" type="info" effect="plain" round>
                  {{ leadershipCount }} 条
                </el-tag>
              </div>
            </div>
          </el-card>

          <el-card
            v-for="(meta, line) in lineMeta" :key="line"
            shadow="hover"
            class="line-card"
            :body-style="{ padding: '20px' }"
            :style="{ borderLeftColor: meta.color, borderLeftWidth: '4px', borderLeftStyle: 'solid' }"
            @click="enterLine(line)"
          >
            <div class="line-card-body">
              <el-icon :size="32" :color="meta.color" class="line-icon">
                <component :is="meta.icon" />
              </el-icon>
              <div class="line-info">
                <div class="line-name">{{ meta.label }}</div>
                <el-tag size="small" type="info" effect="plain" round>
                  {{ lineCount(line) }} 条
                </el-tag>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <!-- 单条线商机列表视图 -->
      <div v-else key="line-list">
        <div style="display: flex; align-items: center; margin-bottom: 16px;">
          <el-button :icon="ArrowLeft" @click="backToOverview">返回</el-button>
          <h2 style="margin: 0 0 0 12px; display: inline-flex; align-items: center; gap: 8px;">
            <el-icon :color="lineMeta[selectedLine].color">
              <component :is="lineMeta[selectedLine].icon" />
            </el-icon>
            {{ lineMeta[selectedLine].label }}
            <el-tag type="info">共 {{ total }} 条</el-tag>
          </h2>
        </div>

        <!-- 优先级筛选 -->
        <div style="display: flex; gap: 12px; margin-bottom: 16px;">
          <el-select v-model="filterPriority" placeholder="全部优先级" clearable style="width: 150px;" @change="onFilterChange">
            <el-option label="critical" value="critical" />
            <el-option label="high" value="high" />
            <el-option label="medium" value="medium" />
            <el-option label="low" value="low" />
          </el-select>
        </div>

        <!-- 商机卡片列表 -->
        <div v-loading="loading">
          <el-card
            v-for="opp in opportunities" :key="opp.id"
            shadow="hover" style="margin-bottom: 12px; cursor: pointer;"
            @click="openDetail(opp)"
          >
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
              <el-tag :type="priorityTag(opp.priority)" size="small" effect="dark">
                {{ opp.priority }}
              </el-tag>
              <el-tag size="small">{{ lineMeta[opp.business_line]?.label || opp.business_line }}</el-tag>
              <el-tag size="small" type="info">{{ opp.opp_type }}</el-tag>
              <span style="font-size: 12px; color: #909399; margin-left: auto;">{{ opp.publish_date }}</span>
            </div>
            <h3 style="margin: 0 0 8px 0; font-size: 16px;">{{ opp.title }}</h3>
            <div v-if="opp.fin_scale" style="font-size: 13px; color: #e6a23c; margin-bottom: 4px;">
              预估规模: {{ opp.fin_scale }}
            </div>
            <div v-if="opp.fin_products?.length" style="font-size: 13px; margin-bottom: 4px;">
              适配产品:
              <el-tag v-for="p in opp.fin_products" :key="p" size="small" style="margin: 0 2px;">{{ p }}</el-tag>
            </div>
            <p v-if="opp.insight" style="font-size: 13px; color: #606266; margin: 4px 0;">
              💡 {{ opp.insight }}
            </p>
          </el-card>
          <el-empty v-if="!loading && opportunities.length === 0" description="该条线暂无商机" />
        </div>

        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          style="margin-top: 16px; justify-content: center;"
          @current-change="fetchData"
        />
      </div>
    </transition>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="selected?.title || ''" size="50%">
      <div v-if="selected" style="line-height: 1.8;">
        <p><strong>业务条线：</strong>{{ lineMeta[selected.business_line]?.label || selected.business_line }}</p>
        <p><strong>商机类型：</strong>{{ selected.opp_type }}</p>
        <p><strong>优先级：</strong>
          <el-tag :type="priorityTag(selected.priority)" size="small" effect="dark">{{ selected.priority }}</el-tag>
        </p>
        <p v-if="selected.fin_scale"><strong>预估规模：</strong>{{ selected.fin_scale }}</p>
        <p v-if="selected.target_client"><strong>目标客户：</strong>{{ selected.target_client }}</p>
        <p v-if="selected.fin_products?.length">
          <strong>适配产品：</strong>
          <el-tag v-for="p in selected.fin_products" :key="p" size="small" style="margin: 0 2px;">{{ p }}</el-tag>
        </p>
        <el-divider />
        <p v-if="selected.trigger_event"><strong>触发事件：</strong>{{ selected.trigger_event }}</p>
        <p v-if="selected.insight"><strong>金融解读：</strong>{{ selected.insight }}</p>
        <p v-if="selected.action_suggest"><strong>建议行动：</strong>{{ selected.action_suggest }}</p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { markRaw } from 'vue'
import { useRouter } from 'vue-router'
import {
  MagicStick, ArrowLeft,
  OfficeBuilding, User, Setting,
  Cpu, Flag, Warning, Star,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { apiClient, type OpportunityItem, type OpportunityStats } from '../api/client'

const router = useRouter()

interface LineMeta {
  label: string
  color: string
  icon: ReturnType<typeof markRaw>
}

const lineMeta: Record<string, LineMeta> = {
  corporate:      { label: '对公+跨境+普惠', color: '#409eff', icon: markRaw(OfficeBuilding) },
  retail:         { label: '对私（个人金融）', color: '#e67e22', icon: markRaw(User) },
  operations:     { label: '营运+数币',   color: '#95a5a6', icon: markRaw(Setting) },
  fintech:        { label: '金融科技',   color: '#1abc9c', icon: markRaw(Cpu) },
  synergy:        { label: '综合条线',   color: '#f39c12', icon: markRaw(Flag) },
  risk_control:   { label: '风控条线',   color: '#e74c3c', icon: markRaw(Warning) },
}

const opportunities = ref<OpportunityItem[]>([])
const total = ref(0)
const stats = ref<OpportunityStats | null>(null)
const leadershipCount = ref(0)
const loading = ref(false)
const analyzing = ref(false)
const page = ref(1)
const pageSize = 20
const selectedLine = ref<string | null>(null)
const filterPriority = ref<string | undefined>(undefined)
const drawerVisible = ref(false)
const selected = ref<OpportunityItem | null>(null)

function lineCount(line: string): number {
  return stats.value?.by_line?.[line] || 0
}

function priorityTag(priority: string) {
  const map: Record<string, string> = {
    critical: 'danger', high: 'danger', medium: 'warning', low: 'info'
  }
  return map[priority] || 'info'
}

function enterLine(line: string) {
  selectedLine.value = line
  page.value = 1
  filterPriority.value = undefined
  fetchData()
  fetchStats()
}

// F-19：筛选变化时重置页码到 1（避免在 page>1 时用旧 offset 导致空结果）
function onFilterChange() {
  page.value = 1
  fetchData()
}

function backToOverview() {
  selectedLine.value = null
  opportunities.value = []
  total.value = 0
  fetchStats()
}

async function fetchData() {
  if (!selectedLine.value) return
  loading.value = true
  try {
    const resp = await apiClient.getOpportunities({
      business_line: selectedLine.value,
      priority: filterPriority.value,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    opportunities.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  const resp = await apiClient.getOpportunityStats()
  stats.value = resp.data
  try {
    const lv = await apiClient.getLeadershipStats()
    leadershipCount.value = lv.data.total
  } catch {
    leadershipCount.value = 0
  }
}

function goLeadership() {
  router.push('/leadership')
}

async function openDetail(opp: OpportunityItem) {
  const resp = await apiClient.getOpportunity(opp.id)
  selected.value = resp.data
  drawerVisible.value = true
}

async function handleAnalyze() {
  analyzing.value = true
  try {
    await apiClient.triggerAnalyze()
    ElMessage.success('分析任务已启动')
    setTimeout(async () => {
      await fetchStats()
      if (selectedLine.value) {
        await fetchData()
      }
      analyzing.value = false
    }, 10000)
  } catch {
    analyzing.value = false
    ElMessage.error('启动分析失败')
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.line-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
@media (max-width: 992px) {
  .line-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .line-grid { grid-template-columns: 1fr; }
}
.line-card {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.line-card:hover {
  transform: translateY(-2px);
}
.line-card-body {
  display: flex;
  align-items: center;
  gap: 16px;
}
.line-icon {
  flex-shrink: 0;
}
.line-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.line-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
