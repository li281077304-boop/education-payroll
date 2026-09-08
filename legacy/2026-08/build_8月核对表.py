#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""8月工资核对表生成：排课列表 -> 工资核对表8月.xlsx

特殊规则（2026-09-01 用户确认）：
  - 班课（小班/1对2）年级段全部回调一级：高三→高二、高二→高一、高一→九年级、
    九年级→八年级、八年级→七年级、七年级→六年级、六年级→五年级、五年级→四年级、
    四年级→三年级、三年级→二年级、二年级→一年级（一年级保持）
  - 衔接班（小升初/初升高/七升八/八升九/幼小衔接）已按在读年级映射，保持不变
  - 领航伴学保持不变；1对1 年级保持不变
  - 工资核对 R/U 列用内嵌「填报数据」隐藏 sheet（WPS 最稳），理化组老师引用
"""
import os
import re
import shutil
import sys

import pandas as pd
import openpyxl

sys.path.insert(0, '/Users/macos/.workbuddy/skills/工资核对表制作/scripts')
from _grade_extractor import (extract_grade, extract_subject,
                              map_class_type, build_switch_formulas,
                              BRIDGE_MAP, GRADE_KEYWORDS, clean_subject)

SRC = "/Users/macos/Desktop/8月工资表/排课列表_08月03日到08月30日_202609011519.xls"
TEMPLATE = "/Users/macos/.workbuddy/skills/工资核对表制作/assets/工资核对表模板.xlsx"
OUT = "/Users/macos/Desktop/8月工资表/工资核对表8月.xlsx"
FILL_SHEET = "/Users/macos/Desktop/8月工资表/2026年8月份理化组薪资.xlsx"  # 理化组填报表

# 班课年级段回调一级（普通年级关键词；衔接班/领航/1对1不回调）
GRADE_RECEDE = {
    "高三": "高二", "高二": "高一", "高一": "九年级",
    "九年级": "八年级", "八年级": "七年级", "七年级": "六年级",
    "六年级": "五年级", "五年级": "四年级", "四年级": "三年级",
    "三年级": "二年级", "二年级": "一年级", "一年级": "一年级",
}
BRIDGE_KW = list(BRIDGE_MAP.keys())  # 衔接班关键词（这些不回调）


def grade_recede(class_name, ctype, grade):
    """班课年级段回调一级。返回回调后的年级。"""
    if ctype not in ("小班", "1对2"):   # 只对班课回调
        return grade
    if not grade:
        return grade
    if "领航" in str(class_name):        # 领航伴学不回调
        return grade
    if any(k in str(class_name) for k in BRIDGE_KW):   # 衔接班不回调（已在读年级）
        return grade
    # 检查年级是否来自普通关键词（而非查表/衔接）
    if grade in GRADE_RECEDE:
        return GRADE_RECEDE[grade]
    return grade


def main():
    if os.path.exists(OUT):
        bak = OUT + ".bak"
        shutil.copy2(OUT, bak)
        print(f"[备份] {bak}")

    try:
        df = pd.read_excel(SRC)   # 自动识别（.xls 实际为 xlsx 时用 openpyxl）
    except Exception:
        df = pd.read_excel(SRC, engine="xlrd")
    print(f"[读取源] {SRC}  行数={len(df)}")
    df = df[df['上课状态'].astype(str).str.strip() == '已上课']
    df = df[df['实到'].notna()]
    df = df[df['实到'] > 0]
    print(f"[过滤] 已上课且实到>0 -> {len(df)} 行")

    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb["排课记录"]
    header_row = 1
    for r in range(1, 6):
        if ws.cell(row=r, column=1).value == "任课老师":
            header_row = r
            break
    data_start = header_row + 1
    for r in range(data_start, ws.max_row + 1):
        for c in range(1, 9):
            ws.cell(row=r, column=c).value = None

    ridx = data_start
    unknown = []
    stats = {"小班回调": 0}
    for _, row in df.iterrows():
        tname = str(row['任课老师']).strip()
        cname = str(row['上课班级']) if pd.notna(row['上课班级']) else ''
        subj = extract_subject(cname, row['上课科目'] if '上课科目' in df.columns else None)
        ctype = map_class_type(row['教学形式'])
        att_n = int(row['实到'])
        grade0 = extract_grade(cname)
        grade = grade_recede(cname, ctype, grade0)
        if grade != grade0:
            stats["小班回调"] += 1
        if not grade:
            unknown.append((tname, cname))
        f, g, h = build_switch_formulas(ridx)
        ws.cell(row=ridx, column=1, value=tname)
        ws.cell(row=ridx, column=2, value=grade)
        ws.cell(row=ridx, column=3, value=subj)
        ws.cell(row=ridx, column=4, value=ctype)
        ws.cell(row=ridx, column=5, value=att_n)
        ws.cell(row=ridx, column=6, value=f)
        ws.cell(row=ridx, column=7, value=g)
        ws.cell(row=ridx, column=8, value=h)
        ridx += 1

    last = ridx - 1
    if ws.max_row > last:
        for r in range(ws.max_row, last, -1):
            ws.delete_rows(r)
    print(f"[排课记录] 写入 {last - data_start + 1} 条 (回调 {stats['小班回调']} 条)")

    # ---- 内嵌填报数据 sheet（隐藏）----
    if "填报数据" in wb.sheetnames:
        del wb["填报数据"]
    fws = wb.create_sheet("填报数据")
    fws.cell(1, 1, "姓名")
    fws.cell(1, 2, "1对1折算AA")
    fws.cell(1, 3, "班课折算AC")
    fill = openpyxl.load_workbook(FILL_SHEET, data_only=False)
    fws_main = fill["教学部"]
    frow = 2
    for r in range(5, 60):
        name = fws_main.cell(r, 3).value
        if not name:
            continue
        aa = fws_main.cell(r, 27).value   # AA
        ac = fws_main.cell(r, 29).value   # AC
        if aa is None and ac is None:
            continue
        # AA 是公式的话取不到值，这里直接复制原始单元格（值或公式）
        fws.cell(frow, 1, str(name).strip())
        fws.cell(frow, 2, aa if isinstance(aa, (int, float)) else (aa if aa is not None else 0))
        fws.cell(frow, 3, ac if isinstance(ac, (int, float)) else (ac if ac is not None else 0))
        frow += 1
    print(f"[填报数据] {frow - 2} 行")

    # ---- 工资核对 sheet：老师名单 + 公式 ----
    gws = wb["工资核对"]
    # 清空旧数据行（保留表头1-2行）
    for r in range(3, gws.max_row + 1):
        for c in range(1, gws.max_column + 1):
            gws.cell(row=r, column=c).value = None
    # 老师名单：排课记录中出现过的老师（按出现顺序）
    teachers = []
    seen = set()
    for r in range(data_start, last + 1):
        t = ws.cell(r, 1).value
        if t and t not in seen:
            seen.add(t)
            teachers.append(t)
    print(f"[老师名单] {len(teachers)} 人")

    rr = 3
    for t in teachers:
        gws.cell(rr, 2, f'=VLOOKUP(C{rr},排课记录!A:C,3,0)')
        gws.cell(rr, 3, t)
        for c, letter in enumerate(['D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P']):
            col_idx = 4 + c
            gws.cell(rr, col_idx,
                     f'=(SUMIFS(排课记录!$E:$E,排课记录!$D:$D,$C$2,排课记录!$A:$A,$C{rr},排课记录!$B:$B,{letter}$2))*3')
        gws.cell(rr, 17,  # Q
                 f'=(D{rr}+E{rr}+F{rr}+G{rr}+H{rr}+I{rr})/3*2*0.85+(J{rr}+K{rr})/3*2*0.9+L{rr}/3*2*1+M{rr}/3*2*1.1+N{rr}/3*2*1.25+O{rr}/3*2*1.35+P{rr}/3*2*1.5')
        # R 填报（内嵌 VLOOKUP：1对1折算 AA），S 差值
        gws.cell(rr, 18, f'=VLOOKUP(C{rr},填报数据!$A:$C,2,0)')
        gws.cell(rr, 19, f'=Q{rr}-R{rr}')
        # T 班课绩效，U 填报（班课折算 AC），V 差值
        gws.cell(rr, 20, f'=SUMIFS(排课记录!F:F,排课记录!A:A,C{rr})*2')
        gws.cell(rr, 21, f'=VLOOKUP(C{rr},填报数据!$A:$C,3,0)')
        gws.cell(rr, 22, f'=T{rr}-U{rr}')
        rr += 1
    if gws.max_row > rr - 1:
        for r in range(gws.max_row, rr - 1, -1):
            gws.delete_rows(r)

    # 隐藏填报数据 sheet
    wb["填报数据"].sheet_state = 'hidden'
    wb.calculation.fullCalcOnLoad = True
    wb.save(OUT)
    print(f"[完成] -> {OUT}")
    if unknown:
        print(f"[警告] {len(unknown)} 条无法识别年级：")
        for t, c in unknown[:30]:
            print(f"   - {t}: {c}")


if __name__ == "__main__":
    main()
