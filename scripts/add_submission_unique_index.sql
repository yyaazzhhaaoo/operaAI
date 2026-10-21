-- 一份作业每个学生只能提交一次（2026-10-21，F3）
--
-- 执行前先查重；本机已确认无重复。若别的环境有重复行，CREATE UNIQUE INDEX
-- 会失败，必须先人工清理（保留哪一条由业务决定，脚本不猜）：
--   SELECT homework_id, student_id, count(*)
--   FROM submissions GROUP BY 1, 2 HAVING count(*) > 1;
--
-- 在真库手工执行（项目不用 Alembic）：
--   psql -U xiyun -d xiyun -f scripts/add_submission_unique_index.sql

CREATE UNIQUE INDEX IF NOT EXISTS uq_submissions_homework_student
  ON submissions(homework_id, student_id);

-- 回滚：
-- DROP INDEX IF EXISTS uq_submissions_homework_student;
