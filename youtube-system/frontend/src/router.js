import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import UploadView from './views/UploadView.vue'
import WatchView from './views/WatchView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/upload', component: UploadView },
    { path: '/watch/:id', component: WatchView },
  ],
})
