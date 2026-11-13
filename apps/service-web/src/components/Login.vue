<script setup>
import { ref } from 'vue';
import { post, saveSession } from '../api.js';
import Icon from './Icon.vue';
defineProps({ config: Object });
const emit = defineEmits(['login']);
const username = ref(''),
  password = ref(''),
  error = ref(''),
  busy = ref(false);
async function login() {
  error.value = '';
  busy.value = true;
  try {
    const result = await post('/auth/login', {
      username: username.value.trim(),
      password: password.value,
    });
    if (!['SERVICE', 'ADMIN'].includes(result.user.role)) {
      saveSession(result);
      try {
        await post('/auth/logout', {});
      } catch {}
      saveSession(null);
      error.value = '此账号没有客服工作台权限，请使用人工客服或管理员账号。';
      return;
    }
    emit('login', result);
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="service-login">
    <div class="service-login-art">
      <div class="brand">
        <div class="brand-icon"><Icon name="headset" :size="28" /></div>
        <div><strong>翱翔车险</strong><small>人工客服工作台</small></div>
      </div>
      <div class="service-story">
        <span class="eyebrow">PERSONAL SERVICE</span>
        <h1>接住每一个问题，<br />服务每一份安心。</h1>
        <p>智能报价与人工服务，在这里自然衔接。</p>
        <div class="sample-chat">
          <div class="sample-row">
            <span class="sample-avatar"><Icon name="car" :size="22" /></span>
            <div>你好，我想咨询摩托车保险。</div>
          </div>
          <div class="sample-row reply">
            <div>您好，人工客服已为您接入，<br />我来协助您核对投保资料。</div>
            <span class="sample-avatar"><Icon name="headset" :size="22" /></span>
          </div>
          <div class="sample-status"><span></span>让业务接待更有温度</div>
        </div>
      </div>
      <span class="login-art-footer">资料 · 会话 · 业务跟进</span>
    </div>
    <section class="login-form-wrap">
      <form class="login-form" @submit.prevent="login">
        <span class="eyebrow">CUSTOMER SERVICE</span>
        <h2>登录客服工作台</h2>
        <p class="muted">使用人工客服或总部管理员账号登录</p>
        <div v-if="config.mode === 'demo'" class="notice amber">演示环境 · 不用于真实承保办理</div>
        <label
          >登录账号<input
            v-model="username"
            required
            autocomplete="username"
            placeholder="输入客服账号" /></label
        ><label
          >登录密码<input
            v-model="password"
            type="password"
            required
            autocomplete="current-password"
            placeholder="输入登录密码"
        /></label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <button class="button primary login-submit" :disabled="busy">
          {{ busy ? '登录中…' : '开始接待' }}<Icon name="arrow" :size="18" />
        </button>
        <div class="login-security"><Icon name="lock" :size="14" />会话与资料按授权范围展示</div>
      </form>
    </section>
  </div>
</template>
