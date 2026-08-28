<!-- web/frontend/src/views/SourceStatus.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">信息源状态</h2>
      <el-button type="primary" :icon="Refresh" @click="store.fetchSources" :loading="store.loading">
        刷新
      </el-button>
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
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { Refresh, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCollectorStore } from '../stores/collector'

const store = useCollectorStore()

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
</script>
