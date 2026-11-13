const api = require('./utils/api')
App({
  globalData: {
    user: null,
    config: null,
    configPromise: null,
    inviteCode: '',
    orderCache: null,
    profileCache: null,
  },
  onLaunch(options) {
    this.globalData.user = wx.getStorageSync('tk.user') || null
    this.globalData.inviteCode =
      (options.query && options.query.inviteCode) || ''
    if (wx.onNeedPrivacyAuthorization)
      wx.onNeedPrivacyAuthorization((resolve) => {
        this.privacyResolve = resolve
        const pages = getCurrentPages()
        const page = pages[pages.length - 1]
        if (page && page.route === 'pages/assistant/index')
          page.setData({ showPrivacy: true })
        else resolve({ event: 'disagree' })
      })
    // 提前建立配置与首屏数据缓存，首次切换订单/我的时直接显示结果。
    this.loadConfig().catch(() => {})
    this.preloadAccountData()
  },
  async loadConfig() {
    if (this.globalData.config) return this.globalData.config
    if (!this.globalData.configPromise) {
      this.globalData.configPromise = api
        .get('/public/config', false)
        .then((value) => {
          this.globalData.config = value
          return value
        })
        .finally(() => {
          this.globalData.configPromise = null
        })
    }
    return this.globalData.configPromise
  },
  preloadAccountData() {
    if (!api.token()) return
    Promise.all([
      api.get('/orders?page=1&size=15'),
      api.get('/auth/me'),
      api.get('/points'),
    ])
      .then(([orders, user, points]) => {
        const now = Date.now()
        this.globalData.orderCache = { at: now, result: orders }
        this.globalData.profileCache = { at: now, user, points }
        this.globalData.user = user
      })
      .catch(() => {})
  },
  setAuth(auth) {
    api.setToken(auth.token)
    wx.setStorageSync('tk.user', auth.user)
    wx.setStorageSync('tk.mode', auth.mode || 'live')
    this.globalData.user = auth.user
    this.globalData.orderCache = null
    this.globalData.profileCache = null
    this.preloadAccountData()
  },
  clearAuth() {
    api.clearToken()
    wx.removeStorageSync('tk.user')
    wx.removeStorageSync('tk.mode')
    this.globalData.user = null
    this.globalData.orderCache = null
    this.globalData.profileCache = null
  },
})
