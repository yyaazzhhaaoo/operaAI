"""数据访问层（SQL 封装）。

约定：
  - 第一个参数永远是 db: Session，由 service 层传下来，本层不自己取全局会话
  - 写操作只 db.flush()（拿 id、触发约束检查），不 commit——事务边界在 service 层
  - 数据隔离规则（《6-登录与数据隔离方案》第 4 节）后续集中落在本层，
    例如 student_repo.get_visible(db, student_id, current_user)，
    越权直接抛 BusinessError(403, ...)，所有调用方自动继承
"""
