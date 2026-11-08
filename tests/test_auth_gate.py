"""AuthGate（萬星变体）：无 Bearer 拒、有 Bearer 放行、缓存生效。"""

from __future__ import annotations

from wanxing_ops_mcp.auth_gate import _CACHE_MAX, AuthGate


async def test_anonymous_rejected():
    assert await AuthGate().check(None) is False


async def test_any_bearer_passes():
    gate = AuthGate()
    assert await gate.check("anything") is True


async def test_cache_short_circuits():
    gate = AuthGate(ttl_seconds=60)
    await gate.check("tok")
    assert await gate.check("tok") is True  # 缓存路径不抛


async def test_cache_is_bounded():
    # 每个不同 bearer 都会写一条缓存键：没有上界就是长跑进程的 RSS 泄漏面
    gate = AuthGate()
    for i in range(_CACHE_MAX * 4):
        await gate.check(f"tok-{i}")
    assert len(gate._cache) <= _CACHE_MAX
