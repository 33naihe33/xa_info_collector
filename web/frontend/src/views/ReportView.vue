<!-- web/frontend/src/views/ReportView.vue -->
<template>
  <div>
    <h2 style="margin: 0 0 16px 0;">报告管理</h2>

    <!-- 条线短结论预览 -->
    <el-card shadow="never" style="margin-bottom: 16px;">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong>条线商机速览</strong>
          <div style="display: flex; align-items: center; gap: 8px;">
            <el-date-picker v-model="briefDateRange" type="daterange" size="small"
              value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束"
              style="width: 220px;" />
            <el-button type="primary" size="small" :loading="briefLoading" @click="handleGenerateBriefs">
              生成速览
            </el-button>
          </div>
        </div>
      </template>

      <div v-if="lineBriefs.length > 0" v-loading="briefLoading">
        <!-- 导出工具栏 -->
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 8px 12px; background: #f5f7fa; border-radius: 4px;">
          <el-checkbox v-model="briefSelectAll" :indeterminate="briefSelectIndeterminate" @change="handleSelectAll">
            全选
          </el-checkbox>
          <span style="font-size: 12px; color: #909399;">已选 {{ selectedCount }} 条</span>
          <el-button size="small" type="success" :icon="Download" :disabled="selectedCount === 0"
            @click="handleExportImage">
            导出图片
          </el-button>
        </div>

        <div v-for="b in lineBriefs" :key="b.line" style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
            <el-tag :color="lineColor(b.line)" style="color: #fff;" size="small">
              {{ b.label }}
            </el-tag>
            <span style="font-size: 12px; color: #909399;">{{ b.count }}条商机</span>
            <el-button text size="small" @click="handleSelectLine(b)">选中本条线</el-button>
          </div>
          <div v-for="(item, idx) in b.items" :key="`${b.line}-${idx}`"
            style="padding: 6px 0 6px 16px; border-left: 2px solid #ebeef5; margin-left: 4px;">
            <div style="display: flex; align-items: center; gap: 6px;">
              <el-checkbox :model-value="isBriefSelected(b.line, idx)" size="small"
                @change="toggleBriefSelect(b.line, idx)" />
              <el-tag :type="priorityTag(item.priority)" size="small" effect="plain">{{ item.priority }}</el-tag>
              <span style="font-size: 11px; color: #c0c4cc; margin-left: auto;">{{ item.publish_date?.slice(5) }}</span>
            </div>
            <p style="margin: 4px 0 0 28px; font-size: 13px; color: #303133; line-height: 1.6;">
              {{ item.clue }}
            </p>
            <p v-if="item.source_url" style="margin: 2px 0 0 28px; font-size: 12px;">
              <span style="color: #909399;">信息来源：</span>
              <a :href="item.source_url" target="_blank" rel="noopener"
                style="color: #0563C1; text-decoration: underline;">
                {{ item.source_name || '查看原文' }}
              </a>
            </p>
          </div>
        </div>
      </div>
      <el-empty v-else description="选择时间范围后点击「生成速览」，快速浏览各条线商机动态" :image-size="50" />
    </el-card>

    <!-- 生成参数 -->
    <el-card shadow="never" style="margin-bottom: 16px;">
      <template #header><strong>生成完整报告</strong></template>
      <el-form :inline="true">
        <el-form-item label="类型">
          <el-select v-model="form.reportType" style="width: 100px;">
            <el-option label="日报" value="daily" />
            <el-option label="周报" value="weekly" />
            <el-option label="月报" value="monthly" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker v-model="dateRange" type="daterange"
            value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束"
            style="width: 260px;" />
        </el-form-item>
        <el-form-item label="条线">
          <el-checkbox-group v-model="form.lines" style="display: inline-flex; flex-wrap: wrap; gap: 4px;">
            <el-checkbox v-for="l in allLines" :key="l.value" :label="l.value">{{ l.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="generating" @click="handleGenerate">
            生成报告
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 报告预览 -->
    <el-card v-if="previewContent" shadow="never" style="margin-bottom: 16px;">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong>{{ previewContent.title }}</strong>
          <div>
            <el-button size="small" type="success" @click="handleExportCurrent">
              导出 Word
            </el-button>
          </div>
        </div>
      </template>
      <div style="line-height: 1.8;">
        <p><strong>本期概要：</strong>{{ previewContent.summary }}</p>
        <p v-if="previewContent.stats">
          <strong>商机总数：</strong>{{ previewContent.stats.total }}
        </p>
        <el-divider />
        <div v-for="(section, i) in previewContent.sections" :key="i">
          <h3>{{ section.line }}（{{ section.opportunities?.length || 0 }}条）</h3>
          <div v-for="(opp, j) in section.opportunities" :key="j"
            style="margin-bottom: 12px; padding: 8px; background: #f5f7fa; border-radius: 4px;">
            <p style="margin: 0;">
              <strong>{{ j + 1 }}. {{ opp.title }}</strong>
              <el-tag v-if="opp.priority" :type="priorityTag(opp.priority)" size="small" effect="dark" style="margin-left: 6px;">
                {{ opp.priority }}
              </el-tag>
              <span v-if="opp.publish_date" style="margin-left: 8px; font-size: 12px; color: #909399;">
                发布时间：{{ opp.publish_date?.slice(0, 10) }}
              </span>
              <span v-if="opp.visit_date" style="margin-left: 8px; font-size: 12px; color: #909399;">
                调研时间：{{ opp.visit_date?.slice(0, 10) }}
              </span>
            </p>
            <p v-if="opp.summary" style="margin: 4px 0; font-size: 13px;">摘要：{{ opp.summary }}</p>
            <p v-if="opp.source_url" style="margin: 4px 0; font-size: 12px;">
              <span style="color: #909399;">信息来源：</span>
              <a :href="opp.source_url" target="_blank" rel="noopener"
                style="color: #0563C1; text-decoration: underline;">
                {{ opp.source_name || '查看原文' }}
              </a>
            </p>
          </div>
        </div>
        <div v-if="previewContent.recommendations">
          <h3>重点关注与建议</h3>
          <p>{{ previewContent.recommendations }}</p>
        </div>
      </div>
    </el-card>

    <!-- 历史报告 -->
    <el-card shadow="never">
      <template #header><strong>历史报告</strong></template>
      <el-table :data="reports" v-loading="loading">
        <el-table-column prop="report_type" label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ typeLabel(row.report_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间范围" width="200">
          <template #default="{ row }">{{ row.period_start }} ~ {{ row.period_end }}</template>
        </el-table-column>
        <el-table-column prop="generated_at" label="生成时间" width="200">
          <template #default="{ row }">{{ formatTime(row.generated_at) }}</template>
        </el-table-column>
        <el-table-column label="商机数" width="80">
          <template #default="{ row }">{{ row.content?.stats?.total || row.opportunity_ids?.length || 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="handlePreview(row)">预览</el-button>
            <el-button size="small" type="success" @click="handleExportExisting(row)">导出</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { apiClient, type ReportItem, type ReportContent, type LineBrief } from '../api/client'

const allLines = [
  { value: 'corporate', label: '对公+跨境+普惠' },
  { value: 'retail', label: '对私' },
  { value: 'operations', label: '营运' },
  { value: 'fintech', label: '科技' },
  { value: 'synergy', label: '综合' },
  { value: 'risk_control', label: '风控' },
]

const lineColors: Record<string, string> = {
  corporate: '#409eff', retail: '#e67e22', operations: '#95a5a6',
  fintech: '#1abc9c', synergy: '#f39c12', risk_control: '#e74c3c',
}
function priorityTag(priority: string) {
  const map: Record<string, string> = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info' }
  return map[priority] || 'info'
}

function lineColor(line: string) {
  return lineColors[line] || '#909399'
}

const form = ref({
  reportType: 'weekly',
  lines: [] as string[],
})
const dateRange = ref<[string, string] | null>(null)
const briefDateRange = ref<[string, string] | null>(null)
const generating = ref(false)
const briefLoading = ref(false)
const loading = ref(false)
const previewContent = ref<ReportContent | null>(null)
const previewReportId = ref<number | null>(null)
const reports = ref<ReportItem[]>([])
const lineBriefs = ref<LineBrief[]>([])

// 速览勾选状态
const selectedBriefKeys = ref<Set<string>>(new Set())
const briefSelectAll = ref(false)
const briefSelectIndeterminate = computed(() => {
  const total = lineBriefs.value.reduce((sum, b) => sum + b.items.length, 0)
  return selectedBriefKeys.value.size > 0 && selectedBriefKeys.value.size < total
})
const selectedCount = computed(() => selectedBriefKeys.value.size)

function briefKey(line: string, idx: number) {
  return `${line}:${idx}`
}

function isBriefSelected(line: string, idx: number) {
  return selectedBriefKeys.value.has(briefKey(line, idx))
}

function toggleBriefSelect(line: string, idx: number) {
  const key = briefKey(line, idx)
  const newSet = new Set(selectedBriefKeys.value)
  if (newSet.has(key)) {
    newSet.delete(key)
  } else {
    newSet.add(key)
  }
  selectedBriefKeys.value = newSet
}

function handleSelectAll(val: any) {
  if (val) {
    const all = new Set<string>()
    lineBriefs.value.forEach(b => b.items.forEach((_, idx) => all.add(briefKey(b.line, idx))))
    selectedBriefKeys.value = all
  } else {
    selectedBriefKeys.value = new Set()
  }
}

function handleSelectLine(b: LineBrief) {
  const newSet = new Set(selectedBriefKeys.value)
  const lineKeys = b.items.map((_, idx) => briefKey(b.line, idx))
  const allSelected = lineKeys.every(k => newSet.has(k))
  if (allSelected) {
    lineKeys.forEach(k => newSet.delete(k))
  } else {
    lineKeys.forEach(k => newSet.add(k))
  }
  selectedBriefKeys.value = newSet
}

function handleExportImage() {
  // 收集选中的线索
  const selected: { line: string; label: string; item: any }[] = []
  lineBriefs.value.forEach(b => {
    b.items.forEach((item, idx) => {
      if (isBriefSelected(b.line, idx)) {
        selected.push({ line: b.line, label: b.label, item })
      }
    })
  })
  if (selected.length === 0) return

  // 按条线分组
  const grouped: Record<string, { label: string; items: any[] }> = {}
  selected.forEach(s => {
    if (!grouped[s.line]) grouped[s.line] = { label: s.label, items: [] }
    grouped[s.line].items.push(s.item)
  })

  // 用 Canvas 生成图片
  const padding = 40
  const cardWidth = 760
  const lineHeight = 26
  const headerHeight = 60

  // 计算总高度
  let totalHeight = headerHeight + padding
  Object.entries(grouped).forEach(([_, data]) => {
    totalHeight += 50 // 条线标题
    data.items.forEach(item => {
      const clueLines = Math.ceil(item.clue.length / 32) // 每行约32字
      totalHeight += 30 + clueLines * lineHeight + 10
    })
    totalHeight += 20
  })

  const canvas = document.createElement('canvas')
  canvas.width = cardWidth
  canvas.height = totalHeight
  const ctx = canvas.getContext('2d')!

  // 背景
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, cardWidth, totalHeight)

  // 标题
  ctx.fillStyle = '#1a1a2e'
  ctx.font = 'bold 24px sans-serif'
  ctx.textBaseline = 'top'
  ctx.fillText('雄安新区商机速览', padding, padding)
  ctx.font = '13px sans-serif'
  ctx.fillStyle = '#909399'
  const dateStr = briefDateRange.value ? `${briefDateRange.value[0]} ~ ${briefDateRange.value[1]}` : ''
  ctx.fillText(`${dateStr}  |  共 ${selected.length} 条商机线索`, padding, padding + 34)

  let y = headerHeight + padding
  Object.entries(grouped).forEach(([line, data]) => {
    // 条线标题栏
    const color = lineColors[line] || '#909399'
    ctx.fillStyle = color
    ctx.fillRect(padding, y, 6, 28)
    ctx.fillStyle = '#303133'
    ctx.font = 'bold 16px sans-serif'
    ctx.fillText(`${data.label}（${data.items.length}条）`, padding + 14, y + 4)
    y += 45

    // 线索列表
    data.items.forEach((item: any) => {
      // 优先级标签
      const tagColor = item.priority === 'high' || item.priority === 'critical' ? '#e74c3c' :
                       item.priority === 'medium' ? '#e6a23c' : '#909399'
      ctx.fillStyle = tagColor
      ctx.fillRect(padding, y, 50, 20)
      ctx.fillStyle = '#fff'
      ctx.font = '11px sans-serif'
      ctx.fillText(item.priority, padding + 8, y + 4)

      // 日期
      ctx.fillStyle = '#c0c4cc'
      ctx.font = '11px sans-serif'
      const dateText = item.publish_date ? item.publish_date.slice(5) : ''
      ctx.fillText(dateText, cardWidth - padding - 40, y + 4)

      y += 28

      // 线索文本（自动换行）
      ctx.fillStyle = '#303133'
      ctx.font = '13px sans-serif'
      const text = item.clue
      const maxChars = 32
      for (let i = 0; i < text.length; i += maxChars) {
        ctx.fillText(text.slice(i, i + maxChars), padding, y)
        y += lineHeight
      }
      y += 14
    })
    y += 10
  })

  // 下载
  canvas.toBlob((blob) => {
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `雄安商机速览_${dateStr || new Date().toISOString().slice(0, 10)}.png`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${selected.length} 条商机线索`)
  }, 'image/png')
}

function typeLabel(t: string) {
  return ({ daily: '日报', weekly: '周报', monthly: '月报' } as Record<string, string>)[t] || t
}

function formatTime(iso: string) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 19)
}

async function handleGenerateBriefs() {
  if (!briefDateRange.value) {
    ElMessage.warning('请选择时间范围')
    return
  }
  briefLoading.value = true
  try {
    const resp = await apiClient.generateLineBriefs({
      date_from: briefDateRange.value[0],
      date_to: briefDateRange.value[1],
    })
    lineBriefs.value = resp.data.briefs
    if (resp.data.briefs.length === 0) {
      ElMessage.info('该时段无商机数据')
    }
  } catch {
    ElMessage.error('生成速览失败')
  } finally {
    briefLoading.value = false
  }
}

async function handleGenerate() {
  if (!dateRange.value) {
    ElMessage.warning('请选择时间范围')
    return
  }
  generating.value = true
  try {
    const resp = await apiClient.generateReport({
      report_type: form.value.reportType,
      date_from: dateRange.value[0],
      date_to: dateRange.value[1],
      business_lines: form.value.lines.length ? form.value.lines : undefined,
    })
    previewContent.value = resp.data.content
    previewReportId.value = resp.data.report_id
    ElMessage.success('报告生成成功')
    await fetchReports()
  } catch {
    ElMessage.error('生成失败')
  } finally {
    generating.value = false
  }
}

function handlePreview(report: ReportItem) {
  previewContent.value = report.content
  previewReportId.value = report.id
}

const exporting = ref(false)

async function downloadReport(reportId: number) {
  exporting.value = true
  ElMessage.info('正在生成 Word 文件（含图片，约需15-30秒）...')
  try {
    // 第一步：调 API 预生成文件（POST 请求，不会被拦截）
    await apiClient.generateReportFile(reportId)
    // 第二步：直接导航到下载 URL（GET，浏览器原生处理下载）
    ElMessage.success('文件已生成，正在下载...')
    window.location.href = apiClient.downloadReportUrl(reportId)
  } catch {
    ElMessage.error('导出失败，请重试')
  } finally {
    setTimeout(() => { exporting.value = false }, 5000)
  }
}

function handleExportCurrent() {
  if (previewReportId.value !== null) {
    downloadReport(previewReportId.value)
  } else {
    ElMessage.warning('无可导出的报告')
  }
}

function handleExportExisting(report: ReportItem) {
  downloadReport(report.id)
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

onMounted(() => fetchReports())
</script>
