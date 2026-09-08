import pandas as pd

# 读取1月排课记录
file_1jan = '/Users/macos/WorkBuddy/20260310145718/排课记录-01月05日到02月01日_202603101526.xlsx'
df_1jan = pd.read_excel(file_1jan)

# 从班级名称提取学科
def extract_subject_from_class(class_name):
    # 格式: 六年级1v1_王语诺(03-英语)
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

# 测试提取
df_1jan['学科'] = df_1jan['班级名称'].apply(extract_subject_from_class)

print("学科提取结果:")
print(df_1jan[['班级名称', '学科']].head(30))
print("\n")

print("学科分布:")
print(df_1jan['学科'].value_counts())
print("\n")

print("没有提取到学科的数量:", df_1jan['学科'].isna().sum())
print("没有提取到学科的记录:")
print(df_1jan[df_1jan['学科'].isna()][['班级名称', '课程名称']])
