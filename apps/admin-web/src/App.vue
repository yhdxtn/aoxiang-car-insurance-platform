<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { get, post, session, saveSession } from './api.js';
import { menu, userRoleName } from './domain.js';
import Icon from './components/Icon.vue';
import Login from './views/Login.vue';
import Dashboard from './views/Dashboard.vue';
import Orders from './views/Orders.vue';
import Customers from './views/Customers.vue';
import OrganizationUsers from './views/OrganizationUsers.vue';
import Policies from './views/Policies.vue';
import FinancePoints from './views/FinancePoints.vue';
import SettingsAudit from './views/SettingsAudit.vue';
const auth = ref(session()),
  config = ref({ mode: 'live', allowDemoLogin: false }),
  page = ref(location.hash.slice(1) || 'dashboard'),
  toast = ref(null),
  mobileMenu = ref(false),
  panel = ref(null),
  checking = ref(true);
let toastTimer;
const notify = (text, tone = 'success') => {
  toast.value = { text, tone };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.value = null), 6000);
};
const items = computed(() => menu.filter((m) => m.roles.includes(auth.value?.user?.role)));
const current = computed(() => items.value.find((i) => i.id === page.value) || items.value[0]);
const component = computed(
  () =>
    ({
      dashboard: Dashboard,
      orders: Orders,
      customers: Customers,
      organizations: OrganizationUsers,
      users: OrganizationUsers,
      policies: Policies,
      finance: FinancePoints,
      points: FinancePoints,
      taikang: SettingsAudit,
      audit: SettingsAudit,
      account: SettingsAudit,
    })[current.value?.id],
);
function go(id) {
  page.value = id;
  location.hash = id;
  mobileMenu.value = false;
}
function loggedIn(value) {
  auth.value = value;
  saveSession(value);
  go('dashboard');
  notify('登录成功，欢迎回来。');
}
async function logout() {
  try {
    await post('/auth/logout', {});
  } catch {}
  saveSession(null);
  auth.value = null;
}
function unauthorized() {
  auth.value = null;
  notify('登录已过期，请重新登录。', 'error');
}
function hashChanged() {
  page.value = location.hash.slice(1) || 'dashboard';
}
onMounted(async () => {
  window.addEventListener('tk:unauthorized', unauthorized);
  window.addEventListener('hashchange', hashChanged);
  try {
    config.value = await get('/public/config');
    if (auth.value) {
      const user = await get('/auth/me');
      auth.value = { ...auth.value, user };
      saveSession(auth.value);
    }
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    checking.value = false;
  }
});
onUnmounted(() => {
  clearTimeout(toastTimer);
  window.removeEventListener('tk:unauthorized', unauthorized);
  window.removeEventListener('hashchange', hashChanged);
});
const serviceUrl = import.meta.env.VITE_SERVICE_URL || 'http://localhost:5174';
</script>
<template>
  <div v-if="checking" class="boot-screen">
    <div class="spinner"></div>
    <p>正在连接车险工作台</p>
  </div>
  <Login v-else-if="!auth" :config="config" @login="loggedIn" />
  <div v-else-if="!items.length" class="boot-screen">
    <h2>此账号没有管理端权限</h2>
    <p>客服请使用客服工作台，普通用户请使用小程序。</p>
    <a class="button primary" :href="serviceUrl">打开客服工作台</a
    ><button class="button" @click="logout">退出登录</button>
  </div>
  <div v-else class="app-shell">
    <div v-if="mobileMenu" class="sidebar-shade" @click="mobileMenu = false"></div>
    <aside class="sidebar" :class="{ open: mobileMenu }">
      <div class="brand">
        <div class="brand-icon"><Icon name="shield" :size="26" /></div>
        <div><strong>泰康车险</strong><small>业务管理工作台</small></div>
      </div>
      <div class="workspace-label">WORKSPACE <span>运营管理</span></div>
      <nav>
        <button
          v-for="item in items"
          :key="item.id"
          :class="{ active: current?.id === item.id }"
          @click="go(item.id)"
        >
          <Icon :name="item.icon" /><span>{{ item.label }}</span
          ><span v-if="item.id === 'taikang'" class="tiny-tag">TK</span>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <div class="channel-card">
          <span class="channel-dot"></span>
          <div><b>专属泰康报价通道</b><small>小程序业务独立运行</small></div>
        </div>
        <button class="logout-button" @click="logout">
          <Icon name="logout" :size="17" />安全退出
        </button>
      </div>
    </aside>
    <main class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">
          <button
            class="icon-button mobile-toggle"
            aria-label="打开菜单"
            @click="mobileMenu = true"
          >
            <Icon name="menu" /></button
          ><span>业务管理</span><Icon name="chevron" :size="14" /><strong>{{
            current?.label
          }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="mode-indicator" :class="config.mode">{{
            config.mode === 'demo' ? '演示环境' : '业务环境'
          }}</span
          ><a :href="serviceUrl" class="text-link" target="_blank" rel="noopener"
            ><Icon name="headset" :size="16" />客服工作台</a
          ><span class="topbar-divider"></span>
          <div class="user-avatar">{{ auth.user.name?.slice(0, 1) || '管' }}</div>
          <div class="user-info">
            <b>{{ auth.user.name }}</b
            ><span>{{ userRoleName(auth.user) }}</span>
          </div>
        </div>
      </header>
      <div v-if="config.mode === 'demo'" class="demo-banner">
        <Icon name="info" :size="16" /><span
          >演示数据 · 当前报价用于功能演示，不能用于真实承保或付款。</span
        >
      </div>
      <div class="page-content">
        <component
          :is="component"
          :key="current.id"
          :page="current.id"
          :user="auth.user"
          :mode="config.mode"
          :notify="notify"
          ref="panel"
          @navigate="go"
        />
      </div>
      <footer class="app-footer">
        <span>泰康车险报价管理系统</span><span>仅限授权业务人员使用 · 数据按组织权限展示</span>
      </footer>
    </main>
  </div>
  <Transition name="toast"
    ><div v-if="toast" class="toast-message" :class="toast.tone" role="status">
      <Icon :name="toast.tone === 'error' ? 'info' : 'check'" :size="18" />{{ toast.text
      }}<button aria-label="关闭提示" @click="toast = null">×</button>
    </div></Transition
  >
</template>
