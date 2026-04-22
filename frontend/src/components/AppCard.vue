<template>
  <n-card
    :bordered="false"
    style="border-radius:12px;background:#1c1c23;border:1px solid #2a2a35"
    hoverable
  >
    <template #header>
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-badge :type="statusColor" dot />
          <n-text style="font-size:16px;font-weight:600">{{ app.name }}</n-text>
        </n-space>
        <n-tag :type="statusColor" size="small">{{ app.status }}</n-tag>
      </n-space>
    </template>
    <template #header-extra>
      <n-button text @click="$router.push(`/apps/${app.id}`)">Details</n-button>
    </template>

    <n-space vertical :size="8">
      <n-text depth="3" style="font-size:12px">Owner: {{ app.owner_username }}</n-text>
      <n-text depth="3" style="font-size:12px">
        Created: {{ new Date(app.created_at).toLocaleDateString() }}
      </n-text>

      <!-- Progress for creating apps -->
      <div v-if="app.status === 'creating'" style="margin-top:4px">
        <n-space align="center" style="margin-bottom:8px">
          <n-spin size="small" />
          <n-text depth="3" style="font-size:12px">{{ currentStep }}</n-text>
        </n-space>
        <n-progress
          type="line"
          :percentage="progressPct"
          :color="'#6366f1'"
          :rail-color="'#2a2a35'"
          :height="4"
          :show-indicator="false"
        />
        <n-button
          text
          size="small"
          style="margin-top:6px;color:#6366f1"
          @click="$emit('track-progress', app)"
        >
          View full progress →
        </n-button>
      </div>

      <n-divider v-if="app.status !== 'creating'" style="margin:8px 0" />

      <!-- Links (only when running) -->
      <n-space v-if="app.status === 'running'" :wrap="true">
        <template v-for="(url, key) in app.urls" :key="key">
          <n-button v-if="String(key) !== 'ssh'" size="small" tag="a" :href="String(url)" target="_blank" :type="linkType(String(key))">
            {{ key }}
          </n-button>
        </template>
      </n-space>

      <!-- SSH / SFTP commands -->
      <div v-if="app.ssh_command && app.status === 'running'" style="margin-top:2px">
        <n-space align="center">
          <n-button text size="small" @click="copySSH" :style="copied === 'ssh' ? 'color:#22c55e' : ''">
            {{ copied === 'ssh' ? '✓ Copied' : 'SSH' }}
          </n-button>
          <n-button text size="small" @click="copySFTP" :style="copied === 'sftp' ? 'color:#22c55e' : ''">
            {{ copied === 'sftp' ? '✓ Copied' : 'SFTP' }}
          </n-button>
          <n-button text size="small" tag="a" href="https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/" target="_blank" style="font-size:10px;color:#6366f1">cloudflared ↗</n-button>
        </n-space>
      </div>

      <!-- Password -->
      <div v-if="app.password && app.status === 'running'" style="margin-top:4px">
        <n-space align="center">
          <n-text depth="3" style="font-size:12px">Password:</n-text>
          <n-tag v-if="showPassword" size="small" style="font-family:monospace">{{ app.password }}</n-tag>
          <n-button v-else text size="small" @click="showPassword = true">Show</n-button>
          <n-button text size="small" @click="copyPassword" :style="copied === 'password' ? 'color:#22c55e' : ''">
            {{ copied === 'password' ? '✓ Copied' : 'Copy' }}
          </n-button>
          <n-button text size="small" @click="handleChangePassword" :loading="changingPw">Change</n-button>
        </n-space>
      </div>

      <!-- Error -->
      <n-alert v-if="app.status === 'error'" type="error" :title="app.error_message || 'Provisioning failed'" size="small" />
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const props = defineProps<{ app: any }>()
const emit = defineEmits(['refresh', 'track-progress'])
const router = useRouter()
const message = useMessage()
const auth = useAuthStore()

const showPassword = ref(false)
const changingPw = ref(false)
const copied = ref('')

function flashCopied(key: string) {
  copied.value = key
  setTimeout(() => { copied.value = '' }, 1500)
}
const currentStep = ref('Provisioning...')
const progressPct = ref(5)

const STEP_ORDER = ['container', 'base', 'desktop', 'cloudflare', 'github', 'claude_code_web', 'done']
const STEP_LABELS: Record<string, string> = {
  container: 'Creating container',
  base: 'Installing packages',
  desktop: 'Setting up desktop',
  cloudflare: 'Configuring tunnel',
  github: 'Creating repo',
  claude_code_web: 'Starting Claude Code',
  done: 'Finishing up',
}

let es: EventSource | null = null

function startProgress() {
  if (props.app.status !== 'creating') return
  es = new EventSource(auth.sseUrl(`/api/apps/${props.app.id}/progress`))
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.step === 'stream_end') {
      es?.close()
      emit('refresh')
      return
    }
    if (msg.step === 'heartbeat' || msg.step === 'error') return
    const idx = STEP_ORDER.indexOf(msg.step)
    if (idx >= 0) {
      progressPct.value = Math.round(((idx + (msg.status === 'done' ? 1 : 0.5)) / STEP_ORDER.length) * 100)
      currentStep.value = STEP_LABELS[msg.step] || msg.step
    }
  }
  es.onerror = () => es?.close()
}

const statusColor = computed((): 'success' | 'info' | 'error' | 'warning' | 'default' => {
  const map: Record<string, 'success' | 'info' | 'error' | 'warning' | 'default'> = {
    running: 'success', creating: 'info', error: 'error', stopped: 'warning', destroying: 'warning',
  }
  return map[props.app.status] || 'default'
})

function linkType(key: string): 'primary' | 'info' | 'success' | 'warning' | 'default' {
  const map: Record<string, 'primary' | 'info' | 'success' | 'warning' | 'default'> = {
    app: 'primary', desktop: 'info', code: 'success', terminal: 'warning',
  }
  return map[key] || 'default'
}

function copyPassword() {
  navigator.clipboard.writeText(props.app.password)
  flashCopied('password')
}

function copySSH() {
  navigator.clipboard.writeText(props.app.ssh_command)
  flashCopied('ssh')
}

function copySFTP() {
  navigator.clipboard.writeText(props.app.sftp_command)
  flashCopied('sftp')
}

async function handleChangePassword() {
  changingPw.value = true
  try {
    const { data } = await api.patch(`/apps/${props.app.id}/password`, {})
    message.success(`New password: ${data.password}`)
    emit('refresh')
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to change password')
  } finally {
    changingPw.value = false
  }
}

onMounted(startProgress)
onUnmounted(() => es?.close())
</script>
