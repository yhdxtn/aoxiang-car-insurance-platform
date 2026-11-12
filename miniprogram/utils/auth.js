const api = require('./api')
let loginNavigationPending = false
function ensureLogin() {
  if (api.token()) return true
  const pages = getCurrentPages()
  if (
    !loginNavigationPending &&
    (!pages.length || pages[pages.length - 1].route !== 'pages/login/index')
  ) {
    loginNavigationPending = true
    wx.navigateTo({
      url: '/pages/login/index',
      complete() {
        loginNavigationPending = false
      },
    })
  }
  return false
}
function handleError(page, error, field) {
  page.setData({ [field || 'error']: error.message || '操作未完成' })
  if (error.status === 401) {
    getApp().clearAuth()
    wx.showToast({ title: '登录已过期，请重新登录', icon: 'none' })
    ensureLogin()
  }
}
module.exports = { ensureLogin, handleError }
