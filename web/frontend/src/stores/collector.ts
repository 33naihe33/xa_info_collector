// web/frontend/src/stores/collector.ts
import { defineStore } from 'pinia'
import { apiClient, type SourceInfo } from '../api/client'
import { ref } from 'vue'

export const useCollectorStore = defineStore('collector', () => {
  const sources = ref<SourceInfo[]>([])
  const loading = ref(false)
  const triggerLoading = ref<string | null>(null)
  const rangeTriggerLoading = ref(false)

  async function fetchSources() {
    loading.value = true
    try {
      const resp = await apiClient.getSources()
      sources.value = resp.data.sources
    } finally {
      loading.value = false
    }
  }

  async function triggerCollect(source: string) {
    triggerLoading.value = source
    try {
      await apiClient.triggerCollect(source)
    } finally {
      triggerLoading.value = null
    }
  }
  async function triggerRangeCollect(sources: string[], dateFrom: string, dateTo: string) {
    rangeTriggerLoading.value = true
    try {
      return await apiClient.triggerRangeCollect(sources, dateFrom, dateTo)
    } finally {
      rangeTriggerLoading.value = false
    }
  }

  return { sources, loading, triggerLoading, rangeTriggerLoading, fetchSources, triggerCollect, triggerRangeCollect }
})
