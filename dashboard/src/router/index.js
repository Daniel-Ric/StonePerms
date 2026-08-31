import { createRouter, createWebHistory } from 'vue-router'
import { useStonePermsStore } from '@/stores/stoneperms'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: 'Sign in' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { public: true, title: 'Create account' },
  },
  {
    path: '/',
    name: 'overview',
    component: () => import('@/views/OverviewView.vue'),
    meta: { title: 'Overview' },
  },
  {
    path: '/servers',
    name: 'servers',
    component: () => import('@/views/ServersView.vue'),
    meta: { title: 'Servers' },
  },
  {
    path: '/servers/:serverId',
    name: 'server',
    component: () => import('@/views/ServerView.vue'),
    meta: { title: 'Server', server: true },
  },
  {
    path: '/servers/:serverId/editor',
    name: 'editor',
    component: () => import('@/views/EditorView.vue'),
    meta: { title: 'Permission editor', server: true },
  },
  {
    path: '/servers/:serverId/players',
    name: 'players',
    component: () => import('@/views/PlayersView.vue'),
    meta: { title: 'Players', server: true },
  },
  {
    path: '/servers/:serverId/groups',
    name: 'groups',
    component: () => import('@/views/GroupsView.vue'),
    meta: { title: 'Groups', server: true },
  },
  {
    path: '/servers/:serverId/tracks',
    name: 'tracks',
    component: () => import('@/views/TracksView.vue'),
    meta: { title: 'Tracks', server: true },
  },
  {
    path: '/servers/:serverId/display',
    name: 'display',
    component: () => import('@/views/DisplayView.vue'),
    meta: { title: 'Chat and nametags', server: true },
  },
  {
    path: '/servers/:serverId/audit',
    name: 'server-audit',
    component: () => import('@/views/AuditView.vue'),
    meta: { title: 'Server audit', server: true },
  },
  {
    path: '/servers/:serverId/team',
    name: 'team',
    component: () => import('@/views/TeamView.vue'),
    meta: { title: 'Team access', server: true },
  },
  {
    path: '/users',
    name: 'users',
    component: () => import('@/views/UsersView.vue'),
    meta: { title: 'Web users' },
  },
  {
    path: '/audit',
    name: 'audit',
    component: () => import('@/views/AuditView.vue'),
    meta: { title: 'API audit' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: 'Settings' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: 'Not found' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const store = useStonePermsStore()
  const authenticated = await store.initialize()
  if (to.name === 'register' && !store.registrationEnabled) return { name: 'login' }
  if (!to.meta.public && !authenticated) return { name: 'login', query: { redirect: to.fullPath } }
  if (['login', 'register'].includes(to.name) && authenticated) return { name: 'overview' }
  if (to.meta.server && to.params.serverId) store.selectServer(String(to.params.serverId))
  return true
})

export default router
