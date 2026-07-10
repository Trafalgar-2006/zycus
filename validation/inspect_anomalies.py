import openpyxl
import pandas as pd
from datetime import datetime
import numpy as np

wb1 = openpyxl.load_workbook('S2P Project.xlsx')
ws1 = wb1['Outokumpu- S2P Project']
rows1 = list(ws1.iter_rows(values_only=True))
df1 = pd.DataFrame(rows1[1:], columns=rows1[0])

def working_day_diff(d1, d2):
    """d1 - d2 in working days. Positive = d1 is later."""
    try:
        if not (isinstance(d1, datetime) and isinstance(d2, datetime)):
            return None
        if pd.isnull(d1) or pd.isnull(d2):
            return None
        d1d, d2d = d1.date(), d2.date()
        if d1d >= d2d:
            return int(np.busday_count(d2d, d1d))
        else:
            return -int(np.busday_count(d1d, d2d))
    except Exception:
        return None

anomaly_tasks = [
    'Onsite- Design Session-Design Session Completion and Sign off',
    'User Setup',
    'Production Deployment & Readiness-Migrate Solution from Staging to Prodcution'
]

print("=== DEEP DIVE: 3 ANOMALOUS ROWS ===\n")
for name in anomaly_tasks:
    rows = df1[df1['Task Name'] == name]
    if len(rows) == 0:
        print(f"NOT FOUND: {name}")
        continue
    r = rows.iloc[0]
    var_val = r['Variance']
    
    sd_diff = working_day_diff(r['Start Date'], r['Baseline Start'])
    ed_diff = working_day_diff(r['End Date'], r['Baseline Finish'])
    
    print(f"Task: {name}")
    print(f"  Status:          {r['Status']}")
    print(f"  RAG:             {r['RAG']}")
    print(f"  Start Date:      {r['Start Date']}")
    print(f"  Baseline Start:  {r['Baseline Start']}")
    print(f"  End Date:        {r['End Date']}")
    print(f"  Baseline Finish: {r['Baseline Finish']}")
    print(f"  Variance col:    {var_val}")
    print(f"  EndDate - BaselineFinish (wd): {ed_diff}  [+ = late]")
    print(f"  StartDate - BaselineStart (wd): {sd_diff}  [+ = started late]")
    # Is variance = start-date delta?
    print(f"  Does Variance match start-delta? {sd_diff}")
    print(f"  Does Variance match end-delta?   {ed_diff}")
    print()

# Also check magnitude distribution for the 196 agreeing rows
print("\n=== MAGNITUDE MATCH DETAIL for 196 agreeing rows ===")

def parse_var(v):
    if v is None or v == '0': return 0
    s = str(v).replace('d', '').strip()
    try: return int(float(s))
    except: return None

df_check = df1[['Task Name', 'Status', 'End Date', 'Baseline Finish', 'Baseline Start', 'Start Date', 'Variance', 'RAG']].copy()
df_check = df_check.dropna(subset=['End Date', 'Baseline Finish', 'Variance'])
df_check['var_days'] = df_check['Variance'].apply(parse_var)
df_check = df_check[df_check['var_days'] != 0].dropna(subset=['var_days'])
df_check['work_delta'] = df_check.apply(lambda r: working_day_diff(r['End Date'], r['Baseline Finish']), axis=1)
df_check = df_check.dropna(subset=['work_delta'])

# Sign agreement under convention: var = -(End-Baseline) = Baseline-End
df_check['work_sign_ok'] = ((df_check['work_delta'] >= 0) == (-df_check['var_days'] >= 0))
ok = df_check[df_check['work_sign_ok']].copy()
ok['expected_var'] = -ok['work_delta']
ok['mag_diff'] = abs(ok['var_days'] - ok['expected_var'])

print(f"Sign-agreeing rows: {len(ok)}")
print(f"Exact magnitude match (diff=0): {(ok['mag_diff']==0).sum()}")
print(f"Within 1 day:                   {(ok['mag_diff']<=1).sum()}")
print(f"Within 2 days:                  {(ok['mag_diff']<=2).sum()}")
print(f"Max diff:                       {ok['mag_diff'].max()}")
print("\nRows with mag_diff > 10 (showing top 10):")
big_diff = ok[ok['mag_diff'] > 10].sort_values('mag_diff', ascending=False)
print(big_diff[['Task Name', 'Status', 'var_days', 'expected_var', 'mag_diff', 'RAG']].head(10).to_string())
