<!-- web/frontend/src/views/mobile/MobileOpportunities.vue -->
<template>
  <div class="m-opp">
    <!-- 筛选标签 -->
    <div class="filter-bar">
      <el-tabs v-model="activeTab" @tab-change="fetchData">
        <el-tab-pane label="今日" name="today" />
        <el-tab-pane label="本周" name="week" />
        <el-tab-pane label="全部" name="all" />
      </el-tabs>
    </div>

    <!-- 商机卡片流 -->
    <div v-loading="loading" style="min-height: 200px;">
      <div v-for="opp in opportunities" :key="opp.id"
        class="opp-card" @click="openDetail(opp)">
        <div class="opp-header">
          <el-tag :type="priorityTag(opp.priority)" size="small" effect="dark">
            {{ opp.priority }}
          </el-tag>
          <el-tag size="small" type="info">{{ lineLabel(opp.business_line) }}</el-tag>
          <span class="opp-date">{{ opp.publish_date?.slice(5) }}</span>
        </div>
        <h3 class="opp-title">{{ opp.title }}</h3>
        <div v-if="opp.fin_scale" class="opp-scale">规模: {{ opp.fin_scale }}</div>
        <div v-if="opp.fin_products?.length" class="opp-products">
          <el-tag v-for="p in opp.fin_products.slice(0, 3)" :key="p" size="small">{{ p }}</el-tag>
        </div>
        <p v-if="opp.insight" class="opp-insight">💡 {{ opp.insight?.slice(0, 60) }}...</p>
      </div>
      <el-empty v-if="!loading && opportunities.length === 0" description="暂无商机" />
    </div>

    <div v-if="hasMore" style="text-align: center; padding: 16px;">
      <el-button text @click="loadMore">加载更多</el-button>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="selected?.title || ''" size="85%" direction="btt">
      <div v-if="selected" class="detail-content">
        <div class="detail-tags">
          <el-tag :type="priorityTag(selected.priority)" effect="dark">{{ selected.priority }}</el-tag>
          <el-tag>{{ lineLabel(selected.business_line) }}</el-tag>
          <el-tag type="info">{{ selected.opp_type }}</el-tag>
        </div>
        <p v-if="selected.fin_scale"><strong>预估规模：</strong>{{ selected.fin_scale }}</p>
        <p v-if="selected.target_client"><strong>目标客户：</strong>{{ selected.target_client }}</p>
        <div v-if="selected.fin_products?.length">
          <strong>适配产品：</strong>
          <el-tag v-for="p in selected.fin_products" :key="p" size="small" style="margin: 2px;">{{ p }}</el-tag>
        </div>
        <el-divider />
        <p v-if="selected.trigger_event"><strong>触发事件：</strong>{{ selected.trigger_event }}</p>
        <p v-if="selected.insight"><strong>金融解读：</strong>{{ selected.insight }}</p>
        <p v-if="selected.action_suggest"><strong>建议行动：</strong>{{ selected.action_suggest }}</p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { apiClient, type OpportunityItem } from '../../api/client'

const PRIORITY_TAGS: Record<string, string> = {
  critical: 'danger', high: 'danger', medium: 'warning', low: 'info',
}
const LINE_LABELS: Record<string, string> = {
  corporate: '对公',
  retail: '对私',
  operations: '营运',
  fintech: '科技',
  synergy: '综合',
  risk_control: '风控',
}

const opportunities = ref<OpportunityItem[]>([])
const loading = ref(false)
const activeTab = ref('all')
const page = ref(1)
const total = ref(0)
const detailVisible = ref(false)
const selected = ref<OpportunityItem | null>(null)

const hasMore = computed(() => opportunities.value.length < total.value)

function priorityTag(p: string) { return PRIORITY_TAGS[p] || 'info' }
function lineLabel(l: string) { return LINE_LABELS[l] || l }

// F-13 / M-06：根据 activeTab 计算 date_from/date_to（本地时间，非 UTC）
function dateRangeForTab() {
  // M-06: 用本地年月日格式化（原 toISOString 用 UTC，凌晨会取前一天）
  const fmt = (d: Date) => {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  const today = new Date()
  if (activeTab.value === 'today') {
    return { date_from: fmt(today), date_to: fmt(today) }
  } else if (activeTab.value === 'week') {
    // M-06: 本周 = 周一至今天（原 today-7 含 8 天）
    const day = today.getDay()  // 0=周日, 1=周一...
    const monday = new Date(today)
    const offset = day === 0 ? 6 : day - 1  // 回到周一
    monday.setDate(today.getDate() - offset)
    return { date_from: fmt(monday), date_to: fmt(today) }
  }
  return {}  // all：不传日期
}

async function fetchData() {
  loading.value = true
  page.value = 1
  try {
    const resp = await apiClient.getOpportunities({ limit: 20, offset: 0, ...dateRangeForTab() })
    opportunities.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  page.value++
  const resp = await apiClient.getOpportunities({ limit: 20, offset: (page.value - 1) * 20, ...dateRangeForTab() })
  opportunities.value.push(...resp.data.items)
}

async function openDetail(opp: OpportunityItem) {
  const resp = await apiClient.getOpportunity(opp.id)
  selected.value = resp.data
  detailVisible.value = true
}

onMounted(() => fetchData())
</script>

<style scoped>
.m-opp { padding: 0 12px; }
.filter-bar { margin-bottom: 8px; }
.opp-card {
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  cursor: pointer;
}
.opp-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.opp-date { margin-left: auto; font-size: 11px; color: #909399; }
.opp-title { margin: 0 0 6px 0; font-size: 15px; line-height: 1.4; }
.opp-scale { font-size: 13px; color: #e6a23c; margin-bottom: 4px; }
.opp-products { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px; }
.opp-insight { font-size: 12px; color: #606266; margin: 4px 0 0 0; }
.detail-content { padding: 0 16px 16px; line-height: 1.8; }
.detail-tags { display: flex; gap: 6px; margin-bottom: 12px; }
</style>
