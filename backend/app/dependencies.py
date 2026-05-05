"""依赖注入模块 —— PostgreSQL 专用

提供数据库会话管理（连接池）和 sqlite3 兼容包装器，
使现有 API 代码无需修改即可在 PostgreSQL 上运行。
"""

import re
from typing import Generator, Union, Any, List, Tuple

from sqlalchemy import text

from backend.app.config import settings


# ═══════════════════════════════════════════════════════════
#  PostgreSQL Storage 实例
# ═══════════════════════════════════════════════════════════

_pg_storage: Any = None


def get_storage():
    """获取 PostgresStorage 单例（复用连接池）"""
    global _pg_storage
    if _pg_storage is None:
        from src.data_storage.postgres_storage import PostgresStorage
        _pg_storage = PostgresStorage(
            database_url=settings.DATABASE_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
    return _pg_storage


# ═══════════════════════════════════════════════════════════
#  sqlite3 兼容包装器（使现有 API 代码无缝运行）
# ═══════════════════════════════════════════════════════════

class PgRow:
    """模拟 sqlite3.Row — 支持 dict() 和下标访问"""

    def __init__(self, keys: Tuple[str, ...], values: Tuple[Any, ...]):
        self._keys = keys
        self._values = values

    def keys(self) -> List[str]:
        return list(self._keys)

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._values[idx]
        return self._values[self._keys.index(idx)]

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"PgRow({dict(zip(self._keys, self._values))})"


class PgCursor:
    """模拟 sqlite3.Cursor"""

    def __init__(self, connection):
        self._connection = connection
        self._keys: Tuple[str, ...] = ()
        self._rows: List[PgRow] = []
        self.lastrowid: int = 0
        self.rowcount: int = 0

    def execute(self, sql: str, params: Union[Tuple, List, dict, None] = None):
        """执行 SQL，? → :pN 命名参数，兼容 SQLAlchemy 2.0"""
        # 替换占位符：? → :p0, :p1, ...
        counter = [0]
        pg_sql = re.sub(
            r"\?",
            lambda _: f":p{counter.__setitem__(0, counter[0] + 1) or counter[0] - 1}",
            sql,
        )

        # INSERT 自动追加 RETURNING id
        if pg_sql.strip().upper().startswith("INSERT") and "RETURNING" not in pg_sql.upper():
            pg_sql = pg_sql.rstrip(";") + " RETURNING id"

        # 参数转换：tuple/list → dict
        if params is None:
            exec_params = {}
        elif isinstance(params, dict):
            exec_params = params
        elif isinstance(params, (list, tuple)):
            exec_params = {f"p{i}": v for i, v in enumerate(params)}
        else:
            exec_params = {}

        result = self._connection.execute(text(pg_sql), exec_params)
        if result.returns_rows:
            keys = tuple(result.keys())
            fetched = result.fetchall()
            rows = [PgRow(keys, tuple(row)) for row in fetched]
            self._keys = keys
            self._rows = rows
            self.rowcount = len(rows)
            if fetched and 'id' in keys:
                self.lastrowid = fetched[-1][keys.index('id')]
        else:
            self._keys = ()
            self._rows = []
            self.rowcount = getattr(result, 'rowcount', 0)
        return self

    def executemany(self, sql: str, params_list: List[Tuple]):
        for params in params_list:
            self.execute(sql, params)
        self.rowcount = len(params_list)
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        pass


class PgConnection:
    """模拟 sqlite3.Connection"""

    def __init__(self, sqlalchemy_conn):
        self._conn = sqlalchemy_conn

    def cursor(self) -> PgCursor:
        return PgCursor(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ═══════════════════════════════════════════════════════════
#  FastAPI 依赖：get_db()
# ═══════════════════════════════════════════════════════════

def get_db() -> Generator:
    """获取数据库连接（PostgreSQL，sqlite3 兼容接口）"""
    storage = get_storage()
    with storage._get_connection() as raw_conn:
        conn = PgConnection(raw_conn)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
