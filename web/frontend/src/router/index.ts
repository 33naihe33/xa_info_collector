// web/frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/opportunities' },
    { path: '/sources', name: 'sources', component: () => import('../views/SourceStatus.vue') },
    { path: '/documents', name: 'documents', component: () => import('../views/DocumentList.vue') },
    { path: '/opportunities', name: 'opportunities', component: () => import('../views/OpportunityList.vue') },
    { path: '/leadership', name: 'leadership', component: () => import('../views/LeadershipVisits.vue') },
    // 关系图谱已下线，GraphView.vue 保留以备参考
    // { path: '/graph', name: 'graph', component: () => import('../views/GraphView.vue') },
    { path: '/reports', name: 'reports', component: () => import('../views/ReportView.vue') },
    // 移动端路由
    { path: '/m', redirect: '/m/opportunities' },
    { path: '/m/opportunities', name: 'm-opportunities', component: () => import('../views/mobile/MobileOpportunities.vue') },
    { path: '/m/reports', name: 'm-reports', component: () => import('../views/mobile/MobileReports.vue') },
    { path: '/m/settings', name: 'm-settings', component: () => import('../views/mobile/MobileSettings.vue') },
  ],
})

// 设备路由守卫：移动设备访问桌面路由 → 重定向到移动端；桌面设备访问移动路由 → 重定向到桌面端
const MOBILE_REDIRECT_MAP: Record<string, string> = {
  '/sources': '/m/opportunities',
  '/documents': '/m/opportunities',
  '/opportunities': '/m/opportunities',
  '/leadership': '/m/opportunities',
  '/reports': '/m/reports',
}

router.beforeEach((to, _from, next) => {
  const isMobile = window.innerWidth < 768
  const isMobileRoute = to.path.startsWith('/m')

  if (isMobile && !isMobileRoute && to.path !== '/') {
    // 移动设备访问桌面路由 → 重定向到对应移动端页面
    next(MOBILE_REDIRECT_MAP[to.path] || '/m/opportunities')
  } else if (!isMobile && isMobileRoute) {
    // 桌面设备访问移动路由 → 重定向到桌面商机列表
    next('/opportunities')
  } else {
    next()
  }
})

export default router
