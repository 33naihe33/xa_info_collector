<!-- web/frontend/src/layouts/DesktopLayout.vue -->
<template>
  <el-container style="min-height: 100vh">
    <el-header style="background: #1a1a2e; display: flex; align-items: center;">
      <h1 style="color: #fff; margin: 0; font-size: 18px; flex: 1;">雄安信息商机挖掘系统</h1>
    </el-header>
    <el-container>
      <el-aside width="200px" style="background: #16213e;">
        <el-menu :default-active="activeMenu" router style="border: none; background: transparent;">
          <el-menu-item index="/opportunities">
            <el-icon><TrendCharts /></el-icon>
            <span>商机（条线入口）</span>
          </el-menu-item>
          <el-menu-item index="/reports">
            <el-icon><Tickets /></el-icon>
            <span>报告</span>
          </el-menu-item>
          <el-menu-item index="/sources">
            <el-icon><Connection /></el-icon>
            <span>信息源</span>
          </el-menu-item>
          <el-menu-item index="/documents">
            <el-icon><Document /></el-icon>
            <span>文档列表</span>
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

<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.el-aside .el-menu-item { color: #ccc; }
.el-aside .el-menu-item.is-active { color: #409eff; background: rgba(64,158,255,0.1); }
</style>
