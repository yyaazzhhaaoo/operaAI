-- practice_records 增加逐字偏差列（2026-10-20）
--
-- 存 B4 分析结果里的 result["words"]：对齐教师轨后按 segments.lyrics_json
-- 逐字算出的偏差。与 dimensions_json 同风格，可空：
--   - 历史练习没有这项数据；
--   - Demucs 上传的示范没有 lyrics_json，words 是空数组 []（表示"算了但没有字"）。
--
-- 在真库手工执行（项目不用 Alembic）：
--   psql -U xiyun -d xiyun -f scripts/add_practice_words_json.sql

ALTER TABLE practice_records ADD COLUMN IF NOT EXISTS words_json JSONB;

COMMENT ON COLUMN practice_records.words_json IS
  '逐字偏差（B4 words）：[{index,word,start,end,deviation_cents,teacher_freq,student_freq,octave_fixed,warning}]';

-- 回滚：
-- ALTER TABLE practice_records DROP COLUMN IF EXISTS words_json;
