<template>
  <div style="min-height:100vh;background:#0f0f13">
    <n-layout-header bordered style="padding:0 24px;height:60px;display:flex;align-items:center;justify-content:space-between;background:#16161a">
      <n-space align="center" :size="10">
        <img src="/geocam-logo.png" style="height:32px;width:auto;object-fit:contain" alt="Geocam" />
        <n-text style="font-size:16px;font-weight:600;color:#a5b4fc;letter-spacing:0.02em">App Manager</n-text>
      </n-space>
      <n-space>
        <n-button text @click="$router.push('/')">← Dashboard</n-button>
        <n-text depth="3">{{ auth.user?.username }}</n-text>
      </n-space>
    </n-layout-header>

    <div style="max-width:800px;margin:0 auto;padding:32px 24px">
      <n-space justify="space-between" align="center" style="margin-bottom:24px">
        <n-text style="font-size:24px;font-weight:600">API Tokens</n-text>
        <n-button type="primary" @click="showCreate = true">+ New Token</n-button>
      </n-space>

      <n-text depth="3" style="font-size:13px;display:block;margin-bottom:24px">
        Tokens let scripts and Claude sessions authenticate with manager-api. Each token is shown once at creation — store it securely.
      </n-text>

      <n-data-table :columns="columns" :data="tokens" :loading="loading" :bordered="false"
        style="background:#1c1c23;border-radius:12px" />
    </div>

    <!-- Create modal -->
    <n-modal v-model:show="showCreate" :mask-closable="!newToken">
      <n-card style="width:480px;border-radius:16px" :title="newToken ? 'Token Created' : 'New API Token'" :bordered="false">

        <div v-if="newToken">
          <n-alert type="warning" style="margin-bottom:16px">
            Copy this token now — you won't see it again.
          </n-alert>
          <n-input-group style="margin-bottom:16px">
            <n-input :value="newToken" readonly style="font-family:monospace;font-size:12px" />
            <n-button @click="copyToken" :style="copied ? 'color:#22c55e' : ''">
              {{ copied ? '✓ Copied' : 'Copy' }}
            </n-button>
          </n-input-group>
          <n-space justify="end">
            <n-button type="primary" @click="closeCreate">Done</n-button>
          </n-space>
        </div>

        <n-form v-else @submit.prevent="handleCreate">
          <n-form-item label="Token name" feedback="e.g. 'claude for planner proto'">
            <n-input v-model:value="form.name" placeholder="my-script" />
          </n-form-item>
          <n-form-item label="Expires (optional)">
            <n-date-picker v-model:value="form.expiresTs" type="datetime" clearable style="width:100%" />
          </n-form-item>
          <n-space justify="end" style="margin-top:8px">
            <n-button @click="showCreate = false">Cancel</n-button>
            <n-button type="primary" attr-type="submit" :loading="creating">Create</n-button>
          </n-space>
        </n-form>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NButton, NTag, useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const auth = useAuthStore()
const message = useMessage()

const tokens = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const newToken = ref('')
const copied = ref(false)
const form = ref({ name: '', expiresTs: null as number | null })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/tokens')
    tokens.value = data
  } catch { message.error('Failed to load tokens') }
  finally { loading.value = false }
}

async function handleCreate() {
  if (!form.value.name.trim()) return
  creating.value = true
  try {
    const payload: any = { name: form.value.name.trim() }
    if (form.value.expiresTs) payload.expires_at = new Date(form.value.expiresTs).toISOString()
    const { data } = await api.post('/tokens', payload)
    newToken.value = data.token
    await load()
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed to create token') }
  finally { creating.value = false }
}

function copyToken() {
  navigator.clipboard.writeText(newToken.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}

function closeCreate() {
  showCreate.value = false
  newToken.value = ''
  form.value = { name: '', expiresTs: null }
}

async function revoke(id: number) {
  try {
    await api.delete(`/tokens/${id}`)
    await load()
    message.success('Token revoked')
  } catch (e: any) { message.error(e.response?.data?.detail || 'Failed') }
}

function fmt(iso: string | null) {
  return iso ? new Date(iso).toLocaleString() : '—'
}

const columns = [
  { title: 'Name', key: 'name' },
  {
    title: 'Token',
    key: 'display',
    render: (row: any) => h('span', { style: 'font-family:monospace;font-size:12px;color:#a5b4fc' }, row.display),
  },
  { title: 'Created', key: 'created_at', render: (row: any) => fmt(row.created_at) },
  { title: 'Last used', key: 'last_used_at', render: (row: any) => fmt(row.last_used_at) },
  { title: 'Expires', key: 'expires_at', render: (row: any) => fmt(row.expires_at) },
  {
    title: 'Status',
    key: 'status',
    render: (row: any) => h(NTag, { type: row.active ? 'success' : 'error', size: 'small' },
      { default: () => row.revoked_at ? 'Revoked' : row.active ? 'Active' : 'Expired' }),
  },
  {
    title: '',
    key: 'action',
    render: (row: any) => row.active
      ? h(NButton, { size: 'small', type: 'error', text: true, onClick: () => revoke(row.id) }, { default: () => 'Revoke' })
      : null,
  },
]

onMounted(load)
</script>
