const test = require('node:test')
const assert = require('node:assert/strict')
const fmt = require('../utils/format')
const media = require('../utils/media')
const api = require('../utils/api')
const storage = new Map()
function resetWx() {
  global.wx = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    showToast() {},
    pageScrollTo() {},
  }
  storage.clear()
}
function assistantPage() {
  let captured
  global.Page = (value) => {
    captured = value
  }
  delete require.cache[require.resolve('../pages/assistant/index')]
  require('../pages/assistant/index')
  const page = Object.assign({}, captured, {
    data: structuredClone(captured.data),
    setData(values) {
      Object.assign(this.data, values)
    },
  })
  page._fileCache = Object.create(null)
  return page
}
test('万元输入精确变为元，拒绝负数及异常格式', () => {
  assert.equal(fmt.yuanFromWan('200'), '2000000')
  assert.equal(fmt.yuanFromWan('0.0001'), '1')
  assert.equal(fmt.yuanFromWan('1.2345'), '12345')
  assert.throws(() => fmt.yuanFromWan('-1'))
  assert.throws(() => fmt.yuanFromWan('1e5'))
  assert.throws(() => fmt.yuanFromWan('1.12345'))
})
test('只接受支持的图片与10MB上限', () => {
  assert.equal(
    media.validateFile({ path: '/tmp/test.png', name: '行驶证.png', size: 100 })
      .size,
    100,
  )
  assert.throws(() =>
    media.validateFile({ path: 'x', name: 'test.pdf', size: 100 }),
  )
  assert.throws(() =>
    media.validateFile({ path: 'x', size: 10 * 1024 * 1024 + 1 }),
  )
  assert.throws(() =>
    media.validateFile({ path: 'x', type: 'video', size: 100 }),
  )
  assert.throws(() => media.validateFile({ size: 10 }))
})
test('微信聊天取消选择不触发上传，明确仅选图片', async () => {
  resetWx()
  let received
  wx.requirePrivacyAuthorize = (options) => options.success()
  wx.chooseMessageFile = (options) => {
    received = options
    options.fail({ errMsg: 'chooseMessageFile:fail cancel' })
  }
  assert.deepEqual(await media.chooseImages('CHAT'), [])
  assert.equal(received.type, 'image')
  assert.equal(received.count, 4)
})
test('拒绝隐私授权后不打开相册', async () => {
  resetWx()
  let called = false
  wx.requirePrivacyAuthorize = (options) => options.fail()
  wx.chooseMedia = () => {
    called = true
  }
  await assert.rejects(media.chooseImages('ALBUM'))
  assert.equal(called, false)
})
test('API以Authorization头传令牌，401清理本地令牌', async () => {
  resetWx()
  api.setToken('unit-test-token')
  let captured
  wx.request = (options) => {
    captured = options
    options.success({ statusCode: 200, data: { items: [] } })
  }
  await api.get('/sessions')
  assert.equal(captured.header.Authorization, 'Bearer unit-test-token')
  assert(!captured.url.includes('unit-test-token'))
  wx.request = (options) =>
    options.success({
      statusCode: 401,
      data: { code: 'UNAUTHORIZED', message: '已过期' },
    })
  await assert.rejects(api.get('/auth/me'), { message: '已过期' })
  assert.equal(api.token(), '')
})
test('未登录不能请求受保护API', async () => {
  resetWx()
  let sent = false
  wx.request = () => {
    sent = true
  }
  await assert.rejects(api.get('/orders'), { message: '请先登录' })
  assert.equal(sent, false)
})
test('网络未知的报价持久标记并阻止再次提交', async () => {
  resetWx()
  const page = assistantPage()
  page.data.mode = 'demo'
  page.data.session = { id: 'session-test', quotes: [] }
  page.data.vehicle = {
    plateNo: 'TEST',
    vin: 'TEST',
    registerDate: '2020-01-01',
    engineNo: 'TEST',
    brandModel: 'TEST',
    ownerName: 'TEST',
    useNature: '家庭自用',
    seatCount: 5,
  }
  page.schedulePoll = () => {}
  const original = api.post
  let count = 0
  api.post = async () => {
    count++
    throw Object.assign(new Error('offline'), { code: 'NETWORK_UNKNOWN' })
  }
  try {
    await page.requestQuote()
    assert.equal(page.data.quoteUncertain, true)
    assert(storage.get('tk.pendingQuote.session-test').key)
    await page.requestQuote()
    assert.equal(count, 1)
  } finally {
    api.post = original
  }
})
test('PROCESSING状态与旧报价无法清除待确认保护，新确定结果可清除', () => {
  resetWx()
  const page = assistantPage()
  storage.set('tk.pendingQuote.s1', { previousIds: ['q1'] })
  page.applySession({
    id: 's1',
    status: 'BOT',
    stage: 2,
    vehicleType: 'CAR',
    vehicle: {},
    quotes: [{ id: 'q1', status: 'QUOTED' }],
  })
  assert.equal(page.data.quoteUncertain, true)
  page.applySession({
    id: 's1',
    status: 'BOT',
    stage: 2,
    vehicleType: 'CAR',
    vehicle: {},
    quotes: [{ id: 'q2', status: 'PROCESSING' }],
  })
  assert.equal(page.data.quoteUncertain, true)
  page.applySession({
    id: 's1',
    status: 'BOT',
    stage: 3,
    vehicleType: 'CAR',
    vehicle: {},
    quotes: [{ id: 'q2', status: 'QUOTED' }],
  })
  assert.equal(page.data.quoteUncertain, false)
  assert.equal(page.data.stage, 2)
  assert.equal(storage.has('tk.pendingQuote.s1'), false)
})
test('摩托车入口不能发自动报价请求', async () => {
  resetWx()
  const page = assistantPage()
  page.data.isMotorcycle = true
  const original = api.post
  api.post = async () => {
    throw new Error('must not call')
  }
  try {
    await page.requestQuote()
    assert.equal(page.data.quoting, false)
  } finally {
    api.post = original
  }
})
test('离开会话页面清除定时器和活动标记', () => {
  resetWx()
  const page = assistantPage()
  page._active = true
  page._pollTimer = setTimeout(() => {
    throw new Error('unexpected timer')
  }, 30000)
  page.onHide()
  assert.equal(page._active, false)
  assert.equal(page._pollTimer, null)
})
test('跳过重复初始欢迎消息时仍推进游标', async () => {
  resetWx()
  const page = assistantPage()
  page.data.session = { id: 's1' }
  const original = api.get
  api.get = async () => ({
    items: [{ id: 'welcome', seq: 1, role: 'ASSISTANT', content: 'welcome' }],
    cursor: 1,
  })
  try {
    await page.refreshMessages()
    assert.equal(page.data.cursor, 1)
    assert.equal(page.data.messages.length, 0)
  } finally {
    api.get = original
  }
})

test('人工申请未核定保费时不显示0元承保', () => {
  const order = fmt.order({
    vehicleType: 'MOTORCYCLE',
    quoteId: null,
    totalPremium: '0.00',
  })
  assert.equal(order.premiumPending, true)
  assert.equal(order.formattedPremium, '待人工核价')
})

test('人工保费确认标记优先于金额与报价关联', () => {
  assert.equal(
    fmt.order({
      vehicleType: 'MOTORCYCLE',
      quoteId: null,
      totalPremium: null,
      premiumConfirmed: false,
    }).formattedPremium,
    '待人工核价',
  )
  assert.equal(
    fmt.order({
      vehicleType: 'MOTORCYCLE',
      quoteId: null,
      totalPremium: '240.00',
      premiumConfirmed: true,
    }).formattedPremium,
    '240.00',
  )
})

test('多个过期请求只触发一次登录页跳转', () => {
  resetWx()
  global.getCurrentPages = () => [{ route: 'pages/assistant/index' }]
  let navigation,
    calls = 0
  wx.navigateTo = (options) => {
    navigation = options
    calls++
  }
  const auth = require('../utils/auth')
  auth.ensureLogin()
  auth.ensureLogin()
  assert.equal(calls, 1)
  navigation.complete()
})
