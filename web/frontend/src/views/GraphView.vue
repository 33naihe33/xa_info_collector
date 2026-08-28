<!-- web/frontend/src/views/GraphView.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div>
        <h2 style="margin: 0; display: inline-block;">关系图谱</h2>
        <span v-if="graphData" style="margin-left: 12px; color: #909399; font-size: 13px;">
          {{ graphData.total_nodes }} 个节点 · {{ graphData.total_edges }} 条关系
        </span>
      </div>
      <el-button type="primary" :icon="Refresh" @click="fetchGraph" :loading="loading">刷新</el-button>
    </div>

    <!-- 筛选栏 -->
    <div style="display: flex; gap: 16px; margin-bottom: 16px; align-items: center;">
      <span style="font-size: 13px; color: #606266;">节点类型：</span>
      <el-checkbox-group v-model="selectedTypes" @change="fetchGraph">
        <el-checkbox label="机构">机构</el-checkbox>
        <el-checkbox label="人物">人物</el-checkbox>
        <el-checkbox label="项目">项目</el-checkbox>
      </el-checkbox-group>
      <span style="font-size: 13px; color: #606266; margin-left: 16px;">节点上限：</span>
      <el-select v-model="nodeLimit" style="width: 100px;" @change="fetchGraph">
        <el-option :value="50" label="50" />
        <el-option :value="100" label="100" />
        <el-option :value="200" label="200" />
        <el-option :value="500" label="500" />
      </el-select>
    </div>

    <!-- 图谱容器 -->
    <div ref="chartRef" style="width: 100%; height: 600px; border: 1px solid #ebeef5; border-radius: 4px;" v-loading="loading"></div>

    <!-- 节点详情面板 -->
    <el-drawer v-model="detailVisible" :title="selectedNode?.name || ''" size="40%">
      <div v-if="selectedNode">
        <p><strong>类型：</strong>
          <el-tag :color="nodeColor(selectedNode.category)" style="color: #fff;" size="small">
            {{ selectedNode.category }}
          </el-tag>
        </p>
        <el-divider />
        <h4>关联实体（通过关系连接）</h4>
        <el-tag v-for="r in relatedEntities" :key="r.name" style="margin: 4px;" size="small">
          {{ r.type }} → {{ r.name }}
        </el-tag>
        <el-empty v-if="relatedEntities.length === 0" description="无关联实体" :image-size="60" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { apiClient, type GraphData, type GraphNode } from '../api/client'

const CATEGORY_COLORS: Record<string, string> = {
  '机构': '#409eff',
  '人物': '#67c23a',
  '项目': '#e6a23c',
  '其他': '#909399',
}

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
const graphData = ref<GraphData | null>(null)
const loading = ref(false)
const selectedTypes = ref<string[]>(['机构', '人物', '项目'])
const nodeLimit = ref(200)
const detailVisible = ref(false)
const selectedNode = ref<GraphNode | null>(null)
const relatedEntities = ref<{ name: string; type: string }[]>([])

function nodeColor(category: string) {
  return CATEGORY_COLORS[category] || '#909399'
}

async function fetchGraph() {
  loading.value = true
  try {
    const resp = await apiClient.getGraph({
      entity_types: selectedTypes.value.join(','),
      limit: nodeLimit.value,
    })
    graphData.value = resp.data
    await nextTick()
    renderChart()
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value || !graphData.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
    chart.on('click', (params: any) => {
      if (params.dataType === 'node') {
        showNodeDetail(params.data)
      }
    })
  }

  const data = graphData.value
  const categories = data.categories.map(c => ({
    name: c.name,
    itemStyle: { color: nodeColor(c.name) },
  }))

  chart.setOption({
    tooltip: {
      formatter: (params: any) => {
        if (params.dataType === 'node') {
          return `<b>${params.data.name}</b><br/>类型: ${params.data.category}`
        } else if (params.dataType === 'edge') {
          return params.data.relation_type || '关联'
        }
        return ''
      },
    },
    legend: [{
      data: categories.map(c => c.name),
      textStyle: { color: '#606266' },
    }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      label: {
        show: true,
        position: 'right',
        fontSize: 11,
      },
      force: {
        repulsion: 200,
        edgeLength: [80, 200],
        gravity: 0.1,
      },
      categories: categories,
      data: data.nodes.map(n => ({
        ...n,
        itemStyle: { color: nodeColor(n.category) },
      })),
      edges: data.edges.map(e => ({
        ...e,
        label: {
          show: true,
          formatter: e.relation_type,
          fontSize: 9,
          color: '#aaa',
        },
      })),
      lineStyle: {
        color: '#ccc',
        width: 1,
        curveness: 0.1,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 },
      },
    }],
  }, true)
}

function showNodeDetail(node: GraphNode) {
  selectedNode.value = node
  // 查找关联实体
  if (graphData.value) {
    const related: { name: string; type: string }[] = []
    for (const edge of graphData.value.edges) {
      if (edge.source === node.id) {
        const target = graphData.value.nodes.find(n => n.id === edge.target)
        if (target) related.push({ name: target.name, type: edge.relation_type })
      } else if (edge.target === node.id) {
        const source = graphData.value.nodes.find(n => n.id === edge.source)
        if (source) related.push({ name: source.name, type: edge.relation_type })
      }
    }
    relatedEntities.value = related
  }
  detailVisible.value = true
}

function handleResize() {
  chart?.resize()
}

onMounted(() => {
  fetchGraph()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})
</script>
