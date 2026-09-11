"""ORM 模型包。

在此集中导入全部 15 个模型，保证 Base.metadata 完整——查询、建表、迁移都依赖它。
若新增模型务必同步加到这里，否则它不会出现在 metadata 中。

注意：表结构的唯一真源是项目根目录的 schema.sql（《4-数据库设计-V1.1》）。
模型只做映射，不负责建表。
"""
from app.models.annotation import Annotation
from app.models.audio import AudioFile
from app.models.calibration import ScoreCalibration
from app.models.cat import CatQuestion
from app.models.coach import ChatMessage
from app.models.demo import Segment, TeacherDemo
from app.models.graph import GraphEdge, GraphNode
from app.models.homework import Homework, Submission
from app.models.practice import BktHistory, PracticeRecord
from app.models.student import Student
from app.models.user import User

__all__ = [
    "Annotation",
    "AudioFile",
    "BktHistory",
    "CatQuestion",
    "ChatMessage",
    "GraphEdge",
    "GraphNode",
    "Homework",
    "PracticeRecord",
    "ScoreCalibration",
    "Segment",
    "Student",
    "Submission",
    "TeacherDemo",
    "User",
]
