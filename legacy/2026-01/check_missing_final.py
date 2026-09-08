import pandas as pd

# 读取1月排课记录
file_1jan = '/Users/macos/WorkBuddy/20260310145718/排课记录-01月05日到02月01日_202603101526.xlsx'
df_1jan = pd.read_excel(file_1jan)

# 查看没有年级的记录
missing = df_1jan[df_1jan['课程所属年级'].isna()]
print(f"没有年级信息的记录数量: {len(missing)}")
print("\n记录样本:")
print(missing[['班级名称', '任课老师']].head(20))
