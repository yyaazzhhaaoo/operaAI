# -*- coding: utf-8 -*-
"""users 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.practice import BktHistory
from app.models.student import Student
from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def update_password(db: Session, user: User, password_hash: str) -> None:
    """改密码哈希。只 flush，提交由 service 层负责。"""
    user.password_hash = password_hash
    db.flush()

def get_by_role(db:Session,role:str) -> list[User]:
    return list(db.scalars(select(User).where(User.role == role)).all())


def get_student_names(db: Session, student_ids: list[int]) -> dict[int, str]:
    """按 students.id 批量取学生姓名，返回 {students.id: display_name}。

    bkt_history / practice_records 等表的 student_id 外键指向 **students.id**，
    不是 users.id——两者只是偶尔数值相同。把它当 users.id 用 db.get(User, ...)
    查，会静默取到另一个人的名字（或取不到返回 None）。
    姓名必须经 students.user_id 拐一次，见 DOC_ISSUES 第 21 条。
    """
    if not student_ids:
        return {}
    rows = db.execute(
        select(Student.id, User.display_name)
        .join(User, User.id == Student.user_id)
        .where(Student.id.in_(set(student_ids)))
    ).all()
    return dict(rows)


def get_student_roster(db: Session) -> list[tuple[int, str | None, str | None, str | None]]:
    """全部在册学生的档案，返回 [(students.id, display_name, level, avatar)]，按 id 升序。

    与 get_students_with_bkt 的唯一差别是**不按 bkt 记录过滤**：「这个学生从没练过」
    在能力状态列表（功能 5.6）里是有用信息，各行字段给 null 即可，不能因为没数据
    就把人从名单里删掉。热力图那边反过来——整行空白不占行。两处口径不同是有意的。

    role='student' 过滤与「姓名要经 students.user_id 拐一次」的理由，同
    get_students_with_bkt 的文档字符串（见 DOC_ISSUES 第 21 条）。
    """
    rows = db.execute(
        select(Student.id, User.display_name, Student.level, Student.avatar)
        .join(User, User.id == Student.user_id)
        .where(User.role == "student")
        .order_by(Student.id)
    ).all()
    return [tuple(row) for row in rows]


def get_students_with_bkt(db: Session, skills: list[str]) -> list[tuple[int, str | None]]:
    """在这批技法上有掌握度记录的学生，返回 [(students.id, display_name)]，按 id 升序。

    只留 `bkt_history` 里对这批技法有记录的学生（子查询 IN）：热力图一行就是一个
    学生，一行全空没有任何信息量，不如不出这一行。按**传入的技法**判而不是「有没有
    任何 bkt 记录」——只测过「颤音」的学生仍然会渲染成整行空白，等于没过滤掉。

    与 get_student_names 同款：id 取 students.id 不取 users.id（DOC_ISSUES 第 21 条），
    姓名经 students.user_id 拐一次。用内连接——students.user_id 列没建 NOT NULL，
    没有账号的档案行取不到姓名，看板上也点不出东西，直接丢掉。
    不按 users.is_active 过滤：口径与 dashboard summary 的 user_count 一致。

    按 role='student' 过滤是挡脏数据：库里 students.id=1 的档案挂在教师账号上，
    不过滤就会在班级热力图里多出一行空白的「王老师」。summary 的 user_count 本来
    也是数 role='student' 的 users，两边口径就此对齐。
    """
    if not skills:
        return []
    rows = db.execute(
        select(Student.id, User.display_name)
        .join(User, User.id == Student.user_id)
        .where(User.role == "student")
        .where(Student.id.in_(
            select(BktHistory.student_id).where(BktHistory.skill.in_(skills))
        ))
        .order_by(Student.id)
    ).all()
    return [tuple(row) for row in rows]