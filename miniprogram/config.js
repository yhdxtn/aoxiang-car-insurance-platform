// 局域网开发：通过服务器的管理端 Nginx 访问 Java API，不直接开放数据库或网关。
// 正式发布前必须替换为 HTTPS request/uploadFile/downloadFile 合法域名。
module.exports = {
  apiBaseUrl: 'http://192.168.1.76:8088/api/v1',
  requestTimeout: 20000,
  quoteTimeout: 240000,
  maxImageBytes: 10 * 1024 * 1024,
  customerServicePhone: '',
}
