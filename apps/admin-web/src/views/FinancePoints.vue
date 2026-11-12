<script setup>
import { ref, onMounted, computed } from 'vue';
import { get, post, uid } from '../api.js';
import { money, date, orderAmount } from '../domain.js';
import Icon from '../components/Icon.vue';
import EmptyState from '../components/EmptyState.vue';
import StatusBadge from '../components/StatusBadge.vue';
import Modal from '../components/Modal.vue';
const props = defineProps({ page: String, user: Object, notify: Function });
const data = ref({ items: [] }),
  busy = ref(false),
  error = ref(''),
  form = ref(null),
  saving = ref(false),
  users = ref([]);
let adjustmentKey = '',
  adjustmentPayload = '';
const finance = computed(() => props.page === 'finance');
const adjustable = computed(() => ['ADMIN', 'FINANCE'].includes(props.user.role));
async function reload() {
  busy.value = true;
  error.value = '';
  try {
    data.value = await get(finance.value ? '/finance' : '/points');
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function openAdjust() {
  form.value = { userId: '', delta: '', reason: '' };
  adjustmentKey = '';
  adjustmentPayload = '';
  try {
    users.value = (await get('/users?page=1&size=100')).items || [];
  } catch (e) {
    props.notify(e.message, 'error');
  }
}
async function save() {
  if (!Number.isInteger(Number(form.value.delta)) || Number(form.value.delta) === 0) {
    props.notify('请输入非零整数积分。', 'error');
    return;
  }
  const payload = JSON.stringify({ ...form.value, delta: Number(form.value.delta) });
  if (payload !== adjustmentPayload) {
    adjustmentPayload = payload;
    adjustmentKey = uid();
  }
  saving.value = true;
  try {
    await post('/points/adjust', {
      ...form.value,
      delta: Number(form.value.delta),
      idempotencyKey: adjustmentKey,
    });
    form.value = null;
    props.notify('积分调整已记录。');
    await reload();
  } catch (e) {
    props.notify(e.message, 'error');
  } finally {
    saving.value = false;
  }
}
onMounted(reload);
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <span class="eyebrow">{{ finance ? 'PERFORMANCE' : 'POINTS LEDGER' }}</span>
        <h1>{{ finance ? '业绩与佣金' : '积分管理' }}</h1>
        <p>
          {{
            finance
              ? '基于订单冻结政策计算，查看权限范围内的业务汇总。'
              : '查看本人积分账本；授权财务可为指定用户登记调整。'
          }}
        </p>
      </div>
      <button v-if="!finance && adjustable" class="button primary" @click="openAdjust">
        <Icon name="plus" :size="17" />登记积分调整</button
      ><button v-else class="button" @click="reload" :disabled="busy">
        <Icon name="refresh" :size="16" />刷新
      </button>
    </div>
    <div v-if="error" class="notice error">{{ error }}</div>
    <div class="stats-grid two">
      <template v-if="finance"
        ><article class="stat-card">
          <div class="stat-top">
            <span>订单保费汇总</span><span class="stat-icon orange"><Icon name="chart" /></span>
          </div>
          <strong class="currency">¥ {{ money(data.premium) }}</strong>
          <p>不等同于实收金额</p>
        </article>
        <article class="stat-card">
          <div class="stat-top">
            <span>预估佣金</span><span class="stat-icon green"><Icon name="gift" /></span>
          </div>
          <strong class="currency">¥ {{ money(data.estimatedCommission) }}</strong>
          <p>按订单冻结的政策比例统计</p>
        </article></template
      ><template v-else
        ><article class="stat-card">
          <div class="stat-top">
            <span>我的积分余额</span><span class="stat-icon orange"><Icon name="gift" /></span>
          </div>
          <strong>{{ data.balance ?? '—' }}<small>积分</small></strong>
          <p>{{ user.name }} · 当前账号</p>
        </article>
        <article class="card side-help">
          <h3>每一笔变动都有记录</h3>
          <p>
            积分调整需要填写原因并保留操作审计。自动赠送、兑换商品和有效期规则在业务确认后配置。
          </p>
        </article></template
      >
    </div>
    <div class="notice subtle" v-if="finance">
      <Icon name="info" :size="17" />此页面用于业务统计；未接入真实资金支付、佣金发放或银行结算。
    </div>
    <div class="card">
      <div class="card-header">
        <h3>{{ finance ? '订单佣金明细' : '我的积分明细' }}</h3>
        <button v-if="!finance" class="icon-button" aria-label="刷新积分" @click="reload">
          <Icon name="refresh" :size="17" />
        </button>
      </div>
      <div v-if="busy" class="loading-line">正在加载…</div>
      <div class="table-wrap" v-if="data.items?.length">
        <table v-if="finance">
          <thead>
            <tr>
              <th>订单号</th>
              <th>所属组织</th>
              <th>订单保费</th>
              <th>政策比例</th>
              <th>预估佣金</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in data.items" :key="o.id || o.orderNo">
              <td class="mono">{{ o.orderNo }}</td>
              <td>{{ o.orgName || '—' }}</td>
              <td>{{ orderAmount(o.totalPremium) }}</td>
              <td>{{ o.rate || 0 }}%</td>
              <td class="money">¥ {{ money(o.commission) }}</td>
              <td><StatusBadge :value="o.status" /></td>
            </tr>
          </tbody>
        </table>
        <table v-else>
          <thead>
            <tr>
              <th>变动时间</th>
              <th>积分变动</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in data.items" :key="p.id">
              <td>{{ date(p.createdAt) }}</td>
              <td :class="Number(p.delta) > 0 ? 'green-text' : 'red-text'">
                <b>{{ Number(p.delta) > 0 ? '+' : '' }}{{ p.delta }}</b>
              </td>
              <td>{{ p.reason }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else-if="!busy"
        :title="finance ? '暂无佣金明细' : '暂无积分变动'"
        :text="
          finance ? '产生订单并匹配有效政策后，将记录统计明细。' : '积分变动将按时间保存在此处。'
        "
      />
    </div>
    <Modal v-if="form" title="登记积分调整" @close="form = null"
      ><form @submit.prevent="save">
        <div class="form-grid">
          <label class="full"
            >用户 ID<input
              v-model="form.userId"
              required
              list="points-user-list"
              placeholder="选择用户，或粘贴其 ID"
            /><datalist id="points-user-list">
              <option v-for="u in users" :key="u.id" :value="u.id">
                {{ u.name }} · {{ u.username || '微信用户' }}
              </option>
            </datalist></label
          ><label class="full"
            >调整积分<input
              v-model="form.delta"
              type="number"
              step="1"
              required
              placeholder="正数增加，负数扣减" /></label
          ><label class="full"
            >调整原因<textarea v-model="form.reason" required maxlength="1000" rows="3" />
          </label>
        </div>
        <p class="form-help">后端校验用户范围与可扣余额，调整将记录审计。</p>
        <div class="form-actions">
          <button type="button" class="button" @click="form = null">取消</button
          ><button class="button primary" :disabled="saving">
            {{ saving ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form></Modal
    >
  </section>
</template>
