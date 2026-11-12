<script setup>
import { ref, onMounted } from 'vue';
import { get } from '../api.js';
import { money, date, orderAmount } from '../domain.js';
import Icon from '../components/Icon.vue';
import StatusBadge from '../components/StatusBadge.vue';
import EmptyState from '../components/EmptyState.vue';
const props = defineProps({ user: Object, notify: Function });
const emit = defineEmits(['navigate']);
const data = ref({}),
  orders = ref([]),
  busy = ref(false),
  error = ref('');
const day = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
});
async function reload() {
  busy.value = true;
  error.value = '';
  try {
    const [d, o] = await Promise.all([get('/dashboard'), get('/orders?size=6&page=1')]);
    data.value = d;
    orders.value = o.items || [];
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(reload);
defineExpose({ reload });
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <span class="eyebrow">OVERVIEW</span>
        <h1>工作台</h1>
        <p>你好，{{ user.name }}。这里是你的业务概览。</p>
      </div>
      <button class="button" @click="reload" :disabled="busy">
        <Icon name="refresh" :size="16" />刷新数据
      </button>
    </div>
    <div v-if="error" class="notice error">{{ error }}</div>
    <div class="welcome-banner">
      <div>
        <span>{{ day }}</span>
        <h2>把每一次咨询，推进一步。</h2>
        <p>车辆资料、客户跟进与投保申请，随时掌握。</p>
        <button class="button white" @click="emit('navigate', 'orders')">
          查看业务订单<Icon name="arrow" :size="16" />
        </button>
      </div>
      <div class="welcome-art">
        <div class="art-ring ring-a"></div>
        <div class="art-ring ring-b"></div>
        <div class="art-shield"><Icon name="shield" :size="80" /></div>
        <div class="art-mini"><Icon name="car" :size="28" />专属泰康通道</div>
      </div>
    </div>
    <div class="stats-grid">
      <article class="stat-card">
        <div class="stat-top">
          <span>业务订单</span><span class="stat-icon orange"><Icon name="orders" /></span>
        </div>
        <strong>{{ data.orders ?? '—' }}<small>笔</small></strong>
        <p>权限范围内全部订单</p>
      </article>
      <article class="stat-card">
        <div class="stat-top">
          <span>客户总数</span><span class="stat-icon blue"><Icon name="users" /></span>
        </div>
        <strong>{{ data.customers ?? '—' }}<small>位</small></strong>
        <p>已建立的客户档案</p>
      </article>
      <article class="stat-card">
        <div class="stat-top">
          <span>待人工接待</span><span class="stat-icon amber"><Icon name="headset" /></span>
        </div>
        <strong>{{ data.pendingSessions ?? '—' }}<small>个</small></strong>
        <p>等待客服处理的会话</p>
      </article>
      <article class="stat-card">
        <div class="stat-top">
          <span>订单保费汇总</span><span class="stat-icon green"><Icon name="chart" /></span>
        </div>
        <strong class="currency">¥ {{ money(data.premium) }}</strong>
        <p>订单统计金额，非实收结算</p>
      </article>
    </div>
    <div class="dashboard-bottom">
      <section class="card">
        <div class="card-header">
          <div>
            <h3>最近订单</h3>
            <p>查看最新投保申请与跟进状态</p>
          </div>
          <button class="text-link" @click="emit('navigate', 'orders')">
            全部订单<Icon name="arrow" :size="15" />
          </button>
        </div>
        <div v-if="busy" class="loading-line">正在加载…</div>
        <div class="table-wrap" v-if="orders.length">
          <table>
            <thead>
              <tr>
                <th>车辆 / 客户</th>
                <th>订单号</th>
                <th>保费</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in orders" :key="o.id">
                <td>
                  <b>{{ o.plateNo || '待补车辆' }}</b
                  ><small>{{ o.customerName || '未填写' }}</small>
                </td>
                <td class="mono">{{ o.orderNo }}</td>
                <td class="money">{{ orderAmount(o.totalPremium) }}</td>
                <td><StatusBadge :value="o.status" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState
          v-else-if="!busy"
          title="还没有业务订单"
          text="小程序提交投保申请后，订单将显示在这里。"
        />
      </section>
      <aside class="card workflow-card">
        <span class="eyebrow">WORKFLOW</span>
        <h3>标准业务流程</h3>
        <div class="workflow-step">
          <span>01</span>
          <div>
            <b>资料确认</b>
            <p>上传证件，核对车辆信息</p>
          </div>
        </div>
        <div class="workflow-step">
          <span>02</span>
          <div>
            <b>泰康方案报价</b>
            <p>按已确认资料获取保费方案</p>
          </div>
        </div>
        <div class="workflow-step">
          <span>03</span>
          <div>
            <b>投保申请与跟进</b>
            <p>人工审核后跟进办理结果</p>
          </div>
        </div>
        <div class="notice subtle">
          <Icon name="info" :size="16" /><span>摩托车业务自动转入人工客服。</span>
        </div>
        <span class="completed-note"
          >已完成业务 <b>{{ data.completedOrders ?? '—' }}</b> 笔</span
        >
      </aside>
    </div>
  </section>
</template>
