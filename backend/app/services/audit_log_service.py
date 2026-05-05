"""审计日志服务（PostgreSQL）"""

from typing import List
from datetime import datetime, timezone

from sqlalchemy import text

from backend.app.dependencies import get_storage
from backend.app.models.audit_log import AuditLogCreate, AuditLogInfo


class AuditLogService:
    """审计日志服务，基于 PostgresStorage 连接池"""

    def create_table_if_not_exists(self):
        """表由 PostgresStorage._init_tables() 自动创建，此方法保留兼容"""
        pass

    def log_event(self, log_data: AuditLogCreate):
        """记录审计日志"""
        created_at = datetime.now(timezone.utc).isoformat()
        storage = get_storage()
        with storage._get_connection() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO audit_logs (user_id, username, action, details, ip_address, created_at) "
                    "VALUES (:uid, :uname, :act, :det, :ip, :ts) RETURNING id"
                ),
                {"uid": log_data.user_id, "uname": log_data.username,
                 "act": log_data.action, "det": log_data.details,
                 "ip": log_data.ip_address, "ts": created_at},
            )
            conn.commit()
            return result.fetchone()[0]

    def get_recent_logs(self, limit: int = 20) -> List[AuditLogInfo]:
        """获取最近的日志"""
        storage = get_storage()
        with storage._get_connection() as conn:
            result = conn.execute(
                text(
                    "SELECT id, user_id, username, action, details, ip_address, created_at "
                    "FROM audit_logs ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            logs = []
            for row in result.fetchall():
                logs.append(AuditLogInfo(
                    id=row[0], user_id=row[1], username=row[2],
                    action=row[3], details=row[4], ip_address=row[5],
                    created_at=row[6],
                ))
            return logs
