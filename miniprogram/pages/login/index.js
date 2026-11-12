const api = require('../../utils/api')
Page({
  data: {
    loading: true,
    submitting: false,
    error: '',
    allowDemoLogin: false,
    agreed: false,
    username: 'customer',
    password: '',
    showAccount: false,
  },
  async onLoad() {
    try {
      const config = await getApp().loadConfig()
      this.setData({
        allowDemoLogin: config.mode === 'demo' && config.allowDemoLogin,
      })
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },
  toggleAgree() {
    this.setData({ agreed: !this.data.agreed })
  },
  showPrivacy() {
    wx.navigateTo({ url: '/pages/info/index?type=privacy' })
  },
  input(event) {
    this.setData({ [event.currentTarget.dataset.field]: event.detail.value })
  },
  toggleAccount() {
    this.setData({ showAccount: !this.data.showAccount })
  },
  async login() {
    if (this.data.submitting) return
    if (!this.data.agreed) {
      this.setData({ error: '请阅读并同意隐私说明后登录' })
      return
    }
    this.setData({ submitting: true, error: '' })
    try {
      const login = await new Promise((resolve, reject) =>
        wx.login({
          timeout: 10000,
          success: resolve,
          fail: () => reject(new Error('微信登录暂不可用，请稍后重试')),
        }),
      )
      if (!login.code) throw new Error('未获取到微信登录凭证，请重试')
      const result = await api.request(
        'POST',
        '/auth/wechat',
        {
          code: login.code,
          inviteCode: getApp().globalData.inviteCode || undefined,
        },
        false,
      )
      this.finish(result)
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ submitting: false })
    }
  },
  async accountLogin() {
    if (!this.data.allowDemoLogin || this.data.submitting) return
    if (!this.data.agreed) {
      this.setData({ error: '请阅读并同意隐私说明' })
      return
    }
    this.setData({ submitting: true, error: '' })
    try {
      const result = await api.request(
        'POST',
        '/auth/login',
        { username: this.data.username.trim(), password: this.data.password },
        false,
      )
      this.finish(result)
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ submitting: false })
    }
  },
  finish(result) {
    getApp().setAuth(result)
    wx.showToast({ title: '登录成功', icon: 'success' })
    if (getCurrentPages().length > 1) wx.navigateBack()
    else wx.switchTab({ url: '/pages/home/index' })
  },
})
