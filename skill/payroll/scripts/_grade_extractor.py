#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""年级 / 班型 / 学科 提取 与 SWITCH 公式构造（工资核对表制作 skill 共用模块）。

提供给 import_paikeshi.py 与 verify_ae_af.py 复用：
  - 学科：优先用「上课科目」列（清理数字前缀），否则从班级名称括号 (XX-学科) 提取
  - 班型：一对一→1对1，集体班→小班，一对多→1对2，10/6/8人班→小班
  - 年级：领航伴学 / 年级关键词 / 赠换特批查学生表（references/学生年级查表.csv）
  - 构造排课记录 F/G/H 三列 SWITCH 公式字符串

依赖：标准库 + openpyxl（仅本文件不强制 openpyxl，公式构造是纯字符串）。
"""
import os
import re
import csv

# ---------- 班型映射 ----------
CLASS_TYPE_MAP = {
    "一对一": "1对1",
    "集体班": "小班",
    "一对多": "1对2",
    "10人班": "小班",
    "6人班": "小班",
    "8人班": "小班",
}

# ---------- SWITCH 公式用系数表 ----------
# 年级系数（G 列）：年级 -> 系数
GRADE_COEFF = {
    "领航伴学": 0.6,
    "一年级": 0.85, "二年级": 0.85, "三年级": 0.85,
    "四年级": 0.85, "五年级": 0.85, "六年级": 0.85,
    "七年级": 0.9, "八年级": 0.9, "九年级": 1,
    "高一": 1.1, "高二": 1.25, "高三": 1.35,
    "雅思": 1.5, "托福": 1.5,
}
# 人数系数（H 列）：实到人数 -> 系数
HEADCOUNT_COEFF = {1: 0.8, 2: 1, 3: 1.2, 4: 1.4, 5: 1.7,
                   6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5, 10: 2.7}

# 年级关键词（长在前，避免「高一」被「一」误匹配）
GRADE_KEYWORDS = ["高三", "高二", "高一", "初三", "初二", "初一",
                  "九年级", "八年级", "七年级",
                  "六年级", "五年级", "四年级", "三年级", "二年级", "一年级",
                  "雅思", "托福"]

# 赠换特批类关键词
SPECIAL_KEYWORDS = ["赠送", "换购", "特批"]
# 提取学生姓名时排除的关键词片段
STUDENT_NAME_EXCLUDE = ["换购课程", "亲属赠送", "推荐赠送", "被推荐赠送",
                        "寒暑假课程消耗赠送", "寒暑假", "课程消耗赠送",
                        "领航伴学", "小学领航", "七年级领航", "1v1", "1v2",
                        "1V2", "校长特批赠送", "校长特批"]


def _load_student_grades():
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "references", "学生年级查表.csv"))
    table = {}
    if not os.path.exists(path):
        return table
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("姓名"):
                continue
            name, _, grade = line.partition(",")
            name, grade = name.strip(), grade.strip()
            if name and grade:
                table[name] = grade
    return table


STUDENT_GRADE = _load_student_grades()


def clean_subject(raw):
    """清理 '02-数学' -> '数学'；无前缀原样返回。"""
    if not isinstance(raw, str):
        return raw
    return re.sub(r"^\d+-", "", raw).strip()


def extract_subject(class_name, subject_col=None):
    """优先用上课科目列（已清理前缀），否则从班级名称括号 (XX-学科) 提取。"""
    if subject_col is not None:
        s = clean_subject(subject_col)
        if s:
            return s
    if not isinstance(class_name, str):
        return ""
    m = re.search(r"[（(](\d+-)?([^）)]+)[）)]", class_name)
    if m:
        return m.group(2).strip()
    return ""


def map_class_type(teaching_form):
    if not isinstance(teaching_form, str):
        return ""
    return CLASS_TYPE_MAP.get(teaching_form.strip(), teaching_form.strip())


def _extract_student_name(class_name):
    """下划线后第一段为学生姓名（赠换特批 / 小班名单常用）。"""
    if "_" in class_name:
        cand = class_name.split("_", 1)[1]
        cand = re.split(r"[_\s（(]", cand)[0]
        return cand
    return ""


# 初一/初二/初三 -> 七年级/八年级/九年级（7月起班级名用初一系，模板表头用七年级系）
GRADE_NORM = {"初一": "七年级", "初二": "八年级", "初三": "九年级"}

# 暑假衔接班 -> 年级（2026-07 确认按当前在读年级；幼小衔接 2026-08-04 改按一年级）
BRIDGE_MAP = {"小升初": "六年级", "小初衔接": "六年级", "初升高": "九年级",
              "七升八": "七年级", "八升九": "八年级", "幼小衔接": "一年级"}


def _norm(g):
    return GRADE_NORM.get(g, g)


def extract_grade(class_name):
    """从班级名称提取年级；返回 '' 表示未知，需人工核对。"""
    if not isinstance(class_name, str):
        return ""
    name = class_name
    if "领航" in name:                      # 1. 领航伴学
        return "领航伴学"
    for kw, g in BRIDGE_MAP.items():        # 2. 暑假衔接班（按当前在读年级）
        if kw in name:
            return g
    for kw in GRADE_KEYWORDS:               # 3. 年级关键词（初一系归一为七年级系）
        if kw in name:
            return _norm(kw)
    if any(k in name for k in SPECIAL_KEYWORDS):   # 4. 赠换特批查学生表
        stu = _extract_student_name(name)
        if stu and stu in STUDENT_GRADE:
            return _norm(STUDENT_GRADE[stu])
    # 5. 班级名直接含学生姓名（如「孙新梦生物1班」，不带赠送关键词）→ 查表
    for stu in sorted(STUDENT_GRADE, key=len, reverse=True):
        if stu in name:
            return _norm(STUDENT_GRADE[stu])
    return ""


# ---------- SWITCH 公式构造 ----------
def _switch_expr(col, mapping):
    parts = []
    for k, v in mapping.items():
        key = f'"{k}"' if isinstance(k, str) else str(k)
        parts.append(f"{key},{v}")
    return f"_xlfn.SWITCH({col}," + ",".join(parts) + ",0)"


def build_switch_formulas(row):
    """返回 (F, G, H) 三列公式字符串（含前导 '='）。"""
    grade_sw = _switch_expr(f"B{row}", GRADE_COEFF)
    head_sw = _switch_expr(f"E{row}", HEADCOUNT_COEFF)
    type_sw = f'_xlfn.SWITCH(D{row},"小班",1,"1对1",0,"1对2",1.2)'
    f = "=" + grade_sw + "*" + head_sw + "*" + type_sw
    g = "=" + grade_sw
    h = "=" + head_sw
    return f, g, h


if __name__ == "__main__":
    print("学生表条数:", len(STUDENT_GRADE))
    print("初三1v1_张三 ->", extract_grade("初三1v1_张三"))
    print("高一小班数学1班（北师大） ->", extract_grade("高一小班数学1班（北师大）"))
    print("亲属赠送_黄小满 ->", extract_grade("亲属赠送_黄小满"))
    print("02-数学 清洗 ->", clean_subject("02-数学"))
    print("F/G/H @2:", build_switch_formulas(2))
