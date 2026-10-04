"""FastAPI 应用入口。

只做装配：动校档/层状模型两套存储、错误响应映射、双曲与层状射线两组路由挂载。
不带任何网页（Swagger/Redoc 页面关闭），能力只走 HTTP JSON。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .errors import NmoError
from .model_store import ModelStore
from .models_router import router as models_router
from .profiles import ProfileStore
from .router import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="反射双曲线动校正核算服务",
        docs_url=None,
        redoc_url=None,
    )
    app.state.profile_store = ProfileStore()
    app.state.model_store = ModelStore()

    @app.exception_handler(NmoError)
    async def handle_nmo_error(_: Request, exc: NmoError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": True, "reason": exc.reason},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        reasons = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            message = err.get("msg", "请求参数不合法")
            reasons.append(f"{location or '请求体'}: {message}" if location else message)
        return JSONResponse(
            status_code=400,
            content={"error": True, "reason": "; ".join(reasons)},
        )

    app.include_router(router)
    app.include_router(models_router)
    return app


app = create_app()
