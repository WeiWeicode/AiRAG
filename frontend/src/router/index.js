import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

import LoginView from '../views/LoginView.vue'
import DashboardView from '../views/DashboardView.vue'
import RagTestView from '../views/RagTestView.vue'
import ExternalApiTestView from '../views/ExternalApiTestView.vue'
import RetrievalTestView from '../views/RetrievalTestView.vue'
import EvaluationView from '../views/EvaluationView.vue'
import PromptTestView from '../views/PromptTestView.vue'
import EmbeddingTestView from '../views/EmbeddingTestView.vue'
import FeedbackView from '../views/FeedbackView.vue'
import RoleSettingsView from '../views/RoleSettingsView.vue'
import KnowledgeBaseSettingsView from '../views/KnowledgeBaseSettingsView.vue'
import AppRegistrationSettingsView from '../views/AppRegistrationSettingsView.vue'
import ImageAuditView from '../views/ImageAuditView.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: DashboardView,
    meta: { requiresAuth: true }
  },
  {
    path: '/rag-test',
    name: 'RagTest',
    component: RagTestView,
    meta: { requiresAuth: true }
  },
  {
    path: '/external-api-test',
    name: 'ExternalApiTest',
    component: ExternalApiTestView,
    meta: { requiresAuth: true }
  },
  {
    path: '/retrieval-test',
    name: 'RetrievalTest',
    component: RetrievalTestView,
    meta: { requiresAuth: true }
  },
  {
    path: '/evaluation',
    name: 'Evaluation',
    component: EvaluationView,
    meta: { requiresAuth: true }
  },
  {
    path: '/prompt-test',
    name: 'PromptTest',
    component: PromptTestView,
    meta: { requiresAuth: true }
  },
  {
    path: '/embedding-test',
    name: 'EmbeddingTest',
    component: EmbeddingTestView,
    meta: { requiresAuth: true }
  },
  {
    path: '/feedback',
    name: 'Feedback',
    component: FeedbackView,
    meta: { requiresAuth: true }
  },
  {
    path: '/role-settings',
    name: 'RoleSettings',
    component: RoleSettingsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/knowledge-base-settings',
    name: 'KnowledgeBaseSettings',
    component: KnowledgeBaseSettingsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/app-registrations',
    name: 'AppRegistrationSettings',
    component: AppRegistrationSettingsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/image-audit',
    name: 'ImageAudit',
    component: ImageAuditView,
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Route guard
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next('/login')
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
