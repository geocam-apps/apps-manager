<template>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f0f13">
    <n-card style="width:400px;border-radius:16px" :bordered="false">
      <div style="text-align:center;margin-bottom:32px">
        <n-text style="font-size:28px;font-weight:700;color:#6366f1">Apps Manager</n-text>
        <n-text depth="3" style="display:block;margin-top:8px">Create your account</n-text>
      </div>
      <n-form @submit.prevent="handleRegister">
        <n-form-item label="Username">
          <n-input v-model:value="form.username" placeholder="johndoe" size="large" />
        </n-form-item>
        <n-form-item label="Email">
          <n-input v-model:value="form.email" type="email" placeholder="john@example.com" size="large" />
        </n-form-item>
        <n-form-item label="Password">
          <n-input
            v-model:value="form.password"
            type="password"
            placeholder="min 6 characters"
            size="large"
            show-password-on="click"
          />
        </n-form-item>
        <n-button type="primary" block size="large" :loading="loading" attr-type="submit" style="margin-top:8px">
          Create Account
        </n-button>
      </n-form>
      <n-divider>or</n-divider>
      <n-button block size="large" @click="$router.push('/login')">Sign In Instead</n-button>
      <n-alert v-if="error" type="error" :title="error" style="margin-top:16px" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const error = ref('')
const form = ref({ username: '', email: '', password: '' })

async function handleRegister() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.post('/auth/register', form.value)
    auth.setAuth(data.access_token, data.user)
    router.push('/')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>
