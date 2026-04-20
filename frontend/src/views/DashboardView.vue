<template>
  <div style="min-height:100vh;background:#0f0f13">
    <!-- Header -->
    <n-layout-header
      bordered
      style="padding:0 24px;height:60px;display:flex;align-items:center;justify-content:space-between;background:#16161a"
    >
      <n-space align="center" :size="10">
        <img src="/geocam-logo.png" style="height:32px;width:auto;object-fit:contain" alt="Geocam" />
        <n-text style="font-size:16px;font-weight:600;color:#a5b4fc;letter-spacing:0.02em">App Manager</n-text>
      </n-space>
      <n-space>
        <n-text depth="3">{{ auth.user?.username }}</n-text>
        <n-tag v-if="auth.isAdmin" type="warning" size="small">Admin</n-tag>
        <n-button text @click="handleLogout">Logout</n-button>
      </n-space>
    </n-layout-header>

    <div style="max-width:1200px;margin:0 auto;padding:32px 24px">
      <n-space justify="space-between" align="center" style="margin-bottom:24px">
        <n-text style="font-size:24px;font-weight:600">Your Apps</n-text>
        <n-button type="primary" size="large" @click="showCreateModal = true">+ Create App</n-button>
      </n-space>

      <n-tabs type="line" animated>
        <n-tab-pane name="mine" :tab="`My Apps (${apps.my_apps.length})`">
          <AppGrid :apps="apps.my_apps" :loading="loading" @refresh="loadApps" @track-progress="openProgressModal" />
        </n-tab-pane>
        <n-tab-pane name="shared" :tab="`Shared with Me (${apps.shared_with_me.length})`">
          <AppGrid :apps="apps.shared_with_me" :loading="loading" @refresh="loadApps" @track-progress="openProgressModal" />
        </n-tab-pane>
        <n-tab-pane name="public" :tab="`Public (${apps.shared_with_everyone.length})`">
          <AppGrid :apps="apps.shared_with_everyone" :loading="loading" @refresh="loadApps" @track-progress="openProgressModal" />
        </n-tab-pane>
      </n-tabs>
    </div>

    <!-- Create / Progress Modal -->
    <n-modal v-model:show="showCreateModal" :mask-closable="!creating">
      <n-card style="width:560px;border-radius:16px" :title="creating ? `Creating ${newAppName}` : 'Create New App'" :bordered="false">
        <n-form v-if="!creating" @submit.prevent="handleCreate">
          <n-form-item label="App Name" feedback="Lowercase letters, numbers, hyphens. 3-30 chars.">
            <n-input v-model:value="newAppName" placeholder="my-app-name" size="large" />
          </n-form-item>
          <n-space justify="end" style="margin-top:16px">
            <n-button @click="showCreateModal = false">Cancel</n-button>
            <n-button type="primary" :loading="submitting" attr-type="submit">Create</n-button>
          </n-space>
        </n-form>

        <div v-else>
          <n-space align="center" style="margin-bottom:16px">
            <n-spin v-if="!createDone" size="small" />
            <n-text depth="2" style="font-size:13px">
              {{ createDone ? 'Provisioning complete!' : 'This takes ~15 minutes. You can close this and track progress from the app card.' }}
            </n-text>
          </n-space>

          <!-- Overall progress bar -->
          <n-progress
            type="line"
            :percentage="overallPct"
            :color="createDone ? '#22c55e' : '#6366f1'"
            :rail-color="'#2a2a35'"
            :height="6"
            style="margin-bottom:20px"
          />

          <n-timeline size="small">
            <n-timeline-item
              v-for="step in progressSteps"
              :key="step.step"
              :type="stepType(step.status)"
              :title="step.label"
              :content="step.message"
            />
          </n-timeline>

          <n-space justify="end" style="margin-top:16px">
            <n-button v-if="createDone" type="primary" @click="onCreateDone">Done ✓</n-button>
            <n-button v-else secondary @click="onCloseProgress">Continue in background</n-button>
          </n-space>
        </div>
      </n-card>
    </n-modal>

    <!-- Re-attach progress modal for existing creating apps -->
    <n-modal v-model:show="showProgressModal" :mask-closable="true">
      <n-card style="width:560px;border-radius:16px" :title="`Progress: ${trackingApp?.name}`" :bordered="false">
        <n-space align="center" style="margin-bottom:16px">
          <n-spin v-if="!trackingDone" size="small" />
          <n-text depth="2" style="font-size:13px">{{ trackingDone ? 'Done!' : 'Streaming live progress...' }}</n-text>
        </n-space>
        <n-progress
          type="line"
          :percentage="trackingPct"
          :color="trackingDone ? '#22c55e' : '#6366f1'"
          :rail-color="'#2a2a35'"
          :height="6"
          style="margin-bottom:20px"
        />
        <n-timeline size="small">
          <n-timeline-item
            v-for="step in trackingSteps"
            :key="step.step + step.status"
            :type="stepType(step.status)"
            :title="step.label"
            :content="step.message"
          />
        </n-timeline>
        <n-space justify="end" style="margin-top:16px">
          <n-button v-if="trackingDone" type="primary" @click="closeProgressModal">Done ✓</n-button>
          <n-button v-else secondary @click="closeProgressModal">Close</n-button>
        </n-space>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useMessage } from 'naive-ui'
import api from '../api'
import AppGrid from '../components/AppGrid.vue'

const router = useRouter()
const auth = useAuthStore()
const message = useMessage()

const loading = ref(false)
const apps = reactive({ my_apps: [] as any[], shared_with_me: [] as any[], shared_with_everyone: [] as any[] })

const showCreateModal = ref(false)
const newAppName = ref('')
const creating = ref(false)
const submitting = ref(false)
const createDone = ref(false)

// Progress modal for re-attaching to an existing creating app
const showProgressModal = ref(false)
const trackingApp = ref<any>(null)
const trackingSteps = ref<ProgressStep[]>([])
const trackingDone = ref(false)
const trackingPct = ref(0)
let trackingEs: EventSource | null = null

interface ProgressStep {
  step: string
  label: string
  status: string
  message: string
}

const STEP_ORDER = ['container', 'base', 'desktop', 'cloudflare', 'github', 'claude_code_web', 'ssh_terminal', 'done']
const STEP_LABELS: Record<string, string> = {
  container: 'Create Container',
  base: 'Install Base Packages',
  desktop: 'Setup Desktop',
  cloudflare: 'Configure Cloudflare',
  github: 'Create GitHub Repo',
  claude_code_web: 'Setup Claude Code',
  ssh_terminal: 'SSH & Browser Terminal',
  done: 'All Done',
}

const progressSteps = ref<ProgressStep[]>([])
let eventSource: EventSource | null = null

const overallPct = computed(() => {
  const doneCount = progressSteps.value.filter(s => s.status === 'done').length
  return Math.min(100, Math.round((doneCount / STEP_ORDER.length) * 100))
})

function stepType(status: string): 'success' | 'error' | 'info' | 'default' {
  if (status === 'done') return 'success'
  if (status === 'error') return 'error'
  if (status === 'running') return 'info'
  return 'default'
}

function applyProgressMsg(steps: ProgressStep[], msg: any) {
  if (msg.step === 'heartbeat' || msg.step === 'stream_end' || msg.step === 'error') return
  const existing = steps.find(s => s.step === msg.step)
  if (existing) {
    existing.status = msg.status
    existing.message = msg.message
  } else {
    steps.push({ step: msg.step, label: STEP_LABELS[msg.step] || msg.step, status: msg.status, message: msg.message })
  }
}

async function loadApps() {
  loading.value = true
  try {
    const { data } = await api.get('/apps')
    apps.my_apps = data.my_apps
    apps.shared_with_me = data.shared_with_me
    apps.shared_with_everyone = data.shared_with_everyone
  } catch {
    message.error('Failed to load apps')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newAppName.value.trim()) return
  submitting.value = true
  try {
    const { data } = await api.post('/apps', { name: newAppName.value.trim() })
    creating.value = true
    progressSteps.value = []
    createDone.value = false
    subscribeProgress(data.id, progressSteps.value, (done) => {
      createDone.value = done
      if (done) loadApps()
    }, (es) => { eventSource = es })
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to create app')
  } finally {
    submitting.value = false
  }
}

function subscribeProgress(
  appId: number,
  steps: ProgressStep[],
  onDone: (done: boolean) => void,
  setEs: (es: EventSource) => void,
) {
  const es = new EventSource(auth.sseUrl(`/api/apps/${appId}/progress`))
  setEs(es)
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.step === 'stream_end') { es.close(); onDone(true); return }
    applyProgressMsg(steps, msg)
  }
  es.onerror = () => es.close()  // don't treat connection errors as completion
}

function onCloseProgress() {
  showCreateModal.value = false
  // keep SSE open in background via AppCard
  creating.value = false
  newAppName.value = ''
  progressSteps.value = []
  createDone.value = false
  eventSource = null
  loadApps()
}

function onCreateDone() {
  eventSource?.close()
  showCreateModal.value = false
  creating.value = false
  newAppName.value = ''
  progressSteps.value = []
  createDone.value = false
  loadApps()
}

function openProgressModal(app: any) {
  trackingApp.value = app
  trackingSteps.value = []
  trackingDone.value = false
  trackingPct.value = 0
  showProgressModal.value = true
  trackingEs?.close()
  subscribeProgress(
    app.id,
    trackingSteps.value,
    (done) => {
      trackingDone.value = done
      const doneCount = trackingSteps.value.filter(s => s.status === 'done').length
      trackingPct.value = Math.min(100, Math.round((doneCount / STEP_ORDER.length) * 100))
      if (done) loadApps()
    },
    (es) => { trackingEs = es },
  )
}

function closeProgressModal() {
  trackingEs?.close()
  showProgressModal.value = false
}

function handleLogout() { auth.logout(); router.push('/login') }

onMounted(loadApps)
onUnmounted(() => { eventSource?.close(); trackingEs?.close() })
</script>
