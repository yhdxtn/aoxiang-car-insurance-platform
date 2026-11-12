<script setup>
import { ref } from 'vue';
import { post } from '../api.js';
import Icon from '../components/Icon.vue';
defineProps({ config: Object });
const emit = defineEmits(['login']);
const username = ref(''),
  password = ref(''),
  error = ref(''),
  busy = ref(false),
  show = ref(false);
async function login() {
  error.value = '';
  busy.value = true;
  try {
    const result = await post('/auth/login', {
      username: username.value.trim(),
      password: password.value,
    });
    emit('login', result);
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="login-page">
    <section class="login-story">
      <div class="brand light">
        <div class="brand-icon"><Icon name="shield" :size="28" /></div>
        <div><strong>泰康车险</strong><small>INSURANCE WORKSPACE</small></div>
      </div>
      <div class="story-main">
        <span class="eyebrow light">一站式车险业务工作台</span>
        <h1>让每一份保障，<br />都有序抵达。</h1>
        <p>连接小程序报价、代理业务与人工服务。<br />让资料、客户与订单，在同一个工作流中衔接。</p>
        <div class="story-card">
          <div class="story-car"><Icon name="car" :size="58" /></div>
          <div>
            <span>专属报价通道</span>
            <h3>TAIKANG <b>泰康在线</b></h3>
            <small>资料确认 → 方案报价 → 投保申请</small>
          </div>
          <span class="story-check"><Icon name="check" :size="22" /></span>
        </div>
        <div class="story-features">
          <span><Icon name="shield" :size="18" />角色权限</span
          ><span><Icon name="tree" :size="18" />多级组织</span
          ><span><Icon name="clock" :size="18" />全程留痕</span>
        </div>
      </div>
      <p class="story-footer">车险业务独立系统 · 管理端</p>
    </section>
    <section class="login-form-wrap">
      <form class="login-form" @submit.prevent="login">
        <span class="eyebrow">WELCOME BACK</span>
        <h2>登录管理工作台</h2>
        <p class="muted">使用管理员、财务或代理账号登录</p>
        <div v-if="config.mode === 'demo'" class="notice amber">
          当前为演示环境，演示账号见项目 README。
        </div>
        <label
          >登录账号<input
            v-model="username"
            autocomplete="username"
            required
            maxlength="100"
            placeholder="请输入登录账号" /></label
        ><label
          >登录密码
          <div class="password-input">
            <input
              v-model="password"
              :type="show ? 'text' : 'password'"
              autocomplete="current-password"
              required
              placeholder="请输入密码"
            /><button
              type="button"
              @click="show = !show"
              :aria-label="show ? '隐藏密码' : '显示密码'"
            >
              <Icon name="eye" :size="18" />
            </button></div
        ></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button type="submit" class="button primary login-submit" :disabled="busy">
          <span v-if="busy" class="spinner small"></span>{{ busy ? '正在登录' : '进入工作台'
          }}<Icon name="arrow" :size="18" />
        </button>
        <div class="login-security"><Icon name="lock" :size="14" />仅供授权业务人员访问</div>
      </form>
      <div class="login-bottom">报价结果以保司实际核验为准</div>
    </section>
  </div>
</template>
