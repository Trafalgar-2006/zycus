"""Diagnostic: trace exactly what score_project produces and why."""
import sys, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '.')
from agent.data_loader import load_all_projects
from agent.rag_scorer import _forward_risk, _historical_slip
import config

dfs = load_all_projects(config.PROJECT_FILES)

for name, df in dfs.items():
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    # Status breakdown
    print("\nStatus value_counts:")
    print(df['Status'].value_counts())
    
    print("\nRAG value_counts:")
    print(df['RAG'].value_counts())

    print("\nis_critical value_counts:")
    print(df['is_critical'].value_counts())

    # Forward risk trace
    active_statuses = {"In Progress", "Not Started"}
    active = df[df['Status'].isin(active_statuses)]
    crit_active = df[df['is_critical'] & df['Status'].isin(active_statuses)]
    
    print(f"\nActive tasks (In Progress + Not Started): {len(active)}")
    print(f"Critical+Active tasks: {len(crit_active)}")
    
    if len(crit_active) < config.MIN_CRITICAL_N:
        pool = active
        print(f"  -> Fallback: using all {len(active)} active tasks")
    else:
        pool = crit_active
        
    if len(pool):
        red_n   = (pool['RAG'] == 'Red').sum()
        amb_n   = pool['RAG'].isin(['Yellow','Amber']).sum()
        fwd     = red_n/len(pool) + 0.5*amb_n/len(pool)
        print(f"  Red={red_n}, Amber/Yellow={amb_n}, total={len(pool)}")
        print(f"  forward_risk = {fwd:.4f}")

    # Historical slip trace
    done = df[
        (~df['Status'].isin(active_statuses)) &
        (df['Status'] != 'Not Applicable')
    ]
    crit_done = df[
        df['is_critical'] &
        (~df['Status'].isin(active_statuses)) &
        (df['Status'] != 'Not Applicable')
    ]
    print(f"\nCompleted/non-active tasks: {len(done)}")
    print(f"Critical+Done tasks: {len(crit_done)}")
    
    pool2 = crit_done if len(crit_done) >= config.MIN_CRITICAL_N else done

    print(f"\nvariance_sign in pool:")
    print(pool2['variance_sign'].value_counts())
    
    print(f"\nactual_minus_planned null count in pool: {pool2['actual_minus_planned'].isna().sum()} / {len(pool2)}")
    print(f"variance_days null count in pool: {pool2['variance_days'].isna().sum()} / {len(pool2)}")

    late_with_amp = pool2[
        (pool2['variance_sign'] == 'late') &
        pool2['actual_minus_planned'].notna()
    ]
    late_with_vd = pool2[pool2['variance_sign'] == 'late']
    
    print(f"\nLate tasks with actual_minus_planned: {len(late_with_amp)}")
    print(f"Late tasks with variance_days: {len(late_with_vd)}")
    
    if not late_with_amp.empty:
        med = late_with_amp['actual_minus_planned'].clip(lower=0).median()
        slip = min(med / config.SLIP_CEILING_DAYS, 1.0)
        print(f"  median actual_minus_planned (late): {med:.2f}d -> slip={slip:.4f}")
    elif not late_with_vd.empty:
        med = late_with_vd['variance_days'].abs().median()
        slip = min(med / config.SLIP_CEILING_DAYS, 1.0)
        print(f"  median variance_days abs (late): {med:.2f}d -> slip={slip:.4f}")
    else:
        print("  -> historical_slip = 0.0 (no late tasks)")

    # Sample: show 5 late tasks
    if not late_with_vd.empty:
        sample = late_with_vd[['Task Name','Status','variance_sign','variance_days',
                                'actual_minus_planned']].head(5)
        print("\nSample late tasks:")
        print(sample.to_string())

    # Check actual_minus_planned values in detail  
    print(f"\nSample actual_minus_planned (all completed, first 10):")
    done_sample = done[done['actual_minus_planned'].notna()][
        ['Task Name','Status','Start Date','End Date','planned_days',
         'actual_elapsed_wd','actual_minus_planned']
    ].head(10)
    print(done_sample.to_string())
