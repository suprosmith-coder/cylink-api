"""
auralis — Full TUI shell for the Auralis code analysis engine
Claude Code-style terminal interface powered by NixAi
Animated nanotech sprite with float, pulse, scanline, glitch, spinup, alert
"""

import asyncio
import argparse
import difflib
import json
import os
import re
import sys
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich.prompt import Prompt, Confirm
from rich.live import Live
from rich import box

from .auralis import AsyncAuralis, AuralisResult
from .sprite import SpriteAnimator, render_sprite, build_frame

# ── Constants ──────────────────────────────────────────────────────────
VERSION      = "0.1.8"
HISTORY_FILE = Path.home() / ".auralis_history.json"
MAX_HISTORY  = 10

SEVERITY_COLORS = {"low": "yellow", "medium": "dark_orange", "high": "red1"}
TIER_COLORS     = {"safe": "green3", "medium": "yellow", "high": "dark_orange", "blocked": "red1"}
TIER_ICONS      = {"safe": "●", "medium": "●", "high": "●", "blocked": "⊘"}

EXT_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".go": "go",
    ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".cpp": "cpp", ".c": "c", ".rb": "ruby",
    ".php": "php", ".sh": "bash", ".sql": "sql",
}
CODE_EXTENSIONS = set(EXT_MAP.keys())

# Chat `ad <path>` context limits
MAX_CONTEXT_BYTES    = 22 * 1024   # mirrors Auralis's edge function payload cap
SENSITIVE_NAME_HINTS = (".env", "id_rsa", "id_ed25519", "credentials", ".pem", ".npmrc", "secret")

console = Console(highlight=False)


# ── History ────────────────────────────────────────────────────────────
def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())[-MAX_HISTORY:]
        except Exception:
            return []
    return []


def save_history(entry: dict):
    history = load_history()
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history[-MAX_HISTORY:], indent=2))


def detect_language(path: Path) -> str:
    return EXT_MAP.get(path.suffix.lower(), "text")


def _looks_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(1024)
    except Exception:
        return False


def _extract_code_block(text: str) -> str | None:
    """Return the content of the LAST fenced code block in text, or None."""
    blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    return blocks[-1].rstrip("\n") if blocks else None


def _unified_diff(old: str, new: str, filename: str) -> str:
    """Build a unified diff string between old and new file contents."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{filename} (current)", tofile=f"{filename} (proposed)",
        lineterm="",
    )
    return "\n".join(lines)


# ── Welcome screen ─────────────────────────────────────────────────────
def render_welcome(api_key: str, animator: SpriteAnimator = None):
    console.clear()

    # Static sprite for welcome layout
    sprite_lines = render_sprite()
    logo = Text()
    logo.append("\n")
    for line in sprite_lines:
        logo.append_text(line)
        logo.append("\n")
    logo.append("\n")
    logo.append("  ⬡  AURALIS\n", style="bold rgb(168,85,247)")
    logo.append("  Code Intelligence · NixAi\n", style="dim rgb(126,34,206)")
    logo.append("\n")
    key_preview = f"cyk_····...{api_key[-4:]}" if len(api_key) > 8 else "cyk_****"
    logo.append(f"  {key_preview}", style="dim")
    logo.append("  ·  ", style="dim")
    logo.append("Ready", style="rgb(34,197,94) bold")
    logo.append("\n")

    tips = Text()
    tips.append("Commands\n\n", style="bold rgb(168,85,247)")
    for cmd, arg, desc in [
        ("analyze", "<file>  ", "Scan for risks"),
        ("fix",     "<file>  ", "Analyze + apply fix"),
        ("scan",    "<dir>   ", "Scan a directory"),
        ("chat",    "[path] ", "Interactive chat"),
        ("history", "        ", "Recent analyses"),
        ("exit",    "        ", "Quit"),
    ]:
        tips.append(f"  {cmd} ", style="rgb(168,85,247) bold")
        tips.append(f"{arg}", style="dim")
        tips.append(f"{desc}\n", style="white")

    history = load_history()
    recent  = Text()
    recent.append("Recent activity\n\n", style="bold rgb(168,85,247)")
    if history:
        for item in reversed(history[-5:]):
            tier  = item.get("tier", "?")
            color = TIER_COLORS.get(tier, "white")
            icon  = TIER_ICONS.get(tier, "●")
            recent.append(f"  [{icon}] ", style=color)
            recent.append(f"{item.get('file', '?')}\n", style="white")
            recent.append(f"       {item.get('risks', 0)} risk(s)  {item.get('time', '')}\n", style="dim")
    else:
        recent.append("  No recent activity\n", style="dim")

    left  = Panel(logo, border_style="rgb(126,34,206)", padding=(0, 2))
    right = Panel(
        Text.assemble(tips, "\n", recent),
        border_style="dim",
        padding=(0, 2),
        title="[dim]Tips & Activity[/dim]",
    )

    console.print(Rule(f"[dim]Auralis v{VERSION}[/dim]", style="rgb(126,34,206)"))
    console.print(Columns([left, right], equal=True))
    console.print(Rule(style="dim"))
    console.print()


# ── Animated welcome (sprite animates while idle) ──────────────────────
def render_welcome_animated(api_key: str) -> SpriteAnimator:
    """
    Draw the welcome screen with the left panel running a live
    animated sprite. Returns the animator so the shell can stop it
    when the user types a command.
    """
    console.clear()
    console.print(Rule(f"[dim]Auralis v{VERSION}[/dim]", style="rgb(126,34,206)"))

    # Tips + recent (right panel — static)
    tips = Text()
    tips.append("Commands\n\n", style="bold rgb(168,85,247)")
    for cmd, arg, desc in [
        ("analyze", "<file>  ", "Scan for risks"),
        ("fix",     "<file>  ", "Analyze + apply fix"),
        ("scan",    "<dir>   ", "Scan a directory"),
        ("chat",    "[path] ", "Interactive chat"),
        ("history", "        ", "Recent analyses"),
        ("exit",    "        ", "Quit"),
    ]:
        tips.append(f"  {cmd} ", style="rgb(168,85,247) bold")
        tips.append(f"{arg}", style="dim")
        tips.append(f"{desc}\n", style="white")

    history = load_history()
    recent  = Text()
    recent.append("\nRecent activity\n\n", style="bold rgb(168,85,247)")
    if history:
        for item in reversed(history[-5:]):
            tier  = item.get("tier", "?")
            color = TIER_COLORS.get(tier, "white")
            icon  = TIER_ICONS.get(tier, "●")
            recent.append(f"  [{icon}] ", style=color)
            recent.append(f"{item.get('file', '?')}\n", style="white")
            recent.append(f"       {item.get('risks', 0)} risk(s)  {item.get('time', '')}\n", style="dim")
    else:
        recent.append("  No recent activity\n", style="dim")

    right_panel = Panel(
        Text.assemble(tips, recent),
        border_style="dim",
        padding=(0, 2),
        title="[dim]Tips & Activity[/dim]",
    )
    console.print(right_panel)
    console.print(Rule(style="dim"))
    console.print()

    # Start animator in background
    animator = SpriteAnimator(console)
    animator.start_idle()
    return animator


# ── Result display ─────────────────────────────────────────────────────
def display_result(result: AuralisResult, path: Path):
    tier_color = TIER_COLORS[result.safety_tier]
    icon       = TIER_ICONS[result.safety_tier]

    header = Text()
    header.append(f"{path.name}\n", style="bold white")
    header.append(f"{result.intent}\n\n", style="dim")
    header.append(f"{icon} ", style=f"{tier_color} bold")
    header.append(f"{result.safety_tier.upper()}", style=f"{tier_color} bold")
    header.append("   Confidence: ", style="dim")
    header.append(f"{result.confidence}%", style="rgb(168,85,247) bold")
    header.append("   Complexity: ", style="dim")
    header.append(f"{result.complexity}", style="rgb(126,34,206)")

    console.print(Panel(header, border_style=tier_color, padding=(0, 2)))

    if result.risks:
        table = Table(box=box.SIMPLE, header_style="bold dim", show_edge=False, padding=(0, 2))
        table.add_column("", width=3)
        table.add_column("Risk", style="white")
        table.add_column("Category", style="dim", width=24)
        table.add_column("Detail", style="dim")
        for risk in result.risks:
            color = SEVERITY_COLORS.get(risk.severity, "white")
            table.add_row(
                f"[{color}]●[/{color}]",
                f"[{color}]{risk.label}[/{color}]",
                risk.category,
                risk.description,
            )
        console.print(table)
    else:
        console.print("  [green3]No risks found.[/green3]\n")

    if result.explanation:
        console.print("  [bold dim]Findings[/bold dim]")
        for point in result.explanation:
            console.print(f"  [dim]·[/dim] {point}")
    console.print()


def display_suggestion(result: AuralisResult, language: str):
    if result.suggestion:
        console.print(Panel(
            Syntax(result.suggestion, language, theme="monokai", line_numbers=True),
            title="[bold rgb(34,197,94)]Suggested Fix[/bold rgb(34,197,94)]",
            border_style="rgb(34,197,94)",
            padding=(0, 1),
        ))


# ── Streaming analysis ─────────────────────────────────────────────────
async def stream_analyze(
    client: AsyncAuralis,
    code: str,
    language: str,
    animator: SpriteAnimator = None,
) -> AuralisResult | None:
    payload    = {"mode": "analyze", "code": code, "language": language}
    result_obj = None
    buf        = Text()

    # Trigger spinup animation
    if animator:
        animator.trigger("spinup", duration=2.0)

    with Live(
        Panel(buf, title="[dim rgb(168,85,247)]Thinking...[/dim rgb(168,85,247)]", border_style="dim", padding=(0, 1)),
        console=console,
        refresh_per_second=20,
        transient=True,
    ) as live:
        async for event in client._stream_sse(payload):
            if "error" in event:
                console.print(f"[red]Error: {event['error']}[/red]")
                return None
            if "token" in event:
                buf.append(event["token"], style="dim")
                live.update(Panel(
                    buf,
                    title="[dim rgb(168,85,247)]Thinking...[/dim rgb(168,85,247)]",
                    border_style="dim",
                    padding=(0, 1),
                ))
            if "result" in event:
                result_obj = AuralisResult.from_dict(event["result"])

    # Trigger alert if high/blocked
    if result_obj and animator:
        if result_obj.safety_tier in ("high", "blocked"):
            animator.trigger("alert", duration=3.0)

    return result_obj


# ── Commands ───────────────────────────────────────────────────────────
async def cmd_analyze(
    client: AsyncAuralis,
    args: list,
    show_fix: bool = False,
    animator: SpriteAnimator = None,
):
    if not args:
        console.print("[red]Usage: analyze <file>[/red]"); return
    path = Path(args[0]).expanduser().resolve()
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]"); return

    language = detect_language(path)
    code     = path.read_text(encoding="utf-8", errors="ignore")
    console.print(f"\n[dim]Analyzing [bold]{path.name}[/bold] ({language})...[/dim]\n")

    result = await stream_analyze(client, code, language, animator=animator)
    if not result: return

    display_result(result, path)
    if show_fix:
        display_suggestion(result, language)

    save_history({
        "file":  path.name,
        "tier":  result.safety_tier,
        "risks": len(result.risks),
        "time":  datetime.now().strftime("%H:%M %d %b"),
    })
    return result


async def cmd_fix(client: AsyncAuralis, args: list, animator: SpriteAnimator = None):
    result = await cmd_analyze(client, args, show_fix=True, animator=animator)
    if not result or not result.suggestion: return
    path = Path(args[0]).expanduser().resolve()
    console.print()
    if Confirm.ask(f"[bold]Apply fix to [rgb(168,85,247)]{path.name}[/rgb(168,85,247)]?[/bold]"):
        backup = path.with_suffix(path.suffix + ".bak")
        path.rename(backup)
        path.write_text(result.suggestion, encoding="utf-8")
        console.print(f"\n[rgb(34,197,94)]✓ Fix applied.[/rgb(34,197,94)] Backup → [dim]{backup.name}[/dim]\n")
    else:
        console.print("[dim]Fix not applied.[/dim]\n")


async def cmd_scan(client: AsyncAuralis, args: list, animator: SpriteAnimator = None):
    directory = Path(args[0]).expanduser().resolve() if args else Path(".")
    if not directory.is_dir():
        console.print(f"[red]Not a directory: {directory}[/red]"); return

    files = [p for p in directory.rglob("*") if p.suffix.lower() in CODE_EXTENSIONS and p.is_file()]
    if not files:
        console.print(f"[yellow]No code files found in {directory}[/yellow]"); return

    console.print(f"\n[bold rgb(168,85,247)]Scanning {len(files)} file(s) in {directory.name}/[/bold rgb(168,85,247)]\n")

    if animator:
        animator.trigger("spinup", duration=1.0)

    summary = []
    for file in files:
        language = detect_language(file)
        code     = file.read_text(encoding="utf-8", errors="ignore")
        with console.status(f"[dim]{file.name}[/dim]", spinner="dots"):
            try:
                result = await client.analyze(code, language=language)
                summary.append((file, result))
            except Exception as e:
                console.print(f"  [red]✗[/red] {file.name}: {e}"); continue

        if animator and result.safety_tier in ("high", "blocked"):
            animator.trigger("alert", duration=1.5)

        tc = TIER_COLORS[result.safety_tier]
        console.print(
            f"  [{tc}]{TIER_ICONS[result.safety_tier]}[/{tc}] "
            f"[bold]{file.name:<30}[/bold] "
            f"[{tc}]{result.safety_tier:<8}[/{tc}] "
            f"[dim]{len(result.risks)} risk(s)[/dim]"
        )

    console.print()
    console.print(Rule("[dim]Scan Complete[/dim]", style="dim"))
    table = Table(box=box.SIMPLE, header_style="bold dim", show_edge=False, padding=(0, 2))
    table.add_column("File")
    table.add_column("Safety",     width=10)
    table.add_column("Risks",      width=6,  justify="right")
    table.add_column("Confidence", width=12, justify="right")
    table.add_column("Top Risk")
    for file, result in summary:
        tc       = TIER_COLORS[result.safety_tier]
        top_risk = result.risks[0].label if result.risks else "—"
        table.add_row(
            str(file.relative_to(directory)),
            f"[{tc}]{result.safety_tier}[/{tc}]",
            str(len(result.risks)),
            f"{result.confidence}%",
            f"[dim]{top_risk}[/dim]",
        )
    console.print(table)


async def cmd_chat(client: AsyncAuralis, args: list, animator: SpriteAnimator = None):
    messages        = []
    pending_context = ""
    loaded_paths    = []   # list[Path] — files loaded into context, in load order
    active_file     = None # Path | None — target for `write` when no name is given
    current_dir     = Path.cwd()

    def _system_prompt() -> str:
        files_line = (
            "Files currently loaded into this conversation: "
            + ", ".join(p.name for p in loaded_paths) + "."
            if loaded_paths else
            "No files are currently loaded into this conversation."
        )
        write_line = f" The active file for writes is {active_file.name}." if active_file else ""
        return (
            "You are Auralis, a CLI code-safety assistant. You do NOT have general filesystem access — "
            "you only see the contents of files the user has explicitly loaded into this chat with the "
            "`ad <path>` command (which behaves like `cd`: it changes the working directory shown in the "
            "prompt, and if given a file it also loads that file's contents here). "
            f"Current directory: {current_dir}. {files_line}{write_line} "
            "You may propose code changes in a fenced code block; if the user runs `write`, your most "
            "recent fenced code block will be diffed against the active file, re-checked for safety risks, "
            "and saved only after the user confirms (with an automatic backup). "
            "If asked what files you have access to, answer based on the information "
            "above — don't give a generic 'I have no file access' disclaimer."
        )

    def _sync_system_message():
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = _system_prompt()
        else:
            messages.insert(0, {"role": "system", "content": _system_prompt()})

    def _enter(target: Path):
        """cd into target if it's a dir; cd into its parent + load it as context if it's a file."""
        nonlocal current_dir, pending_context, active_file
        if target.is_dir():
            current_dir = target
            console.print(f"[dim]📂 now in [bold]{current_dir}[/bold][/dim]")
            _sync_system_message()
            return

        existing = next((p for p in loaded_paths if p.name == target.name), None)
        if existing:
            current_dir = target.parent
            active_file = existing
            console.print(f"[dim]{target.name} is already in context — set as active file[/dim]")
            _sync_system_message()
            return
        if _looks_binary(target):
            console.print(f"[red]{target.name} looks binary — skipping[/red]"); return
        size = target.stat().st_size
        if size > MAX_CONTEXT_BYTES:
            console.print(
                f"[red]{target.name} is {size // 1024}KB — over the "
                f"{MAX_CONTEXT_BYTES // 1024}KB context limit[/red]"
            ); return
        if any(hint in target.name.lower() for hint in SENSITIVE_NAME_HINTS):
            console.print(f"[yellow]⚠ {target.name} looks like it may contain secrets — adding anyway[/yellow]")

        current_dir = target.parent
        language = detect_language(target)
        code     = target.read_text(encoding="utf-8", errors="ignore")
        pending_context += f"File: {target.name} ({language})\n\n```{language}\n{code}\n```\n\n"
        loaded_paths.append(target)
        active_file = target
        console.print(f"[dim]📄 loaded [bold]{target.name}[/bold] as context (active file)[/dim]")
        _sync_system_message()

    if args:
        target = Path(args[0]).expanduser().resolve()
        if not target.exists():
            console.print(f"[red]Path not found: {target}[/red]"); return
        _enter(target)
        console.print()
    else:
        _sync_system_message()

    console.print(
        "[dim]Type [bold]ad <path>[/bold] to cd / load a file, [bold]write[/bold] to save the last "
        "suggestion to the active file, [bold]files[/bold] to list context, "
        "[bold]exit[/bold] to return to shell[/dim]\n"
    )

    while True:
        try:
            user_input = Prompt.ask(
                f"[bold rgb(168,85,247)]you[/bold rgb(168,85,247)] [dim]({current_dir.name})[/dim]"
            )
        except (KeyboardInterrupt, EOFError):
            break
        stripped = user_input.strip()
        low      = stripped.lower()

        if low in ("exit", "quit"):
            break

        # ── "ad <path>" — Auralis Directory, behaves like cd ────────────
        if low.startswith(("ad ", "add ", "cd ")):
            raw_path = stripped.split(maxsplit=1)[1].strip() if len(stripped.split(maxsplit=1)) > 1 else ""
            if not raw_path:
                console.print("[red]Usage: ad <path>[/red]"); continue

            candidate = Path(raw_path).expanduser()
            candidate = candidate if candidate.is_absolute() else current_dir / candidate
            resolved  = candidate.resolve()
            if not resolved.exists():
                console.print(f"[red]Not found: {resolved}[/red]"); continue
            _enter(resolved)
            continue

        if low == "files":
            console.print(f"[dim]Dir: {current_dir}[/dim]")
            if loaded_paths:
                listing = ", ".join(
                    f"{p.name} (active)" if p == active_file else p.name for p in loaded_paths
                )
                console.print("[dim]In context: " + listing + "[/dim]")
            else:
                console.print("[dim]No files in context yet. Use [bold]ad <path>[/bold].[/dim]")
            continue

        # ── "write [name]" / "save [name]" — apply last code block to a loaded file ──
        if low == "write" or low.startswith("write ") or low == "save" or low.startswith("save "):
            parts_cmd  = stripped.split(maxsplit=1)
            name_arg   = parts_cmd[1].strip() if len(parts_cmd) > 1 else None
            target_file = (
                next((p for p in loaded_paths if p.name == name_arg), None)
                if name_arg else active_file
            )

            if target_file is None:
                if name_arg:
                    loaded_names = ", ".join(p.name for p in loaded_paths) or "none"
                    console.print(f"[red]'{name_arg}' isn't loaded. Loaded files: {loaded_names}[/red]")
                else:
                    console.print("[red]No active file. Load one first with [bold]ad <path>[/bold].[/red]")
                continue

            last_reply = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), None)
            code = _extract_code_block(last_reply) if last_reply else None
            if not code:
                console.print("[red]No code block found in the last response.[/red]"); continue

            current_text = target_file.read_text(encoding="utf-8", errors="ignore")
            if code.rstrip("\n") == current_text.rstrip("\n"):
                console.print(f"[dim]No changes — {target_file.name} already matches the proposed code.[/dim]\n")
                continue

            diff_text = _unified_diff(current_text, code, target_file.name)
            console.print(Panel(
                Syntax(diff_text, "diff", theme="monokai", line_numbers=False),
                title=f"[bold rgb(34,197,94)]Diff for {target_file.name}[/bold rgb(34,197,94)]",
                border_style="rgb(34,197,94)",
                padding=(0, 1),
            ))

            language = detect_language(target_file)
            result   = None
            try:
                with console.status("[dim]Re-checking safety...[/dim]", spinner="dots"):
                    result = await client.analyze(code, language=language)
            except Exception as e:
                console.print(f"[yellow]Safety re-check failed ({e}) — proceeding without it[/yellow]")

            risky = False
            if result:
                tc, icon = TIER_COLORS[result.safety_tier], TIER_ICONS[result.safety_tier]
                risky = result.safety_tier in ("high", "blocked")
                console.print(
                    f"\n  [{tc}]{icon}[/{tc}] [bold]{result.safety_tier.upper()}[/bold]"
                    f"  [dim]confidence {result.confidence}%[/dim]  [dim]{len(result.risks)} risk(s)[/dim]"
                )
                for risk in result.risks[:3]:
                    rc = SEVERITY_COLORS.get(risk.severity, "white")
                    console.print(f"    [{rc}]●[/{rc}] {risk.label}")
                if len(result.risks) > 3:
                    console.print(f"    [dim]+{len(result.risks) - 3} more[/dim]")
                console.print()
                if risky and animator:
                    animator.trigger("alert", duration=2.0)

            if risky:
                proceed = Confirm.ask(
                    f"[bold red]⚠ Flagged {result.safety_tier.upper()} — overwrite "
                    f"{target_file.name} anyway? (backup saved to .bak)[/bold red]",
                    default=False,
                )
            else:
                proceed = Confirm.ask(
                    f"[bold]Overwrite [rgb(168,85,247)]{target_file.name}[/rgb(168,85,247)]? "
                    f"(backup saved to .bak)[/bold]"
                )

            if proceed:
                backup = target_file.with_suffix(target_file.suffix + ".bak")
                target_file.rename(backup)
                target_file.write_text(code, encoding="utf-8")
                console.print(
                    f"[rgb(34,197,94)]✓ Wrote {target_file.name}[/rgb(34,197,94)] — "
                    f"backup → [dim]{backup.name}[/dim]\n"
                )
            else:
                console.print("[dim]Not written.[/dim]\n")
            continue

        content = (pending_context + user_input) if pending_context else user_input
        messages.append({"role": "user", "content": content})
        pending_context = ""

        if animator:
            animator.trigger("spinup", duration=1.5)

        console.print("\n[bold rgb(34,197,94)]auralis[/bold rgb(34,197,94)] ", end="")
        full = ""
        async for token in client.stream_chat(messages):
            print(token, end="", flush=True)
            full += token
        print("\n")
        messages.append({"role": "assistant", "content": full})


def cmd_history():
    history = load_history()
    if not history:
        console.print("[dim]No recent activity.[/dim]\n"); return
    table = Table(box=box.SIMPLE, header_style="bold dim", show_edge=False, padding=(0, 2))
    table.add_column("#",         width=4,  justify="right", style="dim")
    table.add_column("File",      width=30)
    table.add_column("Safety",    width=10)
    table.add_column("Risks",     width=6,  justify="right")
    table.add_column("Time",      style="dim")
    for i, item in enumerate(reversed(history), 1):
        tc = TIER_COLORS.get(item.get("tier", "medium"), "white")
        table.add_row(
            str(i),
            item.get("file", "?"),
            f"[{tc}]{item.get('tier', '?')}[/{tc}]",
            str(item.get("risks", 0)),
            item.get("time", ""),
        )
    console.print(table)


# ── Main shell loop ────────────────────────────────────────────────────
async def shell(api_key: str):
    client   = AsyncAuralis(api_key=api_key)
    animator = SpriteAnimator(console)

    render_welcome(api_key, animator)
    animator.start_idle()

    try:
        while True:
            # Stop idle anim BEFORE blocking on input. A Live display
            # repainting in the background while Prompt.ask() reads stdin
            # is what was causing the corruption and the scroll-lock —
            # the terminal kept getting "new output" every 1/24s, which
            # both confused Live's redraw math and forced auto-scroll.
            animator.stop()

            try:
                raw = Prompt.ask("[bold rgb(168,85,247)]auralis[/bold rgb(168,85,247)]")
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Exiting.[/dim]"); break

            parts = raw.strip().split()
            if not parts:
                animator.start_idle()
                continue
            cmd  = parts[0].lower()
            args = parts[1:]

            if cmd in ("exit", "quit", "q"):
                console.print("[dim]Exiting.[/dim]"); break
            elif cmd == "analyze":
                await cmd_analyze(client, args, animator=animator)
            elif cmd == "fix":
                await cmd_fix(client, args, animator=animator)
            elif cmd == "scan":
                await cmd_scan(client, args, animator=animator)
            elif cmd == "chat":
                await cmd_chat(client, args, animator=animator)
            elif cmd == "history":
                cmd_history()
            elif cmd == "clear":
                render_welcome(api_key)
            elif cmd == "help":
                console.print(Panel(
                    "[rgb(168,85,247) bold]analyze[/rgb(168,85,247) bold] [dim]<file>[/dim]    Scan a file for security risks\n"
                    "[rgb(168,85,247) bold]fix[/rgb(168,85,247) bold]     [dim]<file>[/dim]    Analyze and apply suggested fix\n"
                    "[rgb(168,85,247) bold]scan[/rgb(168,85,247) bold]    [dim]<dir>[/dim]     Scan all code files in a directory\n"
                    "[rgb(168,85,247) bold]chat[/rgb(168,85,247) bold]    [dim][file][/dim]    Interactive chat (file or directory)\n"
                    "[rgb(168,85,247) bold]history[/rgb(168,85,247) bold]           Show recent analyses\n"
                    "[rgb(168,85,247) bold]clear[/rgb(168,85,247) bold]             Redraw welcome screen\n"
                    "[rgb(168,85,247) bold]exit[/rgb(168,85,247) bold]              Quit Auralis",
                    title="[bold]Commands[/bold]",
                    border_style="rgb(126,34,206)",
                    padding=(0, 2),
                ))
            else:
                console.print(f"[dim]Unknown: [bold]{cmd}[/bold]. Type [bold]help[/bold].[/dim]")

            # Restart idle animation after command
            animator = SpriteAnimator(console)
            animator.start_idle()

    finally:
        animator.stop()


# ── Entry point ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(prog="auralis", description="Auralis — AI code intelligence by NixAi")
    parser.add_argument("--key", "-k", default=os.environ.get("CYLINK_API_KEY"), help="cyk_ API key")
    sub = parser.add_subparsers(dest="command")
    p_a = sub.add_parser("analyze"); p_a.add_argument("file"); p_a.add_argument("--fix", action="store_true")
    p_f = sub.add_parser("fix");     p_f.add_argument("file")
    p_s = sub.add_parser("scan");    p_s.add_argument("directory", nargs="?", default=".")
    p_c = sub.add_parser("chat");    p_c.add_argument("path", nargs="?")
    sub.add_parser("history")
    args = parser.parse_args()

    if not args.key:
        console.print("[red]No API key. Use --key or set CYLINK_API_KEY.[/red]"); sys.exit(1)

    client = AsyncAuralis(api_key=args.key)

    if args.command == "analyze":
        asyncio.run(cmd_analyze(client, [args.file], show_fix=args.fix))
    elif args.command == "fix":
        asyncio.run(cmd_fix(client, [args.file]))
    elif args.command == "scan":
        asyncio.run(cmd_scan(client, [args.directory]))
    elif args.command == "chat":
        asyncio.run(cmd_chat(client, [args.path] if args.path else []))
    elif args.command == "history":
        cmd_history()
    else:
        asyncio.run(shell(args.key))


if __name__ == "__main__":
    main()
