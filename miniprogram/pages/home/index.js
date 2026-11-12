const api = require('../../utils/api')
const auth = require('../../utils/auth')
const fmt = require('../../utils/format')
Page({
  data: { mode: '', loading: true, error: '', sessions: [], loggedIn: false },
  onShow() {
    this.load()
  },
  async load() {
    this.setData({ loading: true, error: '', loggedIn: !!api.token() })
    try {
      const config = await getApp().loadConfig()
      this.setData({ mode: config.mode })
      if (api.token()) {
        const result = await api.get('/sessions?page=1&size=3')
        this.setData({
          sessions: (result.items || []).map((item) =>
            Object.assign({}, item, {
              typeLabel: fmt.typeLabels[item.vehicleType],
              statusLabel: fmt.statusLabels[item.status] || item.status,
              formattedTime: fmt.formatTime(item.createdAt),
            }),
          ),
        })
      } else this.setData({ sessions: [] })
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },
  start(event) {
    if (!auth.ensureLogin()) return
    const type = event.currentTarget.dataset.type
    wx.navigateTo({ url: '/pages/assistant/index?type=' + type })
  },
  resume(event) {
    if (auth.ensureLogin())
      wx.navigateTo({
        url:
          '/pages/assistant/index?id=' +
          encodeURIComponent(event.currentTarget.dataset.id),
      })
  },
  login() {
    wx.navigateTo({ url: '/pages/login/index' })
  },
  openGuide() {
    wx.navigateTo({ url: '/pages/info/index?type=guide' })
  },
})
