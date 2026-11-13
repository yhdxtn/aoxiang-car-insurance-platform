<script setup>
import { ref, onMounted } from 'vue';
import { get, post, put } from '../api.js';
import { date, userRoleName } from '../domain.js';
import Icon from '../components/Icon.vue';
import StatusBadge from '../components/StatusBadge.vue';
import EmptyState from '../components/EmptyState.vue';
import Pagination from '../components/Pagination.vue';
const props = defineProps({ page: String, user: Object, notify: Function });
const data = ref({ items: [], total: 0 }),
  busy = ref(false),
  error = ref(''),
  pageNo = ref(1),
  checking = ref(false),
  checkResult = ref(null),
  password = ref({ oldPassword: '', newPassword: '', repeat: '' });
async function reload(p = pageNo.value) {
  if (props.page === 'account') return;
  pageNo.value = p;
  busy.value = true;
  error.value = '';
  try {
    data.value = await get(
      props.page === 'audit' ? `/audit?page=${p}&size=20` : '/settings/taikang',
    );
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function check() {
  checking.value = true;
  checkResult.value = null;
  try {
    checkResult.value = await post('/settings/taikang/check', {}, { timeout: 120000 });
    await reload();
  } catch (e) {
    props.notify(e.message, 'error');
  } finally {
    checking.value = false;
  }
}
async function changePassword() {
  if (password.value.newPassword !== password.value.repeat) {
    props.notify('两次输入的新密码不一致。', 'error');
    return;
  }
  busy.value = true;
  try {
    await put('/auth/password', {
      oldPassword: password.value.oldPassword,
      newPassword: password.value.newPassword,
    });
    password.value = { oldPassword: '', newPassword: '', repeat: '' };
    props.notify('密码已修改，请使用新密码登录。');
  } catch (e) {
    props.notify(e.message, 'error');
  } finally {
    busy.value = false;
  }
}
onMounted(() => reload());
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <span class="eyebrow">{{
          page === 'audit'
            ? 'AUDIT TRAIL'
            : page === 'account'
              ? 'ACCOUNT SECURITY'
              : 'CHANNEL CONFIGURATION'
        }}</span>
        <h1>
          {{ page === 'audit' ? '操作日志' : page === 'account' ? '账号安全' : '泰康报价配置' }}
        </h1>
        <p>
          {{
            page === 'audit'
              ? '查看关键业务操作和权限变更记录。'
              : page === 'account'
                ? '管理当前账号的登录密码。'
                : '查看独立泰康通道状态，显式检查保险账号登录。'
          }}
        </p>
      </div>
      <button v-if="page !== 'account'" class="button" @click="reload()" :disabled="busy">
        <Icon name="refresh" :size="16" />刷新状态
      </button>
    </div>
    <div v-if="error" class="notice error">{{ error }}</div>
    <template v-if="page === 'taikang'"
      ><div class="channel-settings-layout">
        <section class="card">
          <div class="channel-header">
            <div class="channel-logo">TK</div>
            <div>
              <h2>泰康在线</h2>
              <p>独立车险报价通道</p>
            </div>
            <span class="badge" :class="data.enabled ? 'green' : 'gray'">{{
              data.enabled ? '已启用' : '未启用'
            }}</span>
          </div>
          <dl class="settings-list">
            <div>
              <dt>当前运行模式</dt>
              <dd>{{ data.mode === 'demo' ? '演示模式' : '真实业务模式' }}</dd>
            </div>
            <div>
              <dt>接口网关配置</dt>
              <dd>{{ data.gatewayConfigured ? '已配置' : '未配置' }}</dd>
            </div>
            <div>
              <dt>保险账号</dt>
              <dd>{{ data.accountMasked || '由服务器环境配置' }}</dd>
            </div>
            <div>
              <dt>最近登录状态</dt>
              <dd><StatusBadge :value="data.loginStatus || '未检查'" /></dd>
            </div>
          </dl>
          <div class="channel-actions">
            <button class="button primary" :disabled="checking || busy" @click="check">
              <Icon name="shield" :size="17" />{{ checking ? '正在检查登录…' : '检查泰康账号登录' }}
            </button>
            <p>{{ data.message || '此操作只检查登录，不创建保险订单。' }}</p>
          </div>
          <div
            v-if="checkResult"
            class="notice"
            :class="checkResult.status === 'ONLINE' ? 'success' : 'amber'"
          >
            <b>{{ checkResult.status }}</b
            ><span>{{ checkResult.message }}</span>
          </div>
        </section>
        <aside class="card side-help">
          <span class="eyebrow">CONNECTION NOTES</span>
          <h3>凭据与业务边界</h3>
          <p>保险账号、密码和网关密钥由服务端环境安全配置，网页不返回密码。</p>
          <div class="help-item">
            <Icon name="car" />
            <div>
              <b>家用车</b>
              <p>调用已接入的泰康报价协议。</p>
            </div>
          </div>
          <div class="help-item">
            <Icon name="headset" />
            <div>
              <b>货车与摩托车</b>
              <p>货车协议不支持时转人工；摩托车始终人工处理。</p>
            </div>
          </div>
          <div class="help-item">
            <Icon name="file" />
            <div>
              <b>投保申请</b>
              <p>用户确认后进入人工审核，不自动付款或出单。</p>
            </div>
          </div>
        </aside>
      </div></template
    ><template v-else-if="page === 'audit'"
      ><div class="card">
        <div class="card-header">
          <h3>关键操作记录</h3>
          <span class="muted">按当前权限展示</span>
        </div>
        <div v-if="busy" class="loading-line">正在加载审计…</div>
        <div class="table-wrap" v-if="data.items.length">
          <table>
            <thead>
              <tr>
                <th>操作时间</th>
                <th>操作人</th>
                <th>动作</th>
                <th>业务对象</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in data.items" :key="a.id">
                <td>{{ date(a.createdAt) }}</td>
                <td>{{ a.actorName || a.userName || a.actorId || '系统' }}</td>
                <td>
                  <span class="role-pill">{{ a.action }}</span>
                </td>
                <td class="mono truncate">{{ a.targetId || a.entityId || a.objectId || '—' }}</td>
                <td>{{ a.detail || a.summary || a.note || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else-if="!busy" title="暂无操作日志" /><Pagination
          :page="pageNo"
          :total="data.total"
          @change="reload"
        /></div></template
    ><template v-else
      ><div class="account-layout">
        <section class="card account-profile">
          <div class="large-avatar">{{ user.name?.slice(0, 1) }}</div>
          <h2>{{ user.name }}</h2>
          <span class="role-pill">{{ userRoleName(user) }}</span>
          <p>{{ user.orgName || '当前组织' }}</p>
          <div class="user-id">
            <small>用户 ID</small><code>{{ user.id }}</code>
          </div>
        </section>
        <form class="card password-form" @submit.prevent="changePassword">
          <h3>修改登录密码</h3>
          <p class="muted">至少 12 位，建议使用独立的强密码。</p>
          <label
            >当前密码<input
              v-model="password.oldPassword"
              type="password"
              autocomplete="current-password"
              required /></label
          ><label
            >新密码<input
              v-model="password.newPassword"
              type="password"
              autocomplete="new-password"
              required
              minlength="12"
              maxlength="128" /></label
          ><label
            >确认新密码<input
              v-model="password.repeat"
              type="password"
              autocomplete="new-password"
              required
              minlength="12"
              maxlength="128" /></label
          ><button class="button primary" :disabled="busy">
            {{ busy ? '正在保存…' : '修改密码' }}
          </button>
        </form>
      </div></template
    >
  </section>
</template>
