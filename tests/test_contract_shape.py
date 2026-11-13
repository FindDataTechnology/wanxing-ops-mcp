"""响应形状断言：本 MCP 摊给模型的字段，契约里必须都声明（close-wanxing-domain-linkage 6.6）。

这个 MCP 是**薄转发**：/agents、agent-card、A2A 回执、fleet board 四路响应原样
摊给模型，代码不做 destructure。正因如此，上游字段改名时这里不会报错——只会把
undefined 摊出去或整段消失，线上表现像"服务挂了"。所以断言分两半：

1. **字段集合 ↔ 契约**：把每一面会摊出去的字段冻结在本文件里，逐字比对
   `contracts/wanxing-public-api.v1.json` 的 `$defs`。契约改名 → 红。
2. **转发不丢字段**：用契约形状的夹具走**真** RegistryClient（httpx.MockTransport，
   无网络、不起服务）+ 真工具注册，断言工具输出与上游 body 逐字段相等。
   哪天有人给工具加了一层投影/改名 → 红。

两面分开标注（任务要求）：
- 萬星 **facade 公开面**：`/api/wanxing/v1/agents`、`agent-card.json`、A2A 回执。
- 萬星 **機群观测面**：`/api/fleet/v1/board`。
- 另有一组 console 管理面工具，它们打的是 facade console 编址（不是壹座 packs），
  响应外层是**本仓自造**的 {added/removed/paused/resumed, result}，契约不管，
  单独一条测试点名，避免以后误以为它们有契约背书。

契约位置优先级：`WANXING_CONTRACTS_DIR` → `../fd-wanxing/contracts` →
`../../finddata/fd-wanxing/contracts`。读不到就**失败并点名尝试过的路径**，绝不 skip。
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from fastmcp import Client, FastMCP

import wanxing_ops_mcp.tools_fleet as tf
from wanxing_ops_mcp.client import RegistryClient

CONTRACT_FILENAME = "wanxing-public-api.v1.json"

# ── 冻结的字段集合（这些就是本仓摊给模型的全部字段；改契约名 → 测试红）─────────

#: `$defs.catalogEntry` —— `/agents` 条目的每一个可能出现的键。
AGENTS_ENTRY_FIELDS = {
    "slug", "name", "description", "version", "tags", "skills", "capabilities",
    "examples", "chatable", "category", "featured", "turns7d", "cluster",
    "facade", "facade_stance", "status", "status_as_of",
}
#: 条目上永真必带的三键。
AGENTS_ENTRY_REQUIRED = {"slug", "name", "description"}
#: 状态四态（判据来源：契约 enum；unknown 是合法终态，不是缺席）。
INSTANCE_STATUSES = {"serving", "idle", "paused", "unknown"}

#: `$defs.agentsResponse` —— 信封。本 MCP 的 browse 总带 page/page_size，
#: 所以 page/page_size/total 恒在；facets 只有显式 facets=1 才有，本仓不请求。
AGENTS_ENVELOPE_FIELDS = {"agents", "page", "page_size", "total", "facets"}
AGENTS_ENVELOPE_ALWAYS = {"agents", "page", "page_size", "total"}
AGENTS_ENVELOPE_REQUIRED = {"agents"}

#: `$defs.fleetBoardResponse` —— 機群观测面。
#:
#: 2026-11-13 起含 7 个观测面新增键（states_window / runner_liveness / leases /
#: cells / shortterm / agent_health / missions）。它们不是"另一个面"，就是同一个
#: board 响应里新长出来的段落，而 board 工具是**整包转发**（`return await
#: client.request(...)`，无投影），所以模型能看到它们、也必须被契约声明。
FLEET_BOARD_FIELDS = {
    "window", "agents_total", "states", "runners", "ingest_lag",
    "settled_pending", "wake_ms", "turns", "errors", "minutes_billed",
    "usd", "budget_kills", "reaped",
    "states_window", "runner_liveness", "leases", "cells", "shortterm",
    "agent_health", "missions",
}
FLEET_BOARD_REQUIRED = {"states", "runners", "ingest_lag", "settled_pending", "wake_ms"}
FLEET_RUNNER_FIELDS = {"children", "queued", "budget_mb", "budget_mb_limit", "agents"}
FLEET_LAG_FIELDS = {"source", "event_age_ms", "arrival_age_ms"}
FLEET_SETTLED_FIELDS = {"count", "usd"}
FLEET_WAKE_FIELDS = {"p50", "p95"}
#: 新增段落的内部字段——顶层声明了但内层没人钉，等于只钉了个名字。
#:
#: 2026-11-13 订正：这两个集合原先按**我读错的形状**冻结（`{state, seen_at}` /
#: `{stalled, silent_ms, reason}`），而发端 `fleet-observer` 实际发的是下面这些
#: ——名字一个都对不上。当时本文件的断言是绿的，因为它只把契约与自己的常量比，
#: 从不与发端比。fd-wanxing 侧已补上那半个方向的判据
#: （`scripts/test-board-contract-shape.mjs`，真起 observer 对账）。
FLEET_LIVENESS_FIELDS = {"last_seen_at", "age_ms", "beats", "presence"}
FLEET_LEASE_FIELDS = {
    "available", "events", "expired_in_window", "active", "window_ms", "units",
}
FLEET_LEASE_UNIT_FIELDS = {"unit", "state", "holder", "attempt", "at", "age_ms"}
FLEET_SHORTTERM_FIELDS = {
    "cells", "running", "queued", "workers_busy", "workers_idle", "workers_cap",
}
FLEET_AGENT_HEALTH_FIELDS = {
    "agent", "health", "since", "consecutive", "consecutiveHours", "turns",
    "errors", "lastErrorKind", "stale", "window_hours",
    # 条件字段：只有声明了节奏的 agent 才带后三个
    "declared_every_ms", "expected_turns", "stalled",
}
FLEET_MISSION_FIELDS = {"id", "owner", "status", "trail", "spent", "at"}

#: `$defs.turnReceipt` —— A2A 同步回执（jsonrpc 必带；result/error 二者其一）。
TURN_RECEIPT_FIELDS = {"jsonrpc", "id", "result", "error"}
TURN_RECEIPT_ERROR_FIELDS = {"code", "message"}
#: turn 工具在外面套的一层（本仓自造，不是回执的一部分）。
TURN_WRAPPER_FIELDS = {"receipt", "idempotencyKey", "note"}

#: A2A **请求**体字段——契约只描述回执，没有请求 def，故在本地冻结。
TURN_REQUEST_FIELDS = {"jsonrpc", "id", "method", "params"}
TURN_REQUEST_MESSAGE_FIELDS = {"role", "parts"}
TURN_REQUEST_PART_FIELDS = {"kind", "text"}

#: agent-card 的实际字段（来源：facade `publicCard()` + 路由追加的 chatable/cluster）。
AGENT_CARD_FIELDS = {
    "name", "description", "version", "provider", "capabilities", "skills",
    "tags", "examples", "default_input_modes", "default_output_modes",
    "preferred_transport", "url", "facade", "facade_stance", "chatable", "cluster",
}
#: 契约 `$defs.agentCard` 之前的空洞白名单。**已清空**：萬星补上了 agentCard 定义
#: （`x-contract-rev` 不变——纯附加），卡片字段现在逐个有声明，不再靠同名键蹭
#: catalogEntry。留空而不是删掉这个常量，是为了让"又冒出新的未声明字段"时仍有一条
#: 显式差异可读（`gap == AGENT_CARD_NOT_IN_CONTRACT` 会直接点名），而不必重新发明判据。
AGENT_CARD_NOT_IN_CONTRACT: set[str] = set()


# ── 契约加载（读不到 = 失败，点名路径）────────────────────────────────────────

def _contract_candidates() -> list[Path]:
    override = os.environ.get("WANXING_CONTRACTS_DIR")
    if override:
        root = Path(override).expanduser()
        return [root / CONTRACT_FILENAME if root.is_dir() else root]
    repo = Path(__file__).resolve().parents[1]
    return [
        repo.parent / "fd-wanxing" / "contracts" / CONTRACT_FILENAME,
        repo.parent.parent / "finddata" / "fd-wanxing" / "contracts" / CONTRACT_FILENAME,
    ]


def load_contract() -> dict:
    import json

    tried = _contract_candidates()
    for path in tried:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise AssertionError(
        "读不到萬星公开 API 契约。尝试过：\n"
        + "\n".join(f"  - {p}" for p in tried)
        + "\n设 WANXING_CONTRACTS_DIR 指向含 "
        + CONTRACT_FILENAME
        + " 的目录。"
    )


def _props(contract: dict, def_name: str) -> set[str]:
    return set(contract["$defs"][def_name]["properties"])


# ── 夹具：契约形状（全部字段填充，含每个可选键）────────────────────────────────

def _agents_entry(status: str = "serving") -> dict:
    return {
        "slug": "packs-p1-heal",
        "name": "heal",
        "description": "工单型 heal agent",
        "version": "1.2.3",
        "tags": ["ops", "heal"],
        "skills": [{"id": "submit", "name": "SUBMIT"}],
        "capabilities": {"streaming": True},
        "examples": ["SUBMIT reports/x.yaml"],
        "chatable": True,
        "category": "运维",
        "featured": True,
        "turns7d": 12,
        "cluster": {"id": "c-1", "slug": "cl-1", "url": "https://x/a2a/cluster/cl-1"},
        "facade": True,
        "facade_stance": "hosted",
        "status": status,
        "status_as_of": "2026-11-13T02:00:00Z",
    }


def _agents_envelope(status: str = "serving") -> dict:
    return {"agents": [_agents_entry(status)], "page": 1, "page_size": 50, "total": 1}


def _agent_card() -> dict:
    return {
        "name": "heal",
        "description": "工单型 heal agent",
        "version": "1.2.3",
        "provider": {"organization": "paas-pack"},
        "capabilities": {"streaming": True},
        "skills": [{"id": "submit", "name": "SUBMIT", "tags": ["default"]}],
        "tags": ["ops"],
        "examples": ["SUBMIT reports/x.yaml"],
        "default_input_modes": ["text"],
        "default_output_modes": ["text"],
        "preferred_transport": "jsonrpc",
        "url": "https://wanxing.example/api/wanxing/v1/a2a/packs-p1-heal",
        "facade": True,
        "facade_stance": "hosted",
        "chatable": True,
        "cluster": {"id": "c-1", "slug": "cl-1"},
    }


def _turn_receipt() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"kind": "queued", "messageId": "m-1", "status": {"state": "working"}},
    }


def _fleet_board() -> dict:
    return {
        "window": "24h",
        "agents_total": 18,
        "states": {"serving": 3, "idle": 10, "paused": 1, "unknown": 4},
        "runners": {
            "wu-1": {"children": 2, "queued": 0, "budget_mb": 512,
                     "budget_mb_limit": 1024, "agents": 4},
        },
        "ingest_lag": [{"source": "agent-events", "event_age_ms": 120, "arrival_age_ms": 80}],
        "settled_pending": {"count": 2, "usd": 1.5},
        "wake_ms": {"p50": 420, "p95": 1800},
        "turns": 30,
        "errors": 1,
        "minutes_billed": 42,
        "usd": 2.5,
        "budget_kills": 0,
        "reaped": 1,
        # ── 2026-11-13 新增的观测段落（整包转发 ⇒ 夹具也必须有，否则"逐字相等"
        #    只是对着一份缺段的夹具自证）
        "states_window": "2h",
        "runner_liveness": {
            "wu-1": {"last_seen_at": 1_800_000_000_000, "age_ms": 12_000,
                     "beats": 38282, "presence": "ok"},
            # 缺一个 runner 是**语义**（不在表里＝不报活着），故这里故意只放一个
        },
        "leases": {
            "available": True,
            "events": 12,
            "expired_in_window": 1,
            "active": 2,
            "window_ms": 300_000,
            "units": [
                {"unit": "cell-a", "state": "claimed", "holder": "wu-1",
                 "attempt": 1, "at": 1_799_999_000_000, "age_ms": 60_000},
            ],
        },
        "cells": {
            "cell-a": {"state": "serving", "agents": 2, "running": 1, "queued": 0},
        },
        "shortterm": {
            "cells": 1, "running": 1, "queued": 0,
            "workers_busy": 1, "workers_idle": 3, "workers_cap": 4,
        },
        "agent_health": [
            {"agent": "spider-heal", "health": "ok", "since": None,
             "consecutive": 0, "consecutiveHours": 0, "turns": 12, "errors": 0,
             "lastErrorKind": None, "stale": False, "window_hours": 72},
        ],
        "missions": [
            {"id": "m-1", "owner": "ops", "status": "running",
             "trail": [{"at": 1_799_999_500_000, "status": "running"}],
             "spent": 0.25, "at": 1_799_999_500_000},
        ],
    }


def _mcp_with(handler) -> tuple[FastMCP, RegistryClient]:
    """真 RegistryClient + 真工具注册，transport 换成 MockTransport（零网络）。"""
    client = RegistryClient("https://wanxing.example", timeout_seconds=5,
                            transport=httpx.MockTransport(handler))
    mcp = FastMCP("t-contract")
    tf.register(mcp, client)
    return mcp, client


def _data(result):
    return result.data if hasattr(result, "data") else result


# ══ 萬星 facade 公开面 ①：/api/wanxing/v1/agents ═════════════════════════════

def test_contract_is_readable_and_versioned():
    contract = load_contract()
    assert contract.get("x-contract-rev"), "契约缺 x-contract-rev"
    assert {"catalogEntry", "agentsResponse", "fleetBoardResponse", "turnReceipt"} <= set(
        contract["$defs"]
    )


def test_facade_agents_entry_fields_are_all_declared():
    contract = load_contract()
    declared = _props(contract, "catalogEntry")
    assert declared == AGENTS_ENTRY_FIELDS, (
        f"契约 catalogEntry 与本仓摊给模型的字段集漂移："
        f"仅契约有={sorted(declared - AGENTS_ENTRY_FIELDS)}，"
        f"仅本仓有={sorted(AGENTS_ENTRY_FIELDS - declared)}"
    )
    assert set(contract["$defs"]["catalogEntry"]["required"]) <= declared
    assert AGENTS_ENTRY_REQUIRED <= declared


def test_facade_agents_status_enum_is_the_four_states():
    contract = load_contract()
    status = contract["$defs"]["catalogEntry"]["properties"]["status"]
    assert set(status["enum"]) == INSTANCE_STATUSES
    assert "status_as_of" in _props(contract, "catalogEntry")


def test_facade_agents_envelope_fields_are_all_declared():
    contract = load_contract()
    declared = _props(contract, "agentsResponse")
    assert declared == AGENTS_ENVELOPE_FIELDS, (
        f"agentsResponse 漂移：仅契约有={sorted(declared - AGENTS_ENVELOPE_FIELDS)}，"
        f"仅本仓有={sorted(AGENTS_ENVELOPE_FIELDS - declared)}"
    )
    assert set(contract["$defs"]["agentsResponse"]["required"]) == AGENTS_ENVELOPE_REQUIRED
    # browse 恒带 page/page_size → 这三个键恒在，属于本仓实际摊出去的信封形状
    assert AGENTS_ENVELOPE_ALWAYS <= declared


@pytest.mark.parametrize("status", sorted(INSTANCE_STATUSES))
async def test_facade_agents_relays_every_field_verbatim(status):
    payload = _agents_envelope(status)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=payload)

    mcp, client = _mcp_with(handler)
    try:
        async with Client(mcp) as c:
            out = _data(await c.call_tool("wanxing_agents_browse", {"page": 1, "page_size": 50}))
    finally:
        await client.aclose()

    assert seen["params"] == {"page": "1", "page_size": "50"}
    assert seen["auth"] is None  # 公开读面不发 Authorization
    assert out == payload  # 逐字段相等：不改名、不丢字段、不塞 undefined
    entry_by_field = out["agents"][0]
    assert set(entry_by_field) == AGENTS_ENTRY_FIELDS
    assert entry_by_field["status"] == status
    assert entry_by_field["status_as_of"] == "2026-11-13T02:00:00Z"


# ══ 萬星 facade 公开面 ②：/.well-known/agent-card.json ═══════════════════════

def test_facade_agent_card_has_a_contract_def():
    """契约必须给 agent-card 一个定义：卡片是公开发现面，字段不能只靠同名键蹭目录条目。

    这条原本是反向绊线（"契约还没有 agentCard，补上就红"）。萬星 2026-11-13 补上后
    按它自己的提示翻面：现在钉的是"定义存在且被本测试真的用上"。
    """
    contract = load_contract()
    assert "agentCard" in contract["$defs"], (
        "契约缺少 agentCard 定义——卡片字段将无处声明"
    )


def test_facade_agent_card_fields_declared_or_documented_gap():
    contract = load_contract()
    declared = _props(contract, "agentCard")
    gap = AGENT_CARD_FIELDS - declared
    assert gap == AGENT_CARD_NOT_IN_CONTRACT, (
        f"agent-card 契约空洞变化：新空洞={sorted(gap - AGENT_CARD_NOT_IN_CONTRACT)}，"
        f"已补上={sorted(AGENT_CARD_NOT_IN_CONTRACT - gap)}"
    )


async def test_facade_agent_card_relayed_verbatim():
    payload = _agent_card()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=payload)

    mcp, client = _mcp_with(handler)
    try:
        async with Client(mcp) as c:
            out = _data(await c.call_tool("wanxing_agent_card", {"agent_slug": "packs-p1-heal"}))
    finally:
        await client.aclose()

    assert seen["path"] == "/api/wanxing/v1/a2a/packs-p1-heal/.well-known/agent-card.json"
    assert out == payload
    assert set(out) == AGENT_CARD_FIELDS


# ══ 萬星 facade 公开面 ③：POST /api/wanxing/v1/a2a/{slug} 回执 ═══════════════

def test_facade_turn_receipt_fields_are_all_declared():
    contract = load_contract()
    receipt = contract["$defs"]["turnReceipt"]
    assert set(receipt["properties"]) == TURN_RECEIPT_FIELDS
    assert set(receipt["required"]) == {"jsonrpc"}
    assert TURN_RECEIPT_ERROR_FIELDS <= set(receipt["properties"]["error"]["properties"])


async def test_facade_turn_receipt_relayed_verbatim_without_shadowing(monkeypatch):
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: "sk-caller")
    receipt = _turn_receipt()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = __import__("json").loads(request.content)
        seen["key"] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, json=receipt)

    mcp, client = _mcp_with(handler)
    try:
        async with Client(mcp) as c:
            out = _data(await c.call_tool(
                "wanxing_agent_turn",
                {"agent_slug": "packs-p1-heal", "text": "SUBMIT x", "idempotency_key": "k-1"},
            ))
    finally:
        await client.aclose()

    # 请求体：契约无请求 def，本地冻结形状（改字段 → 红）
    assert set(seen["body"]) == TURN_REQUEST_FIELDS
    assert seen["body"]["jsonrpc"] == "2.0"
    assert seen["body"]["method"] == "message/send"
    message = seen["body"]["params"]["message"]
    assert set(message) == TURN_REQUEST_MESSAGE_FIELDS
    assert message["role"] == "user"
    assert set(message["parts"][0]) == TURN_REQUEST_PART_FIELDS
    assert seen["key"] == "k-1"

    # 回执：原样在 receipt 下，外层只有本仓自造的三键
    assert set(out) == TURN_WRAPPER_FIELDS
    assert out["receipt"] == receipt
    assert set(out["receipt"]) <= TURN_RECEIPT_FIELDS


# ══ 萬星 機群观测面：/api/fleet/v1/board ════════════════════════════════════

def test_fleet_board_fields_are_all_declared():
    contract = load_contract()
    board = contract["$defs"]["fleetBoardResponse"]
    declared = set(board["properties"])
    assert declared == FLEET_BOARD_FIELDS, (
        f"fleetBoardResponse 漂移：仅契约有={sorted(declared - FLEET_BOARD_FIELDS)}，"
        f"仅本仓有={sorted(FLEET_BOARD_FIELDS - declared)}"
    )
    assert set(board["required"]) == FLEET_BOARD_REQUIRED
    # 嵌套层也要对：runner 水位 / 摄取滞后 / 结算 pending / 唤醒分位
    assert set(board["properties"]["runners"]["additionalProperties"]["properties"]) \
        == FLEET_RUNNER_FIELDS
    assert set(board["properties"]["ingest_lag"]["items"]["properties"]) == FLEET_LAG_FIELDS
    assert set(board["properties"]["ingest_lag"]["items"]["required"]) == {"source"}
    assert set(board["properties"]["settled_pending"]["properties"]) == FLEET_SETTLED_FIELDS
    wake = board["properties"]["wake_ms"]
    assert set(wake["properties"]) == FLEET_WAKE_FIELDS
    assert set(wake["required"]) == FLEET_WAKE_FIELDS
    # 2026-11-13 新增段落的内层：只钉顶层名字等于没钉（内层改名照样静默摊出去）
    props = board["properties"]
    assert set(props["runner_liveness"]["additionalProperties"]["properties"]) \
        == FLEET_LIVENESS_FIELDS
    leases = props["leases"]["properties"]
    assert set(leases) == FLEET_LEASE_FIELDS
    assert set(leases["units"]["items"]["properties"]) == FLEET_LEASE_UNIT_FIELDS
    assert set(props["shortterm"]["properties"]) == FLEET_SHORTTERM_FIELDS
    assert set(props["agent_health"]["items"]["properties"]) == FLEET_AGENT_HEALTH_FIELDS
    assert set(props["agent_health"]["items"]["required"]) == {"agent"}
    assert set(props["missions"]["items"]["properties"]) == FLEET_MISSION_FIELDS
    assert set(props["missions"]["items"]["required"]) == {"id"}
    # `cells` 是 id → 自由形状行（契约有意只写 additionalProperties: object），
    # 不递归——见 close-wanxing-domain-linkage 的 coverage 口径：显式不透明的
    # 声明就是"故意留自由形状"，不是缺口。
    assert props["cells"]["additionalProperties"] == {"type": "object"}
    assert props["states_window"]["type"] == "string"


async def test_fleet_board_relayed_verbatim(monkeypatch):
    monkeypatch.setenv("WANXING_OPS_TOKEN", "svc-observer-token")
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: None)
    payload = _fleet_board()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=payload)

    mcp, client = _mcp_with(handler)
    try:
        async with Client(mcp) as c:
            out = _data(await c.call_tool("wanxing_fleet_board", {}))
    finally:
        await client.aclose()

    assert seen["path"] == "/api/fleet/v1/board"
    assert seen["auth"] == "Bearer svc-observer-token"  # observer 服务凭据
    assert out == payload
    assert set(out) == FLEET_BOARD_FIELDS
    assert set(out["states"]) == INSTANCE_STATUSES  # 四态在本面同样是键名


# ══ console 管理面：本仓自造外层，契约不管（分开标注，防止误认有契约背书）══════

@pytest.mark.parametrize(
    "tool_name,flag,args",
    [
        ("wanxing_callers_add", "added", {"agent_slug": "s1", "email": "x@y.z"}),
        ("wanxing_callers_remove", "removed", {"agent_slug": "s1", "user_id": 7}),
        ("wanxing_agent_pause", "paused", {"agent_slug": "s1"}),
        ("wanxing_agent_resume", "resumed", {"agent_slug": "s1"}),
    ],
)
async def test_management_face_is_local_wrapper_not_contract_pinned(
    monkeypatch, tool_name, flag, args
):
    contract = load_contract()
    assert not [name for name in contract["$defs"] if "console" in name.lower()], (
        "契约新增了 console 管理面定义：管理面工具应改为按契约断言"
    )
    monkeypatch.setenv("WANXING_OPS_TOKEN", "svc-console-token")
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: None)
    upstream = {"ok": True, "echo": tool_name}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=upstream)

    mcp, client = _mcp_with(handler)
    try:
        async with Client(mcp) as c:
            out = _data(await c.call_tool(tool_name, args))
    finally:
        await client.aclose()

    assert set(out) == {flag, "result"}  # 外层是本仓自造，上游体原样在 result
    assert out[flag] is True
    assert out["result"] == upstream
