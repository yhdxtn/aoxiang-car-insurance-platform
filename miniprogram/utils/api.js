const config = require('../config')
const TOKEN_KEY = 'tk.token'
function token() {
  return wx.getStorageSync(TOKEN_KEY) || ''
}
function setToken(value) {
  wx.setStorageSync(TOKEN_KEY, value)
}
function clearToken() {
  wx.removeStorageSync(TOKEN_KEY)
}
function endpoint(path) {
  return config.apiBaseUrl.replace(/\/$/, '') + path
}
function errorOf(response) {
  let data = response.data
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data)
    } catch (_) {
      data = {}
    }
  }
  const error = new Error((data && data.message) || '请求未完成，请稍后重试')
  error.code = (data && data.code) || 'HTTP_' + response.statusCode
  error.status = response.statusCode
  error.fieldErrors = data && data.fieldErrors
  return error
}
function request(method, path, data, authenticated = true, timeout) {
  return new Promise((resolve, reject) => {
    const value = token()
    if (authenticated && !value) {
      const error = new Error('请先登录')
      error.code = 'UNAUTHORIZED'
      error.status = 401
      reject(error)
      return
    }
    wx.request({
      url: endpoint(path),
      method,
      data,
      timeout: timeout || config.requestTimeout,
      header: Object.assign(
        { 'Content-Type': 'application/json' },
        authenticated ? { Authorization: 'Bearer ' + value } : {},
      ),
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300)
          resolve(response.data)
        else {
          if (response.statusCode === 401) clearToken()
          reject(errorOf(response))
        }
      },
      fail() {
        const error = new Error(
          '网络连接失败，请检查网络后刷新。提交中的报价请先查询状态。',
        )
        error.code = 'NETWORK_UNKNOWN'
        reject(error)
      },
    })
  })
}
function upload(sessionId, file, documentType, source, onProgress) {
  return new Promise((resolve, reject) => {
    if (!token()) {
      reject(new Error('请先登录'))
      return
    }
    const task = wx.uploadFile({
      url: endpoint('/sessions/' + encodeURIComponent(sessionId) + '/files'),
      filePath: file.path,
      name: 'file',
      timeout: 90000,
      formData: { documentType, source },
      header: { Authorization: 'Bearer ' + token() },
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          try {
            resolve(
              typeof response.data === 'string'
                ? JSON.parse(response.data)
                : response.data,
            )
          } catch (_) {
            reject(new Error('上传响应无法读取，请刷新会话检查资料'))
          }
        } else reject(errorOf(response))
      },
      fail() {
        reject(new Error('上传未完成，请检查网络后重试'))
      },
    })
    if (onProgress && task.onProgressUpdate) task.onProgressUpdate(onProgress)
  })
}
function download(fileId) {
  return new Promise((resolve, reject) => {
    wx.downloadFile({
      url: endpoint('/files/' + encodeURIComponent(fileId)),
      header: { Authorization: 'Bearer ' + token() },
      timeout: 30000,
      success(response) {
        if (response.statusCode === 200 && response.tempFilePath)
          resolve(response.tempFilePath)
        else reject(new Error('图片读取失败或无权访问'))
      },
      fail() {
        reject(new Error('图片下载失败，请稍后重试'))
      },
    })
  })
}
function query(params) {
  return Object.keys(params || {})
    .filter(
      (key) =>
        params[key] !== undefined && params[key] !== null && params[key] !== '',
    )
    .map(
      (key) => encodeURIComponent(key) + '=' + encodeURIComponent(params[key]),
    )
    .join('&')
}
module.exports = {
  token,
  setToken,
  clearToken,
  endpoint,
  request,
  upload,
  download,
  query,
  get: (path, auth = true) => request('GET', path, undefined, auth),
  post: (path, data, timeout) =>
    request('POST', path, data || {}, true, timeout),
  put: (path, data) => request('PUT', path, data),
  patch: (path, data) => request('PATCH', path, data),
}
