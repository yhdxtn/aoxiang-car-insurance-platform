<script setup>
import { ref, onMounted, computed } from 'vue';
import { get, patch, query } from '../api.js';
import {
  money,
  date,
  vehicleTypes,
  nextOrderStates,
  orderStateOptions,
  orderAmount,
  statusName,
} from '../domain.js';
import Icon from '../components/Icon.vue';
import StatusBadge from '../components/StatusBadge.vue';
import EmptyState from '../components/EmptyState.vue';
import Modal from '../components/Modal.vue';
import Pagination from '../components/Pagination.vue';
const props = defineProps({ user: Object, notify: Function });
const data = ref({ items: [], total: 0 }),
  page = ref(1),
  search = ref(''),
  status = ref(''),
  busy = ref(false),
  error = ref(''),
  detail = ref(null),
  statusForm = ref({ status: '', note: '', policyNo: '' }),
  saving = ref(false);
const editable = computed(() => ['ADMIN', 'AGENT'].includes(props.user.role));
const states = computed(() => orderStateOptions(detail.value, props.user.role));
async function reload(p = page.value) {
  page.value = p;
  busy.value = true;
  error.value = '';
  try {
    data.value = await get(
      '/orders?' + query({ page: p, size: 20, search: search.value, status: status.value }),
    );
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function open(item) {
  try {
    detail.value = await get('/orders/' + item.id);
    statusForm.value = {
      status: orderStateOptions(detail.value, props.user.role)[0] || '',
      note: '',
      policyNo: detail.value.policyNo || '',
      totalPremium:
        !detail.value.quoteId && props.user.role === 'ADMIN'
          ? (detail.value.totalPremium ?? '')
          : undefined,
    };
  } catch (e) {
    props.notify(e.message, 'error');
  }
}
async function update() {
  if (!statusForm.value.note.trim()) {
    props.notify('请填写本次跟进说明。', 'error');
    return;
  }
  if (statusForm.value.status === 'COMPLETED' && !statusForm.value.policyNo.trim()) {
    props.notify('完成业务前请核实并填写保单号。', 'error');
    return;
  }
  saving.value = true;
  try {
    const body = { ...statusForm.value };
    if (body.totalPremium === '' || body.status === 'CANCELLED') delete body.totalPremium;
    else if (body.totalPremium !== undefined) body.totalPremium = String(body.totalPremium);
    detail.value = await patch(`/orders/${detail.value.id}/status`, body);
    statusForm.value.status = orderStateOptions(detail.value, props.user.role)[0] || '';
    statusForm.value.note = '';
    props.notify('订单跟进已保存。');
    await reload();
  } catch (e) {
    props.notify(e.message, 'error');
  } finally {
    saving.value = false;
  }
}
onMounted(() => reload());
defineExpose({ reload });
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <span class="eyebrow">BUSINESS ORDERS</span>
        <h1>订单管理</h1>
        <p>跟踪每笔投保申请，保留完整业务记录。</p>
      </div>
      <button class="button" @click="reload()" :disabled="busy">
        <Icon name="refresh" :size="16" />刷新
      </button>
    </div>
    <div class="card">
      <form class="toolbar" @submit.prevent="reload(1)">
        <div class="search-input">
          <Icon name="search" :size="18" /><input
            v-model="search"
            placeholder="订单号 / 车牌号 / 客户姓名 / 车架号 / 保单号"
          />
        </div>
        <select v-model="status" aria-label="订单状态">
          <option value="">全部状态</option>
          <option
            v-for="s in ['PENDING_REVIEW', 'PROCESSING', 'COMPLETED', 'CANCELLED']"
            :value="s"
          >
            {{ statusName(s) }}
          </option></select
        ><button class="button primary">查询</button>
      </form>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-if="busy" class="loading-line">正在加载订单…</div>
      <div class="table-wrap" v-if="data.items.length">
        <table>
          <thead>
            <tr>
              <th>订单 / 创建时间</th>
              <th>车辆</th>
              <th>客户</th>
              <th>保费金额</th>
              <th>状态</th>
              <th class="right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in data.items" :key="o.id">
              <td>
                <b class="mono">{{ o.orderNo }}</b
                ><small>{{ date(o.createdAt) }}</small>
              </td>
              <td>
                <b>{{ o.plateNo || '待填写' }}</b
                ><small>{{ vehicleTypes[o.vehicleType] || '—' }} · 泰康</small>
              </td>
              <td>
                <b>{{ o.customerName || '待填写' }}</b
                ><small>{{ o.phone || '—' }}</small>
              </td>
              <td class="money">
                {{ orderAmount(o.totalPremium)
                }}<small v-if="o.demo" class="orange-text">演示报价</small>
              </td>
              <td><StatusBadge :value="o.status" /></td>
              <td class="right">
                <button class="text-link" @click="open(o)">
                  查看详情<Icon name="chevron" :size="14" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else-if="!busy"
        title="暂无匹配订单"
        text="试试其他查询条件，或等待小程序提交投保申请。"
      /><Pagination :page="page" :total="data.total" @change="reload" />
    </div>
    <Modal v-if="detail" title="订单详情与业务跟进" wide @close="detail = null"
      ><div class="detail-title">
        <div>
          <h3>{{ detail.plateNo || '车辆待填写' }}</h3>
          <p class="mono">{{ detail.orderNo }}</p>
        </div>
        <StatusBadge :value="detail.status" />
      </div>
      <div class="notice amber" v-if="detail.demo">本订单为演示数据，不可用于真实承保。</div>
      <dl class="detail-grid">
        <div>
          <dt>客户姓名</dt>
          <dd>{{ detail.customerName || '—' }}</dd>
        </div>
        <div>
          <dt>联系电话</dt>
          <dd>{{ detail.phone || '—' }}</dd>
        </div>
        <div>
          <dt>车架号</dt>
          <dd>{{ detail.vin || '—' }}</dd>
        </div>
        <div>
          <dt>车辆类型</dt>
          <dd>{{ vehicleTypes[detail.vehicleType] }}</dd>
        </div>
        <div>
          <dt>总保费</dt>
          <dd class="money">{{ orderAmount(detail.totalPremium) }}</dd>
        </div>
        <div>
          <dt>保单号</dt>
          <dd>{{ detail.policyNo || '尚未录入' }}</dd>
        </div>
        <div>
          <dt>创建时间</dt>
          <dd>{{ date(detail.createdAt) }}</dd>
        </div>
        <div>
          <dt>订单渠道</dt>
          <dd>泰康</dd>
        </div>
      </dl>
      <h3 class="section-title">业务轨迹</h3>
      <div class="timeline">
        <div v-for="(h, i) in detail.history || []" :key="h.id || i">
          <span class="timeline-dot"></span
          ><b>{{ statusName(h.status || h.toStatus) || h.action }}</b
          ><small>{{ date(h.createdAt) }} {{ h.actorName || h.operatorName || '' }}</small>
          <p>{{ h.note || h.message || '状态更新' }}</p>
        </div>
        <p v-if="!detail.history?.length" class="muted">暂无额外跟进记录。</p>
      </div>
      <form v-if="editable && states.length" class="subtle-panel" @submit.prevent="update">
        <h3>更新办理进度</h3>
        <div class="form-grid">
          <label
            >下一状态<select v-model="statusForm.status" required>
              <option v-for="s in states" :value="s">{{ statusName(s) }}</option>
            </select></label
          ><label v-if="statusForm.status === 'COMPLETED'"
            >已核实的保单号<input v-model="statusForm.policyNo" required maxlength="100" /></label
          ><label
            v-if="!detail.quoteId && user.role === 'ADMIN' && statusForm.status !== 'CANCELLED'"
            >人工核实保费（元）<input
              v-model="statusForm.totalPremium"
              type="number"
              min="0.01"
              step="0.01"
              :required="statusForm.status === 'COMPLETED' && !detail.premiumConfirmed"
              placeholder="核实后填写，最多 2 位小数" /></label
          ><label class="full"
            >跟进说明<textarea
              v-model="statusForm.note"
              required
              rows="3"
              maxlength="500"
              placeholder="填写本次处理结果或取消原因"
            />
          </label>
        </div>
        <p class="form-help">业务完成为人工核实记录；提交申请不表示已支付或保司自动出单。</p>
        <button class="button primary" :disabled="saving">
          {{ saving ? '保存中…' : '保存跟进' }}
        </button>
      </form></Modal
    >
  </section>
</template>
