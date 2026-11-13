<script setup>
import { ref, onMounted, computed } from 'vue';
import { get, post, patch, query } from '../api.js';
import { roles, userRoleName } from '../domain.js';
import Icon from '../components/Icon.vue';
import EmptyState from '../components/EmptyState.vue';
import Modal from '../components/Modal.vue';
import Pagination from '../components/Pagination.vue';
const props = defineProps({ page: String, user: Object, notify: Function });
const orgs = ref([]),
  data = ref({ items: [], total: 0 }),
  agentUsers = ref([]),
  pageNo = ref(1),
  role = ref(''),
  busy = ref(false),
  error = ref(''),
  form = ref(null),
  saving = ref(false);
const canEditUser = (u) =>
  props.user.role === 'ADMIN' || (u.role === 'AGENT' && u.orgId !== props.user.orgId);
const isOrg = computed(() => props.page === 'organizations');
const roleChoices = computed(() => (props.user.role === 'ADMIN' ? roles : { AGENT: '代理' }));
const firstLevelAgents = computed(() =>
  agentUsers.value.filter((u) => Number(u.agentLevel) === 1 && u.enabled && u.id !== form.value?.id),
);
const orgNames = computed(() => Object.fromEntries(orgs.value.map((o) => [o.id, o.name])));
const orderedOrgs = computed(() => {
  const rows = [];
  const seen = new Set();
  function walk(parentId, depth) {
    for (const o of orgs.value.filter((x) => x.parentId === parentId)) {
      if (seen.has(o.id)) continue;
      seen.add(o.id);
      rows.push({ ...o, depth });
      walk(o.id, depth + 1);
    }
  }
  for (const o of orgs.value.filter((x) => !orgs.value.some((y) => y.id === x.parentId))) {
    if (seen.has(o.id)) continue;
    seen.add(o.id);
    rows.push({ ...o, depth: 0 });
    walk(o.id, 1);
  }
  for (const o of orgs.value) if (!seen.has(o.id)) rows.push({ ...o, depth: 0 });
  return rows;
});
async function reload(p = pageNo.value) {
  pageNo.value = p;
  busy.value = true;
  error.value = '';
  try {
    const o = await get('/organizations');
    orgs.value = o.items || [];
    if (!isOrg.value) {
      data.value = await get('/users?' + query({ page: p, size: 20, role: role.value }));
      const agents = await get('/users?' + query({ page: 1, size: 100, role: 'AGENT' }));
      agentUsers.value = agents.items || [];
    }
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function edit(item) {
  if (isOrg.value)
    form.value = item
      ? { id: item.id, name: item.name, enabled: item.enabled }
      : { name: '', parentId: props.user.orgId };
  else
    form.value = item
      ? {
          id: item.id,
          name: item.name,
          enabled: item.enabled,
          role: item.role,
          agentLevel: Number(item.agentLevel || 0),
          parentAgentId: item.parentAgentId || '',
          orgId: item.orgId,
        }
      : {
          name: '',
          username: '',
          password: '',
          role: props.user.role === 'ADMIN' ? 'CUSTOMER' : 'AGENT',
          agentLevel: props.user.role === 'ADMIN' ? 0 : 1,
          parentAgentId: '',
          orgId:
            props.user.role === 'ADMIN'
              ? props.user.orgId
              : orgs.value.find((o) => o.id !== props.user.orgId && o.enabled)?.id || '',
        };
}
function onRoleChange() {
  if (form.value?.role !== 'AGENT') {
    form.value.agentLevel = 0;
    form.value.parentAgentId = '';
  } else if (!form.value.agentLevel) form.value.agentLevel = 1;
}
function onAgentLevelChange() {
  if (Number(form.value?.agentLevel) !== 2) form.value.parentAgentId = '';
}
async function save() {
  saving.value = true;
  try {
    const { id, ...body } = form.value;
    if (id) {
      if (props.user.role !== 'ADMIN' && !isOrg.value) {
        delete body.role;
        delete body.orgId;
        delete body.agentLevel;
        delete body.parentAgentId;
      }
      await patch(`/${isOrg.value ? 'organizations' : 'users'}/${id}`, body);
    } else await post('/' + (isOrg.value ? 'organizations' : 'users'), body);
    form.value = null;
    props.notify(isOrg.value ? '组织信息已保存。' : '人员信息已保存。');
    await reload();
  } catch (e) {
    props.notify(e.message, 'error');
  } finally {
    saving.value = false;
  }
}
async function toggle(item) {
  if (!confirm(`确认${item.enabled ? '停用' : '启用'}“${item.name}”？`)) return;
  try {
    await patch(`/${isOrg.value ? 'organizations' : 'users'}/${item.id}`, {
      enabled: !item.enabled,
    });
    props.notify('状态已更新。');
    await reload();
  } catch (e) {
    props.notify(e.message, 'error');
  }
}
onMounted(() => reload());
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <span class="eyebrow">{{ isOrg ? 'ORGANIZATION' : 'ACCESS MANAGEMENT' }}</span>
        <h1>{{ isOrg ? '组织架构' : '人员与权限' }}</h1>
        <p>
          {{
            isOrg
              ? '按上下级关系管理代理体系，历史订单归属保持独立。'
              : '为业务人员分配组织与角色，限制可见数据和操作范围。'
          }}
        </p>
      </div>
      <button class="button primary" @click="edit()">
        <Icon name="plus" :size="17" />{{ isOrg ? '新增下级组织' : '新增人员' }}
      </button>
    </div>
    <div v-if="error" class="notice error">{{ error }}</div>
    <div v-if="isOrg" class="organization-layout">
      <section class="card">
        <div class="card-header">
          <div>
            <h3>组织树</h3>
            <p>{{ orgs.length }} 个可见组织</p>
          </div>
          <button class="icon-button" aria-label="刷新" @click="reload()">
            <Icon name="refresh" :size="17" />
          </button>
        </div>
        <div v-if="busy" class="loading-line">正在加载组织…</div>
        <div
          v-for="o in orderedOrgs"
          :key="o.id"
          class="org-row"
          :style="{ paddingLeft: 24 + o.depth * 28 + 'px' }"
        >
          <div class="org-line">
            <span class="org-icon" :class="o.depth ? 'child' : ''"
              ><Icon :name="o.depth ? 'users' : 'tree'" :size="20"
            /></span>
            <div>
              <b>{{ o.name }}</b
              ><small
                >{{ o.parentId ? '上级：' + (orgNames[o.parentId] || '已授权上级') : '总部' }} · 第
                {{ o.level ?? o.depth }} 级</small
              >
            </div>
          </div>
          <div class="row-actions">
            <span class="badge" :class="o.enabled ? 'green' : 'gray'">{{
              o.enabled ? '启用' : '停用'
            }}</span
            ><button class="text-link" @click="edit(o)">编辑</button
            ><button class="text-link muted" @click="toggle(o)">
              {{ o.enabled ? '停用' : '启用' }}
            </button>
          </div>
        </div>
        <EmptyState v-if="!busy && !orgs.length" title="暂无可见组织" />
      </section>
      <aside class="card side-help">
        <span class="eyebrow">DATA SCOPE</span>
        <h3>数据权限随组织生效</h3>
        <p>总部查看全平台业务；代理仅查看自身及授权下级的数据。</p>
        <div class="help-item">
          <Icon name="tree" />
          <div>
            <b>逐级管理</b>
            <p>代理可创建直接下级组织。</p>
          </div>
        </div>
        <div class="help-item">
          <Icon name="shield" />
          <div>
            <b>服务端校验</b>
            <p>角色和归属由后端验证，前端菜单不替代权限控制。</p>
          </div>
        </div>
        <div class="help-item">
          <Icon name="clock" />
          <div>
            <b>历史独立</b>
            <p>人员归属变化不改写历史订单快照。</p>
          </div>
        </div>
      </aside>
    </div>
    <div v-else class="card">
      <form class="toolbar" @submit.prevent="reload(1)">
        <select v-model="role" aria-label="按角色筛选">
          <option value="">全部角色</option>
          <option v-for="(label, value) in roles" :value="value">{{ label }}</option></select
        ><button class="button">查询人员</button>
      </form>
      <div v-if="busy" class="loading-line">正在加载人员…</div>
      <div v-if="data.items.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>姓名 / 账号</th>
              <th>角色</th>
              <th>所属组织</th>
              <th>状态</th>
              <th class="right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in data.items" :key="u.id">
              <td>
                <div class="person-cell">
                  <span class="avatar soft">{{ u.name?.slice(0, 1) }}</span>
                  <div>
                    <b>{{ u.name }}</b
                    ><small>{{ u.username || '微信用户' }}</small
                    ><small class="copy-id" :title="u.id">ID: {{ u.id }}</small>
                  </div>
                </div>
              </td>
              <td>
                <span class="role-pill">{{ userRoleName(u) }}</span>
              </td>
              <td>{{ orgNames[u.orgId] || u.orgName || '—' }}</td>
              <td>
                <span class="badge" :class="u.enabled ? 'green' : 'gray'">{{
                  u.enabled ? '启用' : '停用'
                }}</span>
              </td>
              <td class="right">
                <div v-if="canEditUser(u)" class="row-actions justify-end">
                  <button class="text-link" @click="edit(u)">编辑</button
                  ><button class="text-link muted" :disabled="u.id === user.id" @click="toggle(u)">
                    {{ u.enabled ? '停用' : '启用' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-else-if="!busy" title="暂无匹配人员" /><Pagination
        :page="pageNo"
        :total="data.total"
        @change="reload"
      />
    </div>
    <Modal
      v-if="form"
      :title="(form.id ? '编辑' : '新增') + (isOrg ? '组织' : '人员')"
      @close="form = null"
      ><form @submit.prevent="save">
        <div class="form-grid">
          <label :class="{ full: isOrg }"
            >{{ isOrg ? '组织名称' : '姓名'
            }}<input v-model="form.name" required maxlength="100" /></label
          ><template v-if="isOrg"
            ><label class="full" v-if="!form.id"
              >上级组织<select v-model="form.parentId" required>
                <option
                  v-for="o in orgs.filter(
                    (o) => o.enabled && (user.role === 'ADMIN' || o.id === user.orgId),
                  )"
                  :value="o.id"
                >
                  {{ o.name }}
                </option>
              </select></label
            ></template
          ><template v-else
            ><label v-if="!form.id"
              >登录账号<input
                v-model="form.username"
                required
                pattern="[A-Za-z0-9_.-]{3,64}"
                placeholder="3–64 位字母、数字或 ._-" /></label
            ><label v-if="!form.id" class="full"
              >初始密码<input
                v-model="form.password"
                type="password"
                autocomplete="new-password"
                required
                minlength="12"
                maxlength="128"
                placeholder="至少 12 位，包含大小写字母和数字" /></label
            ><label
              >角色<select
                v-model="form.role"
                required
                :disabled="!!form.id && user.role !== 'ADMIN'"
                @change="onRoleChange"
              >
                <option v-for="(label, value) in roleChoices" :value="value">{{ label }}</option>
              </select></label
            ><label v-if="form.role === 'AGENT' && user.role === 'ADMIN'"
              >代理级别<select v-model.number="form.agentLevel" required @change="onAgentLevelChange">
                <option :value="1">一级代理</option>
                <option :value="2">二级代理</option>
              </select></label
            ><label
              v-if="form.role === 'AGENT' && Number(form.agentLevel) === 2 && user.role === 'ADMIN'"
              >所属一级代理<select v-model="form.parentAgentId" required>
                <option value="" disabled>请选择一级代理</option>
                <option v-for="a in firstLevelAgents" :key="a.id" :value="a.id">
                  {{ a.name }}（{{ orgNames[a.orgId] || a.orgName || '—' }}）
                </option>
              </select></label
            ><label
              >所属组织<select
                v-model="form.orgId"
                required
                :disabled="!!form.id && user.role !== 'ADMIN'"
              >
                <option
                  v-for="o in orgs.filter(
                    (o) => o.enabled && (user.role === 'ADMIN' || o.id !== user.orgId),
                  )"
                  :value="o.id"
                >
                  {{ o.name }}
                </option>
              </select></label
            ></template
          >
        </div>
        <div class="notice subtle" v-if="!isOrg">
          <Icon name="info" :size="16" />人员首次登录后可在账号安全中修改密码。
        </div>
        <div class="form-actions">
          <button type="button" class="button" @click="form = null">取消</button
          ><button class="button primary" :disabled="saving">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </form></Modal
    >
  </section>
</template>
