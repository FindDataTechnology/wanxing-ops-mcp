# 萬星线鉴权与计费证据（公开清单之外的逐字记录）

> 本文件是 `line-manifest.json` 的自由文本字段的**逐字**归档。清单的每个字符串都会随
> `/.well-known/line-manifest.json` 匿名公开，所以那些字段已从清单里删除（2026-11-15，
> 任务=converge-line-identity-and-keys 的公开载荷清理批次 H）。本文件不随镜像发布、不进门投影。

## `note` — 顶层 note：为何刻意留一条 repo-class FAIL「回退轨缺失」

```text
本清单刻意留一条 repo-class FAIL「回退轨缺失」：萬星今天没有任何线自有的常命客户钥匙（无 wdk-/fdt_/PAT 等价物），客户能绕过壹座直连 wanxing.finddatatech.cloud，但手里那把钥匙是词元平台签发的——按 line-key-track spec，回退轨必须是线自签、能在换票通道不可用时直接消费该线的轨，所以不能把 ciyuan 轨标 fallback。这条 FAIL 是真能力缺口：词元不可用时萬星不可消费。修法是给萬星加线自有客户钥匙并标 fallback:true。surfaces.account=false：本 MCP 无 me/usage/billing/quota 工具，客户账单在 token.finddatatech.cloud 读。surfaces.admin=false：callers_add/remove 与 pause/resume 是部署者自助管理（上游按 Logto 身份 + ownerGate 归属放行），不是平台代做型 admin，且本线无 consent/JIT 机制故不可声明 line:admin。MCP 传输端点为集群 mesh http://cheap6.mesh.finddata.cn:31895/mcp（公网网关会剥掉调用方 Authorization，逐用户 Bearer 必须走 mesh 直连）。
```

## `identity.note` — identity.note：本仓门只查 Bearer、权威鉴权在萬星 facade

```text
本仓工具面只检查「有没有 Bearer」后原样转发（auth_gate.py:29-40 任何非空串放行；client.py:57-60 转发），权威鉴权在上游萬星 facade。上游按面分两种：管理面 console 认线内服务令牌或 allowlist 内的 Logto ID token（fd-wanxing/services/wanxing-facade/routes.js:155-174），A2A 回合只认词元 caller key `sk-`（core.js:66-110）。无断言兑换端点，故 jit_policy=off——平台代做在萬星侧一律不允许。
```

## `auth_tracks[0].note` — auth_tracks[0].note（ciyuan-caller-key）

```text
今天唯一生效的客户门：A2A 回合 `wanxing_agent_turn` 只认词元 `sk-`（`/^sk-/` + probeKeyLiveness + findUserByKey，core.js:66-110），校验即计费门；不落 `sk-` 的调用被拒。5 个 console 工具（callers_* / pause / resume / board）收的是线内服务令牌或 allowlist 内的 Logto ID token，客户 `sk-` 打它们会被上游 401——即词元钥匙今天只覆盖 A2A 面，不覆盖 console 面。
```

## `billing.note` — billing.note：钱在词元平面（A2A 回合结算）

```text
钱在词元平面：A2A 回合按分钟边界结算到调用方 sub2api 余额（core.js:377-405，幂等键=usage 行 id，operation=subtract），deployer 分成反向 add（core.js:325-350）。本线的 wanxing_deployer_earnings 是分成账本、plan/mission 行是本地记账，都不是钱的真源（store.js:287-293；core.js:377-395）。模型调用也走词元网关并按词元计费（paas/agents.json:13-18）。
```
