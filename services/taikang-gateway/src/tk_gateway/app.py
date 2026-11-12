from contextlib import asynccontextmanager
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .carrier import Carrier
from .config import Settings
from .ledger import Ledger, RequestConflict
from .models import OcrRequest, QuoteRequest
from .ocr import VisionOcr


class RequestTooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app, limit=15_000_000):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = self.limit + 1
        if length > self.limit:
            return await JSONResponse({"code": "BODY_TOO_LARGE", "message": "请求资料过大"},
                                      status_code=413)(scope, receive, send)
        count = 0

        async def limited_receive():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > self.limit:
                raise RequestTooLarge()
            return message
        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            await JSONResponse({"code": "BODY_TOO_LARGE", "message": "请求资料过大"},
                               status_code=413)(scope, receive, send)


def create_app(settings: Settings | None = None, carrier=None, ocr=None):
    settings = settings or Settings.from_env()
    ledger = Ledger(settings.ledger_path, settings.ledger_key)
    carrier = carrier or Carrier(settings)
    ocr = ocr or VisionOcr(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        ledger.close()

    app = FastAPI(title="Independent Taikang quote gateway", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit)

    def authenticated(x_gateway_token: str = Header(default="")):
        if not secrets.compare_digest(x_gateway_token, settings.token):
            raise HTTPException(status_code=401, detail="服务认证失败")

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={"code": "INVALID_REQUEST", "message": "请求字段不正确",
            "fieldErrors": [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                            for e in exc.errors()]})

    @app.exception_handler(RequestConflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)})

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code,
                            content={"code": "REQUEST_REJECTED", "message": str(exc.detail)})

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse(status_code=500, content={"code": "GATEWAY_ERROR",
            "message": "网关请求未完成，请保留原请求编号交由管理员核查。"})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/internal/login-check", dependencies=[Depends(authenticated)])
    def login_check():
        return carrier.login_check()

    @app.post("/internal/ocr", dependencies=[Depends(authenticated)])
    def recognize(body: OcrRequest):
        return ocr.recognize(body)

    @app.post("/internal/quote", dependencies=[Depends(authenticated)])
    def quote(body: QuoteRequest):
        replay = ledger.begin(body.requestId, body.model_dump())
        if replay is not None:
            return replay
        # STARTED is committed before any supplier activity. A killed process or
        # uncaught exception stays STARTED and is never automatically executed again.
        response, evidence = carrier.quote(body)
        order_id = evidence.get("orderId") or (evidence.get("orderContext") or {}).get("orderId")
        if order_id:
            response["supplierOrderId"] = str(order_id)
        ledger.complete(body.requestId, response, evidence)
        return response

    app.state.ledger = ledger
    return app
