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
