"""
scheduler.py — Weekly schedule runner.
Runs the full agent pipeline every Monday at 08:00 (configurable in config.py).
"""
from __future__ import annotations

import time
from datetime import datetime

import schedule as sched

import config
from main import run_all


def _job():
    print(f"\n⏰ Scheduled run triggered at {datetime.now().isoformat()}")
    try:
        run_all()
    except Exception as exc:
        print(f"❌ Scheduled run failed: {exc}")


def start():
    print(f"📅 Scheduler active — runs every {config.WEEKLY_RUN_DAY} at {config.WEEKLY_RUN_TIME}")
    print("   Press Ctrl+C to stop.\n")

    getattr(sched.every(), config.WEEKLY_RUN_DAY).at(config.WEEKLY_RUN_TIME).do(_job)

    # Run immediately on startup so you can verify it works
    print("▶️  Running once immediately on startup...")
    _job()

    while True:
        sched.run_pending()
        time.sleep(60)
