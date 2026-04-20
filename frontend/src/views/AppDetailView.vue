<template>
  <div style="min-height:100vh;background:#0f0f13">
    <n-layout-header
      bordered
      style="padding:0 24px;height:60px;display:flex;align-items:center;gap:16px;background:#16161a"
    >
      <n-button text @click="$router.push('/')">← Back</n-button>
      <img src="/geocam-logo.png" style="height:28px;width:auto;object-fit:contain" alt="Geocam" />
      <n-text style="font-size:18px;font-weight:600;color:#a5b4fc">{{ app?.name || 'Loading...' }}</n-text>
    </n-layout-header>

    <div style="max-width:960px;margin:0 auto;padding:32px 24px">
      <n-spin v-if="loading" size="large" style="margin:80px auto;display:block" />
      <template v-else-if="app">
        <n-alert :type="statusType" style="margin-bottom:24px;border-radius:12px">
          Status: <strong>{{ app.status }}</strong>
          <span v-if="app.error_message"> — {{ app.error_message }}</span>
        </n-alert>

        <!-- Destroy progress (replaces everything while destroying) -->
        <template v-if="app.status === 'destroying'">
          <n-card title="Destroying App..." :bordered="false" style="background:#1c1c23;border-radius:12px;border:1px solid #4a1f1f;margin-bottom:24px">
            <n-space align="center" style="margin-bottom:16px">
              <n-spin size="small" />
              <n-text depth="2" style="font-size:13px">Removing container, tunnel, DNS, and GitHub repo...</n-text>
            </n-space>
            <n-timeline size="small">
              <n-timeline-item
                v-for="step in destroySteps"
                :key="step.step"
                :type="step.status === 'done' ? 'success' : step.status === 'error' ? 'error' : 'info'"
                :title="step.label"
                :content="step.message"
              />
            </n-timeline>
          </n-card>
        </template>

        <n-grid v-else :x-gap="16" :y-gap="16" :cols="2">
          <!-- Info -->
          <n-gi>
            <n-card title="Info" :bordered="false" style="background:#1c1c23;border-radius:12px">
              <n-descriptions :column="1" bordered>
                <n-descriptions-item label="Owner">{{ app.owner_username }}</n-descriptions-item>
                <n-descriptions-item label="IP">{{ app.container_ip || '—' }}</n-descriptions-item>
                <n-descriptions-item label="Created">{{ new Date(app.created_at).toLocaleString() }}</n-descriptions-item>
                <n-descriptions-item label="GitHub">
                  <n-button v-if="app.github_repo" text tag="a" :href="app.github_repo" target="_blank" style="font-size:12px">{{ app.github_repo }}</n-button>
                  <span v-else>—</span>
                </n-descriptions-item>
              </n-descriptions>
            </n-card>
          </n-gi>

          <!-- Access -->
          <n-gi>
            <n-card title="Access" :bordered="false" style="background:#1c1c23;border-radius:12px">
              <n-space vertical :size="12">
                <n-space align="center">
                  <n-text depth="3" style="min-width:80px">Password:</n-text>
                  <n-tag v-if="showPassword" style="font-family:monospace">{{ app.password }}</n-tag>
                  <n-button v-else text size="small" @click="showPassword = true">Show</n-button>
                  <n-button v-if="showPassword" text size="small" @click="copyToClipboard(app.password)">Copy</n-button>
                  <n-button v-if="isOwnerOrAdmin" text size="small" @click="handleChangePassword" :loading="changingPw">Regenerate</n-button>
                </n-space>

                <!-- Admin token (owner/admin only) -->
                <n-space v-if="isOwnerOrAdmin && app.admin_token" align="center">
                  <n-text depth="3" style="min-width:80px">Admin token:</n-text>
                  <n-tag v-if="showAdminToken" size="small" style="font-family:monospace;max-width:200px;overflow:hidden;text-overflow:ellipsis">{{ app.admin_token }}</n-tag>
                  <n-button v-else text size="small" @click="showAdminToken = true">Show</n-button>
                  <n-button text size="small" @click="copyAdminToken">Copy</n-button>
                </n-space>
                <n-text v-if="isOwnerOrAdmin && app.admin_token" depth="3" style="font-size:11px">
                  Sent to container as APP_ADMIN_TOKEN env var
                </n-text>

                <!-- SSH access -->
                <div v-if="app.ssh_command">
                  <n-text depth="3" style="font-size:12px;display:block;margin-bottom:6px">SSH (native client):</n-text>
                  <n-space align="center" style="margin-bottom:4px">
                    <n-tag style="font-family:monospace;font-size:12px">{{ app.ssh_command }}</n-tag>
                    <n-button text size="small" @click="copyToClipboard(app.ssh_command)">Copy</n-button>
                  </n-space>
                  <n-collapse>
                    <n-collapse-item title="If SSH doesn't resolve, use Cloudflare tunnel" name="cf-ssh">
                      <n-text depth="3" style="font-size:12px;display:block;margin-bottom:6px">
                        Install cloudflared once: <n-tag size="small" style="font-family:monospace">brew install cloudflare/cloudflare/cloudflared</n-tag>
                      </n-text>
                      <n-text depth="3" style="font-size:12px;display:block;margin-bottom:4px">Then add to ~/.ssh/config:</n-text>
                      <n-space align="center">
                        <n-tag style="font-family:monospace;font-size:11px">Host *.geocam.io</n-tag>
                      </n-space>
                      <n-space align="center" style="margin-top:2px">
                        <n-tag style="font-family:monospace;font-size:11px">  ProxyCommand cloudflared access ssh --hostname %h</n-tag>
                        <n-button text size="small" @click="copyToClipboard('Host *.geocam.io\n  ProxyCommand cloudflared access ssh --hostname %h')">Copy</n-button>
                      </n-space>
                    </n-collapse-item>
                  </n-collapse>
                </div>

                <n-divider style="margin:4px 0" />
                <n-space :wrap="true">
                  <template v-for="(url, key) in app.urls" :key="key">
                    <n-button v-if="String(key) !== 'ssh'" tag="a" :href="String(url)" target="_blank" :type="linkType(String(key))" size="small">
                      Open {{ key }}
                    </n-button>
                  </template>
                </n-space>
              </n-space>
            </n-card>
          </n-gi>

          <!-- Stats (running apps only) -->
          <n-gi :span="2" v-if="app.status === 'running'">
            <n-card title="Resource Usage" :bordered="false" style="background:#1c1c23;border-radius:12px">
              <n-space align="center" style="margin-bottom:12px">
                <n-button size="small" @click="loadStats" :loading="loadingStats">Refresh Stats</n-button>
                <n-text v-if="stats" depth="3" style="font-size:12px">{{ stats.uptime }}</n-text>
              </n-space>
              <n-grid v-if="stats" :x-gap="16" :y-gap="8" :cols="3">
                <n-gi v-if="stats.memory">
                  <n-statistic label="Memory">
                    <template #default>{{ stats.memory.used_mb }} / {{ stats.memory.total_mb }} MB</template>
                  </n-statistic>
                  <n-progress type="line" :percentage="stats.memory.pct" :color="memColor(stats.memory.pct)" :rail-color="'#2a2a35'" :height="4" :show-indicator="false" style="margin-top:4px" />
                </n-gi>
                <n-gi v-if="stats.disk">
                  <n-statistic label="Disk">
                    <template #default>{{ stats.disk.used_mb }} / {{ stats.disk.total_mb }} MB</template>
                  </n-statistic>
                  <n-progress type="line" :percentage="parseInt(stats.disk.pct)" :color="memColor(parseInt(stats.disk.pct))" :rail-color="'#2a2a35'" :height="4" :show-indicator="false" style="margin-top:4px" />
                </n-gi>
                <n-gi v-if="stats.gpu && stats.gpu.length">
                  <n-statistic label="GPU" :value="`${stats.gpu[0].gpu_pct}%`" />
                  <n-progress type="line" :percentage="stats.gpu[0].gpu_pct" :color="'#22d3ee'" :rail-color="'#2a2a35'" :height="4" :show-indicator="false" style="margin-top:4px" />
                  <n-text depth="3" style="font-size:11px">{{ stats.gpu[0].mem_used_mb }}/{{ stats.gpu[0].mem_total_mb }} MB VRAM</n-text>
                </n-gi>
              </n-grid>
              <n-empty v-else-if="!loadingStats" description="Click Refresh Stats" />
            </n-card>
          </n-gi>

          <!-- Services -->
          <n-gi :span="2">
            <n-card title="Services" :bordered="false" style="background:#1c1c23;border-radius:12px">
              <n-button @click="loadStatuses" :loading="loadingStatus" size="small" style="margin-bottom:16px">Refresh Status</n-button>
              <n-data-table v-if="services" :columns="serviceColumns" :data="serviceRows" :bordered="false" size="small" />
              <n-empty v-else description="Click refresh to load service status" />
            </n-card>
          </n-gi>

          <!-- Sharing -->
          <n-gi :span="2" v-if="isOwnerOrAdmin">
            <n-card title="Sharing" :bordered="false" style="background:#1c1c23;border-radius:12px">
              <n-space style="margin-bottom:16px">
                <n-input v-model:value="shareUsername" placeholder="Username (empty = everyone)" style="width:240px" size="small" />
                <n-button type="primary" size="small" @click="handleShare" :loading="sharing">Share with User</n-button>
                <n-button size="small" @click="handleShareEveryone" :loading="sharing">Share with Everyone</n-button>
              </n-space>
              <n-data-table :columns="shareColumns" :data="shares" :bordered="false" size="small" />
            </n-card>
          </n-gi>

          <!-- Build Logs -->
          <n-gi :span="2">
            <n-card title="Build Logs" :bordered="false" style="background:#1c1c23;border-radius:12px">
              <n-button @click="loadLogs" size="small" style="margin-bottom:16px">Load Logs</n-button>
              <n-timeline v-if="logs.length" size="small">
                <n-timeline-item
                  v-for="log in logs"
                  :key="log.created_at + log.step"
                  :type="log.status === 'done' ? 'success' : log.status === 'error' ? 'error' : 'info'"
                  :title="log.step"
                  :content="log.message"
                  :time="new Date(log.created_at).toLocaleTimeString()"
                />
              </n-timeline>
            </n-card>
          </n-gi>

          <!-- Danger Zone -->
          <n-gi :span="2" v-if="isOwnerOrAdmin">
            <n-card title="Danger Zone" :bordered="false" style="background:#1c1c23;border-radius:12px;border:1px solid #4a1f1f">
              <n-button type="error" @click="showDeleteConfirm = true">Destroy App</n-button>
            </n-card>
          </n-gi>
        </n-grid>
      </template>
    </div>

    <n-modal v-model:show="showDeleteConfirm" :mask-closable="!deleting" @after-leave="destroyConfirmName = ''">
      <n-card style="width:440px;border-radius:16px" title="Destroy App" :bordered="false">
        <n-space vertical :size="16">
          <n-text>This will permanently destroy the container, Cloudflare tunnel, and GitHub repo. This cannot be undone.</n-text>
          <n-text depth="3" style="font-size:13px">Type <strong style="color:#ef4444">{{ app?.name }}</strong> to confirm:</n-text>
          <n-input v-model:value="destroyConfirmName" placeholder="app name" @keydown.enter="destroyConfirmName === app?.name && handleDelete()" />
          <n-space justify="end">
            <n-button @click="showDeleteConfirm = false" :disabled="deleting">Cancel</n-button>
            <n-button type="error" :loading="deleting" :disabled="destroyConfirmName !== app?.name" @click="handleDelete">Destroy</n-button>
          </n-space>
        </n-space>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, NButton, NTag } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const message = useMessage()

const app = ref<any>(null)
const loading = ref(true)
const showPassword = ref(false)
const showAdminToken = ref(false)
const changingPw = ref(false)
const services = ref<Record<string, string> | null>(null)
const loadingStatus = ref(false)
const stats = ref<any>(null)
const loadingStats = ref(false)
const shares = ref<any[]>([])
const shareUsername = ref('')
const sharing = ref(false)
const logs = ref<any[]>([])
const showDeleteConfirm = ref(false)
const destroyConfirmName = ref('')
const deleting = ref(false)

interface DestroyStep { step: string; label: string; status: string; message: string }
const destroySteps = ref<DestroyStep[]>([])
let destroyEs: EventSource | null = null

const DESTROY_LABELS: Record<string, string> = {
  destroy_container: 'Stop & delete container',
  destroy_cloudflare: 'Remove Cloudflare tunnel & DNS',
  destroy_github: 'Delete GitHub repo',
  destroy_db: 'Remove app record',
}

const appId = parseInt(route.params.id as string)
const isOwnerOrAdmin = computed(() => app.value && (app.value.owner_id === auth.user?.id || auth.isAdmin))
const statusType = computed((): 'success' | 'info' | 'error' | 'default' | 'warning' => {
  const m: Record<string, any> = { running: 'success', creating: 'info', error: 'error' }
  return m[app.value?.status] || 'default'
})

function linkType(key: string): 'primary' | 'info' | 'success' | 'warning' | 'default' {
  const m: Record<string, any> = { app: 'primary', desktop: 'info', code: 'success', terminal: 'warning' }
  return m[key] || 'default'
}

function memColor(pct: number) { return pct > 80 ? '#ef4444' : pct > 60 ? '#f59e0b' : '#22c55e' }

async function copyAdminToken() {
  if (app.value?.admin_token) {
    await navigator.clipboard.writeText(app.value.admin_token)
    message.success('Admin token copied')
  }
}

function subscribeDestroyProgress() {
  destroyEs?.close()
  destroySteps.value = []
  destroyEs = new EventSource(auth.sseUrl(`/api/apps/${appId}/progress`))
  destroyEs.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.step === 'stream_end') {
      destroyEs?.close()
      // App is gone from DB — go back to dashboard
      message.success('App destroyed')
      router.push('/')
      return
    }
    if (msg.step === 'heartbeat') return
    const existing = destroySteps.value.find(s => s.step === msg.step)
    if (existing) {
      existing.status = msg.status
      existing.message = msg.message
    } else {
      destroySteps.value.push({
        step: msg.step,
        label: DESTROY_LABELS[msg.step] || msg.step,
        status: msg.status,
        message: msg.message,
      })
    }
  }
  destroyEs.onerror = () => destroyEs?.close()
}

async function loadApp() {
  loading.value = true
  try {
    const { data } = await api.get(`/apps/${appId}`)
    app.value = data
    if (data.status === 'destroying') {
      subscribeDestroyProgress()
    } else {
      await loadShares()
    }
  } catch { message.error('Failed to load app') }
  finally { loading.value = false }
}

async function loadStatuses() {
  loadingStatus.value = true
  try {
    const { data } = await api.get(`/apps/${appId}/status`)
    services.value = data.services
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  finally { loadingStatus.value = false }
}

async function loadStats() {
  loadingStats.value = true
  try {
    const { data } = await api.get(`/apps/${appId}/stats`)
    stats.value = data
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  finally { loadingStats.value = false }
}

async function loadShares() {
  try { const { data } = await api.get(`/apps/${appId}/shares`); shares.value = data }
  catch {}
}

async function loadLogs() {
  try { const { data } = await api.get(`/apps/${appId}/logs`); logs.value = data }
  catch { message.error('Failed to load logs') }
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
  message.success('Copied to clipboard')
}

async function handleChangePassword() {
  changingPw.value = true
  try {
    const { data } = await api.patch(`/apps/${appId}/password`, {})
    app.value.password = data.password
    showPassword.value = true
    message.success(`New password: ${data.password}`)
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  finally { changingPw.value = false }
}

async function handleShare() {
  sharing.value = true
  try {
    await api.post(`/apps/${appId}/shares`, { username: shareUsername.value || null })
    shareUsername.value = ''
    await loadShares()
    message.success('Shared!')
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  finally { sharing.value = false }
}

async function handleShareEveryone() {
  sharing.value = true
  try {
    await api.post(`/apps/${appId}/shares`, { username: null })
    await loadShares()
    message.success('Shared with everyone!')
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
  finally { sharing.value = false }
}

async function handleDelete() {
  deleting.value = true
  try {
    await api.delete(`/apps/${appId}`)
    showDeleteConfirm.value = false
    app.value = { ...app.value, status: 'destroying' }
    subscribeDestroyProgress()
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed')
    deleting.value = false
  }
}

async function restartService(service: string) {
  try {
    await api.post(`/apps/${appId}/restart/${service}`)
    message.success(`Restarting ${service}`)
    setTimeout(loadStatuses, 3000)
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
}

const serviceColumns = [
  { title: 'Service', key: 'service' },
  {
    title: 'Status', key: 'status',
    render: (row: any) => h(NTag, { type: row.status === 'active' ? 'success' : 'error', size: 'small' }, { default: () => row.status }),
  },
  {
    title: 'Restart', key: 'action',
    render: (row: any) => h(NButton, { size: 'small', onClick: () => restartService(row.service), disabled: !isOwnerOrAdmin.value }, { default: () => 'Restart' }),
  },
]

const serviceRows = computed(() =>
  services.value ? Object.entries(services.value).map(([service, status]) => ({ service, status })) : []
)

async function removeShare(shareId: number) {
  try { await api.delete(`/apps/${appId}/shares/${shareId}`); await loadShares() }
  catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
}

const shareColumns = [
  { title: 'Type', key: 'type', render: (row: any) => h(NTag, { size: 'small', type: row.type === 'everyone' ? 'warning' : 'info' }, { default: () => row.type }) },
  { title: 'User', key: 'username', render: (row: any) => row.username || '(everyone)' },
  { title: 'Remove', key: 'action', render: (row: any) => h(NButton, { size: 'small', type: 'error', text: true, onClick: () => removeShare(row.id) }, { default: () => 'Remove' }) },
]

onMounted(loadApp)
onUnmounted(() => destroyEs?.close())
</script>
