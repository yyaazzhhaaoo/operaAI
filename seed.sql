-- ============================================================================
-- 戏韵AI 种子数据脚本
-- 依据：《4-数据库设计-V1.1》第 3 节（逐字对齐文档，仅把密码哈希换为实际值）
-- 用法：psql -f seed.sql（需先执行 schema.sql）
--
-- ⚠️ 密码哈希必须显式指定 pbkdf2：werkzeug 3.x 的 generate_password_hash
--    默认算法已由 pbkdf2 改为 scrypt，输出 162 字符，会超出
--    users.password_hash 的 VARCHAR(128)。生成命令：
--      python -c "from werkzeug.security import generate_password_hash; \
--        print(generate_password_hash('你的密码', method='pbkdf2:sha256'))"
--
-- 初始密码：三个账号均为 xiyun@2026，上线前务必修改。
--
-- ⚠️ 本脚本【不是幂等的】，且跨表外键按 SERIAL 推算写死了 id——这两点都是
--    文档原样，已知问题已记入 DOC_ISSUES.md，此处不擅自修改。重跑前先清空：
--      TRUNCATE users, students, audio_files, teacher_demos, segments,
--               annotations, practice_records, bkt_history, homeworks,
--               submissions, chat_messages, score_calibrations,
--               cat_questions, graph_nodes, graph_edges RESTART IDENTITY CASCADE;
-- ============================================================================

-- 教师/学生账号
INSERT INTO users (username, password_hash, role, display_name) VALUES
('teacher01', 'pbkdf2:sha256:1000000$mfKCSpfKvUXWipn8$fa5942b981cabbda43d543e8c59b602fd517cfd06180cdce73f8cda08d019f75', 'teacher', '王老师');
INSERT INTO users (username, password_hash, role, display_name) VALUES
('stu001', 'pbkdf2:sha256:1000000$YozX6NANS81Sx46M$55c15266a5ffa7e7854cefcb6ffe7ab5f50afe9f41d7c7dd334f8fc6ed5014da', 'student', '张三'),
('stu002', 'pbkdf2:sha256:1000000$fl6nfPWpJvgCZm68$7b48dd55c16b6b3c0e9bc8309b58bf88ab7c0bb3a3806521dffb0d587f266b19', 'student', '李四');

INSERT INTO students (user_id, level) VALUES (2, '初学'), (3, '初学');

-- 示范曲目与分段（示例，正式数据由《数据准备清单》交付后替换）
INSERT INTO teacher_demos (title, role, banshi) VALUES ('贵妃醉酒·选段', '旦', '四平调');
INSERT INTO segments (demo_id, seq, title, lyrics_json, duration) VALUES (1, 1, '第一段',
'[{"word":"海","midi":57,"start":0.00,"end":1.20,"note":"half","tip":"起音轻，气息下沉"},
  {"word":"岛","midi":55,"start":1.20,"end":1.80,"note":"quarter","tip":"归韵收净"}]'::jsonb, 30.5);

-- 摸底题库占位（正式题目待教师录制）
INSERT INTO cat_questions (seq, segment_id, focus_dims) VALUES (1, 1, '["音准","气息"]');

-- 知识图谱最小示例
INSERT INTO graph_nodes (node_type, label, pos_x, pos_y) VALUES
('skill','气息支撑',100,100),('skill','归韵',300,100),('skill','拖腔',500,100),
('segment','第一段',300,300),('opera','贵妃醉酒',500,500);
INSERT INTO graph_edges (source_id, target_id, edge_type) VALUES
(1,2,'prereq'),(2,3,'prereq'),(4,2,'contains'),(5,4,'contains');
