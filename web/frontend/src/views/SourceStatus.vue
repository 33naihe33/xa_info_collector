<!-- web/frontend/src/views/SourceStatus.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">信息源状态</h2>
      <div>
        <el-button type="primary" @click="dialogVisible = true">按范围抓取</el-button>
        <el-button type="primary" :icon="Refresh" @click="store.fetchSources" :loading="store.loading">
          刷新
        </el-button>
      </div>
    </div>

    <el-table :data="store.sources" v-loading="store.loading" border>
      <el-table-column prop="display_name" label="数据源" width="180" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">
            {{ row.enabled ? '已启用' : '未启用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="doc_count" label="已抓取文档数" width="140" />
      <el-table-column label="栏目" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="cat in row.categories" :key="cat" size="small" style="margin-right: 4px;">
            {{ cat }}
          </el-tag>
          <span v-if="!row.categories?.length" style="color: #999;">-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small" type="primary" :icon="Download"
            :disabled="!row.enabled"
            :loading="store.triggerLoading === row.name"
            @click="handleCollect(row.name)"
          >
            立即抓取
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="dialogVisible" title="按日期范围抓取" width="min(520px, 95vw)">
      <div style="margin-bottom: 8px;">
        <el-button size="small" @click="selectedSources = enabledSources.map(s => s.name)">全选</el-button>
        <el-button size="small" @click="selectedSources = []">取消全选</el-button>
      </div>
      <el-checkbox-group v-model="selectedSources">
        <el-checkbox v-for="source in enabledSources" :key="source.name" :value="source.name">
          {{ source.display_name }}
        </el-checkbox>
      </el-checkbox-group>
      <el-date-picker
        v-model="dateRange" type="daterange" value-format="YYYY-MM-DD"
        start-placeholder="开始日期" end-placeholder="结束日期"
        style="margin-top: 16px; max-width: 100%;"
      />
      <p style="color: #909399; font-size: 13px;">历史文章能否补采，取决于各信息源当前可检索的范围。</p>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.rangeTriggerLoading" :disabled="store.rangeTriggerLoading" @click="submitRange">
          开始抓取
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCollectorStore } from '../stores/collector'

const store = useCollectorStore()
const dialogVisible = ref(false)
const selectedSources = ref<string[]>([])
const dateRange = ref<[string, string] | null>(null)
const enabledSources = computed(() => store.sources.filter(source => source.enabled))

onMounted(() => store.fetchSources())

async function handleCollect(source: string) {
  try {
    await store.triggerCollect(source)
    ElMessage.success('抓取任务已启动')
    // 3秒后刷新数据源状态
    setTimeout(() => store.fetchSources(), 3000)
  } catch {
    ElMessage.error('启动抓取失败')
  }
}
async function submitRange() {
  if (store.rangeTriggerLoading) return
  const dates = dateRange.value
  if (!selectedSources.value.length || !dates || dates.length !== 2 || !dates[0] || !dates[1]) {
    ElMessage.error('请选择信息源和完整日期范围')
    return
  }
  if (dates[0] > dates[1]) {
    ElMessage.error('开始日期不能晚于结束日期')
    return
  }
  try {
    const response = await store.triggerRangeCollect(selectedSources.value, dates[0], dates[1])
    ElMessage.success(`已启动 ${response.data.source_count} 个信息源的抓取任务`)
    dialogVisible.value = false
    setTimeout(() => store.fetchSources(), 3000)
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '启动抓取失败，请检查信息源和日期')
  }
}
</script>
