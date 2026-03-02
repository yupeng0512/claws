"""
Pipeline State Machine — 断点恢复 + Phase 前置条件检查 + 失败重试。

持久化每日 Pipeline 执行状态到 memory/state/<date>.json，
支持 Phase 级断点恢复和最多 MAX_RETRIES 次自动重试。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("CLAWS.state")

CST = timezone(timedelta(hours=8))
MAX_RETRIES = 3

PHASE_ORDER = ["sense", "dive", "reflect", "review"]
PHASE_DEPS = {
    "sense": [],
    "dive": ["sense"],
    "reflect": ["sense"],
    "review": ["reflect"],
}


@dataclass
class PhaseState:
    status: str = "pending"  # pending | running | success | failed | skipped
    attempts: int = 0
    last_error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass
class DayState:
    date: str = ""
    phases: dict[str, dict] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def get_phase(self, name: str) -> PhaseState:
        raw = self.phases.get(name, {})
        return PhaseState(**{k: v for k, v in raw.items() if k in PhaseState.__dataclass_fields__})

    def set_phase(self, name: str, state: PhaseState) -> None:
        self.phases[name] = asdict(state)
        self.updated_at = datetime.now(CST).isoformat()


class PipelineStateManager:
    """Manages daily pipeline execution state with JSON persistence."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, date: str) -> Path:
        return self.state_dir / f"{date}.json"

    def _load(self, date: str) -> DayState:
        path = self._state_path(date)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return DayState(**{k: v for k, v in raw.items() if k in DayState.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                log.warning(f"状态文件损坏，重新创建: {path}")
        return DayState(
            date=date,
            created_at=datetime.now(CST).isoformat(),
            updated_at=datetime.now(CST).isoformat(),
        )

    def _save(self, state: DayState) -> None:
        path = self._state_path(state.date)
        path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")

    def _today(self) -> str:
        return datetime.now(CST).strftime("%Y-%m-%d")

    def can_run(self, phase: str, date: str = "") -> tuple[bool, str]:
        """Check if a phase can run: dependencies met and retry limit not exceeded."""
        date = date or self._today()
        state = self._load(date)
        ps = state.get_phase(phase)

        if ps.status == "running":
            return False, f"{phase} 正在运行中"

        if ps.attempts >= MAX_RETRIES and ps.status == "failed":
            return False, f"{phase} 已失败 {ps.attempts} 次，超过重试上限 {MAX_RETRIES}"

        for dep in PHASE_DEPS.get(phase, []):
            dep_ps = state.get_phase(dep)
            if dep_ps.status not in ("success", "skipped"):
                return True, f"依赖 {dep} 未完成 (状态: {dep_ps.status})，将使用回退数据"

        return True, "ok"

    def mark_running(self, phase: str, date: str = "") -> None:
        date = date or self._today()
        state = self._load(date)
        ps = state.get_phase(phase)
        ps.status = "running"
        ps.attempts += 1
        ps.started_at = datetime.now(CST).isoformat()
        ps.last_error = None
        state.set_phase(phase, ps)
        self._save(state)
        log.info(f"[状态] {phase} -> running (第 {ps.attempts} 次)")

    def mark_success(self, phase: str, date: str = "") -> None:
        date = date or self._today()
        state = self._load(date)
        ps = state.get_phase(phase)
        ps.status = "success"
        ps.finished_at = datetime.now(CST).isoformat()
        state.set_phase(phase, ps)
        self._save(state)
        log.info(f"[状态] {phase} -> success")

    def mark_failed(self, phase: str, error: str, date: str = "") -> None:
        date = date or self._today()
        state = self._load(date)
        ps = state.get_phase(phase)
        ps.status = "failed"
        ps.last_error = error[:500]
        ps.finished_at = datetime.now(CST).isoformat()
        state.set_phase(phase, ps)
        self._save(state)
        log.warning(f"[状态] {phase} -> failed (第 {ps.attempts} 次): {error[:100]}")

    def mark_skipped(self, phase: str, reason: str, date: str = "") -> None:
        date = date or self._today()
        state = self._load(date)
        ps = state.get_phase(phase)
        ps.status = "skipped"
        ps.last_error = reason[:200]
        ps.finished_at = datetime.now(CST).isoformat()
        state.set_phase(phase, ps)
        self._save(state)
        log.info(f"[状态] {phase} -> skipped: {reason[:100]}")

    def get_today_summary(self) -> dict:
        """Get a summary of today's pipeline execution for stats injection."""
        date = self._today()
        state = self._load(date)
        summary = {}
        for phase in PHASE_ORDER:
            ps = state.get_phase(phase)
            summary[phase] = {
                "status": ps.status,
                "attempts": ps.attempts,
                "error": ps.last_error,
            }
        return summary

    def get_week_stats(self) -> dict:
        """Aggregate stats over the past 7 days for self-evolution."""
        now = datetime.now(CST)
        stats = {"total_runs": 0, "successes": 0, "failures": 0, "by_phase": {}}

        for phase in PHASE_ORDER:
            stats["by_phase"][phase] = {"success": 0, "fail": 0, "skip": 0, "avg_attempts": 0.0}

        attempts_acc: dict[str, list[int]] = {p: [] for p in PHASE_ORDER}

        for i in range(7):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            state = self._load(date)
            for phase in PHASE_ORDER:
                ps = state.get_phase(phase)
                if ps.status == "pending":
                    continue
                stats["total_runs"] += 1
                if ps.status == "success":
                    stats["successes"] += 1
                    stats["by_phase"][phase]["success"] += 1
                elif ps.status == "failed":
                    stats["failures"] += 1
                    stats["by_phase"][phase]["fail"] += 1
                elif ps.status == "skipped":
                    stats["by_phase"][phase]["skip"] += 1
                if ps.attempts > 0:
                    attempts_acc[phase].append(ps.attempts)

        for phase in PHASE_ORDER:
            arr = attempts_acc[phase]
            if arr:
                stats["by_phase"][phase]["avg_attempts"] = round(sum(arr) / len(arr), 1)

        if stats["total_runs"] > 0:
            stats["success_rate"] = round(stats["successes"] / stats["total_runs"] * 100, 1)
        else:
            stats["success_rate"] = 0.0

        return stats

    def find_latest_successful(self, phase: str, lookback_days: int = 7) -> Optional[str]:
        """Find the most recent date where a phase completed successfully.
        Used for fallback data when a dependency hasn't run today."""
        now = datetime.now(CST)
        for i in range(lookback_days):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            state = self._load(date)
            ps = state.get_phase(phase)
            if ps.status == "success":
                return date
        return None
