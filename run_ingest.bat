@echo off
REM ============================================================
REM Automated ingest runner for the Innovation Radar pipeline.
REM Meant to be triggered by Windows Task Scheduler, not run by
REM hand -- if you want a one-off manual run, just use
REM "python -m pipeline.ingest" directly from an activated venv.
REM
REM What this does:
REM   1. Moves to the project root (edit PROJECT_DIR if you move
REM      the repo).
REM   2. Activates the venv.
REM   3. Runs the ingest step and appends console output to a
REM      timestamped log file under logs\, so you can check what
REM      happened without watching it live.
REM
REM Setup (Task Scheduler), see instructions below the script.
REM ============================================================

set PROJECT_DIR=E:\Becode\Orange_use_case
set LOG_DIR=%PROJECT_DIR%\logs

REM Create the logs folder if it doesn't exist yet
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Build a timestamped log filename, e.g. logs\ingest_2026-08-19_0600.log
REM (locale-safe-ish: relies on %date%/%time% format, which can vary by
REM Windows locale -- if the filename looks wrong on your machine, this
REM line is the one to adjust, everything else is unaffected)
set TIMESTAMP=%date:~-4%-%date:~3,2%-%date:~0,2%_%time:~0,2%%time:~3,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG_FILE=%LOG_DIR%\ingest_%TIMESTAMP%.log

cd /d "%PROJECT_DIR%"
call .venv\Scripts\activate.bat

echo ============================================== >> "%LOG_FILE%"
echo Ingest run started: %date% %time% >> "%LOG_FILE%"
echo ============================================== >> "%LOG_FILE%"

python -m pipeline.ingest >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo Ingest run finished: %date% %time% >> "%LOG_FILE%"

REM Optional: keep only the last 30 log files so logs\ doesn't grow forever.
REM Comment this out if you'd rather keep everything.
forfiles /p "%LOG_DIR%" /m ingest_*.log /d -30 /c "cmd /c del @path" 2>nul