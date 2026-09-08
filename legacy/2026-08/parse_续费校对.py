# -*- coding: utf-8 -*-
"""
8月续费校对：钉钉群喜报 vs 表格
核心修正：用全表49位老师作为任课名单（语文/数学/英语/理化四组）
剔除：客服12人(含蒙萌/蒙蒙=孙蒙蒙) + 班主任63人
课时：剔除后剩余任课老师均分
"""
import json, re
from collections import defaultdict

# ---------- 名单 ----------
roster = json.load(open('/Users/macos/Desktop/8月工资表/exports/teacher_roster.json'))
kefu = set(roster['客服部(宣城二校12人)'])
banzhuren = set(roster['班主任(咨询部63人)'])

# 全表49位老师（去空格后）
all49 = set('''马建国 吴名 姜卉镝 袁婷 卞维卫 马金曼 蒋贝贝 艾璐璐 李凡 任勇 高明亮 梁缘 潘瑶 胡长春 徐荣祥 张昱 张旭 徐良琴 李媛媛 杨宇宸 廖永翠 费晓曼 周文婧 董葛飞 李娜 李梦 汪涛 王霞 王芳 孙波 贡滢滢 许颖颖 邱婉 刘立伟 章桃红 杨慧 张昕茹 陈佳烨 鲁德刚 刘文剑 黄雅丽 何心 潘政豪 胡涛 范仙阳 钱瑞 张玉霞 何雨佳 章恒'''.split())

# 客服别名 -> 标准名
kefu_alias = {'蒙萌': '孙蒙蒙', '蒙蒙': '孙蒙蒙'}

# 名字 -> 归属类型（优先任课老师 > 客服 > 班主任）
# 注意"王芳"重名：英语组老师 vs 班主任。表格有王芳课时数据，按任课老师处理
name_role = {}
for n in all49:
    name_role[n] = 'teacher'
for n in kefu:
    if n not in name_role:
        name_role[n] = 'kefu'
for n in banzhuren:
    if n not in name_role:
        name_role[n] = 'banzhuren'
# 别名单独映射
alias_to_std = {a: '孙蒙蒙' for a in kefu_alias}

# ---------- 读取消息 ----------
d1 = json.load(open('/Users/macos/Desktop/8月工资表/exports/aug_messages.json'))
d2 = json.load(open('/Users/macos/Desktop/8月工资表/exports/aug_messages_2.json'))
msgs = d1['messages'] + d2['messages']

# 所有已知名字（含别名）按长度降序，避免短名先匹配（如"吴名"中的"名"）
all_names = sorted(set(all49 | kefu | banzhuren | set(alias_to_std.keys())), key=len, reverse=True)

def norm_name(s):
    return s.replace(' ', '').replace('　', '').replace('老师', '')

def extract_names(text):
    """在文本中按顺序提取已知老师名字（锚点匹配）"""
    found = []  # (position, name)
    t = text
    for nm in all_names:
        # 找到所有出现位置
        start = 0
        while True:
            idx = t.find(nm, start)
            if idx == -1:
                break
            found.append((idx, nm))
            start = idx + 1
    found.sort()
    # 去重（同一位置同一名字只算一次）
    result = []
    used_pos = set()
    for pos, nm in found:
        if pos in used_pos:
            continue
        used_pos.add(pos)
        result.append(nm)
    return result

def classify(names):
    """把名字列表归类为 任课老师 / 客服 / 班主任"""
    teachers = []
    has_kefu = False
    for nm in names:
        std = alias_to_std.get(nm, nm)
        role = name_role.get(std, None)
        if role == 'teacher':
            teachers.append(std)
        elif role == 'kefu':
            has_kefu = True
        elif role == 'banzhuren':
            pass  # 班主任不分单
        else:
            # 未知名字：既不在49人也不在客服/班主任 —— 可能是其他校区老师
            # 这些老师不参与本表分摊，但也要算作"任课"分摊，避免分母错误
            # 关键决策：未知名字视为"其他校区任课老师"，也参与分摊（会稀释本表老师课时）
            teachers.append(('其他:' + std))
    return teachers, has_kefu

# ---------- 课时解析 ----------
def parse_ke(seg):
    """从'续费'之后到结束的片段里解析课时。返回 (1v1, banke, xiaoban)"""
    v1 = 0.0
    bk = 0.0
    xb = 0.0
    s = seg
    # 去掉表情和标点尾缀，但保留数字和单位
    # 匹配各种模式
    # 1V1类：NN课时一对一 / NNks一对一 / NN课时1对1 / 一对三NN课时 / 一对一NN课时 / NN课时一对三
    # 班课类：NN次班课 / NN次 / NN课时班课
    # 小班：NN次领航 / NN次伴学 / 领航伴读 / 领航伴学

    # 先统一：1对1 -> 一对一, 1v1 -> ks
    s2 = s.replace('1对1', '一对一').replace('1V1', 'ks').replace('1v1', 'ks').replace('一对三', '一对三').replace('一对二', '一对三')

    # 领航/伴学 独立算（小班）
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*次\s*(?:领航|伴学|伴读)', s):
        xb += float(m.group(1))
    # 也有"NN次领航伴读"写成别的
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:领航|伴学|伴读)\s*(?:课|次|节)?', s):
        pass

    # 1V1 课时：数字 + (课时|ks) + 一对一/一对三/一对二/1对1
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:课时|ks|KS)\s*(?:一对一|一对三|一对二)', s):
        v1 += float(m.group(1))
    # 一对一/一对三 在前： 一对三NN课时 / 一对一NN课时 / 一对三NN课时
    for m in re.finditer(r'(?:一对一|一对三|一对二)\s*(\d+(?:\.\d+)?)\s*(?:课时|ks|KS)?', s):
        v1 += float(m.group(1))
    # 单独的 NN课时 且后面没有"班课"（可能是纯1v1，需看上下文）
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*课时(?!\s*(?:班课|一对一|一对三|一对二|领航|伴学))', s):
        v1 += float(m.group(1))
    # 单独 NNks（一对一）
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*ks(?!\s*(?:一对一|一对三))', s, re.IGNORECASE):
        v1 += float(m.group(1))

    # 班课：数字 + 次(班课) 或 数字 + 课时班课
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*次\s*班课', s):
        bk += float(m.group(1))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*课时\s*班课', s):
        bk += float(m.group(1))
    # 单独的 NN次（没有领航/伴学/班课修饰，默认班课）
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*次(?!\s*(?:班课|领航|伴学|伴读))', s):
        bk += float(m.group(1))

    return v1, bk, xb

# ---------- 主循环 ----------
teacher_1v1 = defaultdict(float)
teacher_banke = defaultdict(float)
teacher_xiaoban = defaultdict(float)
hit_detail = defaultdict(list)  # 老师 -> [喜报描述]
parse_fail = []

for m in msgs:
    t = m.get('text', '')
    ts = m.get('createTime', '')
    if not ts.startswith('2026-08'):
        continue
    try:
        day = int(ts[8:10])
    except:
        continue
    if day < 3 or day > 30:
        continue
    if '恭喜' not in t or '续费' not in t:
        continue

    # 按"恭喜"切分多条喜报
    segs = re.split(r'恭喜', t)
    for seg in segs:
        if '续费' not in seg:
            continue
        # 名字部分 = 续费 之前
        name_part = seg.split('续费')[0]
        # 课时部分 = 续费 之后
        fee_part = seg.split('续费', 1)[1] if seg.count('续费') >= 1 else seg.split('续费', 1)[-1]

        names = extract_names(name_part)
        # 也检查 fee_part 里是否混着名字（有时名字在'续费'后，如"停课学员续费"）
        # 先只取 name_part 的名字
        teachers, has_kefu = classify(names)

        if not teachers:
            continue

        v1, bk, xb = parse_ke(fee_part)

        if v1 == 0 and bk == 0 and xb == 0:
            parse_fail.append((ts, seg[:120]))
            continue

        n = len(teachers)
        if n == 0:
            continue
        for tch in teachers:
            if tch.startswith('其他:'):
                # 其他校区老师：分摊但不算进本表
                continue
            teacher_1v1[tch] += v1 / n
            teacher_banke[tch] += bk / n
            teacher_xiaoban[tch] += xb / n
            hit_detail[tch].append(f'{ts[:16]} {seg.strip()[:80]}')

# ---------- 输出结果 ----------
print('=== 喜报解析结果（全表49人，剔除客服+班主任后均分）===')
print(f'{"老师":<8}{"喜报1V1":>10}{"喜报班课":>10}{"喜报小班":>10}{"命中条数":>8}')
for tch in sorted(all49):
    v1 = round(teacher_1v1.get(tch, 0), 2)
    bk = round(teacher_banke.get(tch, 0), 2)
    xb = round(teacher_xiaoban.get(tch, 0), 2)
    n = len(hit_detail.get(tch, []))
    if v1 or bk or xb:
        print(f'{tch:<8}{v1:>10}{bk:>10}{xb:>10}{n:>8}')

print()
print('=== 解析失败（有续费但没解析出课时）===')
for ts, seg in parse_fail:
    print(ts, '|', seg)
print(f'失败条数: {len(parse_fail)}')

# 保存到json供下一步对比
out = {
    'teacher_1v1': {k: round(v, 2) for k, v in teacher_1v1.items()},
    'teacher_banke': {k: round(v, 2) for k, v in teacher_banke.items()},
    'teacher_xiaoban': {k: round(v, 2) for k, v in teacher_xiaoban.items()},
    'hit_detail': {k: v for k, v in hit_detail.items()},
    'parse_fail': parse_fail,
}
json.dump(out, open('/Users/macos/Desktop/8月工资表/exports/parse_result.json', 'w'), ensure_ascii=False, indent=1)
print('\n已保存 exports/parse_result.json')
