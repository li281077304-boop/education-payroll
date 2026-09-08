import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
import re

# 读取1月排课记录
file_1jan = '/Users/macos/WorkBuddy/20260310145718/排课记录-01月05日到02月01日_202603101526.xlsx'
df_1jan = pd.read_excel(file_1jan)

# 学生年级映射(从其他课程推断)
student_grade_map = {
    '李泽皓': '高一',
    '金暖欣': '八年级',
    '张佳余': '五年级',
    '傅浩宸': '高一'
}

# 从班级名称提取学生
def extract_student(class_name):
    if '_(' in str(class_name):
        return class_name.split('_(')[1].split(')')[0]
    return None

# 从班级名称提取学科
def extract_subject_from_class(class_name):
    if '(' in str(class_name) and ')' in str(class_name):
        content = class_name.split('(')[1].split(')')[0]
        if '-' in content:
            subject_map = {
                '01': '语文', '02': '数学', '03': '英语', '04': '物理',
                '05': '化学', '06': '生物', '07': '政治', '08': '历史',
                '09': '地理', '10': '科学'
            }
            code = content.split('-')[0]
            return subject_map.get(code, content.split('-')[1])
    return None

# 从班级名称提取年级
def extract_grade_from_class(class_name):
    class_name_str = str(class_name)
    
    # 优先处理小班格式: "二年级小班英语2班"
    grade_pattern = re.search(r'(一|二|三|四|五|六|七|八|九)年级', class_name_str)
    if grade_pattern:
        grade_map = {
            '一': '一年级', '二': '二年级', '三': '三年级', '四': '四年级',
            '五': '五年级', '六': '六年级', '七': '七年级', '八': '八年级',
            '九': '九年级'
        }
        return grade_map[grade_pattern.group(1)]
    
    # 处理高中小班: "高二小班数学4班"
    high_school_pattern = re.search(r'(高一|高二|高三)小班', class_name_str)
    if high_school_pattern:
        return high_school_pattern.group(1)  # 高一, 高二, 高三
    
    # 处理初中小班: "九年级小班数学2班"
    middle_pattern = re.search(r'九年级', class_name_str)
    if middle_pattern:
        return '九年级'
    
    # 处理领航伴学班: "小学领航伴学2班(2-4)"
    if '领航伴学' in class_name_str and '(' in class_name_str:
        range_part = class_name_str.split('(')[1].split(')')[0]
        if '-' in range_part:
            # 取中间值: 2-4 取3, 5-6 取5
            numbers = [int(x) for x in re.findall(r'\d+', range_part)]
            if numbers:
                middle = numbers[len(numbers)//2]
                return f'{["一","二","三","四","五","六"][middle-1]}年级'
    
    return None

# 提取学生
df_1jan['学生'] = df_1jan['班级名称'].apply(extract_student)
df_1jan['学科'] = df_1jan['班级名称'].apply(extract_subject_from_class)

# 定义年级映射
grade_map = {
    '06-六年级': '六年级', '02-二年级': '二年级', '12-高三': '高三',
    '09-初三': '九年级', '05-五年级': '五年级', '04-四年级': '四年级',
    '08-初二': '八年级', '07-初一': '七年级', '11-高二': '高二',
    '03-三年级': '三年级', '10-高一': '高一'
}

# 标准化年级字段
df_1jan['年级_标准'] = df_1jan['课程所属年级'].map(grade_map)

# 如果年级为空,从班级名称提取
nan_indices = df_1jan['年级_标准'].isna()
df_1jan.loc[nan_indices, '年级_标准'] = df_1jan.loc[nan_indices, '班级名称'].apply(extract_grade_from_class)

# 如果年级仍为空,从学生映射获取
still_nan = df_1jan['年级_标准'].isna()
df_1jan.loc[still_nan, '年级_标准'] = df_1jan.loc[still_nan, '学生'].map(student_grade_map)

# 最后,如果年级仍为空,使用默认值四年级
still_nan = df_1jan['年级_标准'].isna()
df_1jan.loc[still_nan, '年级_标准'] = '四年级'

# 定义年级顺序
grade_order = ['一年级', '二年级', '三年级', '四年级', '五年级', '六年级',
               '七年级', '八年级', '九年级', '高一', '高二', '高三', '雅思']

# 定义年级系数
grade_coeff = {
    '一年级': 0.85, '二年级': 0.85, '三年级': 0.85, '四年级': 0.85,
    '五年级': 0.85, '六年级': 0.85,
    '七年级': 0.9, '八年级': 0.9, '九年级': 1.0,
    '高一': 1.1, '高二': 1.25, '高三': 1.35
}

# 定义人数系数(班课)
student_coeff_class = {
    1: 0.8, 2: 1.0, 3: 1.2, 4: 1.4, 5: 1.7,
    6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5, 10: 2.7
}

# 定义人数系数(一对一)
student_coeff_1v1 = {
    1: 0.8,
    2: 1.0
}

# 处理数据
df_processed = df_1jan[['任课老师', '课程所属年级', '课程所属班型', '实到人数', '学科']].copy()
df_processed.columns = ['任课老师', '年级', '课程所属班型', '实到人数', '学科']
df_processed['年级_标准'] = df_1jan['年级_标准']

# 获取年级系数
df_processed['年级系数'] = df_processed['年级_标准'].map(grade_coeff)

# 根据班型获取人数系数
def get_student_coeff(row):
    class_type = row['课程所属班型']
    students = row['实到人数']
    
    if '1对' in str(class_type):
        return student_coeff_1v1.get(students, 0.8)
    else:
        return student_coeff_class.get(students, 1.0)

df_processed['人数系数'] = df_processed.apply(get_student_coeff, axis=1)

# 计算班课绩效
df_processed['班课绩效'] = df_processed['年级系数'] * df_processed['人数系数']

# 一对一课程班课绩效设为0
df_processed.loc[df_processed['课程所属班型'].str.contains('1对', na=False), '班课绩效'] = 0

# 创建工资核对表
def create_wage_table(df):
    # 按学科和老师分组
    teachers = df.groupby(['学科', '任课老师'])
    
    result = []
    
    for (subject, teacher), group in teachers:
        row = {'学科': subject, '任课老师': teacher}
        
        # 统计各年级的一对一次数
        for grade in grade_order:
            filtered = group[group['年级_标准'] == grade]
            one_on_one = filtered[filtered['课程所属班型'].str.contains('1对', na=False)]['实到人数'].sum()
            row[grade] = int(one_on_one)
        
        # 计算一对一总计
        one_on_one_count = group[group['课程所属班型'].str.contains('1对', na=False)]['实到人数'].sum()
        row['一对一总计'] = round(one_on_one_count * 0.8, 1)
        
        # 计算班课绩效
        class_performance = group[~group['课程所属班型'].str.contains('1对', na=False)]['班课绩效'].sum()
        row['班课'] = round(class_performance, 2)
        
        # 填报和差值留空
        row['一对一填报'] = ''
        row['一对一差值'] = ''
        row['班课填报'] = ''
        row['班课差值'] = ''
        
        result.append(row)
    
    return pd.DataFrame(result)

wage_df = create_wage_table(df_processed)

# 重新排列列顺序
columns = ['学科', '任课老师'] + grade_order + ['一对一总计', '一对一填报', '一对一差值', '班课', '班课填报', '班课差值']
wage_df = wage_df[columns]

# 创建Excel文件
output_file = '/Users/macos/WorkBuddy/20260310145718/工资核对表1月.xlsx'

with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
    df_processed.to_excel(writer, sheet_name='排课记录', index=False)
    wage_df.to_excel(writer, sheet_name='工资核对', index=False)

print("工资核对表已保存到:", output_file)

# 格式化Excel并添加公式
wb = load_workbook(output_file)
ws = wb['工资核对']

# 设置边框
thin_border = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)

# 设置列宽
ws.column_dimensions['A'].width = 5
ws.column_dimensions['B'].width = 8
ws.column_dimensions['C'].width = 10
for i in range(4, len(columns)+1):
    col_letter = get_column_letter(i)
    if i < 16:
        ws.column_dimensions[col_letter].width = 8
    elif i == 16:
        ws.column_dimensions[col_letter].width = 10
    elif i == 17 or i == 18:
        ws.column_dimensions[col_letter].width = 8
    elif i == 19:
        ws.column_dimensions[col_letter].width = 10
    elif i == 20 or i == 21:
        ws.column_dimensions[col_letter].width = 8

# 添加公式
for row in range(3, len(wage_df) + 3):
    # 一对一总计 = (小学1-6年级 * 0.85 + 初中7-8年级 * 0.9 + 9年级 * 1 + 高中10-11年级 * 相应系数 + 高三 * 1.35 + 雅思 * 1.5) * 2/3
    formula = f"=(D{row}+E{row}+F{row}+G{row}+H{row}+I{row})/3*2*0.85+(J{row}+K{row})/3*2*0.9+L{row}/3*2*1+M{row}/3*2*1.1+N{row}/3*2*1.25+O{row}/3*2*1.35+P{row}/3*2*1.5"
    ws[f'Q{row}'] = formula
    
    # 班课 = Q列 - R列 (填报)
    ws[f'T{row}'] = f'=Q{row}-R{row}'
    
    # 班课填报 = 系统班课绩效 * 2
    ws[f'U{row}'] = f'=VLOOKUP(C{row},排课记录!A:F,6,0)*2'

# 应用样式到所有单元格
for row in ws.iter_rows():
    for cell in row:
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', vertical='center')

wb.save(output_file)
print("Excel格式化完成,公式已添加")

# 检查还有多少记录没有年级
missing_grade = df_processed[df_processed['年级_标准'].isna()]
print(f"\n仍有 {len(missing_grade)} 条记录没有年级信息")
if len(missing_grade) > 0:
    print("使用默认年级四年级的记录:")
    for idx, row in missing_grade.iterrows():
        print(f"  {row['任课老师']}, {row['课程所属班型']}")
