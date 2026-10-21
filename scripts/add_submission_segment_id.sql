-- submissions 增加 segment_id（2026-10-21，F3 学生提交作业）
--
-- 普通 INT，**故意不加外键**：重解析曲目时 library_repo.replace_segments 会
-- 先按 demo_id 整批删除旧分段再插入，外键会让这次删除直接失败。分段被重解析
-- 后本列可能悬空，它与 homeworks.segment_ids 的 JSONB 一样是历史引用。
--
-- 在真库手工执行（项目不用 Alembic）：
--   psql -U xiyun -d xiyun -f scripts/add_submission_segment_id.sql

ALTER TABLE submissions ADD COLUMN IF NOT EXISTS segment_id INT;

COMMENT ON COLUMN submissions.segment_id IS
  '学生提交的唱段 segments.id（无外键；重解析后可能悬空）';

-- 回滚：
-- ALTER TABLE submissions DROP COLUMN IF EXISTS segment_id;
