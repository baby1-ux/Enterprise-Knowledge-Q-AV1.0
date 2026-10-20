"""业务异常与统一响应结构。"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """业务异常：携带 HTTP 状态码与中文提示。"""

    def __init__(self, message: str, code: int = 400, data: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data


class NotFoundError(AppError):
    """资源不存在。"""

    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message, code=404)


class UnauthorizedError(AppError):
    """未登录或登录失效。"""

    def __init__(self, message: str = "请先登录") -> None:
        super().__init__(message, code=401)


class ForbiddenError(AppError):
    """无权访问。"""

    def __init__(self, message: str = "无权访问该资源") -> None:
        super().__init__(message, code=403)


class ValidationError(AppError):
    """参数校验失败。"""

    def __init__(self, message: str = "参数不合法") -> None:
        super().__init__(message, code=400)


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应体。"""
    return {"code": 0, "message": message, "data": data}


def failure(message: str, code: int = 400, data: Any = None) -> dict[str, Any]:
    """失败响应体。"""
    return {"code": code, "message": message, "data": data}
