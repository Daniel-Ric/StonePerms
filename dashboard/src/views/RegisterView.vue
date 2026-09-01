<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { useStonePermsStore } from '@/stores/stoneperms'

const router = useRouter()
const store = useStonePermsStore()
const username = ref('')
const password = ref('')
const confirmation = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (password.value.length < 12) {
    error.value = 'Use at least 12 characters for your password.'
    return
  }
  if (password.value !== confirmation.value) {
    error.value = 'The passwords do not match.'
    return
  }
  loading.value = true
  try {
    await store.register(username.value.trim(), password.value)
    await router.replace('/')
  } catch (cause) {
    error.value = cause.userMessage || cause.message || 'The account could not be created.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-context">
      <div class="login-brand">
        <img src="/stoneperms-logo.png" alt="" />
        <div><strong>STONEPERMS</strong><span>FOR ENDSTONE</span></div>
      </div>
      <div class="login-copy">
        <h1>Your servers, one permission workspace</h1>
        <p>Connect an Endstone server, then manage players, groups, tracks, chat, and nametags.</p>
      </div>
    </section>
    <section class="login-form-wrap">
      <form class="login-form" @submit.prevent="submit">
        <h2>Create account</h2>
        <p>Create your StonePerms login, then pair your first server from the dashboard.</p>
        <div class="field">
          <label for="username">Username</label>
          <input
            id="username"
            v-model="username"
            autocomplete="username"
            required
            minlength="3"
            maxlength="32"
            pattern="[-A-Za-z0-9_.]+"
          />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            minlength="12"
          />
          <small>At least 12 characters.</small>
        </div>
        <div class="field">
          <label for="confirmation">Repeat password</label>
          <input
            id="confirmation"
            v-model="confirmation"
            type="password"
            autocomplete="new-password"
            required
          />
        </div>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="button primary full" type="submit" :disabled="loading">
          <AppIcon :name="loading ? 'refresh' : 'lock'" />
          {{ loading ? 'Creating account…' : 'Create account' }}
        </button>
        <p class="login-alternate">
          Already registered? <RouterLink to="/login">Sign in</RouterLink>
        </p>
        <div class="login-security">
          <AppIcon name="shield" />
          <span>Your password is used to sign in and isn't saved in this browser.</span>
        </div>
      </form>
    </section>
  </main>
</template>
