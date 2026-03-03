"""
CLAWS Admin API Server
======================

FastAPI-based HTTP API for managing CLAWS pipeline.
Provides status, discoveries, schedule, memory search, manual trigger, and log access.
Dashboard frontend is served as static files.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from claws_runner import ClawsPipeline, ScheduleConfig
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

CST = timezone(timedelta(hours=8))
ROOT = Path(__file__).parent
MEMORY_DIR = ROOT / "memory"
LOG_DIR = ROOT / "logs"
DASHBOARD_DIR = ROOT / "dashboard"

log = logging.getLogger("CLAWS.API")


def create_app(
    pipeline: "ClawsPipeline",
    scheduler: "AsyncIOScheduler",
    schedule_cfg: dict[str, "ScheduleConfig"],
) -> FastAPI:
    app = FastAPI(title="CLAWS Admin API", version="1.0.0")

    # ── Static files ──
    if DASHBOARD_DIR.exists():
        assets_dir = DASHBOARD_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        index = DASHBOARD_DIR / "index.html"
        if not index.exists():
            raise HTTPException(404, "Dashboard not deployed")
        return FileResponse(str(index))

    # ── Health ──

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "time": datetime.now(CST).isoformat()}

    # ── Status ──

    @app.get("/api/status")
    async def status():
        today_summary = pipeline.state.get_today_summary()
        jobs_info = []
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs_info.append({"id": job.id, "name": job.name, "next_run": next_run})

        recent_runs = pipeline._run_history[-20:]

        memory_stats = _memory_stats()

        return {
            "pipeline": today_summary,
            "scheduler": {"running": scheduler.running, "jobs": jobs_info},
            "recent_runs": recent_runs,
            "memory": memory_stats,
            "time": datetime.now(CST).isoformat(),
        }

    # ── Discoveries ──

    @app.get("/api/discoveries")
    async def discoveries(date: str = Query(None, description="Filter by date YYYY-MM-DD")):
        disc_path = MEMORY_DIR / "DISCOVERIES.md"
        if not disc_path.exists():
            return {"items": [], "total": 0}

        content = disc_path.read_text(encoding="utf-8")
        items = _parse_discoveries(content)

        if date:
            items = [i for i in items if i.get("date") == date]

        return {"items": items, "total": len(items)}

    @app.get("/api/discoveries/today")
    async def discoveries_today():
        today = datetime.now(CST).strftime("%Y-%m-%d")
        filtered = _read_dir_by_date("filtered", today)
        deep_dives = _read_dir_by_date("deep-dives", today)
        return {"date": today, "filtered": filtered, "deep_dives": deep_dives}

    # ── Schedule ──

    @app.get("/api/schedule")
    async def schedule():
        result = {}
        for phase, cfg in schedule_cfg.items():
            job = scheduler.get_job(phase)
            next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
            result[phase] = {
                "agent": cfg.agent,
                "interval_hours": cfg.interval_hours,
                "cron": cfg.cron,
                "retention_days": cfg.retention_days,
                "next_run": next_run,
            }
        return result

    # ── Manual Trigger ──

    @app.post("/api/trigger/{phase}")
    async def trigger(phase: str):
        phases = {
            "sense": pipeline.run_sense, "dive": pipeline.run_dive,
            "reflect": pipeline.run_reflect, "review": pipeline.run_review,
            "weekly": pipeline.run_weekly,
        }
        runner = phases.get(phase)
        if not runner:
            raise HTTPException(400, f"Unknown phase: {phase}. Valid: {list(phases.keys())}")

        asyncio.create_task(runner())
        log.info(f"Manual trigger: {phase}")
        return {"status": "triggered", "phase": phase, "time": datetime.now(CST).isoformat()}

    # ── Memory ──

    @app.get("/api/memory/search")
    async def memory_search(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=20)):
        results = pipeline.memory.search(q, top_k=top_k)
        return {"query": q, "results": results, "total": len(results)}

    @app.get("/api/memory/stats")
    async def memory_stats():
        return _memory_stats()

    # ── Config ──

    @app.get("/api/config")
    async def config():
        yaml_path = ROOT / "config" / "agents.yaml"
        if not yaml_path.exists():
            raise HTTPException(404, "agents.yaml not found")
        return {"content": yaml_path.read_text(encoding="utf-8")}

    # ── Logs ──

    @app.get("/api/logs/recent")
    async def logs_recent(lines: int = Query(100, ge=10, le=500)):
        log_path = LOG_DIR / "claws.log"
        if not log_path.exists():
            return {"lines": [], "total": 0}
        all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = all_lines[-lines:]
        return {"lines": tail, "total": len(all_lines)}

    return app


# ── Helpers ──

def _memory_stats() -> dict[str, Any]:
    subdirs = ["raw", "filtered", "deep-dives", "reflections", "reviews", "feedback", "state"]
    stats: dict[str, Any] = {}
    total_files = 0
    total_size = 0
    for sd in subdirs:
        d = MEMORY_DIR / sd
        if not d.exists():
            stats[sd] = {"files": 0, "size_kb": 0, "latest": None}
            continue
        files = list(d.iterdir())
        size = sum(f.stat().st_size for f in files if f.is_file())
        latest = max((f.stat().st_mtime for f in files if f.is_file()), default=0)
        latest_str = datetime.fromtimestamp(latest, CST).isoformat() if latest else None
        stats[sd] = {"files": len(files), "size_kb": round(size / 1024, 1), "latest": latest_str}
        total_files += len(files)
        total_size += size
    stats["_total"] = {"files": total_files, "size_kb": round(total_size / 1024, 1)}
    return stats


def _parse_discoveries(content: str) -> list[dict]:
    items = []
    current: dict[str, str] | None = None
    for line in content.split("\n"):
        m = re.match(r"^### \[(\d{4}-\d{2}-\d{2})\]\s*(.+)", line)
        if m:
            if current:
                items.append(current)
            current = {"date": m.group(1), "title": m.group(2).strip(), "fields": {}}
            continue
        if current and line.startswith("- "):
            kv = line[2:].split(":", 1)
            if len(kv) == 2:
                current["fields"][kv[0].strip()] = kv[1].strip()
    if current:
        items.append(current)
    return items


def _read_dir_by_date(subdir: str, date: str) -> list[dict]:
    d = MEMORY_DIR / subdir
    if not d.exists():
        return []
    results = []
    for f in sorted(d.iterdir()):
        if date in f.name:
            results.append({"file": f.name, "content": f.read_text(encoding="utf-8")})
    return results
