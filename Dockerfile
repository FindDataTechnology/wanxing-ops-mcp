# wanxing-ops-mcp image — 萬星（wanxing 线）舰队操作 MCP。
#
# 发布通道：GitHub Actions -> TCR（家族配方 docs/IMAGE-RELEASE.md；镜像仓
# law-ai-official/facet-ops-mcp-images 增线）。上游源为默认；单层 <300MB。
FROM python:3.12-slim

ARG PIP_INDEX_URL=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY wanxing_ops_mcp ./wanxing_ops_mcp
# 线自描述随镜像走：/.well-known/line-manifest.json 由 server.manifest_path() 读仓根文件
# （不另行内联一份，避免与仓内源漂移）。2026-11-12 补：缺这一行时端点装上了也只会 404
# ——清单在仓里、镜像里没有（lex 线一直有，才只有它线上 200）。
COPY line-manifest.json ./

RUN if [ -n "$PIP_INDEX_URL" ]; then pip install --no-cache-dir -i "$PIP_INDEX_URL" .; else pip install --no-cache-dir .; fi \
 && useradd -m -u 1000 appuser

USER appuser

EXPOSE 8000

CMD ["wanxing-ops-mcp", "serve", "--host", "0.0.0.0", "--port", "8000"]
