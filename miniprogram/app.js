const api = require('./utils/api')
App({
  globalData: { user: null, config: null, inviteCode: '' },
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
  },
  async loadConfig() {
    const value = await api.get('/public/config', false)
    this.globalData.config = value
    return value
  },
  setAuth(auth) {
    api.setToken(auth.token)
    wx.setStorageSync('tk.user', auth.user)
    wx.setStorageSync('tk.mode', auth.mode || 'live')
    this.globalData.user = auth.user
  },
  clearAuth() {
    api.clearToken()
    wx.removeStorageSync('tk.user')
    wx.removeStorageSync('tk.mode')
    this.globalData.user = null
  },
})
