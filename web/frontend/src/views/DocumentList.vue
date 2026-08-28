<!-- web/frontend/src/views/DocumentList.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">文档列表 ({{ total }})</h2>
      <el-select v-model="filterSource" placeholder="全部来源" clearable style="width: 200px;" @change="onFilterChange">
        <el-option v-for="s in enabledSources" :key="s.name" :label="s.display_name" :value="s.name" />
      </el-select>
    </div>

    <el-table :data="documents" v-loading="loading" border @row-click="openDetail">
      <el-table-column prop="title" label="标题" min-width="300" />
      <el-table-column prop="source" label="来源" width="150" />
      <el-table-column prop="publish_date" label="发布日期" width="130" sortable />
      <el-table-column label="分析状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_analyzed ? 'success' : 'warning'" size="small">
            {{ row.is_analyzed ? '已分析' : '待分析' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      style="margin-top: 16px; justify-content: center;"
      @current-change="fetchData"
    />

    <el-drawer v-model="drawerVisible" :title="selectedDoc?.title || ''" size="50%">
      <div v-if="selectedDoc" style="white-space: pre-wrap; line-height: 1.8;">
        <p><strong>来源：</strong>{{ selectedDoc.source }} | <strong>日期：</strong>{{ selectedDoc.publish_date }}</p>
        <p><strong>原文链接：</strong><a :href="selectedDoc.url" target="_blank">{{ selectedDoc.url }}</a></p>
        <el-divider />
        {{ selectedDoc.text }}
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { apiClient, type DocumentItem, type DocumentDetail } from '../api/client'
import { useCollectorStore } from '../stores/collector'

const collectorStore = useCollectorStore()
const enabledSources = computed(() => collectorStore.sources.filter(s => s.enabled))

const documents = ref<DocumentItem[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 20
const filterSource = ref<string | undefined>(undefined)
const drawerVisible = ref(false)
const selectedDoc = ref<DocumentDetail | null>(null)

async function fetchData() {
  loading.value = true
  try {
    const resp = await apiClient.getDocuments({
      source: filterSource.value,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    documents.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

// M-07：筛选变化时重置页码到 1（避免 page>1 时用旧 offset 导致空结果）
function onFilterChange() {
  page.value = 1
  fetchData()
}

async function openDetail(row: DocumentItem) {
  const resp = await apiClient.getDocument(row.id)
  selectedDoc.value = resp.data
  drawerVisible.value = true
}

onMounted(async () => {
  await collectorStore.fetchSources()
  await fetchData()
})
</script>
