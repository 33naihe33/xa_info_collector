<!-- web/frontend/src/views/LeadershipVisits.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div>
        <h2 style="margin: 0; display: inline-block;">领导调研</h2>
        <el-tag v-if="stats" style="margin-left: 12px;" type="info">
          共 {{ stats.total }} 条
        </el-tag>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="fetchData">刷新</el-button>
    </div>

    <!-- 日期筛选 -->
    <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 16px;">
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="调研开始日期"
        end-placeholder="调研结束日期"
        style="width: 280px;"
        @change="onFilterChange"
      />
      <el-button v-if="dateRange" text size="small" @click="clearFilter">清空筛选</el-button>
    </div>

    <!-- 调研卡片列表 -->
    <div v-loading="loading">
      <el-card
        v-for="visit in visits" :key="visit.id"
        shadow="hover" style="margin-bottom: 12px; cursor: pointer;"
        @click="openDetail(visit)"
      >
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <el-icon :size="18" color="#e6a23c"><User /></el-icon>
          <span style="font-size: 15px; font-weight: 600;">{{ visit.leader_name }}</span>
          <span v-if="visit.leader_title" style="font-size: 13px; color: #606266;">{{ visit.leader_title }}</span>
          <el-tag :type="priorityTag(visit.priority)" size="small" effect="dark" style="margin-left: 8px;">
            {{ visit.priority }}
          </el-tag>
          <span style="font-size: 12px; color: #909399; margin-left: auto;">
            {{ visit.visit_date || visit.publish_date || '' }}
          </span>
        </div>
        <div v-if="visit.visit_topic" style="font-size: 14px; color: #303133; margin-bottom: 6px;">
          <el-icon style="vertical-align: -2px;"><ChatLineSquare /></el-icon>
          {{ visit.visit_topic }}
        </div>
        <div v-if="visit.visited_entities?.length" style="margin: 6px 0;">
          <el-tag
            v-for="entity in visit.visited_entities" :key="entity"
            size="small" type="info" effect="plain" style="margin: 2px 4px 2px 0;"
          >
            {{ entity }}
          </el-tag>
        </div>
        <p v-if="visit.summary" style="font-size: 13px; color: #606266; margin: 6px 0 0 0; line-height: 1.6;">
          {{ visit.summary }}
        </p>
        <!-- 缩略图 -->
        <div v-if="visit.images?.length" style="display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap;">
          <el-image
            v-for="(img, idx) in visit.images.slice(0, 4)" :key="idx"
            :src="img"
            :preview-src-list="visit.images"
            :initial-index="idx"
            :preview-teleported="true"
            fit="cover"
            style="width: 80px; height: 80px; border-radius: 4px;"
            @click.stop
          />
        </div>
      </el-card>
      <el-empty v-if="!loading && visits.length === 0" description="暂无领导调研信息" />
    </div>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      style="margin-top: 16px; justify-content: center;"
      @current-change="fetchData"
    />

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="selected?.leader_name || ''" size="50%">
      <div v-if="selected" style="line-height: 1.8;">
        <p><strong>领导姓名：</strong>{{ selected.leader_name }}</p>
        <p v-if="selected.leader_title"><strong>职务：</strong>{{ selected.leader_title }}</p>
        <p v-if="selected.visit_date"><strong>调研日期：</strong>{{ selected.visit_date }}</p>
        <p v-if="selected.visit_topic"><strong>调研主题：</strong>{{ selected.visit_topic }}</p>
        <p><strong>优先级：</strong>
          <el-tag :type="priorityTag(selected.priority)" size="small" effect="dark">{{ selected.priority }}</el-tag>
        </p>
        <p v-if="selected.visited_entities?.length">
          <strong>走访机构：</strong>
          <el-tag
            v-for="entity in selected.visited_entities" :key="entity"
            size="small" type="info" effect="plain" style="margin: 0 4px 4px 0;"
          >{{ entity }}</el-tag>
        </p>
        <el-divider />
        <p v-if="selected.summary"><strong>调研摘要：</strong>{{ selected.summary }}</p>
        <div v-if="selected.images?.length">
          <strong>现场图片：</strong>
          <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
            <el-image
              v-for="(img, idx) in selected.images" :key="idx"
              :src="img"
              :preview-src-list="selected.images"
              :initial-index="idx"
              :preview-teleported="true"
              fit="cover"
              style="width: 140px; height: 140px; border-radius: 4px;"
            />
          </div>
        </div>
        <p v-if="selected.source_url" style="margin-top: 12px;">
          <strong>信息来源：</strong>
          <a :href="selected.source_url" target="_blank" rel="noopener"
            style="color: #0563C1; text-decoration: underline;">
            {{ selected.source_name || '查看原文' }}
          </a>
        </p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Refresh, User, ChatLineSquare } from '@element-plus/icons-vue'
import { apiClient, type LeadershipVisitItem, type LeadershipVisitStats } from '../api/client'

const visits = ref<LeadershipVisitItem[]>([])
const total = ref(0)
const stats = ref<LeadershipVisitStats | null>(null)
const loading = ref(false)
const page = ref(1)
const pageSize = 20
const dateRange = ref<[string, string] | null>(null)
const drawerVisible = ref(false)
const selected = ref<LeadershipVisitItem | null>(null)

function priorityTag(priority: string) {
  const map: Record<string, string> = {
    critical: 'danger', high: 'danger', medium: 'warning', low: 'info'
  }
  return map[priority] || 'info'
}

function onFilterChange() {
  page.value = 1
  fetchData()
}

function clearFilter() {
  dateRange.value = null
  page.value = 1
  fetchData()
}

async function fetchData() {
  loading.value = true
  try {
    const resp = await apiClient.getLeadershipVisits({
      visit_date_from: dateRange.value?.[0],
      visit_date_to: dateRange.value?.[1],
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    visits.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const resp = await apiClient.getLeadershipStats()
    stats.value = resp.data
  } catch {
    /* ignore */
  }
}

async function openDetail(visit: LeadershipVisitItem) {
  try {
    const resp = await apiClient.getLeadershipVisit(visit.id)
    selected.value = resp.data
  } catch {
    selected.value = visit
  }
  drawerVisible.value = true
}

onMounted(() => {
  fetchStats()
  fetchData()
})
</script>
