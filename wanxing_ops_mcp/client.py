"""萬星 registry 客户端：Bearer 转发 + 匿名公开读 + 幂等头 + 诚实错误映射。

公共部分（httpx 客户端构建、超时、不可达归类）与五个 ops-mcp 仓共享，见
`fd_open_data_protocol.line_ops.client`（openspec: enforce-mcp-supply-contract /
line-ops-runtime-core）；但**本仓的 request 不是通用形态**，三处差异是本线契约：

1. `anonymous=True`：公开读面（/agents、agent-card）上游不读 Authorization——
   不发头，也不把「无凭据」伪装成 `Bearer anonymous`（那是自造凭据，污染上游归因）。
2. `headers` 参数：调用方透传幂等键等自定义头。
3. `423 paused`：回合暂停是萬星特有的状态，映射为 `paused`。

所以这里保留自己的 `request`，复用共享的 httpx 构建、`_resolve` 状态码表与 `_detail`。
"""

from __future__ import annotations

from typing import Any

from fd_open_data_protocol.line_ops.client import LineError, _detail as _shared_detail


class RegistryError(LineError):
    """结构化错误：kind + status + 上游 detail 原文（继承共享 LineError，签名不变）。"""


MISSING_CREDENTIAL_HINT = (
    "缺少凭据：管理面工具需要壹座平台令牌；wanxing_agent_turn 需要 caller key"
    "（在计费面板 token.finddatatech.cloud 自铸 sk-）"
)

_HINT_LIMIT = 500  # 本线上游 detail 截断到 500（原实现即此值）


def _detail(res) -> str:
    """本仓的 detail 截到 500 字（原实现），其余逻辑同共享。"""
    return _shared_detail(res)[: _HINT_LIMIT]


class RegistryClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0, transport=None):
        import httpx
        self._httpx = httpx
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds, transport=transport
        )

    async def aclose(self):
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        params: dict | None = None,
        json_body: Any | None = None,
        headers: dict | None = None,
        anonymous: bool = False,
    ) -> Any:
        if anonymous:
            # 公开读面（/agents、agent-card）上游不读 Authorization：不发头，
            # 也不把「无凭据」伪装成 `Bearer anonymous`（那是自造凭据，污染上游归因）。
            req_headers: dict[str, str] = {}
        elif not bearer:
            raise RegistryError("missing_credential", 401, MISSING_CREDENTIAL_HINT)
        else:
            req_headers = {"Authorization": f"Bearer {bearer}"}
        if headers:
            req_headers.update(headers)
        try:
            res = await self._client.request(
                method, path, headers=req_headers, params=params, json=json_body
            )
        except self._httpx.HTTPError as e:
            raise RegistryError(
                "unreachable", None, f"萬星服务不可达：{type(e).__name__}: {e}"
            ) from e
        if res.status_code == 401:
            raise RegistryError("unauthorized", 401, _detail(res))
        if res.status_code == 402:
            raise RegistryError("billing", 402, _detail(res))
        if res.status_code == 403:
            raise RegistryError("forbidden", 403, _detail(res))
        if res.status_code == 404:
            raise RegistryError("not_found", 404, _detail(res))
        if res.status_code == 409:
            raise RegistryError("conflict", 409, _detail(res))
        if res.status_code == 422:
            raise RegistryError("invalid", 422, _detail(res))
        if res.status_code == 423:
            raise RegistryError("paused", 423, _detail(res))
        if res.status_code == 429:
            raise RegistryError("rate_limited", 429, _detail(res))
        if res.status_code >= 500:
            raise RegistryError(
                "unreachable", res.status_code, f"萬星服务错误：{_detail(res)}"
            )
        if res.status_code >= 400:
            raise RegistryError("invalid", res.status_code, _detail(res))
        if not res.content:
            return None
        try:
            return res.json()
        except ValueError:
            return {"_raw": res.text}
