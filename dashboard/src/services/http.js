import axios from 'axios'
import { runtimeConfig } from '@/config/runtime'

const http = axios.create({
  baseURL: runtimeConfig.apiBaseUrl,
  timeout: 20_000,
  withCredentials: true,
  headers: { Accept: 'application/json' },
})

function csrfCookie() {
  const pair = document.cookie
    .split(';')
    .map((value) => value.trim())
    .find(
      (value) =>
        value.startsWith('stoneperms-csrf=') || value.startsWith('__Host-stoneperms-csrf='),
    )
  return pair ? decodeURIComponent(pair.slice(pair.indexOf('=') + 1)) : ''
}

http.interceptors.request.use((config) => {
  if (['post', 'put', 'patch', 'delete'].includes(String(config.method).toLowerCase())) {
    const token = csrfCookie()
    if (token) config.headers['X-CSRF-Token'] = token
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const apiError = error.response?.data?.error
    error.userMessage =
      apiError?.message ||
      (error.code === 'ECONNABORTED'
        ? 'The request timed out.'
        : 'The StonePerms API could not be reached.')
    error.apiCode = apiError?.code || 'NETWORK_ERROR'
    const requestUrl = String(error.config?.url || '')
    const expectedAuthFailure = [
      '/v1/me',
      '/v1/auth/login',
      '/v1/auth/code',
      '/v1/auth/logout',
    ].includes(requestUrl)
    if (error.response?.status === 401 && !expectedAuthFailure) {
      window.dispatchEvent(new CustomEvent('stoneperms:unauthorised'))
    }
    return Promise.reject(error)
  },
)

export default http
