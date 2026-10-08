"""HTTP 제어 서버. 실행: 저장소 루트에서 `python -m drone.server [--config PATH]`.

엔드포인트(모두 X-API-Key 필요): GET /status, POST /dispatch, POST /abort, POST /reset
"""
import argparse
import hmac
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from drone.config import DEFAULT_CONFIG_PATH, config_flags, load_config, print_config_warnings
from drone.controller import Controller
from drone.jsonlog import JsonLog
from drone.link import FcLink


class DispatchReq(BaseModel):
    # NaN/Inf는 422로 거절 (검증 응답 JSON 직렬화도 깨짐)
    lat: float = Field(allow_inf_nan=False, ge=-90, le=90)
    lon: float = Field(allow_inf_nan=False, ge=-180, le=180)
    alt_rel: float = Field(allow_inf_nan=False)


def create_app(cfg, controller, log):
    app = FastAPI(title="PX4 dispatch MVP", docs_url=None, redoc_url=None, openapi_url=None)
    key = cfg["api_key"]

    def require_key(x_api_key: str = Header(default="")):
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), key.encode()):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        t0 = time.monotonic()
        body = None
        if request.method == "POST":
            raw = await request.body()
            body = raw.decode("utf-8", "replace")[:500]
        resp = await call_next(request)
        log.write("http", method=request.method, path=request.url.path,
                  client=request.client.host if request.client else None,
                  status=resp.status_code, body=body, ms=round((time.monotonic() - t0) * 1000, 1),
                  key_present=bool(request.headers.get("x-api-key")))
        return resp

    @app.exception_handler(RequestValidationError)
    async def on_invalid(request: Request, exc: RequestValidationError):
        # 기본 핸들러는 입력값을 되돌려 보내는데 NaN이면 JSON 직렬화가 실패한다 → loc/msg만 반환
        errs = [dict(loc=[str(x) for x in e.get("loc", ())], msg=e.get("msg"), type=e.get("type"))
                for e in exc.errors()]
        log.write("http_invalid", path=request.url.path, errors=errs)
        return JSONResponse(status_code=422, content=dict(accepted=False, sent=False,
                                                          reasons=["invalid_request"], errors=errs))

    deps = [Depends(require_key)]

    @app.get("/status", dependencies=deps)
    def status():
        return controller.status()

    @app.post("/dispatch", dependencies=deps)
    def dispatch(req: DispatchReq):
        code, body = controller.dispatch(req.lat, req.lon, req.alt_rel)
        return JSONResponse(status_code=code, content=body)

    @app.post("/abort", dependencies=deps)
    def abort():
        code, body = controller.abort()
        return JSONResponse(status_code=code, content=body)

    @app.post("/reset", dependencies=deps)
    def reset():
        code, body = controller.reset()
        return JSONResponse(status_code=code, content=body)

    return app


def build(cfg):
    log = JsonLog(cfg["log_dir"])
    link = FcLink(cfg["mavlink"], log)
    ctrl = Controller(cfg, link, log)
    app = create_app(cfg, ctrl, log)
    return app, link, ctrl, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--connection", help="config의 mavlink.connection 덮어쓰기 (예: udpin:0.0.0.0:14540)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.connection:
        cfg["mavlink"]["connection"] = args.connection
    app, link, ctrl, log = build(cfg)
    warns = print_config_warnings(cfg)
    log.write("server_start", http=cfg["http"], mavlink=cfg["mavlink"]["connection"],
              config_flags=config_flags(cfg), config_warnings=warns)
    try:
        link.start()
    except Exception as e:
        log.write("link_open_failed", error=repr(e))
        raise SystemExit("[drone] cannot open %s: %r\n  -> check: sudo fuser %s (port busy?), permissions (dialout group)"
                         % (cfg["mavlink"]["connection"], e, cfg["mavlink"]["connection"]))
    import uvicorn
    try:
        uvicorn.run(app, host=cfg["http"]["host"], port=int(cfg["http"]["port"]), log_level="info")
    finally:
        link.stop()
        log.write("server_stop")


if __name__ == "__main__":
    main()
