const api = require('../../utils/api')
const auth = require('../../utils/auth')
const fmt = require('../../utils/format')
Page({
  data: { loading: true, error: '', order: null, history: [] },
  onLoad(options) {
    this.id = options.id
    this.load()
  },
  onShow() {
    if (this.data.order) this.load()
  },
  async load() {
    if (!auth.ensureLogin()) {
      this.setData({ loading: false })
      return
    }
    if (!this.id) {
      this.setData({ loading: false, error: '未找到订单编号' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      const result = await api.get('/orders/' + encodeURIComponent(this.id))
      this.setData({
        order: fmt.order(result),
        history: (result.history || []).map((item) =>
          Object.assign({}, item, {
            statusLabel: fmt.statusLabels[item.status] || item.status,
            timeLabel: fmt.formatTime(item.createdAt),
          }),
        ),
      })
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this.setData({ loading: false })
    }
  },
  conversation() {
    if (this.data.order.sessionId)
      wx.navigateTo({
        url:
          '/pages/assistant/index?id=' +
          encodeURIComponent(this.data.order.sessionId),
      })
  },
  copyNumber() {
    wx.setClipboardData({ data: this.data.order.orderNo })
  },
})
