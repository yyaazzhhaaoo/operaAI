-- ============================================================================
-- 戏韵AI 建库脚本
-- 依据：《4-数据库设计-V1.1》第 2 节（逐字对齐文档，不自行增删）
-- 用法：psql -f schema.sql && psql -f seed.sql
--
-- ⚠️ 第一行 CREATE DATABASE 需要 CREATEDB 权限，超级用户 postgres 才有。
--    xiyun 角色没有该权限（实测报 permission denied to create database），
--    所以「建库」这一步要用 postgres 跑：
--      docker exec -i -e PGPASSWORD=root docker_postgres \
--        psql -U postgres -f - < schema.sql
--    库已存在时重复执行会报 database "xiyun" already exists，属预期；
--    \c xiyun 之后的建表语句仍会继续执行，故重复跑会看到一批
--    relation already exists 报错。想干净重建就先 DROP DATABASE xiyun;
--
-- 说明：本脚本是表结构的唯一真源。app/models/ 下的 ORM 模型只做映射，
--       不负责建表——改表结构请改本文件并同步模型。
-- ============================================================================

CREATE DATABASE xiyun ENCODING 'UTF8';
\c xiyun

-- 1. 用户账号
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(50) UNIQUE NOT NULL,
  password_hash VARCHAR(128) NOT NULL,
  role VARCHAR(10) NOT NULL CHECK (role IN ('teacher','student')),
  display_name VARCHAR(50) NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 2. 学生教学档案
CREATE TABLE students (
  id SERIAL PRIMARY KEY,
  user_id INT UNIQUE REFERENCES users(id),
  level VARCHAR(20),                     -- 初学/进阶/高级
  avatar VARCHAR(255),
  enrolled_at TIMESTAMP DEFAULT NOW()
);

-- 3. 音频文件登记（权限校验的依据）
CREATE TABLE audio_files (
  id SERIAL PRIMARY KEY,
  uploader_id INT REFERENCES users(id),
  file_path VARCHAR(255) NOT NULL,       -- uploads/ 相对路径
  original_name VARCHAR(255),
  file_size INT,
  duration_sec FLOAT,
  access VARCHAR(10) DEFAULT 'private',  -- public=示范 / private=学生录音
  uploaded_at TIMESTAMP DEFAULT NOW()
);

-- 4. 示范曲目（剧目级）
CREATE TABLE teacher_demos (
  id SERIAL PRIMARY KEY,
  title VARCHAR(100) NOT NULL,
  role VARCHAR(50),                      -- 行当
  banshi VARCHAR(50),                    -- 板式
  audio_id INT REFERENCES audio_files(id),
  elo_difficulty FLOAT DEFAULT 1000,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 5. 曲目分段（含逐字声学数据与教师提示）
CREATE TABLE segments (
  id SERIAL PRIMARY KEY,
  demo_id INT REFERENCES teacher_demos(id),
  seq INT,
  title VARCHAR(100),
  lyrics_json JSONB,   -- [{word,midi,start,end,note,tip}]，tip=功能2.4唱前提示
  duration FLOAT
);

-- 6. 歌词级标注规则（模块9）
CREATE TABLE annotations (
  id SERIAL PRIMARY KEY,
  segment_id INT REFERENCES segments(id),
  word_index INT NOT NULL,
  tag VARCHAR(10) NOT NULL,  -- 滑音/归韵/换气/强音/拖腔/擞音
  tolerance INT CHECK (tolerance BETWEEN 0 AND 100),
  teacher_id INT REFERENCES users(id),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(segment_id, word_index, tag)
);

-- 7. 练习记录（含摸底测试，source 区分）
CREATE TABLE practice_records (
  id SERIAL PRIMARY KEY,
  student_id INT REFERENCES students(id),
  segment_id INT REFERENCES segments(id),
  source VARCHAR(10) DEFAULT 'practice',   -- practice / cat_test
  audio_id INT REFERENCES audio_files(id),
  ai_score FLOAT,
  dimensions_json JSONB,                   -- {音准,节奏,气息,咬字,拖腔}
  duration_sec FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_practice_student_time ON practice_records(student_id, created_at DESC);

-- 8. BKT 历史
CREATE TABLE bkt_history (
  id SERIAL PRIMARY KEY,
  student_id INT REFERENCES students(id),
  skill VARCHAR(50) NOT NULL,
  p_l FLOAT NOT NULL,
  confidence FLOAT,
  source_type VARCHAR(20),                 -- practice/homework/cat_test
  source_id INT,
  recorded_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_bkt_student_skill ON bkt_history(student_id, skill, recorded_at DESC);

-- 9. 作业
CREATE TABLE homeworks (
  id SERIAL PRIMARY KEY,
  teacher_id INT REFERENCES users(id),
  title VARCHAR(100) NOT NULL,
  demo_id INT REFERENCES teacher_demos(id),
  segment_ids JSONB,
  focus_skills JSONB,
  deadline DATE,
  status VARCHAR(10) DEFAULT 'open',       -- open / closed
  created_at TIMESTAMP DEFAULT NOW()
);

-- 10. 作业提交
CREATE TABLE submissions (
  id SERIAL PRIMARY KEY,
  homework_id INT REFERENCES homeworks(id),
  student_id INT REFERENCES students(id),
  audio_id INT REFERENCES audio_files(id),
  ai_score FLOAT,
  ai_detail JSONB,                         -- 逐字偏差 + CDM 归因标签
  bkt_before JSONB,
  bkt_after JSONB,
  teacher_score FLOAT,
  teacher_comment TEXT,
  voice_comment_audio_id INT REFERENCES audio_files(id),  -- 功能4.11语音点评
  voice_comment_text TEXT,
  status VARCHAR(10) DEFAULT 'ai_scored',  -- submitted/ai_scored/reviewed
  submitted_at TIMESTAMP DEFAULT NOW(),
  reviewed_at TIMESTAMP
);

-- 11. AI 教练对话记录（模块3）
CREATE TABLE chat_messages (
  id SERIAL PRIMARY KEY,
  student_id INT REFERENCES students(id),
  role VARCHAR(10) NOT NULL,               -- user / assistant
  content TEXT NOT NULL,
  context_snapshot JSONB,                  -- 当时画像/策略/情绪（功能3.5/3.8）
  created_at TIMESTAMP DEFAULT NOW()
);

-- 12. AI 评分校准记录（功能4.10）
CREATE TABLE score_calibrations (
  id SERIAL PRIMARY KEY,
  submission_id INT REFERENCES submissions(id),
  teacher_id INT REFERENCES users(id),
  bias_mode VARCHAR(10),                   -- high(偏高)/low(偏低)/ok
  ai_score FLOAT,
  teacher_score FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 13. 摸底测试题库（模块8）
CREATE TABLE cat_questions (
  id SERIAL PRIMARY KEY,
  seq INT NOT NULL,                        -- 题目顺序 1~8
  segment_id INT REFERENCES segments(id),  -- 复用分段结构存戏词/示范音频
  focus_dims JSONB,                        -- ["音准","气息"]
  is_active BOOLEAN DEFAULT TRUE
);

-- 14/15. 知识图谱（模块7）
CREATE TABLE graph_nodes (
  id SERIAL PRIMARY KEY,
  node_type VARCHAR(10) NOT NULL,          -- skill / segment / opera
  ref_id INT,                              -- 技法名存label；唱句指向segments.id
  label VARCHAR(50) NOT NULL,
  pos_x FLOAT, pos_y FLOAT,                -- 功能7.5拖拽布局持久化
  mastery_threshold FLOAT DEFAULT 0.60     -- 功能7.3锁定阈值
);
CREATE TABLE graph_edges (
  id SERIAL PRIMARY KEY,
  source_id INT REFERENCES graph_nodes(id),
  target_id INT REFERENCES graph_nodes(id),
  edge_type VARCHAR(10) NOT NULL           -- prereq(前置) / contains(包含)
);

-- 预警数据（功能 5.2/5.3）不建表，由 bkt_history 与 practice_records 实时计算
