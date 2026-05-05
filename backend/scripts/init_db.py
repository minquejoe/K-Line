"""初始化数据库表结构（已弃用：PostgreSQL 表由 PostgresStorage._init_tables() 自动创建）"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir.parent))

from backend.app.dependencies import get_storage


def init_database():
    """初始化数据库（PostgreSQL 由 PostgresStorage 自动处理）"""
    print("正在初始化数据库...")
    storage = get_storage()
    print("数据库初始化完成（PostgreSQL）")


if __name__ == "__main__":
    init_database()
