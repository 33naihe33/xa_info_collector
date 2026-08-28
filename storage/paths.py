# storage/paths.py
"""M-09: 统一 DATA_DIR 配置——所有数据读写路径的唯一来源。

解决 wheel/非仓库目录部署下，采集器写 CWD/data 而 web mount 按包父目录
找 data 的不一致问题。所有模块（collector/web/reporter）统一从此派生路径。
"""
import os

# 包父目录（项目根，开发模式；wheel 安装时可能是 site-packages 上层）
_PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 统一 DATA_DIR：环境变量优先，默认包父目录/data
DATA_DIR = os.environ.get("XA_DATA_DIR", os.path.join(_PACKAGE_PARENT, "data"))


def images_dir() -> str:
    """图片存储目录（采集器写入 + web mount）。"""
    return os.path.join(DATA_DIR, "images")


def snapshots_dir() -> str:
    """HTML 快照存储目录。"""
    return os.path.join(DATA_DIR, "snapshots")


def reports_dir() -> str:
    """报告文件存储目录。"""
    return os.path.join(DATA_DIR, "reports")


def db_path() -> str:
    """默认数据库路径。"""
    return os.path.join(DATA_DIR, "xac.db")


def ensure_dirs() -> None:
    """确保所有数据子目录存在。"""
    for d in (DATA_DIR, images_dir(), snapshots_dir(), reports_dir()):
        os.makedirs(d, exist_ok=True)
