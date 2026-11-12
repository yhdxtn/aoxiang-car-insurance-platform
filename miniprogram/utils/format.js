const roleLabels = {
  ADMIN: '总部管理员',
  FINANCE: '总部财务',
  AGENT: '代理',
  CUSTOMER: '普通用户',
  SERVICE: '人工客服',
}
const typeLabels = { CAR: '家用车', TRUCK: '货车', MOTORCYCLE: '摩托车' }
const statusLabels = {
  PENDING_REVIEW: '待人工核对',
  PROCESSING: '办理中',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
  BOT: '助手服务中',
  WAITING: '等待客服',
  ACTIVE: '客服接待中',
  SERVING: '客服接待中',
  HUMAN: '客服接待中',
  CLOSED: '会话已结束',
  QUOTED: '报价成功',
  MANUAL_REQUIRED: '需人工处理',
  FAILED: '报价未成功',
  OUTCOME_UNKNOWN: '结果待核查',
  PENDING: '报价处理中',
  QUOTING: '报价处理中',
  RUNNING: '报价处理中',
  EXPIRED: '报价已失效',
  SUPERSEDED: '旧版报价已失效',
}
function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (isNaN(date.getTime())) return String(value)
  const two = (n) => ('0' + n).slice(-2)
  return (
    date.getFullYear() +
    '-' +
    two(date.getMonth() + 1) +
    '-' +
    two(date.getDate()) +
    ' ' +
    two(date.getHours()) +
    ':' +
    two(date.getMinutes())
  )
}
function money(value) {
  if (value === undefined || value === null || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(2) : '—'
}
function mask(value, left, right) {
  value = String(value || '')
  return value.length > left + right
    ? value.slice(0, left) + '***' + value.slice(-right)
    : value
}
function id(prefix) {
  return (
    (prefix || 'mp') +
    '-' +
    Date.now().toString(36) +
    '-' +
    Math.random().toString(36).slice(2, 12)
  )
}
function yuanFromWan(value) {
  const text = String(value).trim()
  if (!/^\d{1,5}(\.\d{1,4})?$/.test(text))
    throw new Error('保额须为大于等于 0 的数字，最多四位小数')
  const parts = text.split('.')
  return String(Number(parts[0] + ((parts[1] || '') + '0000').slice(0, 4)))
}
function order(item) {
  const premiumPending =
    item.premiumConfirmed === false ||
    (item.premiumConfirmed === undefined &&
      !item.quoteId &&
      item.vehicleType !== 'CAR' &&
      Number(item.totalPremium || 0) === 0)
  return Object.assign({}, item, {
    statusLabel: statusLabels[item.status] || item.status,
    typeLabel: typeLabels[item.vehicleType] || item.vehicleType,
    formattedTime: formatTime(item.createdAt),
    premiumPending,
    formattedPremium: premiumPending ? '待人工核价' : money(item.totalPremium),
  })
}
function quote(item) {
  return Object.assign({}, item, {
    statusLabel:
      item.status === 'PROCESSING'
        ? '报价处理中'
        : statusLabels[item.status] || item.status,
    formattedPremium: money(item.totalPremium),
    formattedExpiry: formatTime(item.validUntil),
    coverages: (item.coverages || []).map((c) =>
      Object.assign({}, c, { formattedPremium: money(c.premium) }),
    ),
  })
}
module.exports = {
  roleLabels,
  typeLabels,
  statusLabels,
  formatTime,
  money,
  mask,
  id,
  yuanFromWan,
  order,
  quote,
}
