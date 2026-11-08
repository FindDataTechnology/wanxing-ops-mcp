"""八工具接线测试：薄转发+分型语义（fake client）。"""

from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP

import wanxing_ops_mcp.tools_fleet as tf
from wanxing_ops_mcp.client import RegistryError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    async def request(self, method, path, *, bearer=None, params=None, json_body=None,
                      headers=None, anonymous=False):
        self.calls.append({"method": method, "path": path, "bearer": bearer,
                           "params": params, "json_body": json_body, "headers": headers,
                           "anonymous": anonymous})
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def bearer(monkeypatch):
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: "tok-abc")
    return "tok-abc"


async def _mk(fake):
    mcp = FastMCP("t-wx")
    tf.register(mcp, fake)
    return mcp


async def test_browse_public_read_paginates(bearer):
    fake = FakeClient(result={"agents": []})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wanxing_agents_browse", {"page": 2, "page_size": 10})
    call = fake.calls[0]
    assert call["path"] == "/api/wanxing/v1/agents"
    assert call["params"] == {"page": 2, "page_size": 10}


async def test_card_path(bearer):
    fake = FakeClient(result={"name": "heal"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wanxing_agent_card", {"agent_slug": "packs-x-heal"})
    assert fake.calls[0]["path"] == "/api/wanxing/v1/a2a/packs-x-heal/.well-known/agent-card.json"


async def test_callers_add_thin_forward(bearer):
    fake = FakeClient(result={"ok": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wanxing_callers_add",
                          {"agent_slug": "packs-p1-a1", "email": "x@y.z"})
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/wanxing/v1/console/deployments/packs-p1-a1/callers"
    assert call["json_body"] == {"email": "x@y.z"}


async def test_pause_resume_explicit_writes(bearer):
    fake = FakeClient(result={"ok": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wanxing_agent_pause", {"agent_slug": "packs-p-a"})
        await c.call_tool("wanxing_agent_resume", {"agent_slug": "packs-p-a"})
    assert fake.calls[0]["path"].endswith("/pause")
    assert fake.calls[1]["path"].endswith("/resume")


async def test_turn_builds_a2a_message_and_receipt_note(bearer):
    fake = FakeClient(result={"jsonrpc": "2.0", "id": 1, "result": {"kind": "queued"}})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wanxing_agent_turn",
                                {"agent_slug": "s1", "text": "SUBMIT x", "idempotency_key": "k1"})
    call = fake.calls[0]
    assert call["path"] == "/api/wanxing/v1/a2a/s1"
    assert call["json_body"]["method"] == "message/send"
    assert call["json_body"]["params"]["message"]["parts"][0]["text"] == "SUBMIT x"
    assert call["headers"]["Idempotency-Key"] == "k1"
    data = out.data if hasattr(out, "data") else out
    assert data["idempotencyKey"] == "k1"
    assert "回执" in data["note"]


async def test_turn_generates_uuid_key_when_absent(bearer):
    fake = FakeClient(result={})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wanxing_agent_turn", {"agent_slug": "s1", "text": "hi"})
    call = fake.calls[0]
    assert call["headers"]["Idempotency-Key"].startswith("wanxing-ops-mcp-")


async def test_turn_requires_credential(monkeypatch):
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: None)
    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("wanxing_agent_turn", {"agent_slug": "s", "text": "x"})
    assert "caller key" in str(ei.value)
    assert fake.calls == []  # 未触上游


async def test_turn_never_falls_back_to_service_token(monkeypatch):
    # 注释承诺「turn 永不回落」，这条锁住它：没有进站 bearer 就是缺凭据，
    # 不许拿 WANXING_OPS_TOKEN 的服务身份去跑计费回合。
    monkeypatch.setenv("WANXING_OPS_TOKEN", "svc-ops-token")
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: None)
    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("wanxing_agent_turn", {"agent_slug": "s", "text": "x"})
    assert "caller key" in str(ei.value)
    assert fake.calls == []  # 服务身份未被执行


async def test_admin_tools_still_fall_back_to_service_token(monkeypatch):
    # 管理面回落是设计内的 ops 服务行为，收紧 turn 不应波及它
    monkeypatch.setenv("WANXING_OPS_TOKEN", "svc-ops-token")
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: None)
    fake = FakeClient(result={"ok": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wanxing_callers_list", {"agent_slug": "s1"})
    assert fake.calls[0]["bearer"] == "svc-ops-token"


async def test_public_reads_send_no_bearer(monkeypatch):
    # 不把字面量 "anonymous" 当凭据发出去
    monkeypatch.setattr(tf, "_inbound_bearer", lambda: "tok-abc")
    fake = FakeClient(result={"agents": []})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wanxing_agents_browse", {})
        await c.call_tool("wanxing_agent_card", {"agent_slug": "s1"})
    for call in fake.calls:
        assert call["anonymous"] is True and call["bearer"] is None


async def test_billing_402_propagates(bearer):
    fake = FakeClient(error=RegistryError("billing", 402, "INSUFFICIENT_BALANCE"))
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("wanxing_agents_browse", {})
    assert "INSUFFICIENT_BALANCE" in str(ei.value)
