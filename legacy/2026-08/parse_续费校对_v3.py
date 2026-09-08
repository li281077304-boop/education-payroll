# -*- coding: utf-8 -*-
"""
8月续费校对 v3 —— 最终口径
判定规则（用户确认）：
1. 喜报按"恭喜"切分，看第一个名字 = 客服是谁 → 决定校区
   - 二校客服12人打头 → 二校的单，剔除客服后剩余任课老师均分
   - 其他名字打头（一校客服如王芳、蒋梦婷、胡思敏等）→ 别的校区，整条跳过
2. 错别字映射：杨宇辰→杨宇宸、潘正豪→潘政豪、梁媛→梁缘
3. 客服不分课时（客服拿全额，不参与分摊）
4. 王芳：二校单里=英语组老师参与分摊；一校单里自动被跳过
"""
import json, re
from collections import defaultdict

# ---------- 名单 ----------
roster = json.load(open('/Users/macos/Desktop/8月工资表/exports/teacher_roster.json'))
kefu = set(roster['客服部(宣城二校12人)'])  # 二校客服12人
banzhuren = set(roster['班主任(咨询部63人)'])

all49 = set('''马建国 吴名 姜卉镝 袁婷 卞维卫 马金曼 蒋贝贝 艾璐璐 李凡 任勇 高明亮 梁缘 潘瑶 胡长春 徐荣祥 张昱 张旭 徐良琴 李媛媛 杨宇宸 廖永翠 费晓曼 周文婧 董葛飞 李娜 李梦 汪涛 王霞 王芳 孙波 贡滢滢 许颖颖 邱婉 刘立伟 章桃红 杨慧 张昕茹 陈佳烨 鲁德刚 刘文剑 黄雅丽 何心 潘政豪 胡涛 范仙阳 钱瑞 张玉霞 何雨佳 章恒'''.split())

# 客服别名 + 错别字映射
alias = {
    '蒙萌': '孙蒙蒙', '蒙蒙': '孙蒙蒙', '孙萌萌': '孙蒙蒙',  # 客服孙蒙蒙的别名
    '杨宇辰': '杨宇宸',   # 错别字
    '潘正豪': '潘政豪',   # 错别字
    '梁媛': '梁缘',       # 错别字
}

# ---------- 读取消息 ----------
d1 = json.load(open('/Users/macos/Desktop/8月工资表/exports/aug_messages.json'))
d2 = json.load(open('/Users/macos/Desktop/8月工资表/exports/aug_messages_2.json'))
msgs = d1['messages'] + d2['messages']

# 名字识别：先替换别名，再按位置找已知名字
def extract_names(text):
    """在名字段文本里，按顺序提取已知名字（49人+客服+班主任+别名），做错别字映射"""
    t = text
    # 先做别名替换（蒙萌/蒙蒙/孙萌萌 -> 孙蒙蒙 等）
    for a, std in sorted(alias.items(), key=lambda x: -len(x[0])):
        t = t.replace(a, std)
    # 去掉"老师"
    t = t.replace('老师', ' ')

    # 按位置找已知名字（49人+客服+班主任，长度降序）
    all_names = sorted(all49 | kefu | banzhuren, key=len, reverse=True)
    found = []
    for nm in all_names:
        start = 0
        while True:
            idx = t.find(nm, start)
            if idx == -1:
                break
            found.append((idx, nm))
            start = idx + 1
    found.sort()
    seen_pos = set()
    result = []
    for pos, nm in found:
        if pos in seen_pos:
            continue
        seen_pos.add(pos)
        result.append(nm)
    return result

# ---------- 课时解析 ----------
def parse_ke(seg):
    """解析课时。返回 (1v1, banke, xiaoban)"""
    v1 = 0.0
    bk = 0.0
    xb = 0.0
    s = seg.replace('1对1', '一对一').replace('1V1', 'ks').replace('1v1', 'ks').replace('一对三', '一对三').replace('一对二', '一对三')

    # 1V1：数字 + 课时/ks + 一对一/一对三/一对二
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:课时|ks|KS)\s*(?:一对一|一对三|一对二)', s):
        v1 += float(m.group(1))
    # 一对一/一对三 在前：一对三NN课时 / 一对一NN课时
    for m in re.finditer(r'(?:一对一|一对三|一对二)\s*(\d+(?:\.\d+)?)\s*(?:课时|ks|KS)?', s):
        v1 += float(m.group(1))
    # 纯 NN课时（后面不是班课/一对一/一对三/领航/伴学）
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*课时(?!\s*(?:班课|一对一|一对三|一对二|领航|伴学))', s):
        v1 += float(m.group(1))
    # 纯 NNks
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*ks(?!\s*(?:一对一|一对三))', s, re.IGNORECASE):
        v1 += float(m.group(1))

    # 班课：NN次班课 / NN课时班课 / 纯NN次（非领航伴学）
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*次\s*班课', s):
        bk += float(m.group(1))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*课时\s*班课', s):
        bk += float(m.group(1))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*次(?!\s*(?:班课|领航|伴学|伴读))', s):
        bk += float(m.group(1))

    # 小班：NN次领航/伴学/伴读
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*次\s*(?:领航|伴学|伴读)', s):
        xb += float(m.group(1))

    return v1, bk, xb

# ---------- 主循环 ----------
teacher_1v1 = defaultdict(float)
teacher_banke = defaultdict(float)
teacher_xiaoban = defaultdict(float)
hit_detail = defaultdict(list)
skipped = []  # 跳过的非二校单
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

    for seg in re.split(r'恭喜', t):
        if '续费' not in seg:
            continue
        name_part = seg.split('续费')[0]
        fee_part = seg.split('续费', 1)[-1]

        names = extract_names(name_part)
        if not names:
            continue

        # 判定校区：第一个名字是不是二校客服
        first = names[0]
        if first not in kefu:
            # 不是二校客服打头 → 一校/外校单，跳过
            skipped.append((ts, seg[:80]))
            continue

        # 二校单：剔除客服和班主任，剩下的任课老师
        teachers = [n for n in names if n in all49]

        if not teachers:
            # 只有客服，没有任课老师（比如"客服独自续费"）
            continue

        v1, bk, xb = parse_ke(fee_part)
        if v1 == 0 and bk == 0 and xb == 0:
            parse_fail.append((ts, seg[:120]))
            continue

        n = len(teachers)
        for tch in teachers:
            teacher_1v1[tch] += v1 / n
            teacher_banke[tch] += bk / n
            teacher_xiaoban[tch] += xb / n
            hit_detail[tch].append(f'{ts[:16]} {seg.strip()[:80]}')

# ---------- 输出 ----------
print('=== v3 喜报解析结果（客服打头判定校区）===')
print(f'{"老师":<8}{"喜1V1":>8}{"喜班课":>8}{"喜小班":>8}{"条数":>5}')
for tch in sorted(all49):
    v1 = round(teacher_1v1.get(tch, 0), 2)
    bk = round(teacher_banke.get(tch, 0), 2)
    xb = round(teacher_xiaoban.get(tch, 0), 2)
    n = len(hit_detail.get(tch, []))
    if v1 or bk or xb:
        print(f'{tch:<8}{v1:>8}{bk:>8}{xb:>8}{n:>5}')

print()
print(f'跳过的非二校单（一校/外校）条数: {len(skipped)}')
print(f'解析失败条数: {len(parse_fail)}')
for ts, seg in parse_fail:
    print('  失败:', ts, '|', seg)

out = {
    'teacher_1v1': {k: round(v, 2) for k, v in teacher_1v1.items()},
    'teacher_banke': {k: round(v, 2) for k, v in teacher_banke.items()},
    'teacher_xiaoban': {k: round(v, 2) for k, v in teacher_xiaoban.items()},
    'hit_detail': {k: v for k, v in hit_detail.items()},
    'skipped_count': len(skipped),
    'parse_fail': parse_fail,
}
json.dump(out, open('/Users/macos/Desktop/8月工资表/exports/parse_result_v3.json', 'w'), ensure_ascii=False, indent=1)
print('\n已保存 exports/parse_result_v3.json')
