# -*- coding: utf-8 -*-
"""管理岗位考核指标计算器（口径 2026-08-05 用户确认）

计算：
  1. 周平均（一对一）= 组课时生产页「一对一 月周均」(K列, 月总行)
  2. 续推人次 = 续推表当月sheet 1V1每周列(4-8)+班课每周列(10-18) 非0单元格数
  3. 退费人次 = 退费表当月sheet P列(批注/教师姓名, 0-based col15) 非空记录数
  4. 总学员数 = 学生sheet 单科数月均（打印学生sheet供人工取数）

用法:
  /usr/bin/python3 compute_kh_metrics.py \
    --month 7 \
    --folder "/Users/macos/Desktop/7月工资表制作与核查" \
    --math-stat "数学组数据统计表-宣城二校7月第5周.xls" \
    --phy-stat "理化数据统计表xlsx(4).xlsx" \
    --xutui "2026年度续费+推荐数据(1).xlsx" \
    --tuifei "副本宣城二校退费统计表2026年.xls"
"""
import argparse, os, re
import pandas as pd
import openpyxl
import xlrd

def clean(n):
    return re.sub(r"\s+", "", str(n)) if n else ""

# ---------- 1) 周平均：组课时生产 K列(0-based 10) 月总行 ----------
def read_weekly_avg(stat_path):
    """返回 {'数学组': x, '理化组': y} 或单组值。xls/xlsx 通用。"""
    ext = os.path.splitext(stat_path)[1].lower()
    if ext == ".xls":
        xl = pd.ExcelFile(stat_path, engine="xlrd")
        df = xl.parse("组课时生产", header=None)
        # 找“月总”行（第0列==月总），取 K列 index 10（一对一 月周均）
        for i in range(len(df)):
            v0 = str(df.iloc[i, 0] or "")
            if v0.strip() == "月总":
                k = df.iloc[i, 10]
                return float(k) if isinstance(k, (int, float)) else None
    else:
        wb = openpyxl.load_workbook(stat_path, data_only=True)
        ws = wb["组课时生产"]
        for r in range(1, ws.max_row + 1):
            if str(ws.cell(r, 1).value or "").strip() == "月总":
                k = ws.cell(r, 11).value
                return float(k) if isinstance(k, (int, float)) else None
    return None

# ---------- 2) 续推人次：1V1周列(4-8)+班课周列(10-18) 非0单元格数 ----------
def count_xutui(xutui_path, month_sheet):
    wb = openpyxl.load_workbook(xutui_path, data_only=True)
    ws = wb[month_sheet]
    # 学科组列=2，逐行按组统计非0单元格（0-based: 4-8 是 openpyxl 1-based 4..8? 注意 openpyxl cell(row, col) 是1-based）
    from collections import defaultdict
    cnt = defaultdict(int)   # 组 -> 人次
    detail = defaultdict(list)
    for r in range(3, ws.max_row + 1):
        grp = str(ws.cell(r, 2).value or "").strip()
        nm = clean(ws.cell(r, 3).value)
        if not nm:
            continue
        cols = list(range(4, 9)) + list(range(10, 19))   # 1V1 5周 + 班课 9周
        for c in cols:
            v = ws.cell(r, c).value
            if isinstance(v, (int, float)) and v > 0:
                cnt[grp] += 1
                detail[grp].append((nm, c, v))
    return cnt, detail

# ---------- 3) 退费人次：P列(0-based 15) 非空记录数 ----------
def count_tuifei(tuifei_path, month_sheet):
    book = xlrd.open_workbook(tuifei_path, formatting_info=True)
    ws = book.sheet_by_name(month_sheet)
    records = []
    for r in range(2, ws.nrows):
        nm = str(ws.cell_value(r, 3)).strip()
        if not nm:
            continue
        p = str(ws.cell_value(r, 15)).strip()   # P列 = 负责教师
        if p:
            q = ws.cell_value(r, 16)
            e = ws.cell_value(r, 17)
            records.append((nm, p, q, e))
    return records

# ---------- 4) 学生sheet 打印（总学员数人工取数） ----------
def show_students(stat_path, label):
    ext = os.path.splitext(stat_path)[1].lower()
    print(f"\n[{label}] 学生 sheet（人工确认总学员数/单科数月均）：")
    try:
        if ext == ".xls":
            xl = pd.ExcelFile(stat_path, engine="xlrd")
            df = xl.parse("学生", header=None)
            print(df.head(10).to_string(max_colwidth=10))
        else:
            wb = openpyxl.load_workbook(stat_path, data_only=True)
            ws = wb["学生"]
            for r in range(1, min(ws.max_row, 12) + 1):
                print("  r%d:" % r, [ws.cell(r, c).value for c in range(1, min(ws.max_column, 12) + 1)])
    except Exception as ex:
        print("  读取失败:", type(ex).__name__, ex)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="月份，如 7")
    ap.add_argument("--folder", required=True, help="文件所在文件夹")
    ap.add_argument("--math-stat", default=None, help="数学组统计表文件名")
    ap.add_argument("--phy-stat", default=None, help="理化统计表文件名")
    ap.add_argument("--xutui", default=None, help="续费+推荐数据文件名")
    ap.add_argument("--tuifei", default=None, help="退费统计表文件名")
    args = ap.parse_args()
    F = args.folder

    # 1) 周平均
    if args.math_stat:
        m = read_weekly_avg(os.path.join(F, args.math_stat))
        print(f"数学组 周平均(一对一月周均) = {m}")
    if args.phy_stat:
        p = read_weekly_avg(os.path.join(F, args.phy_stat))
        print(f"理化组 周平均(一对一月周均) = {p}")

    # 2) 续推人次
    if args.xutui:
        try:
            cnt, detail = count_xutui(os.path.join(F, args.xutui), f"{args.month}月")
            for grp, n in cnt.items():
                if grp in ("数学组", "理化组"):
                    print(f"续推人次 {grp} = {n}")
            # 数学组分解
            for grp in ("数学组", "理化组"):
                if grp in detail:
                    o1 = sum(1 for _, c, _ in detail[grp] if c <= 8)
                    bk = sum(1 for _, c, _ in detail[grp] if c >= 10)
                    print(f"  ({grp}: 1V1周人次{o1} + 班课周人次{bk})")
        except Exception as ex:
            print("续推读取失败:", type(ex).__name__, ex)

    # 3) 退费人次
    if args.tuifei:
        try:
            recs = count_tuifei(os.path.join(F, args.tuifei), f"{args.month}月份 ")
            print(f"退费人次(退费表P列) 总数 = {len(recs)}")
            for nm, p, q, e in recs:
                print(f"  {nm} -> {p} (人头{q} 业绩{e})")
        except Exception as ex:
            print("退费读取失败:", type(ex).__name__, ex)

    # 4) 学生sheet
    if args.math_stat:
        show_students(os.path.join(F, args.math_stat), "数学组")
    if args.phy_stat:
        show_students(os.path.join(F, args.phy_stat), "理化组")

if __name__ == "__main__":
    main()
