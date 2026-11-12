<script setup>
import { ref, onMounted, computed } from 'vue';
import { get, post } from '../api.js';
import { date, vehicleTypes, policyError } from '../domain.js';
import Icon from '../components/Icon.vue';
import Modal from '../components/Modal.vue';
import EmptyState from '../components/EmptyState.vue';
const props = defineProps({ user: Object, notify: Function });
const items = ref([]),
  orgs = ref([]),
  history = ref(false),
  busy = ref(false),
  error = ref(''),
  form = ref(null),
  detail = ref(null),
  saving = ref(false),
  formError = ref('');
const editable = computed(() => ['ADMIN', 'AGENT'].includes(props.user.role));
const orgName = (id) => orgs.value.find((o) => o.id === id)?.name || id;
async function reload() {
  busy.value = true;
  error.value = '';
  try {
    const [p, o] = await Promise.all([
      get('/policies?history=' + history.value),
      get('/organizations'),
    ]);
    items.value = p.items || [];
    orgs.value = o.items || [];
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function create(parent) {
  formError.value = '';
  form.value = {
    title: '',
    content: '',
    orgId: parent
      ? orgs.value.find((o) => o.parentId === parent.orgId && o.enabled)?.id || ''
      : props.user.role === 'ADMIN'
        ? props.user.orgId
        : orgs.value.find((o) => o.parentId === props.user.orgId && o.enabled)?.id || '',
    parentPolicyId: parent?.id || '',
    rate: parent?.rate ?? '',
    vehicleType: parent?.vehicleType || 'CAR',
    effectiveFrom: parent?.effectiveFrom || '',
    effectiveTo: parent?.effectiveTo || '',
  };
  if (parent) {
    form.value.title = parent.title;
    form.value.content = parent.content;
  }
}
async function save() {
  formError.value = policyError(
    form.value,
    items.value.find((p) => p.id === form.value.parentPolicyId),
  );
  if (formError.value) return;
  saving.value = true;
  try {
    await post('/policies', {
      ...form.value,
      rate: String(form.value.rate),
      parentPolicyId: form.value.parentPolicyId || null,
      effectiveFrom: form.value.effectiveFrom,
      effectiveTo: form.value.effectiveTo || null,
    });
    form.value = null;
    props.notify('政策新版本已保存。');
    await reload();
  } catch (e) {
    formError.value = e.message;
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
        <span class="eyebrow">BUSINESS POLICIES</span>
        <h1>政策管理</h1>
        <p>按组织逐级配置，保留每个政策版本与授权来源。</p>
      </div>
      <button v-if="editable" class="button primary" @click="create()">
        <Icon name="plus" :size="17" />新增政策版本
      </button>
    </div>
    <div class="notice subtle">
      <Icon name="info" :size="17" /><span
        >下级比例、车种与有效期须在上级授权范围内。佣金按订单创建时的政策快照统计。</span
      >
    </div>
    <div class="card">
      <div class="toolbar">
        <label class="checkbox"
          ><input v-model="history" type="checkbox" @change="reload" />显示历史版本</label
        ><span class="toolbar-spacer"></span
        ><button class="button small" @click="reload" :disabled="busy">
          <Icon name="refresh" :size="16" />刷新
        </button>
      </div>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-if="busy" class="loading-line">正在加载政策…</div>
      <div v-if="items.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>政策名称</th>
              <th>适用组织 / 车辆</th>
              <th>比例</th>
              <th>生效区间</th>
              <th class="right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in items" :key="p.id">
              <td>
                <b>{{ p.title }}</b
                ><small
                  >版本 {{ p.version }} <span v-if="p.parentPolicyId">· 继承上级政策</span></small
                >
              </td>
              <td>
                <b>{{ orgName(p.orgId) }}</b
                ><small>{{ vehicleTypes[p.vehicleType] || p.vehicleType }}</small>
              </td>
              <td>
                <span class="rate-number">{{ p.rate }}<small>%</small></span>
              </td>
              <td>
                <span>{{ date(p.effectiveFrom) }}</span
                ><small>至 {{ p.effectiveTo ? date(p.effectiveTo) : '长期有效' }}</small>
              </td>
              <td class="right">
                <div class="row-actions justify-end">
                  <button class="text-link" @click="detail = p">详情</button
                  ><button v-if="editable" class="text-link" @click="create(p)">逐级下发</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else-if="!busy"
        title="暂无政策"
        text="已确认的政策可由总部创建，再按授权向下级下发。"
      />
    </div>
    <Modal v-if="form" title="创建政策新版本" wide @close="form = null"
      ><form @submit.prevent="save">
        <div class="form-grid">
          <label>政策名称<input v-model="form.title" required maxlength="120" /></label
          ><label
            >适用组织<select v-model="form.orgId" required>
              <option
                v-for="o in orgs.filter(
                  (o) => o.enabled && (user.role === 'ADMIN' || o.parentId === user.orgId),
                )"
                :value="o.id"
              >
                {{ o.name }}
              </option>
            </select></label
          ><label
            >上级授权政策<select
              v-model="form.parentPolicyId"
              :required="!!orgs.find((o) => o.id === form.orgId)?.parentId"
            >
              <option value="">总部基础政策</option>
              <option
                v-for="p in items.filter(
                  (p) => p.orgId === orgs.find((o) => o.id === form.orgId)?.parentId,
                )"
                :value="p.id"
              >
                {{ p.title }} · V{{ p.version }} · {{ p.rate }}%
              </option>
            </select></label
          ><label
            >适用车辆<select v-model="form.vehicleType">
              <option v-for="(label, value) in vehicleTypes" :value="value">{{ label }}</option>
            </select></label
          ><label
            >佣金比例（%）<input
              v-model="form.rate"
              type="number"
              min="0"
              max="100"
              step="0.01"
              required
              placeholder="填写已确认的比例"
          /></label>
          <div></div>
          <label>生效时间<input v-model="form.effectiveFrom" type="date" required /></label
          ><label>失效时间（选填）<input v-model="form.effectiveTo" type="date" /></label
          ><label class="full"
            >政策说明<textarea
              v-model="form.content"
              rows="5"
              required
              maxlength="10000"
              placeholder="录入已确认的业务规则与适用条件"
            />
          </label>
        </div>
        <p v-if="formError" class="form-error">{{ formError }}</p>
        <div class="form-actions">
          <button type="button" class="button" @click="form = null">取消</button
          ><button class="button primary" :disabled="saving">
            {{ saving ? '保存中…' : '保存新版本' }}
          </button>
        </div>
      </form></Modal
    ><Modal v-if="detail" title="政策详情" @close="detail = null"
      ><h2>{{ detail.title }}</h2>
      <div class="policy-meta">
        <span class="role-pill">V{{ detail.version }}</span
        ><span>{{ orgName(detail.orgId) }}</span
        ><span>{{ vehicleTypes[detail.vehicleType] }}</span>
      </div>
      <dl class="detail-grid">
        <div>
          <dt>佣金比例</dt>
          <dd>{{ detail.rate }}%</dd>
        </div>
        <div>
          <dt>上级政策来源</dt>
          <dd>{{ detail.parentPolicyId ? '已关联上级授权' : '总部制定' }}</dd>
        </div>
        <div>
          <dt>生效时间</dt>
          <dd>{{ date(detail.effectiveFrom) }}</dd>
        </div>
        <div>
          <dt>失效时间</dt>
          <dd>{{ detail.effectiveTo ? date(detail.effectiveTo) : '长期有效' }}</dd>
        </div>
      </dl>
      <div class="policy-content">{{ detail.content }}</div></Modal
    >
  </section>
</template>
