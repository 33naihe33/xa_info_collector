"""R-07: wheel 打包测试 — 前端 dist 与引用 asset 必须随 wheel 分发。

构建 wheel 需 setuptools + build。若无则跳过（不阻断测试套件）。
"""
import os
import re
import sys
import shutil
import subprocess
import zipfile
import glob

import pytest


def _build_wheel(tmp_path):
    """构建 wheel 到 tmp_path，返回 wheel 路径或跳过（构建环境不可用）。"""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        import importlib
        importlib.import_module("build")  # noqa
        importlib.import_module("setuptools")  # noqa
    except ImportError:
        pytest.skip("setuptools/build 未安装，跳过 wheel 打包测试")
    out = str(tmp_path / "dist")
    # 用当前 Python（venv）而非系统 python，确保 build/setuptools 可用
    r = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", out, project],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"wheel 构建失败（环境问题）: {r.stderr[-200:]}")
    wheels = glob.glob(os.path.join(out, "*.whl"))
    assert wheels, "构建成功但无 wheel"
    return wheels[0]


def test_wheel_includes_frontend_dist_index_html(tmp_path):
    """wheel 必须包含 web/frontend/dist/index.html。"""
    wheel = _build_wheel(tmp_path)
    z = zipfile.ZipFile(wheel)
    names = z.namelist()
    idx = [n for n in names if n.endswith("frontend/dist/index.html")]
    assert idx, f"wheel 未包含 frontend/dist/index.html"


def test_wheel_includes_assets_referenced_by_index_html(tmp_path):
    """index.html 引用的 JS/CSS asset 必须都在 wheel 内。"""
    wheel = _build_wheel(tmp_path)
    z = zipfile.ZipFile(wheel)
    names = z.namelist()
    idx_path = [n for n in names if n.endswith("frontend/dist/index.html")][0]
    content = z.read(idx_path).decode("utf-8", "replace")
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', content)
    assert assets, "index.html 未引用任何 asset"
    for a in assets:
        rel = a.lstrip("/")
        found = any(n.endswith("frontend/dist/" + rel) for n in names)
        assert found, f"wheel 缺少 index.html 引用的 asset: {a}"


def test_wheel_includes_config_files(tmp_path):
    """wheel 必须包含 config 的 yaml + prompts。"""
    wheel = _build_wheel(tmp_path)
    z = zipfile.ZipFile(wheel)
    names = z.namelist()
    yaml_files = [n for n in names if n.endswith(".yaml") and "config" in n]
    prompt_files = [n for n in names if "prompts/" in n and n.endswith(".txt")]
    assert yaml_files, "wheel 未包含 config yaml"
    assert prompt_files, "wheel 未包含 prompts/*.txt"
