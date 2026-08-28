<!-- web/frontend/src/views/mobile/MobileSettings.vue -->
<template>
  <div class="m-settings" v-loading="loading">
    <el-card shadow="never" style="margin: 12px;">
      <template #header><strong>推送设置</strong></template>
      <el-form label-position="top">
        <el-form-item label="即时预警">
          <el-switch v-model="settings.instantEnabled" />
          <span class="hint">高优先级商机实时推送</span>
        </el-form-item>
        <el-form-item label="预警阈值">
          <el-select v-model="settings.instantThreshold" style="width: 100%;">
            <el-option label="仅紧急 (critical)" value="critical" />
            <el-option label="高及以上 (high)" value="high" />
            <el-option label="中及以上 (medium)" value="medium" />
          </el-select>
        </el-form-item>
        <el-form-item label="每日上限">
          <el-input-number v-model="settings.dailyLimit" :min="0" :max="50" style="width: 100%;" />
          <span class="hint">0 = 不限制</span>
        </el-form-item>
        <el-form-item label="每日早报">
          <div class="row">
            <el-switch v-model="settings.dailyDigest" />
            <el-time-picker v-if="settings.dailyDigest" v-model="settings.digestTime"
              value-format="HH:mm" placeholder="08:00" class="time-flex" />
          </div>
        </el-form-item>
        <el-form-item label="免打扰时段">
          <div class="row">
            <el-switch v-model="settings.dndEnabled" />
            <template v-if="settings.dndEnabled">
              <el-time-picker v-model="settings.dndStart" value-format="HH:mm" placeholder="22:00" />
              <span>-</span>
              <el-time-picker v-model="settings.dndEnd" value-format="HH:mm" placeholder="07:00" />
            </template>
          </div>
        </el-form-item>
      </el-form>
      <el-button type="primary" style="width: 100%;" :loading="saving" @click="handleSave">保存设置</el-button>
    </el-card>

    <el-card shadow="never" style="margin: 12px;">
      <template #header><strong>推送状态</strong></template>
      <div class="stat-row">
        <span>今日推送</span>
        <strong>{{ stats.today_count }} 条</strong>
      </div>
      <div class="stat-row">
        <span>其中即时预警</span>
        <strong>{{ stats.today_instant }} 条</strong>
      </div>
      <div class="stat-row">
        <span>订阅设备</span>
        <strong>{{ stats.subscriptions }} 个</strong>
      </div>
      <el-button v-if="!stats.subscriptions" type="success" plain size="small" style="margin-top: 8px; width: 100%;"
        :loading="subscribing" @click="handleSubscribe">开启本机推送</el-button>
    </el-card>

    <el-card shadow="never" style="margin: 12px;">
      <template #header><strong>关于</strong></template>
      <p class="about">雄安信息商机挖掘系统 v0.1.0</p>
      <p class="about">面向银行分行行长的雄安商机情报服务</p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, type PushStats } from '../../api/client'

// 本地 camelCase 视图模型（后端字段为 snake_case，加载/保存时转换）
const settings = reactive({
  instantEnabled: true,
  instantThreshold: 'high',
  dailyLimit: 5,
  dailyDigest: true,
  digestTime: '08:00',
  dndEnabled: true,
  dndStart: '22:00',
  dndEnd: '07:00',
})

const stats = ref<PushStats>({ subscriptions: 0, today_count: 0, today_instant: 0, today_scheduled: 0 })
const loading = ref(false)
const saving = ref(false)
const subscribing = ref(false)

async function fetchSettings() {
  loading.value = true
  try {
    const { data } = await apiClient.getPushSettings()
    settings.instantEnabled = data.instant_enabled
    settings.instantThreshold = data.instant_threshold
    settings.dailyLimit = data.daily_limit
    settings.dailyDigest = data.daily_digest_enabled
    settings.digestTime = data.daily_digest_time
    settings.dndEnabled = data.dnd_enabled
    settings.dndStart = data.dnd_start
    settings.dndEnd = data.dnd_end
  } catch {
    ElMessage.error('加载设置失败')
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const { data } = await apiClient.getPushStats()
    stats.value = data
  } catch {
    // 统计非关键，静默失败
  }
}

async function handleSave() {
  saving.value = true
  try {
    await apiClient.updatePushSettings({
      instant_enabled: settings.instantEnabled,
      instant_threshold: settings.instantThreshold,
      daily_limit: settings.dailyLimit,
      daily_digest_enabled: settings.dailyDigest,
      daily_digest_time: settings.digestTime,
      dnd_enabled: settings.dndEnabled,
      dnd_start: settings.dndStart,
      dnd_end: settings.dndEnd,
    })
    ElMessage.success('设置已保存')
    fetchStats()
  } catch {
    ElMessage.error('保存失败，请重试')
  } finally {
    saving.value = false
  }
}

async function handleSubscribe() {
  // 浏览器不支持 / 未授权时给出提示，不阻塞设置页
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    ElMessage.warning('当前浏览器不支持 Web Push')
    return
  }
  subscribing.value = true
  try {
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') {
      ElMessage.warning('未授权通知权限')
      return
    }
    // F-07：先注册 Service Worker（若未注册），再获取 VAPID 公钥
    await navigator.serviceWorker.register('/sw.js').catch(() => {})
    const reg = await navigator.serviceWorker.ready
    // F-07：从后端获取 VAPID 公钥，传入 subscribe（原缺 applicationServerKey 导致订阅无效）
    const vapidResp = await apiClient.getVapidKey()
    const vapidKey = vapidResp.data.public_key
    if (!vapidKey) {
      ElMessage.error('服务器未配置 VAPID 密钥')
      return
    }
    // base64url → Uint8Array
    const keyBytes = Uint8Array.from(atob(vapidKey.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes })
    const subJson = sub.toJSON()
    await apiClient.subscribePush(subJson.endpoint!, subJson.keys as Record<string, string>)
    ElMessage.success('已开启本机推送')
    fetchStats()
  } catch {
    ElMessage.error('订阅失败')
  } finally {
    subscribing.value = false
  }
}

onMounted(() => {
  fetchSettings()
  fetchStats()
})
</script>

<style scoped>
.m-settings { padding-bottom: 20px; }
.hint { margin-left: 8px; font-size: 12px; color: #909399; }
.row { display: flex; align-items: center; width: 100%; gap: 8px; }
.time-flex { margin-left: 12px; flex: 1; }
.about { font-size: 13px; color: #909399; margin: 0; }
.stat-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; font-size: 13px; color: #606266; }
</style>
