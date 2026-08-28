<!-- web/frontend/src/views/mobile/MobileReports.vue -->
<template>
  <div class="m-reports">
    <div v-loading="loading">
      <div v-for="report in reports" :key="report.id" class="report-card" @click="openReport(report)">
        <div class="report-header">
          <el-tag size="small">{{ typeLabel(report.report_type) }}</el-tag>
          <span class="report-date">{{ report.period_start }} ~ {{ report.period_end }}</span>
        </div>
        <h3 class="report-title">{{ report.content?.title || '未命名报告' }}</h3>
        <p class="report-summary">{{ report.content?.summary?.slice(0, 80) }}</p>
        <div class="report-meta">
          <span>{{ report.content?.stats?.total || 0 }} 条商机</span>
          <span>{{ report.generated_at?.slice(0, 10) }}</span>
        </div>
      </div>
      <el-empty v-if="!loading && reports.length === 0" description="暂无报告" />
    </div>

    <el-drawer v-model="detailVisible" :title="selected?.content?.title || '报告详情'" size="90%" direction="btt">
      <div v-if="selected" class="report-detail">
        <p class="summary">{{ selected.content?.summary }}</p>
        <div v-for="(section, i) in selected.content?.sections" :key="i">
          <h4>{{ section.line }}</h4>
          <div v-for="(opp, j) in section.opportunities" :key="j" class="section-opp">
            <p>
              <strong>{{ j + 1 }}. {{ opp.title }}</strong>
              <span v-if="opp.publish_date" class="meta" style="margin-left: 6px;">发布时间：{{ opp.publish_date?.slice(0, 10) }}</span>
              <span v-if="opp.visit_date" class="meta" style="margin-left: 6px;">调研时间：{{ opp.visit_date?.slice(0, 10) }}</span>
            </p>
            <p v-if="opp.summary" class="meta">摘要：{{ opp.summary }}</p>
          </div>
        </div>
        <div v-if="selected.content?.recommendations">
          <h4>重点关注</h4>
          <p>{{ selected.content.recommendations }}</p>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiClient, type ReportItem } from '../../api/client'

const reports = ref<ReportItem[]>([])
const loading = ref(false)
const detailVisible = ref(false)
const selected = ref<ReportItem | null>(null)

function typeLabel(t: string) {
  return ({ daily: '日报', weekly: '周报', monthly: '月报' } as Record<string, string>)[t] || t
}

async function fetchReports() {
  loading.value = true
  try {
    const resp = await apiClient.getReports()
    reports.value = resp.data.items
  } finally {
    loading.value = false
  }
}

function openReport(report: ReportItem) {
  selected.value = report
  detailVisible.value = true
}

onMounted(() => fetchReports())
</script>

<style scoped>
.m-reports { padding: 0 12px; }
.report-card {
  background: #fff; border-radius: 8px; padding: 12px;
  margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); cursor: pointer;
}
.report-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.report-date { font-size: 11px; color: #909399; }
.report-title { margin: 0 0 4px 0; font-size: 15px; }
.report-summary { font-size: 13px; color: #606266; margin: 0 0 6px 0; }
.report-meta { display: flex; justify-content: space-between; font-size: 11px; color: #909399; }
.report-detail { padding: 0 16px 16px; line-height: 1.8; }
.summary { font-size: 14px; color: #303133; }
.section-opp { margin-bottom: 10px; padding: 8px; background: #f5f7fa; border-radius: 4px; }
.meta { font-size: 13px; color: #606266; margin: 2px 0; }
</style>
