const api = require('../../utils/api')
const auth = require('../../utils/auth')
const media = require('../../utils/media')
const fmt = require('../../utils/format')
const config = require('../../config')
const initialVehicle = (type) => ({
  plateNo: '',
  vin: '',
  engineNo: '',
  brandModel: '',
  registerDate: '',
  issueDate: '',
  ownerName: '',
  idNumber: '',
  address: '',
  phone: '',
  vehicleType: type,
  useNature: type === 'CAR' ? '家庭自用' : '',
  seatCount: type === 'CAR' ? 5 : '',
  selectedModelCode: '',
})
Page({
  data: {
    mode: '',
    loading: true,
    busy: false,
    error: '',
    session: null,
    messages: [],
    cursor: 0,
    vehicleType: 'CAR',
    vehicleTypeLabel: '家用车',
    vehicle: {},
    vehicleSummary: {},
    hasVehicle: false,
    stage: 1,
    showForm: false,
    form: {},
    formError: '',
    messageText: '',
    uploading: false,
    uploadProgress: 0,
    quote: null,
    quoteError: '',
    quoting: false,
    quoteUncertain: false,
    submittingOrder: false,
    plan: 'FULL',
    thirdPartyWan: '200',
    driverWan: '1',
    passengerWan: '1',
    medicalWan: '20',
    sessionStatus: '',
    pollPaused: false,
    canSend: true,
    isMotorcycle: false,
    isManualVehicle: false,
    doneOrder: null,
    greeting: '你好，我是你的车险助手。先上传行驶证，我来帮你整理车辆信息。',
    useNatures: [
      '家庭自用',
      '非营业货运',
      '营业货运',
      '非营业客车',
      '其他（请联系客服确认）',
    ],
  },
  onLoad(options) {
    this._options = options || {}
    this._fileCache = Object.create(null)
    this._active = true
    this._pollDeadline = Date.now() + 300000
    this.initialize()
  },
  onShow() {
    this._active = true
    this._pollDeadline = Date.now() + 300000
    if (this.data.session) {
      this.refresh()
      this.schedulePoll()
    } else if (!this._initializing && this._options) this.initialize()
  },
  onHide() {
    this.stopPolling()
  },
  onUnload() {
    this.stopPolling()
    this._disposed = true
    if (this.data.showPrivacy) this.rejectPrivacy()
  },
  stopPolling() {
    this._active = false
    clearTimeout(this._pollTimer)
    this._pollTimer = null
  },
  async initialize() {
    if (this._initializing || this.data.session) return
    if (!auth.ensureLogin()) {
      this.setData({ loading: false })
      return
    }
    this._initializing = true
    this.setData({ loading: true, error: '' })
    try {
      const publicConfig = await getApp().loadConfig()
      this.setData({ mode: publicConfig.mode })
      const type = ['CAR', 'TRUCK', 'MOTORCYCLE'].includes(this._options.type)
        ? this._options.type
        : 'CAR'
      let session = this._options.id
        ? await api.get('/sessions/' + encodeURIComponent(this._options.id))
        : await api.post('/sessions', { vehicleType: type })
      if (session.vehicleType === 'TRUCK' && session.status === 'BOT')
        session = await api.post('/sessions/' + session.id + '/handoff', {
          reason: '货车车型与用途需要人工核验',
        })
      this.applySession(session)
      this._options.id = session.id
      await this.refreshMessages()
      this.schedulePoll()
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this._initializing = false
      this.setData({ loading: false })
    }
  },
  applySession(session) {
    const vehicle = Object.assign(
      initialVehicle(session.vehicleType),
      session.vehicle || {},
    )
    const quotes = session.quotes || []
    const newest = quotes.length ? fmt.quote(quotes[0]) : null
    if (newest)
      newest.expired =
        !!newest.validUntil &&
        new Date(newest.validUntil).getTime() <= Date.now()
    const pending = wx.getStorageSync('tk.pendingQuote.' + session.id)
    let uncertain = !!pending
    if (pending) {
      const newResult = quotes.find(
        (item) => !(pending.previousIds || []).includes(item.id),
      )
      if (
        newResult &&
        ['QUOTED', 'FAILED', 'MANUAL_REQUIRED'].includes(newResult.status)
      ) {
        uncertain = false
        wx.removeStorageSync('tk.pendingQuote.' + session.id)
      }
    }
    const status = session.status
    this.setData({
      session,
      vehicleType: session.vehicleType,
      vehicleTypeLabel: fmt.typeLabels[session.vehicleType] || '车辆',
      isMotorcycle: session.vehicleType === 'MOTORCYCLE',
      isManualVehicle: session.vehicleType !== 'CAR',
      vehicle,
      vehicleSummary: {
        plateNo: vehicle.plateNo,
        ownerName: vehicle.ownerName,
        useNature: vehicle.useNature,
        vin: fmt.mask(vehicle.vin, 5, 4),
        seatCount: vehicle.seatCount,
      },
      hasVehicle: !!(vehicle.plateNo || vehicle.vin || vehicle.ownerName),
      stage: session.orderId
        ? 3
        : newest && newest.status === 'QUOTED'
          ? wx.getStorageSync('tk.selectedQuote.' + session.id) === newest.id
            ? 3
            : 2
          : Number(session.stage) >= 2
            ? 2
            : 1,
      sessionStatus: fmt.statusLabels[status] || status,
      canSend: status !== 'CLOSED',
      quote: newest,
      quoteUncertain:
        uncertain ||
        !!(
          newest &&
          [
            'OUTCOME_UNKNOWN',
            'PROCESSING',
            'PENDING',
            'QUOTING',
            'RUNNING',
          ].includes(newest.status)
        ),
      greeting:
        session.vehicleType === 'TRUCK'
          ? '你好，货车的车型与用途需要人工核验，已为你转接客服。你可以先上传行驶证并留言。'
          : session.vehicleType === 'MOTORCYCLE'
            ? '你好，摩托车业务由人工客服协助办理。你可以先上传行驶证，客服接入后会继续为你服务。'
            : '你好，我是你的车险助手。先上传行驶证，我来帮你整理车辆信息。',
    })
  },
  async refresh() {
    if (!this.data.session || this._refreshing) return
    this._refreshing = true
    try {
      const result = await api.get('/sessions/' + this.data.session.id)
      this.applySession(result)
      await this.refreshMessages()
      this.setData({ error: '' })
    } catch (error) {
      if (this._active) auth.handleError(this, error)
    } finally {
      this._refreshing = false
    }
  },
  async refreshMessages() {
    if (!this.data.session || this._fetchingMessages) return
    this._fetchingMessages = true
    try {
      const result = await api.get(
        '/sessions/' +
          this.data.session.id +
          '/messages?after=' +
          this.data.cursor,
      )
      const known = new Set(this.data.messages.map((item) => item.id))
      const added = (result.items || [])
        .filter(
          (item) =>
            !known.has(item.id) &&
            !(Number(item.seq) === 1 && item.role === 'ASSISTANT'),
        )
        .map((item) =>
          Object.assign({}, item, {
            user: item.role === 'USER',
            service: item.role === 'SERVICE',
            timeLabel: fmt.formatTime(item.createdAt),
            imagePath: this._fileCache[item.fileId] || '',
          }),
        )
      this.setData({ cursor: result.cursor || this.data.cursor })
      if (added.length) {
        this.setData({ messages: this.data.messages.concat(added) })
        this.loadMessageImages(added)
      }
    } finally {
      this._fetchingMessages = false
    }
  },
  async loadMessageImages(items) {
    for (const item of items.filter((m) => m.fileId && !m.imagePath)) {
      if (this._disposed) return
      try {
        const path = await api.download(item.fileId)
        this._fileCache[item.fileId] = path
        const index = this.data.messages.findIndex((m) => m.id === item.id)
        if (index >= 0 && !this._disposed)
          this.setData({ ['messages[' + index + '].imagePath']: path })
      } catch (_) {
        /* 保留文件卡片，用户点击时可重试授权读取。 */
      }
    }
  },
  schedulePoll() {
    clearTimeout(this._pollTimer)
    if (
      !this._active ||
      !this.data.session ||
      this.data.session.status === 'CLOSED'
    )
      return
    if (Date.now() >= this._pollDeadline) {
      this.setData({ pollPaused: true })
      return
    }
    const human = this.data.session.status !== 'BOT' || this.data.quoteUncertain
    if (!human) return
    this._pollTimer = setTimeout(
      async () => {
        if (!this._active) return
        await this.refresh()
        this.schedulePoll()
      },
      this.data.error ? 15000 : 5000,
    )
  },
  continuePolling() {
    this._pollDeadline = Date.now() + 300000
    this.setData({ pollPaused: false })
    this.refresh()
    this.schedulePoll()
  },
  async chooseUpload() {
    await this.uploadDocument('DRIVING_LICENSE')
  },
  async addAttachment() {
    if (this.data.uploading || !this.data.canSend) return
    wx.showActionSheet({
      itemList: ['上传行驶证', '上传身份证', '上传其他图片'],
      success: async (result) =>
        this.uploadDocument(
          ['DRIVING_LICENSE', 'ID_CARD', 'OTHER'][result.tapIndex],
        ),
    })
  },
  async uploadDocument(documentType) {
    if (!this.data.session || this.data.uploading || !this.data.canSend) return
    const source = await media.selectSource()
    if (!source) return
    this.setData({ error: '' })
    try {
      const files = await media.chooseImages(source)
      if (!files.length) return
      this.setData({ uploading: true, uploadProgress: 0 })
      const uploaded = []
      for (const file of files) {
        const metadata = await api.upload(
          this.data.session.id,
          file,
          documentType,
          source,
          (progress) => this.setData({ uploadProgress: progress.progress }),
        )
        this._fileCache[metadata.id] = file.path
        await api.post('/sessions/' + this.data.session.id + '/messages', {
          content:
            '已上传' +
            { DRIVING_LICENSE: '行驶证', ID_CARD: '身份证', OTHER: '资料图片' }[
              documentType
            ],
          fileId: metadata.id,
          clientMessageId: fmt.id('file'),
        })
        uploaded.push(metadata)
        await this.refreshMessages()
      }
      if (
        documentType !== 'OTHER' &&
        !this.data.isManualVehicle &&
        uploaded.length
      )
        await this.recognize(uploaded[0].id)
      else wx.showToast({ title: '资料已上传', icon: 'success' })
    } catch (error) {
      if (!error.cancelled) auth.handleError(this, error)
    } finally {
      this.setData({ uploading: false, uploadProgress: 0 })
    }
  },
  async recognize(fileId) {
    this.setData({ busy: true })
    try {
      const result = await api.post(
        '/sessions/' + this.data.session.id + '/ocr',
        { fileId },
        90000,
      )
      if (result.status === 'RECOGNIZED' && result.vehicle) {
        const vehicle = Object.assign({}, this.data.vehicle, result.vehicle, {
          vehicleType: this.data.vehicleType,
        })
        this.setData({
          form: vehicle,
          showForm: true,
          formError: '',
          error: '',
        })
        wx.showToast({ title: '识别完成，请核对资料', icon: 'none' })
      } else {
        this.setData({
          error:
            result.message ||
            '这张资料暂未识别成功，请手动填写或联系人工客服。',
        })
        this.openForm()
      }
    } finally {
      this.setData({ busy: false })
    }
  },
  openForm() {
    if (this.data.quoteUncertain) {
      wx.showToast({
        title: '当前报价待核查，暂不能修改车辆资料',
        icon: 'none',
      })
      return
    }
    if (this.data.session && this.data.session.orderId) {
      wx.showToast({ title: '申请已提交，请联系客服修改', icon: 'none' })
      return
    }
    this.setData({
      form: Object.assign(
        initialVehicle(this.data.vehicleType),
        this.data.vehicle,
      ),
      showForm: true,
      formError: '',
    })
  },
  closeForm() {
    if (!this.data.busy) this.setData({ showForm: false })
  },
  formInput(event) {
    this.setData({
      ['form.' + event.currentTarget.dataset.field]: event.detail.value,
    })
  },
  chooseUse(event) {
    this.setData({
      'form.useNature': this.data.useNatures[Number(event.detail.value)],
    })
  },
  async saveVehicle() {
    if (this.data.busy) return
    const form = Object.assign({}, this.data.form)
    Object.keys(form).forEach((key) => {
      if (typeof form[key] === 'string') form[key] = form[key].trim()
    })
    form.plateNo = (form.plateNo || '').toUpperCase()
    form.vin = (form.vin || '').toUpperCase()
    form.vehicleType = this.data.vehicleType
    form.seatCount = Number(form.seatCount)
    if (!form.plateNo && !form.vin) {
      this.setData({ formError: '车牌号和车架号至少填写一项' })
      return
    }
    if (form.vin && !/^[A-HJ-NPR-Z0-9]{17}$/.test(form.vin)) {
      this.setData({ formError: '车架号需为 17 位字母与数字，不包含 I、O、Q' })
      return
    }
    if (form.idNumber && !/^[0-9]{17}[0-9Xx]$/.test(form.idNumber)) {
      this.setData({ formError: '车主身份证号应为18位' })
      return
    }
    if (form.phone && !/^1[3-9]\d{9}$/.test(form.phone)) {
      this.setData({ formError: '请输入 11 位联系人手机号' })
      return
    }
    if (!form.ownerName) {
      this.setData({ formError: '请填写车主姓名' })
      return
    }
    if (!form.useNature) {
      this.setData({ formError: '请确认车辆使用性质' })
      return
    }
    if (
      !Number.isInteger(form.seatCount) ||
      form.seatCount < 1 ||
      form.seatCount > 99
    ) {
      this.setData({ formError: '请填写 1 至 99 的核定座位数' })
      return
    }
    this.setData({ busy: true, formError: '' })
    try {
      const session = await api.put(
        '/sessions/' + this.data.session.id + '/vehicle',
        form,
      )
      this.setData({ stage: 1 })
      this.applySession(session)
      this.setData({ showForm: false, error: '', quote: null, stage: 1 })
      wx.showToast({ title: '资料已保存', icon: 'success' })
      await this.refreshMessages()
    } catch (error) {
      auth.handleError(this, error, 'formError')
    } finally {
      this.setData({ busy: false })
    }
  },
  confirmVehicle() {
    if (!this.data.hasVehicle) {
      this.openForm()
      return
    }
    this.setData({ stage: 2, quoteError: '' })
    setTimeout(
      () => wx.pageScrollTo({ selector: '#plan-card', duration: 250 }),
      100,
    )
  },
  selectPlan(event) {
    if (!this.data.quoting && !this.data.quoteUncertain)
      this.setData({ plan: event.currentTarget.dataset.plan })
  },
  amountInput(event) {
    this.setData({ [event.currentTarget.dataset.field]: event.detail.value })
  },
  async requestQuote() {
    if (
      this.data.quoting ||
      this.data.quoteUncertain ||
      this.data.isMotorcycle ||
      this.data.isManualVehicle
    )
      return
    const requiredFields = {
      plateNo: '车牌号（未上牌车辆请联系人工）',
      vin: '车架号',
      registerDate: '注册日期',
      engineNo: '发动机号',
      brandModel: '品牌型号',
      ownerName: '车主姓名',
      useNature: '使用性质',
      seatCount: '核定座位数',
    }
    if (this.data.mode !== 'demo')
      Object.assign(requiredFields, {
        idNumber: '车主身份证号',
        address: '证件详细地址',
        phone: '联系人手机号',
      })
    const missing = Object.keys(requiredFields).filter(
      (key) => !this.data.vehicle[key],
    )
    if (missing.length) {
      this.setData({
        quoteError:
          '请先修改资料，补充：' +
          missing.map((key) => requiredFields[key]).join('、'),
      })
      return
    }
    let payload
    try {
      payload = {
        plan: this.data.plan,
        thirdPartyAmount: fmt.yuanFromWan(this.data.thirdPartyWan),
        driverAmount: fmt.yuanFromWan(this.data.driverWan),
        passengerAmount: fmt.yuanFromWan(this.data.passengerWan),
        medicalAmount: fmt.yuanFromWan(this.data.medicalWan),
        idempotencyKey: fmt.id('quote'),
      }
    } catch (error) {
      this.setData({ quoteError: error.message })
      return
    }
    this.setData({ quoting: true, quoteError: '' })
    wx.setStorageSync('tk.pendingQuote.' + this.data.session.id, {
      key: payload.idempotencyKey,
      previousIds: (this.data.session.quotes || []).map((q) => q.id),
      createdAt: Date.now(),
    })
    try {
      const result = await api.post(
        '/sessions/' + this.data.session.id + '/quotes',
        payload,
        config.quoteTimeout,
      )
      if (
        ![
          'OUTCOME_UNKNOWN',
          'PROCESSING',
          'PENDING',
          'QUOTING',
          'RUNNING',
        ].includes(result.status)
      )
        wx.removeStorageSync('tk.pendingQuote.' + this.data.session.id)
      this.setData({
        quote: fmt.quote(result),
        quoteUncertain: [
          'OUTCOME_UNKNOWN',
          'PROCESSING',
          'PENDING',
          'QUOTING',
          'RUNNING',
        ].includes(result.status),
        stage: 2,
      })
      if (result.status !== 'QUOTED')
        this.setData({
          quoteError: result.message || '当前资料需要人工核查，请联系人工客服',
        })
      await this.refresh()
      this.schedulePoll()
    } catch (error) {
      if (
        error.code === 'NETWORK_UNKNOWN' ||
        (error.status >= 500 && error.code !== 'TAIKANG_NOT_CONFIGURED')
      )
        this.setData({
          quoteUncertain: true,
          quoteError:
            '报价请求的结果尚未确认。请先刷新查询或联系人工客服，避免重复提交。',
        })
      else {
        wx.removeStorageSync('tk.pendingQuote.' + this.data.session.id)
        auth.handleError(this, error, 'quoteError')
      }
    } finally {
      this.setData({ quoting: false })
      this.schedulePoll()
    }
  },
  chooseQuote() {
    if (
      !this.data.quote ||
      this.data.quote.status !== 'QUOTED' ||
      this.data.quoteUncertain
    )
      return
    if (
      this.data.quote.validUntil &&
      new Date(this.data.quote.validUntil).getTime() <= Date.now()
    ) {
      this.setData({ quoteError: '该报价已过期，请重新报价' })
      return
    }
    wx.setStorageSync(
      'tk.selectedQuote.' + this.data.session.id,
      this.data.quote.id,
    )
    this.setData({ stage: 3 })
    setTimeout(
      () => wx.pageScrollTo({ selector: '#confirmation-card', duration: 250 }),
      100,
    )
  },
  changePlan() {
    wx.removeStorageSync('tk.selectedQuote.' + this.data.session.id)
    this.setData({ stage: 2 })
  },
  async submitOrder() {
    if (
      this.data.submittingOrder ||
      !this.data.quote ||
      this.data.quoteUncertain
    )
      return
    const confirmed = await new Promise((resolve) =>
      wx.showModal({
        title: '确认提交投保申请',
        content:
          '请确认车辆和保障方案。提交后由客服核对承保资料，此操作不代表已付款或已出单。',
        confirmText: '确认提交',
        confirmColor: '#ff7526',
        success: (result) => resolve(result.confirm),
        fail: () => resolve(false),
      }),
    )
    if (!confirmed) return
    const keyName = 'tk.orderKey.' + this.data.quote.id
    const key = wx.getStorageSync(keyName) || fmt.id('order')
    wx.setStorageSync(keyName, key)
    this.setData({ submittingOrder: true, error: '' })
    try {
      const result = await api.post(
        '/sessions/' + this.data.session.id + '/orders',
        { quoteId: this.data.quote.id, idempotencyKey: key, confirmed: true },
      )
      this.setData({ doneOrder: result })
      await this.refresh()
      wx.navigateTo({
        url: '/pages/order-detail/index?id=' + encodeURIComponent(result.id),
      })
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this.setData({ submittingOrder: false })
    }
  },
  viewOrder() {
    const id =
      this.data.session.orderId ||
      (this.data.doneOrder && this.data.doneOrder.id)
    if (id)
      wx.navigateTo({
        url: '/pages/order-detail/index?id=' + encodeURIComponent(id),
      })
  },
  messageInput(event) {
    this.setData({ messageText: event.detail.value })
  },
  async sendMessage() {
    const content = this.data.messageText.trim()
    if (!content || !this.data.canSend || this._sending) return
    this._sending = true
    this.setData({ error: '' })
    const pending =
      this._pendingMessage && this._pendingMessage.content === content
        ? this._pendingMessage
        : { content, clientMessageId: fmt.id('msg') }
    this._pendingMessage = pending
    try {
      await api.post('/sessions/' + this.data.session.id + '/messages', pending)
      this._pendingMessage = null
      this.setData({ messageText: '' })
      await this.refresh()
      this.schedulePoll()
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this._sending = false
    }
  },
  async handoff() {
    if (!this.data.session || this.data.busy) return
    this.setData({ busy: true, error: '' })
    try {
      const result = await api.post(
        '/sessions/' + this.data.session.id + '/handoff',
        {
          reason: this.data.isMotorcycle
            ? '摩托车人工办理'
            : '用户请求人工客服协助',
        },
      )
      this.applySession(result)
      await this.refreshMessages()
      this._pollDeadline = Date.now() + 300000
      this.schedulePoll()
      wx.showToast({ title: '已进入人工服务队列', icon: 'none' })
    } catch (error) {
      auth.handleError(this, error)
    } finally {
      this.setData({ busy: false })
    }
  },
  async preview(event) {
    try {
      await media.previewFile(
        event.currentTarget.dataset.id,
        event.currentTarget.dataset.path,
      )
    } catch (error) {
      auth.handleError(this, error)
    }
  },
  openPrivacyContract() {
    if (wx.openPrivacyContract)
      wx.openPrivacyContract({
        fail: () =>
          wx.showToast({ title: '请在微信后台配置隐私保护指引', icon: 'none' }),
      })
  },
  acceptPrivacy() {
    const app = getApp()
    if (app.privacyResolve)
      app.privacyResolve({ buttonId: 'agree-privacy', event: 'agree' })
    app.privacyResolve = null
    this.setData({ showPrivacy: false })
  },
  rejectPrivacy() {
    const app = getApp()
    if (app.privacyResolve) app.privacyResolve({ event: 'disagree' })
    app.privacyResolve = null
    this.setData({ showPrivacy: false })
  },
  noop() {},
})
