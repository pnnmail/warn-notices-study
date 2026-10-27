@echo off
REM Daily live collection (Windows Task Scheduler).
cd /d %~dp0
set PYTHONIOENCODING=utf-8
python live_collect.py >> logs\run_daily.out 2>&1
