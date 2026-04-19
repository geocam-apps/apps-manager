<template>
  <div style="padding-top:16px">
    <n-spin v-if="loading" style="margin:40px auto;display:block" />
    <n-empty v-else-if="!apps.length" description="No apps here yet" style="margin:40px 0" />
    <n-grid v-else :x-gap="16" :y-gap="16" :cols="3" responsive="screen" :item-responsive="true">
      <n-gi v-for="app in apps" :key="app.id" span="3 s:3 m:1">
        <AppCard :app="app" @refresh="$emit('refresh')" @track-progress="$emit('track-progress', $event)" />
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import AppCard from './AppCard.vue'

defineProps<{ apps: any[]; loading: boolean }>()
defineEmits(['refresh', 'track-progress'])
</script>
