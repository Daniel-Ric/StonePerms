<script setup>
import { computed, ref } from 'vue'
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
const claimSetup = ref(false)
const claimLegacy = ref(false)
const claimMode = ref('create')
const claimUsername = ref('')
const claimPassword = ref('')
const claimPasswordConfirmation = ref('')
const loading = ref(false)
const error = ref('')
const submitLabel = computed(() => {
  if (loading.value) return 'Signing in…'
  if (method.value !== 'code') return 'Sign in'
  if (!claimSetup.value) return 'Continue'
  if (claimLegacy.value)
    return claimMode.value === 'create' ? 'Save credentials and sign in' : 'Transfer and sign in'
  return claimMode.value === 'create' ? 'Create account and connect' : 'Sign in and connect'
})

async function submit() {
  loading.value = true
  error.value = ''
  try {
    if (method.value === 'code') {
      if (
        claimSetup.value &&
        claimMode.value === 'create' &&
        claimPassword.value !== claimPasswordConfirmation.value
      ) {
        error.value = 'The passwords do not match.'
        return
      }
      const result = await store.loginWithCode(
        code.value,
        claimSetup.value
          ? {
              accountMode: claimMode.value,
              username: claimUsername.value.trim(),
              password: claimPassword.value,
            }
          : null,
      )
      if (result.accountSetupRequired) {
        claimSetup.value = true
        claimLegacy.value = Boolean(result.legacyUpgrade)
        return
      }
    } else await store.login(username.value.trim(), password.value)
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
  claimSetup.value = false
  claimLegacy.value = false
  error.value = ''
}

function selectClaimMode(value) {
  claimMode.value = value
  claimPassword.value = ''
  claimPasswordConfirmation.value = ''
  error.value = ''
}

function resetClaimCode() {
  claimSetup.value = false
  claimLegacy.value = false
  code.value = ''
  claimUsername.value = ''
  claimPassword.value = ''
  claimPasswordConfirmation.value = ''
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
              ? claimSetup
                ? claimLegacy
                  ? 'Recover this legacy login with permanent credentials or transfer its server.'
                  : 'Choose permanent credentials or connect the server to an existing account.'
                : 'Enter the code from /stoneperms web login.'
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
            :readonly="claimSetup"
            maxlength="19"
            placeholder="ABCD-EFGH-JKLM-NPQR"
            @input="updateCode"
          />
          <small>Run /stoneperms web login in the Endstone server console.</small>
        </div>
        <div v-if="method === 'code' && claimSetup" class="login-claim-setup">
          <div class="login-claim-heading">
            <div>
              <strong>{{ claimLegacy ? 'Recover legacy access' : 'Secure this server' }}</strong>
              <small>{{
                claimLegacy
                  ? 'This server still uses an account without known credentials.'
                  : 'The one-time code verified the server. Its account needs permanent access.'
              }}</small>
            </div>
            <button type="button" class="login-text-action" @click="resetClaimCode">
              Change code
            </button>
          </div>
          <div class="login-methods" role="tablist" aria-label="Server account choice">
            <button
              type="button"
              role="tab"
              :aria-selected="claimMode === 'create'"
              :class="{ 'is-active': claimMode === 'create' }"
              @click="selectClaimMode('create')"
            >
              {{ claimLegacy ? 'Set credentials' : 'New account' }}
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="claimMode === 'existing'"
              :class="{ 'is-active': claimMode === 'existing' }"
              @click="selectClaimMode('existing')"
            >
              Existing account
            </button>
          </div>
          <div class="field">
            <label for="claim-username">Username</label>
            <input
              id="claim-username"
              v-model.trim="claimUsername"
              autocomplete="username"
              required
              minlength="3"
              maxlength="32"
              pattern="[-A-Za-z0-9_.]{3,32}"
            />
            <small>Use 3–32 letters, numbers, dots, underscores, or hyphens.</small>
          </div>
          <div class="field">
            <label for="claim-password">Password</label>
            <input
              id="claim-password"
              v-model="claimPassword"
              type="password"
              :autocomplete="claimMode === 'create' ? 'new-password' : 'current-password'"
              required
              :minlength="claimMode === 'create' ? 12 : 1"
            />
            <small v-if="claimMode === 'create'">Use at least 12 characters.</small>
          </div>
          <div v-if="claimMode === 'create'" class="field">
            <label for="claim-password-confirmation">Confirm password</label>
            <input
              id="claim-password-confirmation"
              v-model="claimPasswordConfirmation"
              type="password"
              autocomplete="new-password"
              required
              minlength="12"
            />
          </div>
        </div>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="button primary full" type="submit" :disabled="loading">
          <AppIcon :name="loading ? 'refresh' : 'lock'" />{{ submitLabel }}
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
              ? claimSetup
                ? claimLegacy
                  ? 'Saving credentials upgrades the legacy account without changing server data.'
                  : 'The server is connected only after its account credentials are confirmed.'
                : 'The code works once and expires after a few minutes.'
              : "Your password is used only to sign in and isn't saved in this browser."
          }}</span>
        </div>
      </form>
    </section>
  </main>
</template>
