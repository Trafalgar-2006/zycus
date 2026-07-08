import sys, warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
from agent.data_loader import load_all_projects
import config

dfs = load_all_projects(config.PROJECT_FILES)
for name, df in dfs.items():
    print(f'\n=== {name} ===')
    rag_cols = [c for c in df.columns if 'RAG' in c.upper() or 'AT' in c.upper() or 'RISK' in c.upper()]
    print('Relevant columns:', rag_cols)
    for c in rag_cols:
        vc = df[c].value_counts()
        if len(vc):
            print(f'  {c}:', vc.to_dict())

    in_prog = int((df['Status'] == 'In Progress').sum())
    print(f'In Progress tasks: {in_prog}')
    
    leaf = df[df['planned_days'].notna() & (df['planned_days'] <= 45) &
              ~df['Status'].isin(['Completed', 'Not Applicable'])].copy()
    remaining = leaf['planned_days'].mul(1 - leaf['pct_complete'].fillna(0)).sum()
    calendar_serial = remaining * 7 / 5
    concurrency = max(in_prog, 1)
    calendar_parallel = calendar_serial / concurrency
    print(f'Leaf active tasks (<=45d): {len(leaf)}, serial remaining: {remaining:.0f} wd')
    print(f'  -> serial calendar: {calendar_serial:.0f}d = {calendar_serial/365:.1f}yr')
    print(f'  -> parallel calendar (/{concurrency} concurrent): {calendar_parallel:.0f}d = {calendar_parallel/365:.1f}yr')
