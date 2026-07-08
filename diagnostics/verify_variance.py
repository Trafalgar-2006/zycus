import openpyxl
import pandas as pd
from datetime import datetime
import numpy as np

wb1 = openpyxl.load_workbook('S2P Project.xlsx')
ws1 = wb1['Outokumpu- S2P Project']
rows1 = list(ws1.iter_rows(values_only=True))
df1 = pd.DataFrame(rows1[1:], columns=rows1[0])

def parse_var(v):
    if v is None or v == '0': return 0
    s = str(v).replace('d','').strip()
    try: return int(float(s))
    except: return None

def calendar_diff(d1, d2):
    if isinstance(d1, datetime) and isinstance(d2, datetime):
        return (d1 - d2).days
    return None

def working_day_diff(d1, d2):
    """d1 - d2 in working days. Positive = d1 is later (later end date)."""
    if not (isinstance(d1, datetime) and isinstance(d2, datetime)):
        return None
    d1_date = d1.date()
    d2_date = d2.date()
    if d1_date >= d2_date:
        return int(np.busday_count(d2_date, d1_date))
    else:
        return -int(np.busday_count(d1_date, d2_date))

# Build comparison frame
df_check = df1[['Task Name','Status','End Date','Baseline Finish','Variance','RAG']].copy()
df_check = df_check.dropna(subset=['End Date','Baseline Finish','Variance'])
df_check['var_days'] = df_check['Variance'].apply(parse_var)
df_check = df_check[df_check['var_days'] != 0].dropna(subset=['var_days'])

df_check['cal_delta']  = df_check.apply(lambda r: calendar_diff(r['End Date'], r['Baseline Finish']), axis=1)
df_check['work_delta'] = df_check.apply(lambda r: working_day_diff(r['End Date'], r['Baseline Finish']), axis=1)
df_check = df_check.dropna(subset=['cal_delta','work_delta'])

# Convention being tested: Variance = Baseline Finish - End Date (in working days)
# So var_days = -work_delta
# Sign agreement: sign(var_days) should equal sign(-work_delta)
df_check['cal_sign_ok']  = ((df_check['cal_delta']  >= 0) == (df_check['var_days'] >= 0))
df_check['work_sign_ok'] = ((df_check['work_delta'] >= 0) == (-df_check['var_days'] >= 0))

print("=== OVERALL COUNTS ===")
print(f"Total rows checked:          {len(df_check)}")
print(f"Calendar sign agrees:        {df_check['cal_sign_ok'].sum()} / {len(df_check)}")
print(f"Working-day sign agrees:     {df_check['work_sign_ok'].sum()} / {len(df_check)}")

# The 3 rows that DID agree under calendar check
cal_agree = df_check[df_check['cal_sign_ok']]
print(f"\n=== Exact 3 rows that agreed under calendar-day check ===")
cols = ['Task Name','Status','End Date','Baseline Finish','cal_delta','work_delta','var_days','RAG']
print(cal_agree[cols].to_string())

print(f"\nDo those same 3 agree under working-day check?")
print(cal_agree[['Task Name','var_days','work_delta','work_sign_ok']].to_string())

# Working-day failures
work_fail = df_check[~df_check['work_sign_ok']]
print(f"\n=== Rows STILL failing after working-day correction: {len(work_fail)} ===")
if len(work_fail) > 0:
    print(work_fail[cols].head(20).to_string())
    # Check magnitude match for sign-agreeing rows
    work_ok = df_check[df_check['work_sign_ok']].copy()
    work_ok['expected_var'] = -work_ok['work_delta']
    work_ok['mag_diff'] = abs(work_ok['var_days'] - work_ok['expected_var'])
    print(f"\nMagnitude match for working-day-agreeing rows:")
    print(f"  Exact magnitude match (diff=0): {(work_ok['mag_diff']==0).sum()} / {len(work_ok)}")
    print(f"  Within 1 day:                   {(work_ok['mag_diff']<=1).sum()} / {len(work_ok)}")
    print(f"  Within 2 days:                  {(work_ok['mag_diff']<=2).sum()} / {len(work_ok)}")
    print(f"  Max diff:                        {work_ok['mag_diff'].max()}")
else:
    print("None remaining — working-day correction resolves all discrepancies.")
    # Check magnitudes
    df_check['expected_var'] = -df_check['work_delta']
    df_check['mag_diff'] = abs(df_check['var_days'] - df_check['expected_var'])
    print(f"\nMagnitude match check (sign-resolved rows):")
    print(f"  Exact match (diff=0): {(df_check['mag_diff']==0).sum()} / {len(df_check)}")
    print(f"  Within 1 day:         {(df_check['mag_diff']<=1).sum()} / {len(df_check)}")
    print(f"  Within 2 days:        {(df_check['mag_diff']<=2).sum()} / {len(df_check)}")
    print(f"  Max diff:             {df_check['mag_diff'].max()}")
    print(f"\nRows with mag_diff > 2:")
    print(df_check[df_check['mag_diff']>2][['Task Name','var_days','expected_var','mag_diff','RAG']].head(10).to_string())
