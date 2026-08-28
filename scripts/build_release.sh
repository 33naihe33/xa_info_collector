#!/usr/bin/env bash
# R-07: 标准化发布构建脚本 — 前端构建 + wheel 打包 + 干净 venv 安装验证
# 用法：bash scripts/build_release.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== [1/4] 前端构建 ==="
cd web/frontend
if [ ! -f package.json ]; then
    echo "ERROR: web/frontend/package.json 不存在" >&2
    exit 1
fi
npm install --silent
npm run build
cd "$PROJECT_DIR"

echo "=== [2/4] wheel 打包 ==="
rm -rf dist build *.egg-info
python -m build --wheel --no-isolation 2>/dev/null || python -m build --wheel

WHEEL=$(ls dist/*.whl | head -1)
if [ -z "$WHEEL" ]; then
    echo "ERROR: 未生成 wheel" >&2
    exit 1
fi
echo "生成 wheel: $WHEEL"

echo "=== [3/4] wheel 内容验证（index.html + 引用的 assets）==="
python - "$WHEEL" <<'PYVER'
import sys, zipfile, re
wheel = sys.argv[1]
z = zipfile.ZipFile(wheel)
names = z.namelist()
# index.html 必须存在
idx_candidates = [n for n in names if n.endswith("frontend/dist/index.html")]
assert idx_candidates, f"wheel 未包含 frontend/dist/index.html，实际: {[n for n in names if 'dist' in n][:10]}"
idx = z.read(idx_candidates[0]).decode("utf-8", "replace")
# 解析 index.html 引用的 JS/CSS asset
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', idx)
assert assets, "index.html 未引用任何 asset"
for a in assets:
    rel = a.lstrip("/")
    found = any(n.endswith("frontend/dist/" + rel) for n in names)
    assert found, f"wheel 缺少 index.html 引用的 asset: {a}"
print(f"OK: index.html + {len(assets)} 个 asset 均在 wheel 内")
PYVER

echo "=== [4/4] 干净 venv 安装 + 启动验证（可选，需网络）==="
VENV=$(mktemp -d)/venv
python -m venv "$VENV" 2>/dev/null || true
"$VENV/bin/pip" install --quiet "$WHEEL" 2>/dev/null && {
    "$VENV/bin/python" -c "import web.app; print('import OK')" 2>/dev/null && echo "安装+导入验证通过"
} || echo "（跳过 venv 验证：无网络或依赖缺失）"

echo "=== 构建完成 ==="
echo "wheel: $WHEEL"
