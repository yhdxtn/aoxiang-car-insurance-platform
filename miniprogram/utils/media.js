const config = require('../config')
const api = require('./api')
const ALLOWED_EXT = /\.(jpe?g|png|webp)$/i
function validateFile(file) {
  if (!file || !file.path) throw new Error('没有读取到图片，请重新选择')
  if (file.size > config.maxImageBytes)
    throw new Error('单张图片不能超过 10MB，请压缩后上传')
  if (
    file.type &&
    !['image', 'image/jpeg', 'image/png', 'image/webp'].includes(file.type)
  )
    throw new Error('只支持 JPG、PNG 和 WEBP 图片')
  // 相册临时路径可能没有后缀；聊天文件的真实文件名存在时明确校验扩展名。
  if (file.name && /\.[^.]+$/.test(file.name) && !ALLOWED_EXT.test(file.name))
    throw new Error('请使用 JPG、PNG 或 WEBP 图片')
  return file
}
function authorize() {
  return new Promise((resolve, reject) => {
    if (!wx.requirePrivacyAuthorize) {
      resolve()
      return
    }
    wx.requirePrivacyAuthorize({
      success: resolve,
      fail: () =>
        reject(
          Object.assign(new Error('请同意隐私保护指引后选择资料图片'), {
            cancelled: true,
          }),
        ),
    })
  })
}
function cancelled(error) {
  return error && /cancel|取消/.test(error.errMsg || error.message || '')
}
async function chooseImages(source) {
  await authorize()
  return new Promise((resolve, reject) => {
    const fail = (error) => {
      if (cancelled(error)) resolve([])
      else reject(new Error('无法选择图片，请检查微信权限后重试'))
    }
    if (source === 'CHAT') {
      if (!wx.chooseMessageFile) {
        reject(new Error('当前微信版本暂不支持聊天选图，请更新微信或使用相册'))
        return
      }
      wx.chooseMessageFile({
        count: 4,
        type: 'image',
        success(result) {
          try {
            resolve(
              (result.tempFiles || []).map((file) =>
                validateFile({
                  path: file.path,
                  name: file.name,
                  size: file.size,
                  type: file.type,
                }),
              ),
            )
          } catch (error) {
            reject(error)
          }
        },
        fail,
      })
    } else {
      wx.chooseMedia({
        count: 4,
        mediaType: ['image'],
        sourceType: [source === 'CAMERA' ? 'camera' : 'album'],
        sizeType: ['compressed'],
        success(result) {
          try {
            resolve(
              (result.tempFiles || []).map((file) =>
                validateFile({
                  path: file.tempFilePath,
                  size: file.size,
                  type: file.fileType,
                }),
              ),
            )
          } catch (error) {
            reject(error)
          }
        },
        fail,
      })
    }
  })
}
function selectSource() {
  return new Promise((resolve) =>
    wx.showActionSheet({
      itemList: ['从手机相册选择', '从微信群 / 聊天选择', '拍摄照片'],
      success: (result) =>
        resolve(['ALBUM', 'CHAT', 'CAMERA'][result.tapIndex]),
      fail: () => resolve(null),
    }),
  )
}
async function previewFile(fileId, cachedPath) {
  const path = cachedPath || (await api.download(fileId))
  wx.previewImage({ urls: [path], current: path })
  return path
}
module.exports = {
  validateFile,
  authorize,
  chooseImages,
  selectSource,
  previewFile,
}
