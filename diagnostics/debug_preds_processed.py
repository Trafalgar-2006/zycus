"""Debug: check what columns + predecessor data looks like AFTER data_loader processes the files."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from agent.data_loader import load_all_projects

dfs = load_all_projects(config.PROJECT_FILES)
for name, df in dfs.items():
    print(f"\n=== {name} ===")
    print(f"Shape: {df.shape}")
    # Find predecessor-like columns
    pred_cols = [c for c in df.columns if 'pred' in str(c).lower()]
    print(f"Predecessor cols: {pred_cols}")
    if pred_cols:
        p = pred_cols[0]
        non_null = df[p].notna().sum()
        print(f"  {p}: {non_null}/{len(df)} non-null ({non_null/len(df)*100:.1f}%)")
        print(f"  Sample values: {df[p].dropna().head(5).tolist()}")
    # Check if original column names survived or were renamed
    orig_check = [c for c in df.columns if 'Pred' in str(c)]
    print(f"  Orig-case Pred cols: {orig_check}")
    # Show all columns
    print(f"  All columns: {list(df.columns)}")
