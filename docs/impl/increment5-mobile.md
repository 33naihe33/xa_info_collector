# 增量 5 实施文档：移动端 PWA — 响应式适配 + 商机信息流 + 报告阅读

> 创建日期：2026-07-10
> 状态：已完成

## 交付内容

本增量纯前端，未改动任何后端代码。所有数据沿用既有 API。

### 响应式布局（同一套 Vue 代码按屏幕宽度切换）

- **设备检测 composable**（`src/composables/useDevice.ts`）
  - 断点 `window.innerWidth < 768` 判定移动端，监听 `resize` 实时更新
- **桌面布局**（`src/layouts/DesktopLayout.vue`）
  - 从原 `App.vue` 原样提取：`el-header` + `el-aside`（200px 侧边栏）+ `el-menu` 五项导航（信息源/文档/商机/图谱/报告）
  - 全局样式（body、菜单项配色）随组件保留，桌面端外观与原版完全一致
- **移动布局**（`src/layouts/MobileLayout.vue`）
  - 顶部标题栏（雄安商机通）+ 内容区 + 底部三 Tab（商机/报告/我的）
  - `max-width: 480px` 居中，底部 Tab 固定悬浮，激活态高亮 #409eff
- **`App.vue`** 改造为布局切换器：`<DesktopLayout v-if="!isMobile" /> <MobileLayout v-else />`

### 移动端视图（`src/views/mobile/`）

| 文件 | 功能 | 调用 API |
|------|------|----------|
| `MobileOpportunities.vue` | 商机信息流卡片（今日/本周/全部筛选 + 卡片流 + 加载更多 + 底部弹出详情抽屉 `direction="btt"`） | `getOpportunities()`、`getOpportunity(id)` |
| `MobileReports.vue` | 报告列表（类型标签/时间/摘要/商机数）+ 底部弹出阅读抽屉（条线章节/重点建议） | `getReports()` |
| `MobileSettings.vue` | 推送偏好占位（即时预警/阈值/每日早报/免打扰），保存仅 toast，推送持久化留待增量 6 | 无（占位） |

### PWA 配置（`vite-plugin-pwa` 1.3.0）

- `vite.config.ts` 接入 `VitePWA`，`registerType: 'autoUpdate'` 自动注册 service worker
- **manifest**：name/short_name/theme_color(#1a1a2e)/standalone/中文，含 192/512 PNG 图标
- **workbox 缓存策略**：
  - 预缓存 `**/*.{js,css,html,ico,png,svg,woff2}`
  - 运行时缓存 `/api/*` → `NetworkFirst`（`api-cache`，最多 50 条、5 分钟过期）
- **图标**：`public/icon-192.png`、`public/icon-512.png`（品牌色纯色块占位，PNG 有效）
- **`index.html`** 增加 `theme-color`、`apple-mobile-web-app-capable`、`apple-mobile-web-app-title` meta

构建产物含 `dist/sw.js`、`dist/manifest.webmanifest`、`dist/registerSW.js`、workbox 引擎文件，22 条预缓存条目。

### 路由守卫（设备↔布局自动重定向）

`src/router/index.ts` 全局 `beforeEach`：

- 移动设备访问桌面路由（非 `/`）→ 重定向到移动端等价页
  - `/sources`、`/documents`、`/opportunities` → `/m/opportunities`
  - `/reports` → `/m/reports`；其余 → `/m/opportunities`
- 桌面设备访问 `/m/*` → 重定向到 `/opportunities`

移动端路由表：

| 路径 | 组件 |
|------|------|
| `/m` | 重定向到 `/m/opportunities` |
| `/m/opportunities` | MobileOpportunities |
| `/m/reports` | MobileReports |
| `/m/settings` | MobileSettings |

## API 契约（前端 ↔ 后端映射）

全部为既有端点，本增量无新增：

| 前端调用 | 后端接口 | 用途 |
|----------|----------|------|
| `apiClient.getOpportunities({ limit, offset })` | `GET /api/opportunities` | 商机信息流列表 |
| `apiClient.getOpportunity(id)` | `GET /api/opportunities/{id}` | 商机详情（抽屉） |
| `apiClient.getReports()` | `GET /api/reports` | 报告列表/阅读 |

## 设计决策

1. **移动端定位"信息触达"，非"分析工具"**：移动端裁掉图谱拖拽、报告生成、LLM 分析触发等复杂功能，仅保留浏览/阅读。
2. **`direction="btt"` 底部弹出抽屉**：模拟原生 App 推入动画，详情/阅读体验更接近移动端习惯。
3. **图标用纯色块占位**：PWA 无图标也能工作，纯色块满足 manifest 规范，后续可换正式品牌图标。
4. **设备检测基于屏幕宽度而非 UA**：平板/桌面窄窗也会切换到移动布局，重定向守卫同样按 `innerWidth < 768` 判定，逻辑一致。

## 验证

- `npm run build`（含 `vue-tsc --noEmit`）通过，dist 生成 sw.js / manifest.webmanifest
- 后端 `pytest tests/ -v` 仍为 85 passed（本增量无后端改动）

## 文件清单

新增：
- `web/frontend/src/composables/useDevice.ts`
- `web/frontend/src/layouts/DesktopLayout.vue`
- `web/frontend/src/layouts/MobileLayout.vue`
- `web/frontend/src/views/mobile/MobileOpportunities.vue`
- `web/frontend/src/views/mobile/MobileReports.vue`
- `web/frontend/src/views/mobile/MobileSettings.vue`
- `web/frontend/public/icon-192.png`
- `web/frontend/public/icon-512.png`

修改：
- `web/frontend/src/App.vue` — 改为布局切换器
- `web/frontend/src/router/index.ts` — 移动端路由 + 设备重定向守卫
- `web/frontend/vite.config.ts` — 接入 vite-plugin-pwa
- `web/frontend/index.html` — PWA meta 标签
- `web/frontend/package.json` — 新增 vite-plugin-pwa 依赖
