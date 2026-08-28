// web/frontend/src/stores/collector.ts
import { defineStore } from 'pinia'
import { apiClient, type SourceInfo } from '../api/client'
import { ref } from 'vue'

export const useCollectorStore = defineStore('collector', () => {
  const sources = ref<SourceInfo[]>([])
  const loading = ref(false)
  const triggerLoading = ref<string | null>(null)

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

  return { sources, loading, triggerLoading, fetchSources, triggerCollect }
})
