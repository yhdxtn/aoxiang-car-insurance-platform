export const roles = {
  ADMIN: '总部管理员',
  FINANCE: '总部财务',
  AGENT: '代理',
  CUSTOMER: '普通用户',
  SERVICE: '人工客服',
};
export const vehicleTypes = { CAR: '家用车', TRUCK: '货车', MOTORCYCLE: '摩托车' };
export const statuses = {
  PENDING_REVIEW: '待审核',
  PROCESSING: '处理中',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
  BOT: '智能接待',
  WAITING: '等待人工',
  SERVING: '人工接待',
  ACTIVE: '人工接待',
  CLOSED: '已结束',
  QUOTED: '报价成功',
  MANUAL_REQUIRED: '需人工核验',
  FAILED: '报价失败',
  OUTCOME_UNKNOWN: '结果待核实',
  INVALIDATED: '已失效',
  EXPIRED: '已过期',
  SUPERSEDED: '已失效',
  ONLINE: '已登录',
  ERROR: '检查失败',
  VERIFICATION_REQUIRED: '需要人工验证',
  DEMO: '演示模式',
  NOT_CHECKED: '尚未检查',
  READY: '待检查',
};
export const menu = [
  { id: 'dashboard', label: '工作台', icon: 'grid', roles: ['ADMIN', 'FINANCE', 'AGENT'] },
  { id: 'orders', label: '订单管理', icon: 'orders', roles: ['ADMIN', 'FINANCE', 'AGENT'] },
  { id: 'customers', label: '客户管理', icon: 'users', roles: ['ADMIN', 'AGENT'] },
  { id: 'organizations', label: '组织架构', icon: 'tree', roles: ['ADMIN', 'AGENT'] },
  { id: 'users', label: '人员与权限', icon: 'shield', roles: ['ADMIN', 'AGENT'] },
  { id: 'policies', label: '政策管理', icon: 'file', roles: ['ADMIN', 'FINANCE', 'AGENT'] },
  { id: 'finance', label: '业绩与佣金', icon: 'chart', roles: ['ADMIN', 'FINANCE', 'AGENT'] },
  { id: 'points', label: '积分管理', icon: 'gift', roles: ['ADMIN', 'FINANCE', 'AGENT'] },
  { id: 'taikang', label: '泰康报价配置', icon: 'sliders', roles: ['ADMIN'] },
  { id: 'audit', label: '操作日志', icon: 'clock', roles: ['ADMIN'] },
  { id: 'account', label: '账号安全', icon: 'lock', roles: ['ADMIN', 'FINANCE', 'AGENT'] },
];
export const money = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—';
};
export const date = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('zh-CN', { hour12: false });
};
export const roleName = (value) => roles[value] || value || '—';
export const statusName = (value) => statuses[value] || value || '—';
export function statusTone(status) {
  if (['COMPLETED', 'QUOTED', 'ONLINE', 'SUCCEEDED'].includes(status)) return 'green';
  if (['FAILED', 'CANCELLED', 'ERROR', 'OUTCOME_UNKNOWN'].includes(status)) return 'red';
  if (['PROCESSING', 'ACTIVE', 'SERVING', 'BOT'].includes(status)) return 'blue';
  return 'amber';
}
export function nextOrderStates(status) {
  return (
    { PENDING_REVIEW: ['PROCESSING', 'CANCELLED'], PROCESSING: ['COMPLETED', 'CANCELLED'] }[
      status
    ] || []
  );
}
export function canManage(role) {
  return ['ADMIN', 'AGENT'].includes(role);
}
export function policyError(form, parent, now = new Date()) {
  if (!form.title?.trim() || !form.content?.trim() || !form.orgId)
    return '请填写政策名称、内容和下发组织。';
  const rate = Number(form.rate);
  if (form.rate === '' || !Number.isFinite(rate) || rate < 0 || rate > 100)
    return '佣金比例必须为 0–100 之间的数值。';
  if (!form.effectiveFrom) return '请选择生效时间。';
  const from = new Date(form.effectiveFrom).getTime(),
    to = form.effectiveTo ? new Date(form.effectiveTo).getTime() : Infinity;
  if (!Number.isFinite(from) || (form.effectiveTo && !Number.isFinite(to)) || to < from)
    return '失效时间应晚于生效时间。';
  if (parent) {
    if (rate > Number(parent.rate)) return '下级佣金比例不能超过上级授权比例。';
    if (parent.vehicleType !== form.vehicleType) return '下级政策车辆类型必须与上级一致。';
    if (from < new Date(parent.effectiveFrom).getTime()) return '下级政策不能早于上级政策生效。';
    if (parent.effectiveTo && to > new Date(parent.effectiveTo).getTime())
      return '下级政策有效期不能超出上级政策。';
  }
  return '';
}

export const orderAmount = (value) =>
  value === null || value === undefined ? '待人工核价' : '¥ ' + money(value);
export function orderStateOptions(order, role) {
  if (!order) return [];
  const states = nextOrderStates(order.status);
  if (!order.quoteId && order.status === 'PROCESSING' && ['ADMIN', 'SERVICE'].includes(role))
    states.unshift('PROCESSING');
  return role === 'AGENT' && order.premiumConfirmed === false
    ? states.filter((s) => s !== 'COMPLETED')
    : states;
}
