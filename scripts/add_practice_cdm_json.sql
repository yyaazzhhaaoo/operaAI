-- practice_records 增加 CDM 归因列（2026-10-20）
--
-- 存分析管线算出的 {defects:[{id,label,status,category,evidence,features,
-- confidence}], overallConfidence}。与 dimensions_json 同风格，可空：
--   - 历史练习没有这项数据；
--   - NULL = 没有数据源；defects=[] = 查了但没有缺陷。
--
-- 执行顺序很重要：代码里的 PracticeRecord 已映射 cdm_json，ORM 查询会 SELECT
-- 这一列。**先执行本脚本，再让后端/worker 加载新代码**；反过来会报
-- UndefinedColumn: column practice_records.cdm_json does not exist。
--
-- 在真库手工执行（项目不用 Alembic）：
--   psql -U xiyun -d xiyun -f scripts/add_practice_cdm_json.sql
--
-- 幂等：可重复执行。
ALTER TABLE practice_records ADD COLUMN IF NOT EXISTS cdm_json JSONB;

COMMENT ON COLUMN practice_records.cdm_json IS
  'CDM 归因：{defects:[{id,label,status,category,evidence,features,confidence}], overallConfidence}；NULL=无数据源，defects=[]=查了无缺陷';

-- 回滚：ALTER TABLE practice_records DROP COLUMN IF EXISTS cdm_json;
