"""
Check 1: Does Duration cascade through parent-child hierarchy?
Check 2: Which Variance version feeds the GBT — raw magnitude or sign only?
"""
import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime

# ── Load S2P ────────────────────────────────────────────────────────────────
wb = openpyxl.load_workbook('S2P Project.xlsx')
ws = wb['Outokumpu- S2P Project']
rows = list(ws.iter_rows(values_only=True))
df = pd.DataFrame(rows[1:], columns=rows[0]).reset_index(drop=True)

def parse_days(v):
    if v is None: return None
    s = str(v).strip().lower().replace('d','').replace(' ','')
    if s in ('','nan','#unparseable'): return None
    try: return float(s)
    except: return None

df['dur_days']  = df['Duration'].apply(parse_days)
df['Level']     = pd.to_numeric(df['Level'], errors='coerce')

# ── CHECK 1: Duration cascade ────────────────────────────────────────────────
print("=== CHECK 1: Does Duration cascade through hierarchy? ===\n")

# Find parent tasks (Level N) and their immediate children (Level N+1)
# by looking at consecutive rows where Level increases then returns.
# Strategy: for each row with dur_days, find the next same-or-lower-level row
# to define the sibling group.

results = []
for i, row in df.iterrows():
    parent_level = row['Level']
    parent_dur   = row['dur_days']
    parent_name  = row['Task Name']

    if pd.isna(parent_level) or parent_dur is None or parent_dur == 0:
        continue

    child_level = parent_level + 1

    # Collect immediate children: rows between this row and the next
    # row at same or higher level (i.e., next sibling or uncle)
    children = []
    for j in range(i + 1, min(i + 50, len(df))):
        child_row = df.iloc[j]
        cl = child_row['Level']
        if pd.isna(cl):
            continue
        if cl <= parent_level:
            break                     # back to sibling or above
        if cl == child_level:
            cd = child_row['dur_days']
            if cd is not None:
                children.append((child_row['Task Name'], cd))

    if len(children) >= 2:
        child_sum = sum(c[1] for c in children)
        child_max = max(c[1] for c in children)
        results.append({
            'parent':     parent_name,
            'parent_dur': parent_dur,
            'n_children': len(children),
            'child_sum':  child_sum,
            'child_max':  child_max,
            'sum_ratio':  round(parent_dur / child_sum, 3) if child_sum else None,
            'max_ratio':  round(parent_dur / child_max, 3) if child_max else None,
        })

results_df = pd.DataFrame(results).dropna()
print(f"Parent tasks with 2+ children and known Duration: {len(results_df)}")

if len(results_df):
    # Is parent_dur == child_sum (additive)?
    additive = (abs(results_df['sum_ratio'] - 1.0) < 0.05).sum()
    # Is parent_dur == child_max (critical path)?
    cp_like  = (abs(results_df['max_ratio'] - 1.0) < 0.05).sum()
    neither  = len(results_df) - additive - cp_like

    print(f"parent_dur ≈ sum(children):  {additive}/{len(results_df)} ({100*additive//len(results_df)}%)")
    print(f"parent_dur ≈ max(children):  {cp_like}/{len(results_df)} ({100*cp_like//len(results_df)}%)")
    print(f"Neither (cascaded/adjusted): {neither}/{len(results_df)}")
    print()
    print("Sample rows (sum_ratio and max_ratio):")
    print(results_df[['parent','parent_dur','n_children','child_sum','child_max',
                       'sum_ratio','max_ratio']].head(15).to_string())

    print("\nRows where sum_ratio >> 1 (parent larger than sum — cascade suspect):")
    suspect = results_df[results_df['sum_ratio'] > 1.5]
    print(suspect[['parent','parent_dur','child_sum','sum_ratio']].to_string()
          if len(suspect) else "None")

# ── CHECK 2: Which Variance feeds the model? ─────────────────────────────────
print("\n\n=== CHECK 2: GBT feature = raw Variance magnitude or sign? ===\n")
print("In agent/rag_scorer.py, _FEATURE_COLS contains: 'variance_days'")
print("In agent/data_loader.py, variance_days = df['Variance'].apply(_parse_days)")
print("This is the RAW magnitude from the Variance column.")
print()
print("Established earlier: Variance magnitude is unreliable (PM-tool cascaded).")
print("Max observed discrepancy vs computed date delta: 141 days.")
print()
print("Therefore: GBT/SHAP 'variance_days' importance IS driven by")
print("           the corrupted magnitude — not a clean signal.")
print()
print("Fix options:")
print("  A) Replace 'variance_days' with 'variance_sign_code' (-1/0/1) — sign only")
print("  B) Replace with 'actual_minus_planned' (real date delta) — cleaner magnitude")
print("  C) Include both A and B, drop raw variance_days")
print()

# Show distribution of variance_days vs actual_minus_planned in the labeled rows
df['variance_days']       = df['Variance'].apply(parse_days)
df['planned_days']        = df['Duration'].apply(parse_days)

def wd_diff(d1, d2):
    try:
        if pd.isnull(d1) or pd.isnull(d2): return None
        if not (isinstance(d1, datetime) and isinstance(d2, datetime)): return None
        a,b = d1.date(), d2.date()
        sign = 1 if a>=b else -1
        return sign * int(np.busday_count(min(a,b), max(a,b)))
    except: return None

df['actual_elapsed_wd']   = df.apply(lambda r: wd_diff(r['End Date'], r['Start Date']), axis=1)
df['actual_minus_planned'] = df.apply(
    lambda r: r['actual_elapsed_wd'] - r['planned_days']
    if (r['actual_elapsed_wd'] is not None and r['planned_days'] is not None) else None, axis=1)

labeled = df[df['RAG'].isin(['Green','Yellow','Red'])].copy()
print(f"Labeled task rows: {len(labeled)}")
print(f"variance_days non-null: {labeled['variance_days'].notna().sum()}")
print(f"actual_minus_planned non-null: {labeled['actual_minus_planned'].notna().sum()}")
print()
corr_vd  = labeled[['variance_days']].corrwith(labeled['actual_minus_planned'].rename('amp'))
print(f"Correlation between variance_days and actual_minus_planned: "
      f"{labeled['variance_days'].corr(labeled['actual_minus_planned']):.3f}")
print("(Low correlation confirms they measure different things)")
