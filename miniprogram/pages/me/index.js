const api = require('../../utils/api')
const auth = require('../../utils/auth')
const fmt = require('../../utils/format')
Page({
  data: {
    loading: false,
    error: '',
    user: null,
    roleLabel: '',
    mode: '',
    balance: 0,
    canManage: false,
    canViewCustomers: false,
    canViewSessions: false,
    showPassword: false,
    oldPassword: '',
    newPassword: '',
    passwordError: '',
    saving: false,
  },
  onShow() {
    this.load()
  },
  async load() {
    if (!api.token()) {
      this.setData({ user: null, balance: 0 })
      return
    }
    const app = getApp()
    const cached = app.globalData.profileCache
    if (cached && Date.now() - cached.at < 30000) {
      const user = cached.user
      this.setData({
        user,
        balance: cached.points.balance,
        roleLabel:
          user.role === 'AGENT' && Number(user.agentLevel) === 2
            ? '二级代理'
            : user.role === 'AGENT' && Number(user.agentLevel) === 1
              ? '一级代理'
              : fmt.roleLabels[user.role] || user.role,
        canManage: ['ADMIN', 'FINANCE', 'AGENT'].includes(user.role),
        canViewCustomers: ['ADMIN', 'AGENT'].includes(user.role),
        canViewSessions: user.role !== 'FINANCE',
        loading: false,
        error: '',
      })
      return
    }
    this.setData({
      loading: true,
      error: '',
      mode: wx.getStorageSync('tk.mode'),
    })
    try {
      const [user, points] = await Promise.all([api.get('/auth/me'), api.get('/points')])
      getApp().globalData.user = user
      app.globalData.profileCache = { at: Date.now(), user, points }
      this.setData({
        user,
        balance: points.balance,
        roleLabel:
          user.role === 'AGENT' && Number(user.agentLevel) === 2
            ? '二级代理'
            : user.role === 'AGENT' && Number(user.agentLevel) === 1
              ? '一级代理'
              : fmt.roleLabels[user.role] || user.role,
        canManage: ['ADMIN', 'FINANCE', 'AGENT'].includes(user.role),
        canViewCustomers: ['ADMIN', 'AGENT'].includes(user.role),
        canViewSessions: user.role !== 'FINANCE',
      })
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this.setData({ loading: false })
    }
  },
  login() {
    auth.ensureLogin()
  },
  openInfo(event) {
    if (auth.ensureLogin())
      wx.navigateTo({
        url: '/pages/info/index?type=' + event.currentTarget.dataset.type,
      })
  },
  privacy() {
    wx.navigateTo({ url: '/pages/info/index?type=privacy' })
  },
  showPassword() {
    this.setData({
      showPassword: true,
      passwordError: '',
      oldPassword: '',
      newPassword: '',
    })
  },
  closePassword() {
    this.setData({ showPassword: false })
  },
  passwordInput(event) {
    this.setData({ [event.currentTarget.dataset.field]: event.detail.value })
  },
  async changePassword() {
    if (this.data.saving) return
    if (this.data.newPassword.length < 12) {
      this.setData({
        passwordError: '新密码至少 12 位，请使用字母、数字与符号组合',
      })
      return
    }
    this.setData({ saving: true, passwordError: '' })
    try {
      await api.put('/auth/password', {
        oldPassword: this.data.oldPassword,
        newPassword: this.data.newPassword,
      })
      getApp().clearAuth()
      this.setData({ showPassword: false, user: null, balance: 0 })
      wx.showToast({ title: '密码已更新，请重新登录', icon: 'none' })
      wx.navigateTo({ url: '/pages/login/index' })
    } catch (error) {
      auth.handleError(this, error, 'passwordError')
    } finally {
      this.setData({ saving: false })
    }
  },
  async logout() {
    const accepted = await new Promise((resolve) =>
      wx.showModal({
        title: '退出登录',
        content: '退出后需要重新登录才能查看个人资料。',
        success: (result) => resolve(result.confirm),
      }),
    )
    if (!accepted) return
    try {
      await api.post('/auth/logout', {})
    } catch (_) {}
    getApp().clearAuth()
    this.setData({ user: null, balance: 0, mode: '' })
  },
})
