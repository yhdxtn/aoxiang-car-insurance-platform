<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue';
import { get, post, put, patch, session, saveSession, query, uid } from './api.js';
import {
  date,
  money,
  vehicleTypes,
  statusName,
  roleName,
  nextOrderStates,
  orderStateOptions,
  orderAmount,
  canCreateManualApplication,
} from './domain.js';
import { createVisiblePoller } from './polling.js';
import Icon from './components/Icon.vue';
import Login from './components/Login.vue';
import StatusBadge from './components/StatusBadge.vue';
import EmptyState from './components/EmptyState.vue';
import Modal from './components/Modal.vue';
import PrivateImage from './components/PrivateImage.vue';
const auth = ref(session()),
  config = ref({ mode: 'live' }),
  checking = ref(true),
  toast = ref(null),
  queue = ref('WAITING'),
  search = ref(''),
  sessions = ref([]),
  total = ref(0),
  pageNo = ref(1),
  loading = ref(false),
  listError = ref(''),
  selected = ref(null),
  messages = ref([]),
  cursor = ref(0),
  text = ref(''),
  sending = ref(false),
  working = ref(false),
  pollPaused = ref(false),
  connectionError = ref(''),
  agents = ref([]),
  transferTo = ref(''),
  transferOpen = ref(false),
  vehicleForm = ref(null),
  quoteForm = ref(null),
  preview = ref(null),
  order = ref(null),
  orderForm = ref(null),
  showDetails = ref(false),
  passwordForm = ref(null),
  docType = ref('DRIVING_LICENSE'),
  uploading = ref(false),
  fileInput = ref(null),
  chatScroll = ref(null);
let toastTimer,
  selectedController,
  selectionVersion = 0,
  readVersion = 0,
  loops = 0,
  sendKey = null,
  lastText = '',
  destroyed = false;
const notify = (message, tone = 'success') => {
  toast.value = { message, tone };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.value = null), 6500);
};
const filtered = computed(() =>
  sessions.value.filter((s) =>
    [s.ownerName, s.vehicle?.plateNo, vehicleTypes[s.vehicleType]].some((v) =>
      String(v || '')
        .toLowerCase()
        .includes(search.value.toLowerCase()),
    ),
  ),
);
const editable = computed(
  () =>
    !!selected.value &&
    selected.value.status !== 'CLOSED' &&
    (auth.value?.user.role === 'ADMIN' ||
      (selected.value.assignedTo === auth.value?.user.id && selected.value.status === 'ACTIVE')),
);
const quotes = computed(() => selected.value?.quotes || []);
const currentQuote = computed(() =>
  quotes.value.find(
    (q) => q.status === 'QUOTED' && q.validUntil && new Date(q.validUntil).getTime() > Date.now(),
  ),
);
const unknownQuote = computed(() =>
  quotes.value.some((q) => ['OUTCOME_UNKNOWN', 'PROCESSING'].includes(q.status)),
);
const canManualApply = computed(() => canCreateManualApplication(selected.value, auth.value?.user));
const isMotorcycle = computed(() => selected.value?.vehicleType === 'MOTORCYCLE');
const isTruck = computed(() => selected.value?.vehicleType === 'TRUCK');
const adminUrl = import.meta.env.VITE_ADMIN_URL || 'http://localhost:5173';
const stages = ['资料确认', '方案报价', '投保确认'];
const poller = createVisiblePoller({
  run: async () => {
    if (!auth.value) return;
    loops++;
    if (loops % 3 === 0 || !selected.value) await loadList(false);
    if (selected.value) await refreshSelected(false);
    connectionError.value = '';
  },
  onPause: () => {
    pollPaused.value = true;
  },
});
function active() {
  poller.activity();
}
function resume() {
  pollPaused.value = false;
  poller.activity();
  poller.start();
  void reload();
}
function visibility() {
  if (document.hidden) {
    poller.stop();
    selectedController?.abort();
  } else if (auth.value && !pollPaused.value) {
    poller.start();
    void reload();
  }
}
async function login(value) {
  sessions.value = [];
  total.value = 0;
  auth.value = value;
  saveSession(value);
  await reload();
  poller.activity();
  poller.start();
}
async function logout() {
  poller.stop();
  selectedController?.abort();
  try {
    await post('/auth/logout', {});
  } catch {}
  saveSession(null);
  auth.value = null;
  selected.value = null;
  messages.value = [];
  sessions.value = [];
  total.value = 0;
  selectionVersion++;
  readVersion++;
}
function unauthorized() {
  poller.stop();
  auth.value = null;
  selected.value = null;
  messages.value = [];
  sessions.value = [];
  total.value = 0;
  selectionVersion++;
  readVersion++;
  notify('登录已过期，请重新登录。', 'error');
}
async function loadList(show = true) {
  const authId = auth.value?.user?.id;
  const requestedQueue = queue.value,
    requestedPage = pageNo.value;
  if (!authId) return;
  if (show) loading.value = true;
  listError.value = '';
  try {
    const result = await get(
      '/sessions?' + query({ status: queue.value, page: pageNo.value, size: 30 }),
    );
    if (
      auth.value?.user?.id !== authId ||
      queue.value !== requestedQueue ||
      pageNo.value !== requestedPage
    )
      return;
    sessions.value = result.items || [];
    total.value = result.total || 0;
  } catch (e) {
    listError.value = e.message;
    if (!show) throw e;
  } finally {
    loading.value = false;
  }
}
async function changeQueue(value) {
  queue.value = value;
  pageNo.value = 1;
  active();
  await loadList();
}
async function reload() {
  active();
  try {
    await loadList();
    if (selected.value) await refreshSelected(false);
  } catch (e) {
    connectionError.value = e.message;
  }
}
function merge(items) {
  const merged = new Map(messages.value.map((m) => [m.id, m]));
  for (const item of items || []) merged.set(item.id, item);
  messages.value = [...merged.values()].sort((a, b) => Number(a.seq) - Number(b.seq));
}
async function scrollBottom(force = false) {
  await nextTick();
  const el = chatScroll.value;
  if (el && (force || el.scrollHeight - el.scrollTop - el.clientHeight < 250))
    el.scrollTop = el.scrollHeight;
}
async function selectSession(item) {
  active();
  selectionVersion++;
  const version = selectionVersion;
  selectedController?.abort();
  selectedController = new AbortController();
  const controller = selectedController;
  selected.value = item;
  messages.value = [];
  cursor.value = 0;
  text.value = '';
  sendKey = null;
  order.value = null;
  connectionError.value = '';
  showDetails.value = false;
  try {
    const [s, m] = await Promise.all([
      get('/sessions/' + item.id, { signal: controller.signal }),
      get('/sessions/' + item.id + '/messages?after=0', { signal: controller.signal }),
    ]);
    if (version !== selectionVersion || destroyed) return;
    selected.value = s;
    merge(m.items);
    cursor.value = m.cursor || 0;
    await scrollBottom(true);
    if (s.orderId) await loadOrder(s.orderId);
  } catch (e) {
    if (version === selectionVersion && !controller.signal.aborted) notify(e.message, 'error');
  }
}
async function refreshSelected(force = false) {
  const sid = selected.value?.id;
  if (!sid) return;
  const version = selectionVersion;
  const readId = ++readVersion;
  const after = cursor.value;
  selectedController?.abort();
  const controller = new AbortController();
  selectedController = controller;
  try {
    const [s, m] = await Promise.all([
      get('/sessions/' + sid, { signal: controller.signal }),
      get(`/sessions/${sid}/messages?after=${after}`, { signal: controller.signal }),
    ]);
    if (version !== selectionVersion || readId !== readVersion || destroyed) return;
    selected.value = s;
    merge(m.items);
    cursor.value = m.cursor || cursor.value;
    if (m.items?.length) await scrollBottom(force);
    if (s.orderId && order.value?.id !== s.orderId) await loadOrder(s.orderId);
    if ((s.quotes || []).some((q) => q.status === 'QUOTED'))
      sessionStorage.removeItem('tk-quote-' + sid);
  } catch (e) {
    if (!controller.signal.aborted && version === selectionVersion) {
      connectionError.value = e.message;
      throw e;
    }
  }
}
async function action(path, body = {}) {
  if (working.value) return;
  working.value = true;
  active();
  try {
    const sid = selected.value.id;
    const result = await post(`/sessions/${sid}/${path}`, body);
    if (path === 'transfer' && auth.value?.user.role !== 'ADMIN') {
      selectedController?.abort();
      selectionVersion++;
      selected.value = null;
      messages.value = [];
      order.value = null;
    } else if (selected.value?.id === sid) selected.value = result;
    await refreshSelected(true).catch((e) => notify('操作已保存，刷新失败：' + e.message, 'error'));
    await loadList(false).catch((e) => notify('操作已保存，队列刷新失败：' + e.message, 'error'));
    return result;
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    working.value = false;
  }
}
async function claim() {
  if (await action('claim')) notify('已接入会话，可以开始接待。');
}
async function close() {
  if (!confirm('确认结束本次客服会话？历史消息与资料将保留。')) return;
  if (await action('close')) notify('会话已结束。');
}
async function openTransfer() {
  try {
    const result = await get('/service/agents');
    agents.value = (result.items || []).filter((u) => u.id !== auth.value.user.id);
    transferTo.value = '';
    transferOpen.value = true;
  } catch (e) {
    notify(e.message, 'error');
  }
}
async function transfer() {
  if (await action('transfer', { serviceUserId: transferTo.value })) {
    transferOpen.value = false;
    notify('会话已转接。');
  }
}
async function send() {
  if (!editable.value || sending.value || !text.value.trim()) return;
  const content = text.value.trim(),
    sid = selected.value.id;
  if (lastText !== content || !sendKey) {
    sendKey = uid();
    lastText = content;
  }
  sending.value = true;
  active();
  try {
    await post(`/sessions/${sid}/messages`, { content, clientMessageId: sendKey });
    if (selected.value?.id === sid) {
      text.value = '';
      sendKey = null;
      await refreshSelected(true);
    }
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    sending.value = false;
  }
}
async function upload(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !editable.value) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    notify('仅支持 JPEG、PNG、WEBP 图片。', 'error');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    notify('图片不能超过 10MB。', 'error');
    return;
  }
  const sid = selected.value.id;
  uploading.value = true;
  active();
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('documentType', docType.value);
    body.append('source', 'WEB');
    const uploaded = await post(`/sessions/${sid}/files`, body);
    await post(`/sessions/${sid}/messages`, {
      content: '已上传资料',
      clientMessageId: uid(),
      fileId: uploaded.id,
    });
    if (selected.value?.id === sid) await refreshSelected(true);
    notify('资料已上传。');
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    uploading.value = false;
  }
}
function editVehicle() {
  const s = selected.value;
  vehicleForm.value = {
    plateNo: '',
    vin: '',
    engineNo: '',
    brandModel: '',
    registerDate: '',
    issueDate: '',
    ownerName: '',
    idNumber: '',
    address: '',
    phone: '',
    seatCount: 5,
    useNature: s.vehicleType === 'CAR' ? '家庭自用' : '',
    ...s.vehicle,
    vehicleType: s.vehicleType,
  };
}
async function saveVehicle() {
  working.value = true;
  active();
  try {
    const sid = selected.value.id;
    const body = { ...vehicleForm.value, seatCount: Number(vehicleForm.value.seatCount) };
    selected.value = await put(`/sessions/${sid}/vehicle`, body);
    vehicleForm.value = null;
    notify('车辆资料已保存，旧报价已失效。');
    await refreshSelected(true);
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    working.value = false;
  }
}
async function recognize(fileId) {
  if (!editable.value) {
    notify('请先接入会话后再识别资料。', 'error');
    return;
  }
  working.value = true;
  active();
  try {
    const result = await post(
      `/sessions/${selected.value.id}/ocr`,
      { fileId },
      { timeout: 120000 },
    );
    editVehicle();
    if (result.status === 'RECOGNIZED') {
      vehicleForm.value = {
        ...vehicleForm.value,
        ...result.vehicle,
        vehicleType: selected.value.vehicleType,
      };
      notify('识别完成，请人工核对后保存。');
    } else notify(result.message || '需要手动填写车辆资料。', 'error');
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    working.value = false;
  }
}
function openQuote() {
  quoteForm.value = {
    plan: 'STANDARD',
    thirdPartyAmount: '2000000',
    driverAmount: '10000',
    passengerAmount: '10000',
    medicalAmount: '200000',
  };
}
async function quote() {
  if (isMotorcycle.value || working.value) return;
  working.value = true;
  active();
  const sid = selected.value.id;
  let stored;
  try {
    stored = JSON.parse(sessionStorage.getItem('tk-quote-' + sid) || 'null');
  } catch {}
  const body = { ...quoteForm.value, idempotencyKey: stored?.key || uid() };
  if (stored && JSON.stringify(stored.body) !== JSON.stringify(quoteForm.value)) {
    notify('上一笔请求尚未确认，不能更换方案再次提交。请先刷新或人工核实。', 'error');
    working.value = false;
    return;
  }
  sessionStorage.setItem(
    'tk-quote-' + sid,
    JSON.stringify({ key: body.idempotencyKey, body: quoteForm.value }),
  );
  try {
    const result = await post(`/sessions/${sid}/quotes`, body, { timeout: 180000 });
    if (!['OUTCOME_UNKNOWN', 'PROCESSING'].includes(result.status))
      sessionStorage.removeItem('tk-quote-' + sid);
    quoteForm.value = null;
    notify(
      result.status === 'QUOTED'
        ? '报价已返回，请核对险种与保费。'
        : result.message || '报价需要人工处理。',
      result.status === 'QUOTED' ? 'success' : 'error',
    );
    await refreshSelected(true);
  } catch (e) {
    if (e.status >= 400 && e.status < 500) sessionStorage.removeItem('tk-quote-' + sid);
    notify(e.message, 'error');
    await refreshSelected(false).catch(() => {});
  } finally {
    working.value = false;
  }
}
async function apply(manual = false) {
  if (!editable.value || working.value || (manual && !canManualApply.value)) return;
  const qid = manual ? '' : currentQuote.value?.id;
  if (!manual && !qid) return;
  if (
    !confirm(
      manual
        ? '确认登记人工核价申请？此操作仅在本系统留存，不会重新请求保司报价。如已有结果未知的报价，请先核对原外部单。'
        : '请确认客户已核对车辆资料与本版报价。是否提交投保申请交人工审核？',
    )
  )
    return;
  working.value = true;
  active();
  const sid = selected.value.id;
  let key = sessionStorage.getItem('tk-order-' + sid) || uid();
  sessionStorage.setItem('tk-order-' + sid, key);
  try {
    order.value = await post(`/sessions/${sid}/orders`, {
      quoteId: qid,
      idempotencyKey: key,
      confirmed: true,
    });
    notify('投保申请已登记，等待后续审核。');
    await refreshSelected(true);
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    working.value = false;
  }
}
async function loadOrder(id) {
  try {
    const result = await get('/orders/' + id);
    if (selected.value?.orderId === id) order.value = result;
  } catch (e) {
    notify(e.message, 'error');
  }
}
function editOrder() {
  orderForm.value = {
    status: orderStateOptions(order.value, auth.value.user.role)[0],
    note: '',
    policyNo: order.value.policyNo || '',
    totalPremium: !order.value.quoteId ? (order.value.totalPremium ?? '') : undefined,
  };
}
async function updateOrder() {
  working.value = true;
  try {
    const body = { ...orderForm.value };
    if (body.totalPremium === '' || body.status === 'CANCELLED') delete body.totalPremium;
    else if (body.totalPremium !== undefined) body.totalPremium = String(body.totalPremium);
    order.value = await patch(`/orders/${order.value.id}/status`, body);
    orderForm.value = null;
    notify('订单跟进已保存。');
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    working.value = false;
  }
}
async function changePassword() {
  if (passwordForm.value.newPassword !== passwordForm.value.repeat) {
    notify('两次新密码不一致。', 'error');
    return;
  }
  working.value = true;
  try {
    await put('/auth/password', {
      oldPassword: passwordForm.value.oldPassword,
      newPassword: passwordForm.value.newPassword,
    });
    passwordForm.value = null;
    notify('密码已修改。');
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    working.value = false;
  }
}
onMounted(async () => {
  window.addEventListener('tk:unauthorized', unauthorized);
  document.addEventListener('visibilitychange', visibility);
  try {
    config.value = await get('/public/config');
    if (auth.value) {
      const user = await get('/auth/me');
      if (!['ADMIN', 'SERVICE'].includes(user.role)) {
        await logout();
      } else {
        auth.value = { ...auth.value, user };
        saveSession(auth.value);
        await loadList();
        poller.start();
      }
    }
  } catch (e) {
    notify(e.message, 'error');
  } finally {
    checking.value = false;
  }
});
onUnmounted(() => {
  destroyed = true;
  poller.stop();
  selectedController?.abort();
  clearTimeout(toastTimer);
  window.removeEventListener('tk:unauthorized', unauthorized);
  document.removeEventListener('visibilitychange', visibility);
});
</script>
<template>
  <div v-if="checking" class="boot-screen">
    <div class="spinner"></div>
    <p>正在连接客服工作台</p>
  </div>
  <Login v-else-if="!auth" :config="config" @login="login" />
  <div v-else class="service-shell" @pointerdown="active" @keydown="active">
    <aside class="service-rail">
      <a class="rail-logo" :href="adminUrl" title="管理端"><Icon name="shield" :size="27" /></a
      ><button class="rail-button active" title="客服会话" @click="reload">
        <Icon name="chat" :size="24" /></button
      ><button
        class="rail-button"
        title="账号安全"
        @click="passwordForm = { oldPassword: '', newPassword: '', repeat: '' }"
      >
        <Icon name="lock" :size="21" />
      </button>
      <div class="rail-spacer"></div>
      <div class="rail-avatar" :title="auth.user.name">{{ auth.user.name?.slice(0, 1) }}</div>
      <button class="rail-button" title="安全退出" @click="logout">
        <Icon name="logout" :size="21" />
      </button>
    </aside>
    <div class="service-main">
      <header class="service-topbar">
        <div>
          <h1>客服工作台 <span>泰康车险</span></h1>
          <p>人工接待 · 资料核验 · 业务跟进</p>
        </div>
        <div class="service-top-actions">
          <span class="mode-indicator" :class="config.mode">{{
            config.mode === 'demo' ? '演示环境' : '业务环境'
          }}</span
          ><span class="service-presence"><i></i>{{ auth.user.name }}</span
          ><button class="button small" @click="reload" :disabled="loading">
            <Icon name="refresh" :size="15" />刷新
          </button>
        </div>
      </header>
      <div v-if="config.mode === 'demo'" class="demo-banner">
        <Icon name="info" :size="14" />演示数据，仅用于流程测试，不能作为真实保费或承保结果。
      </div>
      <div v-if="pollPaused" class="poll-notice">
        长时间未操作，已暂停自动刷新。<button @click="resume">恢复接待刷新</button>
      </div>
      <div class="service-workspace">
        <section class="session-list">
          <div class="queue-heading">
            <h2>会话列表</h2>
            <span>{{ total }}</span>
          </div>
          <div class="queue-tabs">
            <button
              v-for="(label, value) in { WAITING: '待接入', ACTIVE: '接待中', CLOSED: '已结束' }"
              :class="{ active: queue === value }"
              @click="changeQueue(value)"
            >
              {{ label }}
            </button>
          </div>
          <div class="session-search">
            <Icon name="search" :size="16" /><input
              v-model="search"
              placeholder="搜索本页姓名 / 车牌"
            />
          </div>
          <div v-if="listError" class="list-error">
            {{ listError }}<button @click="loadList()">重试</button>
          </div>
          <div class="session-items">
            <div v-if="loading" class="loading-line">加载会话中…</div>
            <button
              v-for="s in filtered"
              :key="s.id"
              class="session-item"
              :class="{ selected: selected?.id === s.id }"
              @click="selectSession(s)"
              :disabled="working || uploading || sending"
            >
              <div class="session-avatar" :class="{ motor: s.vehicleType === 'MOTORCYCLE' }">
                <Icon :name="s.vehicleType === 'MOTORCYCLE' ? 'headset' : 'car'" :size="22" />
              </div>
              <div class="session-info">
                <div>
                  <b>{{ s.ownerName || '小程序用户' }}</b
                  ><time>{{
                    s.createdAt
                      ? new Date(s.createdAt).toLocaleTimeString('zh-CN', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })
                      : ''
                  }}</time>
                </div>
                <p>{{ s.vehicle?.plateNo || '待填写车辆' }} · {{ vehicleTypes[s.vehicleType] }}</p>
                <span class="session-label">{{
                  s.vehicleType === 'MOTORCYCLE' ? '摩托车 · 人工办理' : statusName(s.status)
                }}</span>
              </div></button
            ><EmptyState
              v-if="!loading && !filtered.length"
              title="暂无会话"
              text="新会话进入队列后会显示在这里。"
              icon="chat"
            />
          </div>
          <div class="queue-pagination">
            <button
              class="icon-button"
              :disabled="pageNo <= 1"
              @click="
                pageNo--;
                loadList();
              "
              aria-label="上一页"
            >
              <Icon name="chevron" :size="16" class="rotate" /></button
            ><span>{{ pageNo }} / {{ Math.max(1, Math.ceil(total / 30)) }}</span
            ><button
              class="icon-button"
              :disabled="pageNo * 30 >= total"
              @click="
                pageNo++;
                loadList();
              "
              aria-label="下一页"
            >
              <Icon name="chevron" :size="16" />
            </button>
          </div>
          <div class="queue-footer"><Icon name="lock" :size="12" />仅展示当前账号可接待的会话</div>
        </section>
        <section v-if="!selected" class="chat-blank">
          <div class="blank-art"><Icon name="headset" :size="64" /></div>
          <span class="eyebrow">READY TO HELP</span>
          <h2>从一个会话开始</h2>
          <p>选择左侧会话查看资料。<br />接入后，即可协助客户核对信息与办理业务。</p>
          <div class="blank-tags">
            <span><Icon name="shield" :size="15" />授权接待</span
            ><span><Icon name="file" :size="15" />资料留存</span
            ><span><Icon name="clock" :size="15" />过程追溯</span>
          </div>
        </section>
        <template v-else
          ><section class="chat-panel">
            <header class="chat-header">
              <div class="chat-customer">
                <span class="avatar">{{ selected.ownerName?.slice(0, 1) || '客' }}</span>
                <div>
                  <h2>
                    {{ selected.ownerName || '小程序用户' }}<StatusBadge :value="selected.status" />
                  </h2>
                  <p>{{ vehicleTypes[selected.vehicleType] }} · 泰康报价会话</p>
                </div>
              </div>
              <div class="chat-actions">
                <button
                  v-if="selected.status === 'WAITING'"
                  class="button primary small"
                  :disabled="working"
                  @click="claim"
                >
                  接入会话</button
                ><template v-if="editable && selected.status === 'ACTIVE'"
                  ><button class="button small" @click="openTransfer" :disabled="working">
                    转接</button
                  ><button class="button small" @click="close" :disabled="working">
                    结束
                  </button></template
                ><button
                  class="icon-button detail-toggle"
                  @click="showDetails = !showDetails"
                  title="车辆资料"
                >
                  <Icon name="file" :size="18" />
                </button>
              </div>
            </header>
            <div class="chat-steps">
              <div
                v-for="(label, i) in stages"
                :key="label"
                :class="{
                  done: Number(selected.stage) > i + 1,
                  active: Number(selected.stage) === i + 1,
                }"
              >
                <span>{{ i + 1 }}</span
                >{{ label }}
              </div>
            </div>
            <div v-if="isMotorcycle" class="chat-notice">
              <Icon name="headset" :size="16" />摩托车专属人工流程，不调用自动报价。
            </div>
            <div v-else-if="isTruck" class="chat-notice">
              <Icon name="info" :size="16" />货车承保条件需人工核验；通道不支持时由客服继续处理。
            </div>
            <div v-if="connectionError" class="connection-warning">
              {{ connectionError }}<button @click="refreshSelected()">刷新会话</button>
            </div>
            <div class="chat-messages" ref="chatScroll">
              <div class="conversation-start">会话开始于 {{ date(selected.createdAt) }}</div>
              <template v-for="m in messages" :key="m.id"
                ><div v-if="m.role === 'SYSTEM'" class="system-message">{{ m.content }}</div>
                <div
                  v-else
                  class="message-row"
                  :class="{ outgoing: m.role === 'SERVICE', assistant: m.role === 'ASSISTANT' }"
                >
                  <span class="message-avatar"
                    ><Icon v-if="m.role === 'ASSISTANT'" name="shield" :size="19" /><Icon
                      v-else-if="m.role === 'SERVICE'"
                      name="headset"
                      :size="19"
                    /><span v-else>{{ selected.ownerName?.slice(0, 1) || '客' }}</span></span
                  >
                  <div class="message-body">
                    <div class="message-meta">
                      <span>{{
                        m.role === 'SERVICE'
                          ? '人工客服'
                          : m.role === 'ASSISTANT'
                            ? '车险助手'
                            : selected.ownerName || '用户'
                      }}</span
                      ><time>{{ date(m.createdAt) }}</time>
                    </div>
                    <div class="message-bubble">
                      <p v-if="m.content">{{ m.content }}</p>
                      <PrivateImage
                        v-if="m.fileId"
                        :file-id="m.fileId"
                        :file-name="m.fileName"
                        @preview="(url, name) => (preview = { url, name })"
                        @ocr="recognize"
                      />
                    </div>
                  </div></div
              ></template>
              <div v-if="!messages.length" class="loading-line">正在读取会话记录…</div>
            </div>
            <div v-if="!editable" class="readonly-composer">
              <Icon name="lock" :size="16" />{{
                selected.status === 'CLOSED'
                  ? '会话已结束，历史记录可继续查看。'
                  : selected.status === 'WAITING'
                    ? '请先接入会话，再发送消息或编辑资料。'
                    : '此会话正在由其他客服接待。'
              }}
            </div>
            <form v-else class="chat-composer" @submit.prevent="send">
              <div class="composer-tools">
                <button
                  type="button"
                  class="icon-button"
                  title="上传资料图片"
                  @click="fileInput.click()"
                  :disabled="uploading"
                >
                  <Icon name="image" :size="21" /></button
                ><select v-model="docType" aria-label="上传证件类型">
                  <option value="DRIVING_LICENSE">行驶证</option>
                  <option value="ID_CARD">身份证</option>
                  <option value="OTHER">其他资料</option></select
                ><span>{{ uploading ? '正在上传…' : '支持 JPG / PNG / WEBP，单张 10MB 以内' }}</span
                ><input
                  ref="fileInput"
                  class="hidden-file"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  @change="upload"
                />
              </div>
              <textarea
                v-model="text"
                maxlength="2000"
                rows="3"
                placeholder="输入消息，协助客户完善资料…"
                @keydown.ctrl.enter.prevent="send"
              />
              <div class="composer-bottom">
                <span>Ctrl + Enter 发送 · {{ text.length }}/2000</span
                ><button class="button primary small" :disabled="sending || !text.trim()">
                  {{ sending ? '发送中…' : '发送' }}<Icon name="send" :size="15" />
                </button>
              </div>
            </form>
          </section>
          <aside class="detail-panel" :class="{ open: showDetails }">
            <div class="detail-panel-header">
              <h2>业务资料</h2>
              <button
                class="icon-button detail-toggle"
                @click="showDetails = false"
                aria-label="关闭资料"
              >
                <Icon name="close" :size="18" /></button
              ><span v-if="!showDetails" class="badge amber">{{
                vehicleTypes[selected.vehicleType]
              }}</span>
            </div>
            <section class="detail-section">
              <div class="detail-section-title">
                <h3><Icon name="car" :size="17" />车辆信息</h3>
                <button
                  v-if="editable && !selected.orderId && !unknownQuote"
                  class="text-link"
                  @click="editVehicle"
                >
                  编辑
                </button>
              </div>
              <dl class="vehicle-fields">
                <div
                  v-for="(label, key) in {
                    plateNo: '车牌号',
                    ownerName: '车主姓名',
                    phone: '联系电话',
                    vin: '车架号',
                    brandModel: '品牌型号',
                    engineNo: '发动机号',
                    registerDate: '注册日期',
                    useNature: '使用性质',
                    seatCount: '座位数',
                  }"
                >
                  <dt>{{ label }}</dt>
                  <dd>{{ selected.vehicle?.[key] || '待填写' }}</dd>
                </div>
              </dl>
              <button
                v-if="editable && !selected.orderId && !unknownQuote"
                class="button block small"
                @click="editVehicle"
              >
                <Icon name="file" :size="15" />核对并完善资料
              </button>
            </section>
            <section class="detail-section">
              <div class="detail-section-title">
                <h3><Icon name="shield" :size="17" />报价方案</h3>
                <span class="tk-tag">TK</span>
              </div>
              <div v-if="unknownQuote" class="notice error">
                {{
                  quotes.some((q) => q.status === 'PROCESSING')
                    ? '外部报价正在处理中，请先等待结果，暂不能登记人工申请。'
                    : '外部报价结果未知，请先核对原外部单。可登记内部人工核价申请，不会重发报价。'
                }}
              </div>
              <template v-if="currentQuote"
                ><div class="quote-summary">
                  <span
                    >{{
                      { COMPULSORY: '交强险方案', STANDARD: '交强 + 三者方案', FULL: '全险方案' }[
                        currentQuote.plan
                      ] || '泰康报价'
                    }}<span v-if="currentQuote.demo" class="demo-small">演示</span></span
                  ><strong>¥ {{ money(currentQuote.totalPremium) }}</strong
                  ><small>含车船税，金额以本版报价为准</small>
                </div>
                <div class="coverage-row" v-for="(c, i) in currentQuote.coverages || []" :key="i">
                  <span>{{ c.name }}</span
                  ><b>¥ {{ money(c.premium) }}</b>
                </div>
                <p class="quote-valid">有效期至 {{ date(currentQuote.validUntil) }}</p></template
              >
              <div v-else class="quote-empty">
                <Icon name="file" :size="24" />
                <p>{{ isMotorcycle ? '摩托车由人工协助办理' : '暂未取得有效报价' }}</p>
              </div>
              <div
                class="quote-failed"
                v-for="q in quotes
                  .filter((q) => ['MANUAL_REQUIRED', 'FAILED'].includes(q.status))
                  .slice(0, 1)"
                :key="q.id"
              >
                {{ q.message || statusName(q.status) }}
              </div>
              <button
                v-if="editable && !isMotorcycle && !selected.orderId && !unknownQuote"
                class="button primary block"
                @click="openQuote"
                :disabled="working"
              >
                <Icon name="refresh" :size="15" />{{
                  currentQuote ? '调整方案并重新报价' : '发起泰康报价'
                }}</button
              ><button
                v-if="editable && currentQuote && !selected.orderId"
                class="button block apply-button"
                @click="apply(false)"
                :disabled="working"
              >
                确认并提交投保申请<Icon name="arrow" :size="15" /></button
              ><button
                v-if="canManualApply"
                class="button block"
                @click="apply(true)"
                :disabled="working"
              >
                登记人工核价申请
              </button>
              <details v-if="quotes.length" class="quote-history">
                <summary>查看报价记录（{{ quotes.length }}）</summary>
                <div v-for="q in quotes" :key="q.id">
                  <StatusBadge :value="q.status" /><small>本地报价：{{ q.id }}</small
                  ><small v-if="q.supplierOrderId">外部单号：{{ q.supplierOrderId }}</small
                  ><small v-if="q.supplierQuoteRef">外部报价：{{ q.supplierQuoteRef }}</small>
                  <p>{{ q.message }}</p>
                </div>
              </details>
              <p class="quote-note">提交申请进入人工审核，不代表付款或自动出单。</p>
            </section>
            <section v-if="order" class="detail-section">
              <div class="detail-section-title">
                <h3><Icon name="orders" :size="17" />业务申请</h3>
                <StatusBadge :value="order.status" />
              </div>
              <p class="order-number">{{ order.orderNo }}</p>
              <div class="order-premium">
                <span>核实保费</span><b>{{ orderAmount(order.totalPremium) }}</b>
              </div>
              <p class="quote-note" v-if="order.policyNo">保单号：{{ order.policyNo }}</p>
              <button
                v-if="editable && orderStateOptions(order, auth.user.role).length"
                class="button block small"
                @click="editOrder"
              >
                登记办理进度
              </button>
              <div v-for="h in (order.history || []).slice(-3)" :key="h.id" class="order-track">
                <span>{{ statusName(h.status) }}</span
                ><small>{{ date(h.createdAt) }}</small>
                <p>{{ h.note }}</p>
              </div>
            </section>
            <div class="detail-footer">
              <Icon name="shield" :size="14" />证件资料仅供本笔业务核验
            </div>
          </aside></template
        >
      </div>
    </div>
  </div>
  <Modal v-if="vehicleForm" title="核对车辆与投保资料" wide @close="vehicleForm = null"
    ><form @submit.prevent="saveVehicle">
      <div class="notice amber">请对照原始证件核对后保存。修改资料会使已生成的旧报价失效。</div>
      <div class="form-grid">
        <label>车牌号<input v-model="vehicleForm.plateNo" maxlength="20" required /></label
        ><label>品牌型号<input v-model="vehicleForm.brandModel" maxlength="100" /></label
        ><label class="full"
          >车架号 VIN<input
            v-model="vehicleForm.vin"
            pattern="[A-HJ-NPR-Za-hj-npr-z0-9]{17}"
            maxlength="17"
            placeholder="17 位车架号" /></label
        ><label>发动机号<input v-model="vehicleForm.engineNo" maxlength="100" /></label
        ><label
          >核定座位数<input
            v-model="vehicleForm.seatCount"
            type="number"
            min="1"
            max="100"
            step="1" /></label
        ><label>注册日期<input v-model="vehicleForm.registerDate" type="date" /></label
        ><label>发证日期<input v-model="vehicleForm.issueDate" type="date" /></label
        ><label>车主姓名<input v-model="vehicleForm.ownerName" maxlength="100" required /></label
        ><label
          >联系电话<input
            v-model="vehicleForm.phone"
            pattern="1[3-9][0-9]{9}"
            maxlength="11"
            inputmode="tel"
            required /></label
        ><label
          >使用性质<input
            v-model="vehicleForm.useNature"
            maxlength="50"
            placeholder="请按行驶证填写" /></label
        ><label
          >车主身份证号<input
            v-model="vehicleForm.idNumber"
            maxlength="18"
            pattern="[0-9]{17}[0-9Xx]" /></label
        ><label class="full">证件地址<input v-model="vehicleForm.address" maxlength="300" /></label
        ><label class="full"
          >已核实车型代码（可选）<input
            v-model="vehicleForm.selectedModelCode"
            maxlength="100"
            placeholder="仅在保司返回车型待确认时填写"
        /></label>
      </div>
      <div class="form-actions">
        <button type="button" class="button" @click="vehicleForm = null">取消</button
        ><button class="button primary" :disabled="working">
          {{ working ? '保存中…' : '确认并保存资料' }}
        </button>
      </div>
    </form></Modal
  >
  <Modal v-if="quoteForm" title="配置泰康报价方案" @close="quoteForm = null"
    ><form @submit.prevent="quote">
      <div v-if="isTruck" class="notice amber">
        货车承保协议未支持时会返回人工处理，请勿按家庭自用车辆填写。
      </div>
      <div class="form-grid">
        <label class="full"
          >报价方案<select v-model="quoteForm.plan">
            <option value="COMPULSORY">交强险</option>
            <option value="STANDARD">交强 + 三者</option>
            <option value="FULL">全险（含车损）</option>
          </select></label
        ><template v-if="quoteForm.plan !== 'COMPULSORY'"
          ><label
            >第三者责任保额（元）<input
              v-model="quoteForm.thirdPartyAmount"
              type="number"
              min="0"
              step="10000"
              required /></label
          ><label
            >医保外责任保额（元）<input
              v-model="quoteForm.medicalAmount"
              type="number"
              min="0"
              step="10000"
              required /></label
          ><label
            >司机每座保额（元）<input
              v-model="quoteForm.driverAmount"
              type="number"
              min="0"
              step="10000"
              required /></label
          ><label
            >乘客每座保额（元）<input
              v-model="quoteForm.passengerAmount"
              type="number"
              min="0"
              step="10000"
              required /></label
        ></template>
      </div>
      <p class="form-help">
        每次只请求一个明确方案。新报价会使旧报价版本失效，结果未知时须先核实。
      </p>
      <div class="form-actions">
        <button type="button" class="button" @click="quoteForm = null" :disabled="working">
          取消</button
        ><button class="button primary" :disabled="working">
          {{ working ? '报价处理中，请勿重复提交…' : '确认请求报价' }}
        </button>
      </div>
    </form></Modal
  >
  <Modal v-if="transferOpen" title="转接人工客服" @close="transferOpen = false"
    ><form @submit.prevent="transfer">
      <label
        >接收客服<select v-model="transferTo" required>
          <option value="">请选择客服</option>
          <option v-for="a in agents" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select></label
      >
      <p class="form-help">服务端会再次检查接收客服的组织授权。</p>
      <div class="form-actions">
        <button type="button" class="button" @click="transferOpen = false">取消</button
        ><button class="button primary" :disabled="working || !transferTo">确认转接</button>
      </div>
    </form></Modal
  >
  <Modal v-if="preview" :title="preview.name || '资料原图'" wide @close="preview = null"
    ><img class="document-preview" :src="preview.url" :alt="preview.name || '用户资料'"
  /></Modal>
  <Modal v-if="orderForm" title="登记业务办理进度" @close="orderForm = null"
    ><form @submit.prevent="updateOrder">
      <div class="form-grid">
        <label class="full"
          >下一状态<select v-model="orderForm.status" required>
            <option v-for="s in orderStateOptions(order, auth.user.role)" :value="s">
              {{ statusName(s) }}
            </option>
          </select></label
        ><label v-if="orderForm.status === 'COMPLETED'" class="full"
          >核实后的保单号<input v-model="orderForm.policyNo" required maxlength="100" /></label
        ><label v-if="!order.quoteId && orderForm.status !== 'CANCELLED'" class="full"
          >人工核实保费（元）<input
            v-model="orderForm.totalPremium"
            type="number"
            min="0.01"
            step="0.01"
            :required="orderForm.status === 'COMPLETED' && !order.premiumConfirmed"
            placeholder="最多2位小数，核实后填写" /></label
        ><label class="full"
          >跟进说明<textarea v-model="orderForm.note" required maxlength="500" rows="4" />
        </label>
      </div>
      <p class="form-help">完成状态需核实正式保单号，不由本页面自动出单。</p>
      <div class="form-actions">
        <button type="button" class="button" @click="orderForm = null">取消</button
        ><button class="button primary" :disabled="working">保存跟进</button>
      </div>
    </form></Modal
  >
  <Modal v-if="passwordForm" title="修改客服登录密码" @close="passwordForm = null"
    ><form @submit.prevent="changePassword">
      <div class="form-grid">
        <label class="full"
          >原密码<input
            v-model="passwordForm.oldPassword"
            type="password"
            autocomplete="current-password"
            required /></label
        ><label class="full"
          >新密码<input
            v-model="passwordForm.newPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="128"
            required /></label
        ><label class="full"
          >确认新密码<input
            v-model="passwordForm.repeat"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="128"
            required
        /></label>
      </div>
      <div class="form-actions">
        <button class="button primary" :disabled="working">修改密码</button>
      </div>
    </form></Modal
  >
  <Transition name="toast"
    ><div v-if="toast" class="toast-message" :class="toast.tone" role="status">
      <Icon :name="toast.tone === 'error' ? 'info' : 'check'" :size="18" />{{ toast.message
      }}<button @click="toast = null" aria-label="关闭提示">×</button>
    </div></Transition
  >
</template>
