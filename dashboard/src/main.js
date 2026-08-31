import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/base.css'
import './assets/main.css'
import { initialisePreferences } from './composables/usePreferences'

initialisePreferences()
createApp(App).use(createPinia()).use(router).mount('#app')
