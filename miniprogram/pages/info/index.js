const api = require('../../utils/api')
const auth = require('../../utils/auth')
const fmt = require('../../utils/format')
const titles = {
  points: '积分明细',
  policies: '适用政策',
  organizations: '组织架构',
  finance: '业绩与预估佣金',
  customers: '客户资料',
  sessions: '服务会话记录',
  guide: '办理指南',
  privacy: '隐私与资料使用',
}
const paths = {
  points: '/points',
  policies: '/policies',
  organizations: '/organizations',
  finance: '/finance',
  customers: '/customers',
  sessions: '/sessions',
}
function organizationTree(items) {
  const byParent = Object.create(null)
  const ids = new Set(items.map((item) => item.id))
  items.forEach((item) => {
    const key = ids.has(item.parentId) ? item.parentId : ''
    ;(byParent[key] || (byParent[key] = [])).push(item)
  })
  const result = [],
    visited = new Set()
  function visit(parentId, depth) {
    ;(byParent[parentId] || []).forEach((item) => {
      if (visited.has(item.id)) return
      visited.add(item.id)
      result.push(
        Object.assign({}, item, {
          indent: Math.min(depth, 8) * 25,
          depthLabel: depth === 0 ? '当前可见组织' : '下级组织',
        }),
      )
      visit(item.id, depth + 1)
    })
  }
  visit('', 0)
  items
    .filter((item) => !visited.has(item.id))
    .forEach((item) =>
      result.push(Object.assign({}, item, { indent: 0, depthLabel: '组织' })),
    )
  return result
}
Page({
  data: {
    type: 'guide',
    title: '',
    loading: false,
    error: '',
    items: [],
    balance: 0,
    premium: '0.00',
    commission: '0.00',
    history: false,
    mode: '',
    page: 1,
    hasMore: false,
    search: '',
    canEditCustomers: false,
    showCustomerForm: false,
    customer: { name: '', phone: '', notes: '' },
    customerError: '',
    saving: false,
  },
  onLoad(options) {
    const type = Object.prototype.hasOwnProperty.call(titles, options.type)
      ? options.type
      : 'guide'
    this.setData({
      type,
      title: titles[type],
      mode: wx.getStorageSync('tk.mode'),
      canEditCustomers: !!(
        getApp().globalData.user &&
        ['ADMIN', 'AGENT'].includes(getApp().globalData.user.role)
      ),
    })
    wx.setNavigationBarTitle({ title: titles[type] })
    this.load(true)
  },
  onReachBottom() {
    if (this.data.hasMore) this.load(false)
  },
  async load(reset) {
    const type = this.data.type
    if (!paths[type] || this.data.loading || !auth.ensureLogin()) return
    const page = reset ? 1 : this.data.page + 1
    this.setData({ loading: true, error: '' })
    try {
      const path =
        paths[type] +
        '?' +
        api.query({
          history: type === 'policies' ? this.data.history : undefined,
          page,
          size: 20,
          search: type === 'customers' ? this.data.search.trim() : undefined,
        })
      const result = await api.get(path)
      let incoming = result.items || []
      if (type === 'organizations') incoming = organizationTree(incoming)
      if (type === 'sessions')
        incoming = incoming.map((item) =>
          Object.assign({}, item, {
            typeLabel: fmt.typeLabels[item.vehicleType],
            statusLabel: fmt.statusLabels[item.status] || item.status,
            timeLabel: fmt.formatTime(item.createdAt),
          }),
        )
      if (type === 'points')
        incoming = incoming.map((item) =>
          Object.assign({}, item, {
            timeLabel: fmt.formatTime(item.createdAt),
            positive: Number(item.delta) > 0,
          }),
        )
      if (type === 'policies')
        incoming = incoming.map((item) =>
          Object.assign({}, item, {
            typeLabel: fmt.typeLabels[item.vehicleType] || '适用车型',
            fromLabel: fmt.formatTime(item.effectiveFrom),
            toLabel: fmt.formatTime(item.effectiveTo),
          }),
        )
      if (type === 'finance')
        incoming = incoming.map((item) =>
          Object.assign({}, item, {
            statusLabel: fmt.statusLabels[item.status] || item.status,
            premiumPending: item.premiumConfirmed === false,
            premiumLabel:
              item.premiumConfirmed === false
                ? '待人工核价'
                : fmt.money(item.totalPremium),
            commissionLabel: fmt.money(item.commission),
          }),
        )
      const items = reset ? incoming : this.data.items.concat(incoming)
      this.setData({
        items,
        balance: result.balance || 0,
        premium: fmt.money(result.premium || 0),
        commission: fmt.money(result.estimatedCommission || 0),
        page,
        hasMore:
          ['customers', 'sessions'].includes(type) &&
          items.length < result.total,
      })
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this.setData({ loading: false })
    }
  },
  retry() {
    this.load(true)
  },
  toggleHistory() {
    this.setData({ history: !this.data.history })
    this.load(true)
  },
  searchInput(event) {
    this.setData({ search: event.detail.value })
  },
  search() {
    this.load(true)
  },
  openSession(event) {
    wx.navigateTo({
      url:
        '/pages/assistant/index?id=' +
        encodeURIComponent(event.currentTarget.dataset.id),
    })
  },
  goHome() {
    wx.switchTab({ url: '/pages/home/index' })
  },
  openPrivacyContract() {
    if (wx.openPrivacyContract)
      wx.openPrivacyContract({
        fail: () =>
          wx.showToast({ title: '暂未获取到微信隐私保护指引', icon: 'none' }),
      })
  },
  addCustomer() {
    this.setData({
      showCustomerForm: true,
      customerError: '',
      customer: { name: '', phone: '', notes: '' },
    })
  },
  editCustomer(event) {
    if (!this.data.canEditCustomers) return
    const customer = this.data.items.find(
      (item) => item.id === event.currentTarget.dataset.id,
    )
    this.setData({
      showCustomerForm: true,
      customerError: '',
      customer: Object.assign({}, customer),
    })
  },
  customerInput(event) {
    this.setData({
      ['customer.' + event.currentTarget.dataset.field]: event.detail.value,
    })
  },
  closeCustomer() {
    if (!this.data.saving) this.setData({ showCustomerForm: false })
  },
  async saveCustomer() {
    if (this.data.saving) return
    const customer = this.data.customer
    if (!customer.name.trim() || !/^1[3-9]\d{9}$/.test(customer.phone)) {
      this.setData({ customerError: '请填写姓名和正确的11位手机号' })
      return
    }
    this.setData({ saving: true, customerError: '' })
    try {
      const data = {
        name: customer.name.trim(),
        phone: customer.phone,
        notes: customer.notes || '',
      }
      if (customer.id) await api.put('/customers/' + customer.id, data)
      else await api.post('/customers', data)
      this.setData({ showCustomerForm: false })
      await this.load(true)
      wx.showToast({ title: '客户资料已保存', icon: 'success' })
    } catch (error) {
      auth.handleError(this, error, 'customerError')
    } finally {
      this.setData({ saving: false })
    }
  },
})
