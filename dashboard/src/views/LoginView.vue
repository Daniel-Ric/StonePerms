<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { useStonePermsStore } from '@/stores/stoneperms'

const route = useRoute()
const router = useRouter()
const store = useStonePermsStore()
const method = ref(!store.demoMode && route.query.method === 'code' ? 'code' : 'account')
const username = ref(store.demoMode ? 'demo' : '')
const password = ref(store.demoMode ? 'stoneperms-demo' : '')
const code = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    if (method.value === 'code') await store.loginWithCode(code.value)
    else await store.login(username.value.trim(), password.value)
    const destination = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(destination)
  } catch (cause) {
    error.value = cause.userMessage || cause.message || 'Sign-in failed.'
  } finally {
    loading.value = false
  }
}

function selectMethod(value) {
  method.value = value
  error.value = ''
}

function updateCode(event) {
  const value = event.target.value
    .replace(/[^A-HJ-NP-Za-hj-np-z2-9]/g, '')
    .toUpperCase()
    .slice(0, 16)
  code.value = value.match(/.{1,4}/g)?.join('-') ?? ''
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
        <h1>Permissions for your Endstone server</h1>
        <p>Players, groups, tracks, chat prefixes, suffixes, and nametags.</p>
      </div>
    </section>
    <section class="login-form-wrap">
      <form class="login-form" @submit.prevent="submit">
        <h2>Sign in</h2>
        <p>
          {{
            method === 'code'
              ? 'Enter the code from /stoneperms web login.'
              : 'Sign in to pair a server or manage your account.'
          }}
        </p>
        <div
          v-if="!store.demoMode"
          class="login-methods"
          role="tablist"
          aria-label="Sign-in method"
        >
          <button
            type="button"
            role="tab"
            :aria-selected="method === 'account'"
            :class="{ 'is-active': method === 'account' }"
            @click="selectMethod('account')"
          >
            Account
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="method === 'code'"
            :class="{ 'is-active': method === 'code' }"
            @click="selectMethod('code')"
          >
            One-time code
          </button>
        </div>
        <div v-if="method === 'account'" class="field">
          <label for="username">Username</label
          ><input
            id="username"
            v-model="username"
            autocomplete="username"
            required
            maxlength="32"
          />
        </div>
        <div v-if="method === 'account'" class="field">
          <label for="password">Password</label
          ><input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
          />
        </div>
        <div v-else class="field">
          <label for="login-code">One-time code</label
          ><input
            id="login-code"
            :value="code"
            class="login-code-input"
            autocomplete="one-time-code"
            autocapitalize="characters"
            spellcheck="false"
            required
            maxlength="19"
            placeholder="ABCD-EFGH-JKLM-NPQR"
            @input="updateCode"
          />
          <small>Run /stoneperms web login in the Endstone server console.</small>
        </div>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="button primary full" type="submit" :disabled="loading">
          <AppIcon :name="loading ? 'refresh' : 'lock'" />{{
            loading ? 'Signing in…' : method === 'code' ? 'Use code' : 'Sign in'
          }}
        </button>
        <p v-if="method === 'code'" class="login-alternate">
          Prefer an account?
          <button type="button" class="login-text-action" @click="selectMethod('account')">
            Sign in with credentials
          </button>
          <template v-if="store.registrationEnabled">
            or <RouterLink to="/register">create an account</RouterLink></template
          >.
        </p>
        <p v-else-if="store.registrationEnabled" class="login-alternate">
          New to StonePerms? <RouterLink to="/register">Create an account</RouterLink>
        </p>
        <div class="login-security">
          <AppIcon name="shield" /><span>{{
            method === 'code'
              ? 'The code works once, connects a new server when needed, and expires after a few minutes.'
              : "Your password is used only to sign in and isn't saved in this browser."
          }}</span>
        </div>
      </form>
    </section>
  </main>
</template>
