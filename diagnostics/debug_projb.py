import openpyxl, pandas as pd

wb = openpyxl.load_workbook('Project Plan B.xlsx')
ws = wb['Project Plan']
rows = list(ws.iter_rows(values_only=True))
headers = [str(h) if h is not None else f'_col{i}' for i, h in enumerate(rows[0])]
df = pd.DataFrame(rows[1:], columns=headers)

print('Schedule Health value_counts:')
print(df['Schedule Health'].value_counts())

print('\nAt Risk? value_counts:')
print(df['At Risk?'].value_counts())

sh_unique = df['Schedule Health'].dropna().unique()
print('\nAll unique Schedule Health values:', sh_unique[:15])

print('\nStatus value_counts:')
print(df['Status'].value_counts())

# Cross-check: At Risk? = True rows that have Schedule Health
risk_rows = df[df['At Risk?'] == True]
print(f'\nAt Risk=True rows: {len(risk_rows)}')
print(risk_rows['Schedule Health'].value_counts())
