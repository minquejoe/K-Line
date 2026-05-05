"""依赖注入模块

提供数据库会话管理，支持 SQLite（开发）和 PostgreSQL（生产）。
使用工厂函数模式，根据配置自动选择存储后端。
"""

import re
from typing import Generator, Union, Any, List, Tuple

from sqlalchemy import text

from backend.app.config import settings


def get_storage():
    """
    获取数据存储实例（工厂函数）

    根据 DATABASE_TYPE 配置自动选择存储后端：
    - postgresql: 使用 PostgreSQL + SQLAlchemy 连接池
    - sqlite: 使用 SQLite（回退方案）

    Returns:
        DataStorage 实例
    """
    if settings.DATABASE_TYPE == "postgresql":
        from src.data_storage.postgres_storage import PostgresStorage
        return PostgresStorage(
            database_url=settings.DATABASE_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
    else:
        # SQLite 回退（单机/开发环境）
        from src.data_storage.sqlite_storage import SQLiteStorage
        return SQLiteStorage(database_path=str(settings.DATABASE_PATH))


# ────────────── PostgreSQL 兼容包装器 ──────────────


class PgRow:
    """模拟 sqlite3.Row，同时支持 dict() 转换和索引访问"""

    def __init__(self, keys: Tuple[str, ...], values: Tuple[Any, ...]):
        self._keys = keys
        self._values = values

    def keys(self):
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
    """模拟 sqlite3.Cursor，基于 SQLAlchemy 连接"""

    def __init__(self, connection):
        self._connection = connection
        self._keys: Tuple[str, ...] = ()
        self._rows: List[PgRow] = []
        self.lastrowid: int = 0
        self.rowcount: int = 0

    def execute(self, sql: str, params: Union[Tuple, List, dict, None] = None):
        """执行 SQL，将 ? 占位符转换为 SQLAlchemy :param 格式"""
        # 将 ? 替换为 :p0, :p1, ... 递增命名参数
        counter = [0]
        def replace_q(m):
            name = f"p{counter[0]}"
            counter[0] += 1
            return f":{name}"
        pg_sql = re.sub(r"\?", replace_q, sql)

        # 检测 INSERT 语句，自动追加 RETURNING id
        is_insert = pg_sql.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in pg_sql.upper():
            pg_sql = pg_sql.rstrip(";") + " RETURNING id"

        # 将 tuple/list 参数转为 dict（SQLAlchemy 2.0 要求）
        if params is None or (isinstance(params, (list, tuple)) and len(params) == 0):
            exec_params = {}
        elif isinstance(params, (list, tuple)):
            exec_params = {f"p{i}": v for i, v in enumerate(params)}
        elif isinstance(params, dict):
            exec_params = params
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
            self.rowcount = result.rowcount if hasattr(result, 'rowcount') else 0
        return self

    def executemany(self, sql: str, params_list: List[Tuple]):
        """批量执行"""
        counter = [0]
        def replace_q(m):
            name = f"p{counter[0]}"
            counter[0] += 1
            return f":{name}"
        pg_sql = re.sub(r"\?", replace_q, sql)

        for params in params_list:
            exec_params = {f"p{i}": v for i, v in enumerate(params)} if params else {}
            self._connection.execute(text(pg_sql), exec_params)
        self.rowcount = len(params_list)
        return self

    def fetchone(self):
        if self._rows:
            return self._rows.pop(0)
        return None

    def fetchall(self):
        rows = self._rows[:]
        self._rows = []
        return rows

    def close(self):
        pass


class PgConnection:
    """模拟 sqlite3.Connection，基于 SQLAlchemy 连接"""

    def __init__(self, sqlalchemy_conn):
        self._conn = sqlalchemy_conn

    def cursor(self):
        return PgCursor(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ────────────── 数据库连接工厂 ──────────────

_pg_storage_cache: Any = None


def _get_pg_storage():
    """获取缓存的 PostgresStorage 实例（复用连接池）"""
    global _pg_storage_cache
    if _pg_storage_cache is None:
        from src.data_storage.postgres_storage import PostgresStorage
        _pg_storage_cache = PostgresStorage(
            database_url=settings.DATABASE_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
    return _pg_storage_cache


def get_db() -> Generator:
    """
    获取数据库连接（兼容 sqlite3 和 PostgreSQL）

    自动根据 DATABASE_TYPE 选择后端，对外暴露统一的 cursor/execute/fetchone 接口。
    """
    if settings.DATABASE_TYPE == "postgresql":
        storage = _get_pg_storage()
        with storage._get_connection() as raw_conn:
            conn = PgConnection(raw_conn)
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    else:
        import sqlite3
        conn = sqlite3.connect(str(settings.DATABASE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
