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
