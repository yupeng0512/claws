#!/usr/bin/env python3
"""
CLAWS Runner v2 — Continuous Learning And Working System
=========================================================

基于 Knot Agent (AG-UI) 的自主探索系统。
一主多从 Pipeline 架构，品味自进化。

架构（参考 alpha-radar Pipeline 模式）:

  本地调度器 (APScheduler)
       │
       ├── Phase 1: Scout (侦察兵)
       │   ├── deepseek-v3.2 + web search
       │   └── 快速扫描 + 品味过滤
       │
       ├── Phase 2: Analyst (分析师)
       │   ├── claude-4.5-sonnet + web search
       │   └── 深度研究 + 结构化报告
       │
       ├── Phase 3: Evolve (进化者)
       │   ├── claude-4.5-sonnet
       │   └── 反思 + 品味自进化
       │
       └── Phase 4: Reviewer (审查者)
           ├── claude-4.5-sonnet + web search
           └── 独立审计 + 商业评估 + 盲区检测

自进化机制:
  Evolve agent 输出 JSON → Runner 写入:
  - TASTE.md   (品味模型)
  - SOUL.md    (探索者灵魂)
  - DISCOVERIES.md (发现库)
  所有修改都有版本追踪 (memory/taste-changelog.md)
  Reviewer 提供自动反馈信号 (memory/feedback/)

运行:
  python claws_runner.py                # 守护进程
  python claws_runner.py -p sense       # 手动: 侦察
  python claws_runner.py -p dive        # 手动: 深挖
  python claws_runner.py -p reflect     # 手动: 反思+进化
  python claws_runner.py -p review      # 手动: 独立审查
  python claws_runner.py -p weekly      # 手动: 周报+大进化
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
from logging.handlers import RotatingFileHandler

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
except ImportError:
    print("pip install apscheduler")
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None

# ─── 常量 ───

CST = timezone(timedelta(hours=8))
ROOT = Path(__file__).parent
MEMORY_DIR = ROOT / "memory"
LOG_DIR = ROOT / "logs"


# ─── 日志（带轮转，防磁盘爆满）───

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            LOG_DIR / "claws.log", maxBytes=10 * 1024 * 1024,
            backupCount=5, encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("CLAWS")


# ─── Ops 运维事件上报（静默、非阻塞）───

try:
    from ops_reporter import report_event as _ops_report
except ImportError:
    def _ops_report(**kwargs):
        pass


def ops_report(level: str, category: str, title: str, detail: str = "", action_hint: str = ""):
    _ops_report(
        project="claws", level=level, category=category,
        title=title, detail=detail[:2000], action_hint=action_hint,
        dedup_key=f"claws:{category}:{title[:50]}",
    )


# ─── 飞书推送 ───

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK_URL", "")


async def _feishu_send(payload: dict) -> bool:
    if not FEISHU_WEBHOOK:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(FEISHU_WEBHOOK, json=payload)
            data = resp.json()
            return data.get("code") == 0 or data.get("StatusCode") == 0
    except Exception as e:
        log.warning(f"飞书推送失败: {e}")
        return False


async def feishu_text(content: str) -> bool:
    return await _feishu_send({"msg_type": "text", "content": {"text": content}})


async def feishu_card(title: str, md_content: str, color: str = "blue") -> bool:
    return await _feishu_send({
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}, "template": color},
            "elements": [{"tag": "markdown", "content": md_content}],
        },
    })


# ─── .env 加载 ───

def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

_load_dotenv()


# ─── Agent 配置 ───

@dataclass
class AgentConfig:
    name: str
    description: str = ""
    agent_id: str = ""
    model: str = "deepseek-v3.2"
    temperature: float = 0.3
    enable_web_search: bool = False
    prompt_file: str = ""
    timeout: int = 180
    base_url: str = "http://knot.woa.com"
    api_token: str = ""
    agent_token: str = ""
    username: str = ""
    cloud_workspace: bool = False
    workspace_uuid: str = ""
    mcp_deps: list[str] = field(default_factory=list)


def _resolve_env_var(raw: str) -> str:
    """解析 ${ENV_VAR} 或 ${ENV_VAR:-default} 格式的环境变量引用。"""
    if not raw.startswith("${"):
        return raw
    inner = raw[2:].rstrip("}")
    if ":-" in inner:
        env_key, default_val = inner.split(":-", 1)
    else:
        env_key, default_val = inner, ""
    return os.getenv(env_key, default_val)


def load_agents() -> dict[str, AgentConfig]:
    """从 agents.yaml 加载 agent 配置。

    认证方式（自动判断）：
      方式 1: 个人 Token (KNOT_API_TOKEN) — 一个 token 调所有 Agent
      方式 2: 智能体 Token (KNOT_<NAME>_AGENT_TOKEN) + 用户名 — per-agent 独立密钥
    """
    default_base = os.getenv("KNOT_API_BASE_URL", "http://knot.woa.com")
    default_timeout = int(os.getenv("KNOT_TIMEOUT", "180"))
    default_workspace = os.getenv("KNOT_WORKSPACE_UUID", "")
    personal_token = os.getenv("KNOT_API_TOKEN", "")
    username = os.getenv("KNOT_USERNAME", "")

    agents: dict[str, AgentConfig] = {}

    yaml_path = ROOT / "config" / "agents.yaml"
    if not yaml_path.exists():
        log.error(f"agents.yaml 不存在: {yaml_path}")
        sys.exit(1)
    if yaml is None:
        log.error("缺少 pyyaml 依赖: pip install pyyaml")
        sys.exit(1)

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})

    for name, spec in raw.get("agents", {}).items():
        agent_id = _resolve_env_var(spec.get("agent_id", ""))
        agent_token_key = f"KNOT_{name.upper()}_AGENT_TOKEN"
        agent_token = os.getenv(agent_token_key, "")
        workspace = _resolve_env_var(defaults.get("workspace_uuid", default_workspace))

        agents[name] = AgentConfig(
            name=name,
            description=spec.get("description", ""),
            agent_id=agent_id,
            model=spec.get("model", defaults.get("model", "deepseek-v3.2")),
            temperature=spec.get("temperature", defaults.get("temperature", 0.3)),
            enable_web_search=spec.get("enable_web_search", False),
            prompt_file=spec.get("prompt_file", ""),
            timeout=spec.get("timeout", default_timeout),
            base_url=_resolve_env_var(defaults.get("base_url", default_base)),
            api_token=personal_token,
            agent_token=agent_token,
            username=username,
            cloud_workspace=spec.get("cloud_workspace", False),
            workspace_uuid=workspace,
            mcp_deps=spec.get("mcp_deps", []),
        )

    return agents


def validate_agents(agents: dict[str, AgentConfig]) -> None:
    """启动前校验：确保每个 Agent 都有有效的独立 ID 和认证凭证。"""
    errors = []
    for name, cfg in agents.items():
        if not cfg.agent_id or cfg.agent_id.startswith("<"):
            errors.append(f"  [{name}] Agent ID 未配置 (KNOT_{name.upper()}_AGENT_ID)")
        if not cfg.api_token and not cfg.agent_token:
            errors.append(f"  [{name}] 缺少认证: 需要 KNOT_API_TOKEN 或 KNOT_{name.upper()}_AGENT_TOKEN")
        if cfg.agent_token and not cfg.api_token and not cfg.username:
            errors.append(f"  [{name}] 使用智能体 Token 时需要 KNOT_USERNAME")

    if errors:
        log.error("Agent 配置校验失败:\n" + "\n".join(errors))
        sys.exit(1)

    sample = next(iter(agents.values()))
    auth_mode = "个人 Token" if sample.api_token else "智能体 Token"
    log.info(f"认证方式: {auth_mode}")

    if sample.workspace_uuid:
        log.info(f"云工作区: {sample.workspace_uuid}")
    else:
        log.warning("⚠️ 云工作区未配置，Agent 将无法读写 workspace 文件")


# ─── Knot AG-UI 客户端 ───

class KnotClient:
    """精简的 Knot AG-UI 客户端。"""

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.api_url = f"{cfg.base_url.rstrip('/')}/apigw/api/v1/agents/agui/{cfg.agent_id}"

    async def chat(self, message: str, **overrides) -> dict[str, Any]:
        model = overrides.get("model", self.cfg.model)
        temp = overrides.get("temperature", self.cfg.temperature)
        web = overrides.get("enable_web_search", self.cfg.enable_web_search)

        result: dict[str, Any] = {"content": "", "conversation_id": "", "error": None, "token_usage": None}
        parts: list[str] = []

        chat_extra: dict[str, Any] = {"attached_images": [], "extra_headers": {}}
        if self.cfg.workspace_uuid:
            chat_extra["agent_client_uuid"] = self.cfg.workspace_uuid

        body = {
            "input": {
                "message": message,
                "conversation_id": overrides.get("conversation_id", ""),
                "model": model,
                "stream": True,
                "enable_web_search": web,
                "temperature": temp,
                "chat_extra": chat_extra,
            }
        }
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_token:
            headers["x-knot-api-token"] = self.cfg.api_token
        elif self.cfg.agent_token:
            headers["x-knot-token"] = self.cfg.agent_token
            if self.cfg.username:
                headers["X-Username"] = self.cfg.username

        try:
            timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", self.api_url, json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        err = await resp.aread()
                        result["error"] = f"HTTP {resp.status_code}: {err.decode()}"
                        return result
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        chunk = line.removeprefix("data:").strip()
                        if not chunk or chunk == "[DONE]":
                            break
                        try:
                            msg = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        if "type" not in msg:
                            continue
                        raw = msg.get("rawEvent", {})
                        if "conversation_id" in raw:
                            result["conversation_id"] = raw["conversation_id"]
                        match msg["type"]:
                            case "TEXT_MESSAGE_CONTENT":
                                parts.append(raw.get("content", ""))
                            case "STEP_FINISHED":
                                if "token_usage" in raw:
                                    result["token_usage"] = raw["token_usage"]
                            case "RUN_ERROR":
                                result["error"] = raw.get("tip_option", {}).get("content", "Unknown")
            result["content"] = "".join(parts)
        except httpx.TimeoutException:
            result["error"] = f"超时 ({self.cfg.timeout}s)"
        except Exception as e:
            result["error"] = str(e)
        return result


def extract_json(text: str) -> Optional[dict]:
    """多层容错 JSON 提取（含 CJK 引号修复和未转义引号修复）。"""
    if not text:
        return None
    text = text.strip().lstrip("\ufeff")

    def _try(s: str) -> Optional[dict]:
        for strict in (True, False):
            try:
                r = json.loads(s, strict=strict)
                if isinstance(r, dict):
                    return r
            except json.JSONDecodeError:
                pass
        return None

    def _fix_and_try(s: str) -> Optional[dict]:
        s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
        s = re.sub(r",\s*([\]}])", r"\1", s)
        s = s.replace("\u201c", '\\"').replace("\u201d", '\\"')
        s = s.replace("\u2018", "\\'").replace("\u2019", "\\'")
        if (r := _try(s)):
            return r
        # Fix unescaped quotes inside string values:
        # Find patterns like "key": "...text with "quotes" inside..."
        # by replacing inner quotes with escaped quotes
        fixed = _fix_inner_quotes(s)
        return _try(fixed)

    def _fix_inner_quotes(s: str) -> str:
        """Attempt to fix unescaped double quotes inside JSON string values."""
        result = []
        i = 0
        in_string = False
        escaped = False
        while i < len(s):
            ch = s[i]
            if escaped:
                result.append(ch)
                escaped = False
            elif ch == '\\':
                result.append(ch)
                escaped = True
            elif ch == '"':
                if not in_string:
                    in_string = True
                    result.append(ch)
                else:
                    # Look ahead: if next non-whitespace is : , ] } or end, it's a real close
                    rest = s[i+1:].lstrip()
                    if not rest or rest[0] in ':,]}':
                        in_string = False
                        result.append(ch)
                    else:
                        result.append('\\"')
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    if (r := _try(text)):
        return r

    for m in re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text):
        if (r := _try(m)):
            return r
        if (r := _fix_and_try(m)):
            return r

    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        c = text[s:e + 1]
        if (r := _try(c)):
            return r
        if (r := _fix_and_try(c)):
            return r

    return None


# ─── 文件工具 ───

def _today() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")

def _now() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log.info(f"写入: {path.relative_to(ROOT)}")

def _append(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)

def _load_prompt(prompt_file: str, **kwargs) -> str:
    """从 Agent 的 main.md 中提取 Prompt 部分并渲染变量。

    main.md 格式：元信息 + --- + ... + ## Prompt + (正文)
    提取 '## Prompt' 之后的所有内容作为实际 Prompt。
    如果文件不含 '## Prompt' 标记，则使用全文。
    """
    path = ROOT / prompt_file
    if not path.exists():
        log.warning(f"Prompt 文件不存在: {path}")
        return ""
    content = path.read_text(encoding="utf-8")

    prompt_marker = "## Prompt"
    marker_pos = content.find(prompt_marker)
    if marker_pos >= 0:
        content = content[marker_pos + len(prompt_marker):].lstrip("\n")

    for key, value in kwargs.items():
        content = content.replace(f"{{{key}}}", str(value))
    return content

def _read_today(subdir: str) -> str:
    d = MEMORY_DIR / subdir
    if not d.exists():
        return "(无记录)"
    parts = []
    for f in sorted(d.iterdir()):
        if _today() in f.name:
            parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts) if parts else "(今日无记录)"

def _read_week(subdir: str) -> str:
    d = MEMORY_DIR / subdir
    if not d.exists():
        return "(无记录)"
    cutoff = datetime.now(CST) - timedelta(days=7)
    parts = []
    for f in sorted(d.iterdir()):
        try:
            fdate = datetime.strptime(f.stem[:10], "%Y-%m-%d").replace(tzinfo=CST)
            if fdate >= cutoff:
                parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
        except ValueError:
            continue
    return "\n\n".join(parts) if parts else "(本周无记录)"

def _discoveries_summary() -> str:
    content = _read(MEMORY_DIR / "DISCOVERIES.md")
    if not content or "等待" in content:
        return "(尚无已有发现)"
    lines = [l for l in content.split("\n") if l.startswith("### [")]
    return "已有发现：\n" + "\n".join(lines[-20:]) if lines else "(尚无已有发现)"


# ─── CLAWS Pipeline Engine ───

class RunStats:
    """单次 Pipeline 运行统计。"""

    def __init__(self):
        self.phase = ""
        self.agent = ""
        self.start_time = 0.0
        self.elapsed = 0.0
        self.chars = 0
        self.error: Optional[str] = None
        self.token_usage: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "phase": self.phase, "agent": self.agent,
            "elapsed_s": round(self.elapsed, 1), "chars": self.chars,
            "error": self.error,
        }


class ClawsPipeline:
    """CLAWS 探索 Pipeline — 一主多从架构。"""

    CONSECUTIVE_FAIL_THRESHOLD = 3

    def __init__(self, agents: dict[str, AgentConfig]):
        self.agents = agents
        self.clients = {name: KnotClient(cfg) for name, cfg in agents.items()}
        self._consecutive_failures: dict[str, int] = {n: 0 for n in agents}
        self._run_history: list[dict] = []

    def _taste(self) -> str:
        t = _read(ROOT / "TASTE.md")
        return t[:6000] if len(t) > 6000 else t if t else "(品味模型未初始化 — 将在首次 REFLECT 后生成)"

    def _soul(self) -> str:
        s = _read(ROOT / "SOUL.md")
        return s[:3000] if len(s) > 3000 else s if s else "(灵魂文件未初始化)"

    def _latest_feedback(self) -> str:
        fb_dir = MEMORY_DIR / "feedback"
        if not fb_dir.exists():
            return "(暂无审查反馈)"
        files = sorted(fb_dir.iterdir(), reverse=True)
        if not files:
            return "(暂无审查反馈)"
        content = files[0].read_text(encoding="utf-8")
        return f"最近一次审查反馈 ({files[0].stem}):\n{content[:3000]}"

    async def _call_agent(self, name: str, prompt: str, phase: str = "") -> dict[str, Any]:
        client = self.clients[name]
        cfg = self.agents[name]
        log.info(f"调用 {name} agent (model={cfg.model}, web_search={cfg.enable_web_search})")
        start = time.monotonic()
        result = await client.chat(prompt)
        elapsed = time.monotonic() - start

        stats = RunStats()
        stats.phase = phase or name
        stats.agent = name
        stats.elapsed = elapsed
        stats.chars = len(result.get("content", ""))
        stats.token_usage = result.get("token_usage")

        if result["error"]:
            stats.error = result["error"]
            self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
            log.error(f"{name} 失败 ({elapsed:.1f}s): {result['error']}")
            ops_report("warning", "agent_failed", f"CLAWS {name} 调用失败",
                       detail=f"错误: {result['error']}\n耗时: {elapsed:.1f}s",
                       action_hint=f"检查 Agent {cfg.agent_id[:12]}... 状态")
            if self._consecutive_failures[name] >= self.CONSECUTIVE_FAIL_THRESHOLD:
                ops_report("critical", "agent_consecutive_fail",
                           f"CLAWS {name} 连续失败 {self._consecutive_failures[name]} 次",
                           action_hint="检查 Knot Agent 服务状态和网络连接")
        else:
            self._consecutive_failures[name] = 0
            log.info(f"{name} 完成 ({elapsed:.1f}s, {stats.chars} chars)")

        self._run_history.append(stats.to_dict())
        return result

    # ── Phase 1: SENSE + FILTER (Scout) ──

    async def run_sense(self) -> None:
        log.info("=" * 60)
        log.info("Phase 1: SENSE + FILTER (Scout)")
        log.info("=" * 60)

        prompt = _load_prompt(self.agents["scout"].prompt_file,
                              taste_context=self._taste(),
                              existing_discoveries=_discoveries_summary())

        result = await self._call_agent("scout", prompt, phase="sense")
        if result["error"]:
            return

        today = _today()
        _write(MEMORY_DIR / "raw" / f"{today}.md", f"# Raw Scan — {_now()}\n\n{result['content']}\n")

        parsed = extract_json(result["content"])
        if not parsed or "items" not in parsed:
            log.warning("JSON 解析失败，原始数据已保存到 raw/")
            ops_report("warning", "json_parse_failed", "Scout JSON 解析失败",
                       detail=result["content"][:500])
            return

        items = parsed["items"]
        deep = [i for i in items if i.get("verdict") == "deep_dive"]
        watch = [i for i in items if i.get("verdict") == "watch"]
        log.info(f"结果: {len(items)} 项 → {len(deep)} deep_dive + {len(watch)} watch")

        filtered_md = f"# Filtered — {_now()}\n\n"
        filtered_md += f"deep_dive: {len(deep)} | watch: {len(watch)} | total: {len(items)}\n\n"
        if parsed.get("meta_observation"):
            filtered_md += f"**趋势观察**: {parsed['meta_observation']}\n\n"
        for item in sorted(items, key=lambda x: x.get("total_score", 0), reverse=True):
            sc = item.get("scores", {})
            filtered_md += f"### {item.get('title', '?')} ({item.get('total_score', 0)}/25) [{item.get('verdict', '?')}]\n"
            filtered_md += f"- {item.get('one_liner', '')}\n"
            filtered_md += f"- 来源: {item.get('source', '?')} | 新颖{sc.get('novelty',0)} 深度{sc.get('depth',0)} 实用{sc.get('utility',0)} 趋势{sc.get('trend_signal',0)} 品味{sc.get('taste_match',0)}\n"
            filtered_md += f"- 理由: {item.get('reason', '')}\n"
            if item.get("url"):
                filtered_md += f"- 链接: {item['url']}\n"
            filtered_md += "\n"
        _write(MEMORY_DIR / "filtered" / f"{today}.md", filtered_md)

        if deep:
            summary_lines = [f"扫描 {len(items)} 项 → {len(deep)} 个值得深挖："]
            for d in deep[:3]:
                summary_lines.append(f"  • {d.get('title', '?')} ({d.get('total_score', 0)}/25)")
            if parsed.get("meta_observation"):
                summary_lines.append(f"\n趋势: {parsed['meta_observation'][:100]}")
            await feishu_card("🦀 CLAWS 侦察报告", "\n".join(summary_lines), "blue")

    # ── Phase 2: DIVE (Analyst) ──

    async def run_dive(self) -> None:
        log.info("=" * 60)
        log.info("Phase 2: DIVE (Analyst)")
        log.info("=" * 60)

        filtered = _read_today("filtered")
        if "无记录" in filtered or len(filtered) < 50:
            log.info("今日无筛选数据，跳过 DIVE")
            return

        prompt = _load_prompt(self.agents["analyst"].prompt_file,
                              taste_context=self._taste(),
                              filtered_items=filtered)

        result = await self._call_agent("analyst", prompt, phase="dive")
        if result["error"]:
            return

        today = _today()
        meta = extract_json(result["content"])
        slug = "analysis"
        if meta and "analyzed_items" in meta:
            slug = "-".join(str(x) for x in meta["analyzed_items"][:2]).lower()
            slug = re.sub(r"[^a-z0-9\u4e00-\u9fff-]", "", slug)[:40]

        out_path = MEMORY_DIR / "deep-dives" / f"{today}-{slug}.md"
        _write(out_path, f"# Deep Dive — {_now()}\n\n{result['content']}\n")

        if meta:
            insight = meta.get("key_insight", "")
            items_str = ", ".join(meta.get("analyzed_items", [])[:2])
            await feishu_card("🔬 CLAWS 深度分析",
                              f"**分析目标**: {items_str}\n**核心洞察**: {insight}", "green")

    # ── Phase 3: REFLECT + EVOLVE ──

    async def run_reflect(self) -> None:
        log.info("=" * 60)
        log.info("Phase 3: REFLECT + EVOLVE")
        log.info("=" * 60)

        exploration = f"### 原始采集\n{_read_today('raw')}\n\n### 筛选结果\n{_read_today('filtered')}\n\n### 深度分析\n{_read_today('deep-dives')}"

        feedback = self._latest_feedback()
        prompt = _load_prompt(self.agents["evolve"].prompt_file,
                              taste_context=self._taste(),
                              soul_context=self._soul(),
                              exploration_data=exploration,
                              review_feedback=feedback)

        result = await self._call_agent("evolve", prompt, phase="reflect")
        if result["error"]:
            return

        today = _today()
        _write(MEMORY_DIR / "reflections" / f"{today}.md",
               f"# Reflection — {_now()}\n\n{result['content']}\n")

        parsed = extract_json(result["content"])
        if not parsed:
            log.warning("进化者响应 JSON 解析失败")
            ops_report("warning", "json_parse_failed", "Evolve JSON 解析失败",
                       detail=result["content"][:500])
            return

        await self._apply_evolution(parsed, today)

    async def run_review(self) -> None:
        """Phase 4: REVIEW — 独立审查者 Agent，替代人工反馈回路。"""
        log.info("=" * 60)
        log.info("Phase 4: REVIEW (Automated Feedback)")
        log.info("=" * 60)

        reflections = _read_today("reflections")
        if "无记录" in reflections:
            log.info("今日无反思数据，跳过 REVIEW")
            return

        discoveries_raw = _read(MEMORY_DIR / "DISCOVERIES.md")

        prompt = _load_prompt(self.agents["reviewer"].prompt_file,
                              taste_context=self._taste(),
                              filtered_items=_read_today("filtered"),
                              reflections=reflections,
                              discoveries=discoveries_raw[:3000])

        result = await self._call_agent("reviewer", prompt, phase="review")
        if result["error"]:
            return

        today = _today()
        _write(MEMORY_DIR / "reviews" / f"{today}.md",
               f"# Review — {_now()}\n\n{result['content']}\n")

        parsed = extract_json(result["content"])
        if parsed:
            grade = parsed.get("overall_grade", "?")
            verdict = parsed.get("one_line_verdict", "")
            action_score = parsed.get("actionability_score", "?")
            log.info(f"📋 审查评级: {grade} | 可执行性: {action_score}/10 | {verdict}")

            feedback = parsed.get("feedback_signals", [])
            if feedback:
                _write(MEMORY_DIR / "feedback" / f"{today}.json",
                       json.dumps(feedback, ensure_ascii=False, indent=2))

            await feishu_card("📋 CLAWS 审查报告",
                              f"**评级**: {grade} | **可执行性**: {action_score}/10\n\n{verdict}", "orange")

    async def run_weekly(self) -> None:
        log.info("=" * 60)
        log.info("Phase 3+: WEEKLY DIGEST + TASTE OVERHAUL")
        log.info("=" * 60)

        exploration = f"### 本周反思\n{_read_week('reflections')}\n\n### 本周筛选\n{_read_week('filtered')}\n\n### 本周深挖\n{_read_week('deep-dives')}"

        feedback = self._latest_feedback()
        prompt = _load_prompt(self.agents["evolve"].prompt_file,
                              taste_context=self._taste(),
                              soul_context=self._soul(),
                              exploration_data=exploration,
                              review_feedback=feedback)

        prompt += """

## 额外任务：周度品味大调整

这是每周一次的大反思。除了常规反思，还要：
1. 对比品味参考源（Simon Willison, swyx, Karpathy）本周关注了什么
2. 找到自己的探索盲区
3. 大胆调整品味权重（允许 ±3 的变化幅度）
4. 生成周报摘要"""

        result = await self._call_agent("evolve", prompt, phase="weekly")
        if result["error"]:
            return

        _write(MEMORY_DIR / "weekly-digest.md",
               f"# Weekly Digest — {_now()}\n\n{result['content']}\n")

        parsed = extract_json(result["content"])
        if parsed:
            await self._apply_evolution(parsed, _today())
            await feishu_card("📊 CLAWS 周报", result["content"][:2000], "purple")

    async def _apply_evolution(self, data: dict, today: str) -> None:
        """将进化者的输出应用到上下文文件 —— 这是自进化的核心。

        写入策略（避免与 Evolve Agent 云工作区操作冲突）：
        - TASTE.md / SOUL.md：由 Runner 写入（Evolve Agent Prompt 中不要求直接写文件）
        - taste-changelog.md / DISCOVERIES.md：由 Runner 追加
        """

        push_parts: list[str] = []

        # 1. 品味进化：覆盖 TASTE.md
        taste_evo = data.get("taste_evolution", {})
        if isinstance(taste_evo, dict):
            new_taste = taste_evo.get("new_taste_md")
            if new_taste and new_taste != "null" and len(new_taste) > 100:
                _write(ROOT / "TASTE.md", new_taste)
                log.info("🧬 TASTE.md 已进化")

            changes = taste_evo.get("changes", [])
            if changes:
                version = taste_evo.get("version", "?")
                changelog = f"\n## {today} — {version}\n\n"
                change_summaries = []
                for c in changes:
                    changelog += f"- **{c.get('field', '?')}**: {c.get('old_value', '?')} → {c.get('new_value', '?')}\n"
                    changelog += f"  证据: {c.get('evidence', '无')}\n"
                    change_summaries.append(f"  • {c.get('field', '?')}: {c.get('old_value', '?')[:30]} → {c.get('new_value', '?')[:30]}")
                _append(MEMORY_DIR / "taste-changelog.md", changelog)
                push_parts.append(f"**品味进化 → {version}**\n" + "\n".join(change_summaries[:5]))

        # 2. 灵魂进化：覆盖 SOUL.md
        new_soul = data.get("soul_evolution")
        if new_soul and new_soul != "null" and len(str(new_soul)) > 100:
            _write(ROOT / "SOUL.md", str(new_soul))
            log.info("🧬 SOUL.md 已进化")
            push_parts.append("**灵魂文件已进化**")

        # 3. 发现沉淀：追加到 DISCOVERIES.md
        new_disc = data.get("new_discoveries", [])
        if new_disc:
            disc_path = MEMORY_DIR / "DISCOVERIES.md"
            entries = "\n"
            disc_summaries = []
            for d in new_disc:
                entries += f"### [{today}] {d.get('title', '?')}\n"
                entries += f"- **领域**: {d.get('domain', '?')}\n"
                entries += f"- **评分**: {d.get('score', '?')}/25\n"
                entries += f"- **一句话**: {d.get('one_liner', '')}\n"
                entries += f"- **状态**: {d.get('status', '🔴 新发现')}\n\n"
                disc_summaries.append(f"  • {d.get('title', '?')} ({d.get('score', '?')}/25)")

            existing = _read(disc_path)
            if "等待" in existing:
                existing = existing.replace("_等待 CLAWS 第一次运行后填充..._", entries)
            else:
                existing = existing.replace("## 发现列表\n", f"## 发现列表\n{entries}")
            _write(disc_path, existing)
            log.info(f"📌 新增 {len(new_disc)} 条发现")
            push_parts.append(f"**新增 {len(new_disc)} 条发现**\n" + "\n".join(disc_summaries[:5]))

        # 4. 反思统计
        refl = data.get("reflection", {})
        stats = refl.get("stats", {})
        if stats:
            stats_line = (
                f"扫描{stats.get('scanned', '?')} → "
                f"筛选{stats.get('filtered_in', '?')} → "
                f"深挖{stats.get('deep_dived', '?')} → "
                f"发现{stats.get('discoveries', '?')} "
                f"(通过率{stats.get('pass_rate_percent', '?')}%)"
            )
            log.info(f"📊 统计: {stats_line}")
            push_parts.insert(0, f"**统计**: {stats_line}")

        # 5. 推送给主人
        push = data.get("push_to_human")
        if push and push != "null":
            push_parts.append(f"\n**Evolve 说**: {str(push)[:300]}")
            log.info(f"📨 推送给主人: {str(push)[:150]}...")

        if push_parts:
            await feishu_card("🧬 CLAWS 反思 & 进化", "\n\n".join(push_parts), "orange")


# ─── 调度器 ───

def build_scheduler(pipeline: ClawsPipeline) -> AsyncIOScheduler:
    tz = os.getenv("CLAWS_TIMEZONE", "Asia/Shanghai")
    interval = int(os.getenv("CLAWS_SENSE_INTERVAL_HOURS", "4"))
    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(pipeline.run_sense, IntervalTrigger(hours=interval, timezone=tz),
                      id="sense", name="SENSE+FILTER", max_instances=1, misfire_grace_time=600)
    scheduler.add_job(pipeline.run_dive, CronTrigger(hour="10,22", timezone=tz),
                      id="dive", name="DIVE", max_instances=1, misfire_grace_time=600)
    scheduler.add_job(pipeline.run_reflect, CronTrigger(hour=21, timezone=tz),
                      id="reflect", name="REFLECT+EVOLVE", max_instances=1, misfire_grace_time=600)
    scheduler.add_job(pipeline.run_review, CronTrigger(hour=21, minute=30, timezone=tz),
                      id="review", name="REVIEW", max_instances=1, misfire_grace_time=600)
    scheduler.add_job(pipeline.run_weekly, CronTrigger(day_of_week="sun", hour=15, timezone=tz),
                      id="weekly", name="WEEKLY", max_instances=1, misfire_grace_time=3600)
    return scheduler


# ─── 入口 ───

async def main_daemon() -> None:
    agents = load_agents()
    validate_agents(agents)
    pipeline = ClawsPipeline(agents)
    scheduler = build_scheduler(pipeline)

    log.info("🦀 CLAWS Runner v2 启动")
    for name, cfg in agents.items():
        log.info(f"  [{name}] id={cfg.agent_id[:12]}... token={cfg.api_token[:12]}... model={cfg.model} web={cfg.enable_web_search}")

    scheduler.start()
    log.info("首次运行: 立即执行 SENSE+FILTER")
    await pipeline.run_sense()

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    await stop.wait()
    scheduler.shutdown()
    log.info("🦀 CLAWS 已关闭")


async def main_manual(phase: str) -> None:
    agents = load_agents()
    validate_agents(agents)
    pipeline = ClawsPipeline(agents)
    phases = {"sense": pipeline.run_sense, "dive": pipeline.run_dive,
              "reflect": pipeline.run_reflect, "review": pipeline.run_review,
              "weekly": pipeline.run_weekly}
    if phase not in phases:
        log.error(f"未知阶段: {phase}")
        return
    log.info(f"🦀 手动执行: {phase}")
    await phases[phase]()
    log.info(f"🦀 {phase} 完成")


def main():
    parser = argparse.ArgumentParser(description="CLAWS Runner v2")
    parser.add_argument("-p", "--phase", choices=["sense", "dive", "reflect", "review", "weekly"])
    args = parser.parse_args()

    asyncio.run(main_manual(args.phase) if args.phase else main_daemon())


if __name__ == "__main__":
    main()
