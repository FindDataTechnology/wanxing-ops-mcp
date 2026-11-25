"""FastMCP 组装 + ASGI 布线（鉴权门 + /health + /.well-known/line-manifest.json）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fd_open_data_protocol import surface_report

from . import SERVER_NAME, tools_fleet
from .client import RegistryClient
from .config import Settings

INSTRUCTIONS = (
    "萬星舰队操作助手：浏览公开 agent 目录、读卡片、部署者管允许清单与启停、"
    "以 caller key 发起 A2A 回合。回合的同步应答是回执不是最终结果——工单型 agent "
    "的查询约定在各自卡片里。错误如实透传（401=凭据失效、402=计费门拒绝、403=无权限、"
    "404=无此条目/无计费账号、409=回合在跑按 Retry-After 重试、423=已暂停、429=超频）；"
    "空目录如实为空，绝不编造 agent 或结果。写操作（callers/pause/resume）前先读现状确认。"
)

_HEALTH_OK = b'{"status":"ok"}'
_HEALTH_OK_REPORTED = b'{"status":"ok","last_surface_report":"ok"}'
_HEALTH_FAILED_REPORTED = b'{"status":"ok","last_surface_report":"failed"}'

#: 线自描述端点（converge-line-identity-and-keys 的家族实现）：公开、免鉴权、零网络。
from fd_open_data_protocol.line_ops import assemble as _assemble
from fd_open_data_protocol.line_ops.auth_gate import (  # noqa: F401  (tests monkeypatch server.AuthGateMiddleware)
    AuthGateMiddleware,
    AuthGate,
)
from fd_open_data_protocol.line_ops.wellknown import (
    LINE_MANIFEST_ENV,
    WELL_KNOWN_PATH,
)

#: 清单定位必须锚在本仓 `server.py`，不能锚在 protocol 包里——共享实现的
#: `__file__` 指向 fd_open_data_protocol 的目录，算出来的仓根是错的
#: （2026-11-25 实测：五个消费仓的 manifest_path() 全指到 protocol 包里）。
#: **每次调用读本模块的 `__file__`（不缓存成常量）**：测试会 monkeypatch
#: `server.__file__` 模拟「pip 装的包在 site-packages」，缓存常量会让它打不中。
def _anchor():
    return globals()["__file__"]


def manifest_candidates() -> list:
    from fd_open_data_protocol.line_ops.wellknown import manifest_candidates as _f
    return _f(_anchor())


def manifest_path():
    from fd_open_data_protocol.line_ops.wellknown import manifest_path as _f
    return _f(_anchor())


def manifest_response():
    from fd_open_data_protocol.line_ops.wellknown import manifest_response as _f
    return _f(_anchor())


def create_server(settings: Settings | None = None) -> "FastMCP":
    from fastmcp import FastMCP

    settings = settings or Settings.from_env()
    mcp = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)
    client = RegistryClient(settings.base_url, timeout_seconds=settings.timeout_seconds)
    tools_fleet.register(mcp, client)
    mcp._wanxing_ops_client = client
    mcp._wanxing_ops_settings = settings
    mcp._surface_report = "not_configured"
    return mcp


def build_app(settings: Settings | None = None):
    """完整 ASGI 应用：/health 与线自描述免门；其余（/mcp）走鉴权门（无 Bearer 拒）。

    ASGI 布线由 `fd_open_data_protocol.line_ops.assemble` 提供（openspec:
    enforce-mcp-supply-contract / line-ops-runtime-core）。
    """
    settings_ = settings or Settings.from_env()
    return _assemble(
        lambda: create_server(settings_),
        auth_cache_ttl_seconds=settings_.auth_cache_ttl_seconds,
        gate_cls=AuthGateMiddleware,
        manifest_anchor=_anchor(),
        enable_surface_report=True,
    )
