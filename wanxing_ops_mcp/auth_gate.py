"""HTTP 层鉴权门（ASGI 中间件）——「无 Bearer 拒 / 有 Bearer 放行」变体。

运行时实现已收敛到 `fd_open_data_protocol.line_ops.auth_gate`（openspec:
enforce-mcp-supply-contract / line-ops-runtime-core）。有界缓存（`_MAX_ENTRIES` +
`_evict()`）现在由全部五个消费仓共享——本仓此前 `_cache` 无上界。
"""

from __future__ import annotations

from fd_open_data_protocol.line_ops.auth_gate import (
    DEFAULT_MAX_ENTRIES,
    AuthGate,
    AuthGateMiddleware,
    bearer_from_scope,
)

#: 兼容别名：本仓测试与潜在内部调用曾用私有名。
#: `_bearer_from_scope` = 双头读取函数；`_CACHE_MAX` = 同一个缓存上界（旧值 1024，与共享常量同值）。
_bearer_from_scope = bearer_from_scope
_CACHE_MAX = DEFAULT_MAX_ENTRIES

__all__ = ["AuthGate", "AuthGateMiddleware", "bearer_from_scope", "_bearer_from_scope",
           "DEFAULT_MAX_ENTRIES", "_CACHE_MAX"]
