# -*- coding: utf-8 -*-
"""B 组音频/分析接口的入参/出参模型。

校验失败抛 ValidationError，由 app/common/errors.py 的 handler 转成 422 中文文案。
"""

from pydantic import BaseModel, Field, model_validator


class AnalyzeSubmitIn(BaseModel):
    """B2 入参（《5-接口清单》3.1 异步分析协议）。

    两种模式二选一：

      模式一  {"teacher_audio_id": 1, "student_audio_id": 2}   —— 直接比对两条音轨
      模式二  {"segment_id": 5, "student_audio_id": 9}          —— 陪练/作业/摸底复用，
                                                                 教师侧取该分段的示范音频

    三个 id 都是**数据库主键**，不是磁盘文件名：
      - student_audio_id / teacher_audio_id → audio_files.id（B1 返回的 file_id）
      - segment_id → segments.id，服务端经 segments.demo_id → teacher_demos.audio_id
        解析出示范音频
    """

    # 两种模式下学生音轨都必填
    student_audio_id: int = Field(gt=0)
    # 教师音轨与分段互斥，必须恰好给一个——由下面的 validator 兜住
    teacher_audio_id: int | None = Field(default=None, gt=0)
    segment_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _exactly_one_teacher_source(self):
        # 两个都给（该听谁的？）和两个都不给（教师侧从哪来？）都是调用方搞错了，
        # 与其在 service 里猜，不如在这里当场拒掉。
        if (self.teacher_audio_id is None) == (self.segment_id is None):
            raise ValueError("teacher_audio_id 与 segment_id 必须且只能给一个")
        return self
