<script setup>
import { ref, onMounted } from 'vue';
import { get, post, put, query } from '../api.js';
import { date } from '../domain.js';
import Icon from '../components/Icon.vue';
import EmptyState from '../components/EmptyState.vue';
import Modal from '../components/Modal.vue';
import Pagination from '../components/Pagination.vue';
const props = defineProps({ notify: Function });
const data = ref({ items: [], total: 0 }),
  page = ref(1),
  search = ref(''),
  busy = ref(false),
  error = ref(''),
  form = ref(null),
  saving = ref(false),
  orgNames = ref({});
async function reload(p = page.value) {
  page.value = p;
  busy.value = true;
  error.value = '';
  try {
    const [customers, orgs] = await Promise.all([
      get('/customers?' + query({ page: p, size: 20, search: search.value })),
      get('/organizations'),
    ]);
    orgNames.value = Object.fromEntries((orgs.items || []).map((o) => [o.id, o.name]));
    data.value = customers;
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function edit(c) {
  form.value = c
    ? { id: c.id, name: c.name, phone: c.phone, notes: c.notes || '' }
    : { name: '', phone: '', notes: '' };
}
async function save() {
  saving.value = true;
  try {
    const { id, ...body } = form.value;
    id ? await put('/customers/' + id, body) : await post('/customers', body);
    form.value = null;
    props.notify('客户资料已保存。');
    await reload();
  } catch (e) {
    props.notify(e.message, 'error');
  } finally {
    saving.value = false;
  }
}
onMounted(() => reload());
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <span class="eyebrow">CUSTOMER RELATIONSHIPS</span>
        <h1>客户管理</h1>
        <p>维护客户资料与跟进备注，数据按组织授权展示。</p>
      </div>
      <button class="button primary" @click="edit()">
        <Icon name="plus" :size="17" />新增客户
      </button>
    </div>
    <div class="card">
      <form class="toolbar" @submit.prevent="reload(1)">
        <div class="search-input">
          <Icon name="search" :size="18" /><input v-model="search" placeholder="搜索姓名或手机号" />
        </div>
        <button class="button">查询客户</button>
      </form>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-if="busy" class="loading-line">正在加载客户…</div>
      <div v-if="data.items.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>客户姓名</th>
              <th>联系电话</th>
              <th>所属组织</th>
              <th>跟进备注</th>
              <th>创建时间</th>
              <th class="right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in data.items" :key="c.id">
              <td>
                <div class="person-cell">
                  <span class="avatar soft">{{ c.name?.slice(0, 1) }}</span
                  ><b>{{ c.name }}</b>
                </div>
              </td>
              <td>{{ c.phone }}</td>
              <td>{{ c.orgName || orgNames[c.orgId] || '未关联组织' }}</td>
              <td class="truncate" :title="c.notes">{{ c.notes || '—' }}</td>
              <td>{{ date(c.createdAt) }}</td>
              <td class="right"><button class="text-link" @click="edit(c)">编辑资料</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else-if="!busy"
        title="暂无客户档案"
        text="新增客户，或从投保申请建立业务联系。"
      /><Pagination :page="page" :total="data.total" @change="reload" />
    </div>
    <Modal v-if="form" :title="form.id ? '编辑客户资料' : '新增客户'" @close="form = null"
      ><form @submit.prevent="save">
        <div class="form-grid">
          <label>客户姓名<input v-model="form.name" required maxlength="100" /></label
          ><label
            >手机号<input
              v-model="form.phone"
              required
              inputmode="tel"
              pattern="1[3-9][0-9]{9}"
              maxlength="11"
              placeholder="11 位手机号" /></label
          ><label class="full"
            >跟进备注<textarea
              v-model="form.notes"
              rows="4"
              maxlength="2000"
              placeholder="记录客户需求或跟进情况"
            />
          </label>
        </div>
        <div class="form-actions">
          <button type="button" class="button" @click="form = null">取消</button
          ><button class="button primary" :disabled="saving">
            {{ saving ? '保存中…' : '保存客户' }}
          </button>
        </div>
      </form></Modal
    >
  </section>
</template>
