"""Captured read/prepare quotation paths shared by Java-leased stages."""

ALLOWED_PATHS = frozenset({
    "/rest/controller/identity",
    "/rest/tplatform/getCaptcha",
    "/rest/tplatform/checkCaptcha",
    "/rest/tplatform/login",
    "/rest/groupOrder/getNewNoticeStatus",
    "/rest/tplatform/checkMenu",
    "/rest/controller/getOrderId",
    "/rest/init/basicData",
    "/rest/init/basicInfo",
    "/rest/init/car/type",
    "/rest/init/identify",
    "/rest/ocr/smartOcr",
    "/rest/ocr/saveOcrPrefillInfo",
    "/rest/car/modelinfo/query",
    "/rest/car/modelinfo/checkVehicleType",
    "/rest/save/basicInfo",
    "/rest/init/quote",
    "/rest/precise/init",
    "/rest/agent/tax",
    "/rest/init/quotation",
})
