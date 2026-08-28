# 增量 5：移动端 PWA — 响应式适配 + 商机信息流 + 报告阅读

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 将 Web 服务适配为 PWA，新增移动端布局（底部 Tab 导航 + 商机信息流 + 报告阅读 + 我的设置），支持添加到手机桌面、离线缓存。

**Architecture:** 同一套 Vue 代码，通过响应式 CSS + UA 检测切换桌面/移动布局。移动端裁掉复杂功能（图谱拖拽、报告生成），保留商机浏览、报告阅读、设置。PWA manifest + service worker 实现可安装和离线缓存。

**Tech Stack:** Vue 3 响应式布局，vite-plugin-pwa（PWA 配置），Element Plus 移动端适配。

---

## 设计原则

- **移动端定位是"信息触达"**，不是"分析工具"
- 桌面端功能不删减，移动端独立精简视图
- 通过屏幕宽度检测（< 768px）切换布局，不要求单独 URL
- PWA 让用户可"添加到主屏幕"，体验接近原生 App

## 文件结构（本增量创建/修改）

```
web/frontend/
├── src/
│   ├── composables/useDevice.ts      # 设备检测（桌面/移动）
│   ├── layouts/MobileLayout.vue      # 移动端布局（底部 Tab）
│   ├── layouts/DesktopLayout.vue     # 桌面端布局（从 App.vue 提取）
│   ├── views/mobile/
│   │   ├── MobileOpportunities.vue   # 商机信息流
│   │   ├── MobileReports.vue         # 报告阅读
│   │   └── MobileSettings.vue        # 设置（推送偏好占位）
│   ├── App.vue                       # 改为布局切换器
│   └── main.ts                       # PWA 注册
├── vite.config.ts                    # 添加 vite-plugin-pwa
├── public/manifest.json              # PWA manifest（由插件生成）
└── package.json                      # 新增 vite-plugin-pwa
```

---

## Task 1: 设备检测 + 布局切换

**Files:**
- Create: `web/frontend/src/composables/useDevice.ts`
- Create: `web/frontend/src/layouts/DesktopLayout.vue`
- Create: `web/frontend/src/layouts/MobileLayout.vue`
- Modify: `web/frontend/src/App.vue`

- [ ] **Step 1: 创建设备检测 composable**

```typescript
// web/frontend/src/composables/useDevice.ts
import { ref, onMounted, onBeforeUnmount } from 'vue'

const MOBILE_BREAKPOINT = 768

export function useDevice() {
  const isMobile = ref(false)

  function check() {
    isMobile.value = window.innerWidth < MOBILE_BREAKPOINT
  }

  onMounted(() => {
    check()
    window.addEventListener('resize', check)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', check)
  })

  return { isMobile }
}
```

- [ ] **Step 2: 创建 DesktopLayout.vue（从现有 App.vue 提取）**

将现有 App.vue 的侧边栏布局移到此组件。路由出口用 `<router-view />`。

```vue
<!-- web/frontend/src/layouts/DesktopLayout.vue -->
<template>
  <el-container style="min-height: 100vh">
    <el-header style="background: #1a1a2e; display: flex; align-items: center;">
      <h1 style="color: #fff; margin: 0; font-size: 18px; flex: 1;">雄安信息商机挖掘系统</h1>
    </el-header>
    <el-container>
      <el-aside width="200px" style="background: #16213e;">
        <el-menu :default-active="activeMenu" router style="border: none; background: transparent;">
          <el-menu-item index="/sources">
            <el-icon><Connection /></el-icon>
            <span>信息源状态</span>
          </el-menu-item>
          <el-menu-item index="/documents">
            <el-icon><Document /></el-icon>
            <span>文档列表</span>
          </el-menu-item>
          <el-menu-item index="/opportunities">
            <el-icon><TrendCharts /></el-icon>
            <span>商机列表</span>
          </el-menu-item>
          <el-menu-item index="/graph">
            <el-icon><Share /></el-icon>
            <span>关系图谱</span>
          </el-menu-item>
          <el-menu-item index="/reports">
            <el-icon><Tickets /></el-icon>
            <span>报告</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>
```

- [ ] **Step 3: 创建 MobileLayout.vue（底部 Tab 导航）**

```vue
<!-- web/frontend/src/layouts/MobileLayout.vue -->
<template>
  <div class="mobile-app">
    <header class="mobile-header">
      <h1>雄安商机通</h1>
    </header>
    <main class="mobile-content">
      <router-view />
    </main>
    <nav class="mobile-tabbar">
      <router-link to="/m/opportunities" class="tab-item" :class="{ active: isActive('/m/opportunities') }">
        <el-icon><TrendCharts /></el-icon>
        <span>商机</span>
      </router-link>
      <router-link to="/m/reports" class="tab-item" :class="{ active: isActive('/m/reports') }">
        <el-icon><Tickets /></el-icon>
        <span>报告</span>
      </router-link>
      <router-link to="/m/settings" class="tab-item" :class="{ active: isActive('/m/settings') }">
        <el-icon><Setting /></el-icon>
        <span>我的</span>
      </router-link>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
function isActive(path: string) {
  return route.path.startsWith(path)
}
</script>

<style scoped>
.mobile-app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  max-width: 480px;
  margin: 0 auto;
  background: #f5f7fa;
}
.mobile-header {
  background: #1a1a2e;
  color: #fff;
  padding: 12px 16px;
  text-align: center;
  position: sticky;
  top: 0;
  z-index: 100;
}
.mobile-header h1 {
  margin: 0;
  font-size: 16px;
}
.mobile-content {
  flex: 1;
  padding-bottom: 60px;
  overflow-y: auto;
}
.mobile-tabbar {
  display: flex;
  position: fixed;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100%;
  max-width: 480px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
  z-index: 100;
}
.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
  color: #909399;
  text-decoration: none;
  font-size: 11px;
  gap: 2px;
}
.tab-item.active {
  color: #409eff;
}
.tab-item .el-icon {
  font-size: 20px;
}
</style>
```

- [ ] **Step 4: 改造 App.vue 为布局切换器**

```vue
<!-- web/frontend/src/App.vue -->
<template>
  <DesktopLayout v-if="!isMobile" />
  <MobileLayout v-else />
</template>

<script setup lang="ts">
import DesktopLayout from './layouts/DesktopLayout.vue'
import MobileLayout from './layouts/MobileLayout.vue'
import { useDevice } from './composables/useDevice'

const { isMobile } = useDevice()
</script>
```

- [ ] **Step 5: 添加移动端路由（占位，Task 2-3 填充实际页面）**

在 router/index.ts 中添加移动端路由（重定向到移动端页面）。移动端访问 `/sources` 等桌面路由时重定向到对应移动端页面。

```typescript
// 在 routes 数组中添加
{ path: '/m', redirect: '/m/opportunities' },
{ path: '/m/opportunities', name: 'm-opportunities', component: () => import('../views/mobile/MobileOpportunities.vue') },
{ path: '/m/reports', name: 'm-reports', component: () => import('../views/mobile/MobileReports.vue') },
{ path: '/m/settings', name: 'm-settings', component: () => import('../views/mobile/MobileSettings.vue') },
```

创建占位文件（Task 2-3 填充）：
- `web/frontend/src/views/mobile/MobileOpportunities.vue` — 临时内容 `<template><div style="padding:16px;">商机信息流（开发中）</div></template>`
- `web/frontend/src/views/mobile/MobileReports.vue` — 同上
- `web/frontend/src/views/mobile/MobileSettings.vue` — 同上

- [ ] **Step 6: 验证构建 + Commit**

Run: `cd web/frontend && npm run build` → 必须通过

```bash
git add web/frontend/
git commit -m "feat: 移动端布局 — 设备检测 + 桌面/移动布局切换 + 底部 Tab 导航"
```

---

## Task 2: 移动端商机信息流

**Files:**
- Create: `web/frontend/src/views/mobile/MobileOpportunities.vue`

- [ ] **Step 1: 实现商机信息流页面**

```vue
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
          <el-tag v-for="p in opp.fin_products.slice(0,3)" :key="p" size="small">{{ p }}</el-tag>
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
  corporate: '对公', inclusive: '普惠', retail: '个金', partnership: '政银',
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

async function fetchData() {
  loading.value = true
  page.value = 1
  try {
    const resp = await apiClient.getOpportunities({ limit: 20, offset: 0 })
    opportunities.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  page.value++
  const resp = await apiClient.getOpportunities({ limit: 20, offset: (page.value - 1) * 20 })
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
```

- [ ] **Step 2: 验证构建 + Commit**

```bash
git add web/frontend/src/views/mobile/MobileOpportunities.vue
git commit -m "feat: 移动端商机信息流 — 卡片列表 + 筛选 + 详情抽屉"
```

---

## Task 3: 移动端报告阅读 + 设置页

**Files:**
- Create: `web/frontend/src/views/mobile/MobileReports.vue`
- Create: `web/frontend/src/views/mobile/MobileSettings.vue`

- [ ] **Step 1: 报告阅读页**

```vue
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
            <p><strong>{{ j+1 }}. {{ opp.title }}</strong></p>
            <p v-if="opp.scale" class="meta">规模：{{ opp.scale }}</p>
            <p v-if="opp.products" class="meta">产品：{{ opp.products }}</p>
            <p v-if="opp.action" class="meta">建议：{{ opp.action }}</p>
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
  return { daily: '日报', weekly: '周报', monthly: '月报' }[t] || t
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
```

- [ ] **Step 2: 设置页（推送偏好占位，增量 6 实现）**

```vue
<!-- web/frontend/src/views/mobile/MobileSettings.vue -->
<template>
  <div class="m-settings">
    <el-card shadow="never" style="margin: 12px;">
      <template #header><strong>推送设置</strong></template>
      <el-form label-position="top">
        <el-form-item label="即时预警">
          <el-switch v-model="settings.instantEnabled" />
          <span style="margin-left: 8px; font-size: 12px; color: #909399;">高优先级商机实时推送</span>
        </el-form-item>
        <el-form-item label="预警阈值">
          <el-select v-model="settings.instantThreshold" style="width: 100%;">
            <el-option label="仅紧急 (critical)" value="critical" />
            <el-option label="高及以上 (high)" value="high" />
            <el-option label="中及以上 (medium)" value="medium" />
          </el-select>
        </el-form-item>
        <el-form-item label="每日早报">
          <div style="display: flex; align-items: center; width: 100%;">
            <el-switch v-model="settings.dailyDigest" />
            <el-time-picker v-if="settings.dailyDigest" v-model="settings.digestTime"
              value-format="HH:mm" placeholder="08:00" style="margin-left: 12px; flex: 1;" />
          </div>
        </el-form-item>
        <el-form-item label="免打扰时段">
          <div style="display: flex; align-items: center; width: 100%; gap: 8px;">
            <el-switch v-model="settings.dndEnabled" />
            <template v-if="settings.dndEnabled">
              <el-time-picker v-model="settings.dndStart" value-format="HH:mm" placeholder="22:00" />
              <span>-</span>
              <el-time-picker v-model="settings.dndEnd" value-format="HH:mm" placeholder="07:00" />
            </template>
          </div>
        </el-form-item>
      </el-form>
      <el-button type="primary" style="width: 100%;" @click="handleSave">保存设置</el-button>
    </el-card>

    <el-card shadow="never" style="margin: 12px;">
      <template #header><strong>关于</strong></template>
      <p style="font-size: 13px; color: #909399; margin: 0;">雄安信息商机挖掘系统 v0.1.0</p>
      <p style="font-size: 13px; color: #909399;">面向银行分行行长的雄安商机情报服务</p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const settings = ref({
  instantEnabled: true,
  instantThreshold: 'high',
  dailyDigest: true,
  digestTime: '08:00',
  dndEnabled: true,
  dndStart: '22:00',
  dndEnd: '07:00',
})

function handleSave() {
  // 增量 6 实现推送设置 API 持久化
  ElMessage.success('设置已保存（推送功能将在后续版本生效）')
}
</script>

<style scoped>
.m-settings { padding-bottom: 20px; }
</style>
```

- [ ] **Step 3: 验证构建 + Commit**

```bash
git add web/frontend/src/views/mobile/
git commit -m "feat: 移动端报告阅读 + 设置页"
```

---

## Task 4: PWA 配置

**Files:**
- Modify: `web/frontend/package.json`
- Modify: `web/frontend/vite.config.ts`
- Modify: `web/frontend/index.html`

- [ ] **Step 1: 安装 vite-plugin-pwa**

Run: `cd web/frontend && npm install vite-plugin-pwa -D`

- [ ] **Step 2: 配置 vite-plugin-pwa**

修改 `vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: '雄安信息商机挖掘系统',
        short_name: '雄安商机通',
        description: '面向银行分行行长的雄安商机情报服务',
        theme_color: '#1a1a2e',
        background_color: '#ffffff',
        display: 'standalone',
        lang: 'zh-CN',
        icons: [
          {
            src: '/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^\/api\/.*/i,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 300 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: 创建简单图标占位**

创建 `web/frontend/public/icon-192.png` 和 `icon-512.png`。如果无法生成图标，可以用一个纯色方块 SVG 转 PNG，或用占位图。实际上 PWA 没有图标也能工作（只是安装时显示默认图标）。

如果无法生成 PNG 图标，从 manifest 中移除 icons 配置，仅保留基本 PWA 功能。这是可接受的降级。

- [ ] **Step 4: index.html 添加 PWA meta 标签**

在 `<head>` 中添加:
```html
<meta name="theme-color" content="#1a1a2e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="雄安商机通">
```

- [ ] **Step 5: 验证构建**

Run: `cd web/frontend && npm run build`
Expected: 构建成功，dist 目录包含 sw.js (service worker) 和 manifest.webmanifest

- [ ] **Step 6: Commit**

```bash
git add web/frontend/
git commit -m "feat: PWA 配置 — 可安装 + 离线缓存 + manifest"
```

---

## Task 5: 移动路由重定向 + 实施文档

**Files:**
- Modify: `web/frontend/src/router/index.ts`
- Modify: `web/frontend/src/layouts/MobileLayout.vue`（添加路由守卫逻辑）

- [ ] **Step 1: 路由重定向**

移动设备访问桌面路由时自动重定向到移动端。在 router 中添加全局守卫：

```typescript
// 在 router/index.ts 的 createRouter 之后添加守卫
router.beforeEach((to, from, next) => {
  const isMobile = window.innerWidth < 768
  const isDesktopRoute = !to.path.startsWith('/m')
  const isMobileRoute = to.path.startsWith('/m')

  if (isMobile && isDesktopRoute && to.path !== '/') {
    // 移动设备访问桌面路由 → 重定向
    const map: Record<string, string> = {
      '/sources': '/m/opportunities',
      '/documents': '/m/opportunities',
      '/opportunities': '/m/opportunities',
      '/reports': '/m/reports',
    }
    next(map[to.path] || '/m/opportunities')
  } else if (!isMobile && isMobileRoute) {
    // 桌面设备访问移动路由 → 重定向
    next('/opportunities')
  } else {
    next()
  }
})
```

- [ ] **Step 2: 验证构建**

Run: `cd web/frontend && npm run build`

- [ ] **Step 3: 实施文档**

撰写 `docs/impl/increment5-mobile.md` 并提交。

- [ ] **Step 4: Commit**

```bash
git add web/frontend/ docs/impl/increment5-mobile.md
git commit -m "feat: 移动路由重定向 + 增量5实施文档"
```

---

## 完成标准

1. ✅ 前端 `npm run build` 无错误
2. ✅ 桌面端布局不变（侧边栏导航）
3. ✅ 移动端布局（底部 Tab + 信息流）
4. ✅ PWA 可安装（manifest + service worker）
5. ✅ 移动端访问桌面路由自动重定向
6. ✅ 每个 Task 有 commit
