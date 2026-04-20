<template>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f0f13">
    <n-card style="width:400px;border-radius:16px" :bordered="false">
      <div style="text-align:center;margin-bottom:32px">
        <img src="/geocam-logo.png" style="height:52px;width:auto;object-fit:contain;margin-bottom:10px" alt="Geocam" />
        <n-text style="display:block;font-size:17px;font-weight:600;color:#a5b4fc">App Manager</n-text>
        <n-text depth="3" style="display:block;margin-top:4px;font-size:13px">Sign in to your account</n-text>
      </div>
      <n-form @submit.prevent="handleLogin">
        <n-form-item label="Email">
          <n-input v-model:value="form.email" type="email" placeholder="admin@geocam.io" size="large" />
        </n-form-item>
        <n-form-item label="Password">
          <n-input
            v-model:value="form.password"
            type="password"
            placeholder="••••••••"
            size="large"
            show-password-on="click"
          />
        </n-form-item>
        <n-button type="primary" block size="large" :loading="loading" attr-type="submit" style="margin-top:8px">
          Sign In
        </n-button>
      </n-form>
      <n-divider>or</n-divider>
      <n-button block size="large" @click="$router.push('/register')">Create Account</n-button>
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
const form = ref({ email: '', password: '' })

async function handleLogin() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.post('/auth/login', form.value)
    auth.setAuth(data.access_token, data.user)
    router.push('/')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>
