import pandas as pd

for fname, label, sheet in [('S2P Project.xlsx','S2P','Outokumpu- S2P Project'), ('Project Plan B.xlsx','UniSan','Project Plan')]:
    df = pd.ExcelFile(fname).parse(sheet)
    print(f'--- {label} ---')
    print(f'Shape: {df.shape}')
    # Ancestors sample
    anc = df['Ancestors'].dropna().head(5).tolist() if 'Ancestors' in df.columns else 'N/A'
    print(f'Ancestors sample: {anc}')
    # Numeric potential ID cols
    numeric_cols = [c for c in df.columns if str(df[c].dtype).startswith('int') or str(df[c].dtype).startswith('float')]
    print(f'Numeric cols: {numeric_cols[:8]}')
    pred_col = [c for c in df.columns if 'pred' in str(c).lower()][0]
    print(f'Predecessors dtype: {df[pred_col].dtype}')
    # Show index alongside predecessors to understand mapping
    pred_rows = df[df[pred_col].notna()][['Task Name', pred_col]].head(8)
    print(pred_rows.to_string())
    print()
