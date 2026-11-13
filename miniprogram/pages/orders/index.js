const api = require('../../utils/api')
const auth = require('../../utils/auth')
const fmt = require('../../utils/format')
Page({
  data: {
    mode: '',
    loggedIn: false,
    items: [],
    loading: false,
    error: '',
    search: '',
    status: '',
    page: 1,
    hasMore: false,
    tabs: [
      { value: '', label: '全部' },
      { value: 'PENDING_REVIEW', label: '待核对' },
      { value: 'PROCESSING', label: '办理中' },
      { value: 'COMPLETED', label: '已完成' },
    ],
  },
  onShow() {
    this.setData({
      mode: wx.getStorageSync('tk.mode'),
      loggedIn: !!api.token(),
    })
    if (api.token()) this.load(true)
    else this.setData({ items: [] })
  },
  onPullDownRefresh() {
    this.load(true).finally(() => wx.stopPullDownRefresh())
  },
  onReachBottom() {
    if (this.data.hasMore) this.load(false)
  },
  async load(reset) {
    if (!api.token() || this.data.loading) return
    const app = getApp()
    const cached = app.globalData.orderCache
    if (reset && cached && Date.now() - cached.at < 30000) {
      const result = cached.result || { items: [], total: 0 }
      const items = (result.items || []).map(fmt.order)
      this.setData({ items, page: 1, hasMore: items.length < result.total, error: '' })
      return
    }
    const page = reset ? 1 : this.data.page + 1
    this.setData({ loading: true, error: '' })
    try {
      const result = await api.get(
        '/orders?' +
          api.query({
            search: this.data.search.trim(),
            status: this.data.status,
            page,
            size: 15,
          }),
      )
      const incoming = (result.items || []).map(fmt.order)
      const items = reset ? incoming : this.data.items.concat(incoming)
      this.setData({ items, page, hasMore: items.length < result.total })
      if (reset) app.globalData.orderCache = { at: Date.now(), result }
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this.setData({ loading: false })
    }
  },
  searchInput(event) {
    this.setData({ search: event.detail.value })
  },
  search() {
    this.load(true)
  },
  chooseStatus(event) {
    this.setData({ status: event.currentTarget.dataset.status })
    this.load(true)
  },
  open(event) {
    wx.navigateTo({
      url:
        '/pages/order-detail/index?id=' +
        encodeURIComponent(event.currentTarget.dataset.id),
    })
  },
  login() {
    auth.ensureLogin()
  },
  goHome() {
    wx.switchTab({ url: '/pages/home/index' })
  },
})
