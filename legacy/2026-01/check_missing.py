import pandas as pd

# 读取1月排课记录
file_1jan = '/Users/macos/WorkBuddy/20260310145718/排课记录-01月05日到02月01日_202603101526.xlsx'
df_1jan = pd.read_excel(file_1jan)

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

df_1jan['学科'] = df_1jan['班级名称'].apply(extract_subject_from_class)

# 检查年级为空的记录
nan_grade = df_1jan[df_1jan['课程所属年级'].isna()]
print("没有年级信息的记录数量:", len(nan_grade))
if len(nan_grade) > 0:
    print("\n没有年级信息的记录:")
    print(nan_grade[['班级名称', '课程名称', '任课老师', '课程所属班型', '学科']].to_string())

# 检查学科为空的记录
nan_subject = df_1jan[df_1jan['学科'].isna()]
print("\n\n没有学科信息的记录数量:", len(nan_subject))
if len(nan_subject) > 0:
    print("\n没有学科信息的记录:")
    print(nan_subject[['班级名称', '课程名称', '任课老师']].to_string())
