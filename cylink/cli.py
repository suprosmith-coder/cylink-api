"""
auralis — CLI for the Auralis code analysis engine
Part of the cylink SDK (pip install cylink[cli])

Commands:
  auralis analyze <file>   Analyze a file for risks
  auralis fix <file>       Analyze and apply the suggested fix
  auralis chat             Interactive coding session
  auralis scan <dir>       Scan all code files in a directory
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich import print as rprint

from .auralis import AsyncAuralis, AuralisResult

console = Console()

# ── Language detection ─────────────────────────────────────────────────
EXT_MAP = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".jsx":  "javascript",
    ".tsx":  "typescript",
    ".go":   "go",
    ".rs":   "rust",
    ".java": "java",
    ".cs":   "csharp",
    ".cpp":  "cpp",
    ".c":    "c",
    ".rb":   "ruby",
    ".php":  "php",
    ".sh":   "bash",
    ".sql":  "sql",
}

CODE_EXTENSIONS = set(EXT_MAP.keys())

SEVERITY_COLORS = {
    "low":    "yellow",
    "medium": "orange3",
    "high":   "red",
}

TIER_COLORS = {
    "safe":    "green",
    "medium":  "yellow",
    "high":    "orange3",
    "blocked": "red",
}

TIER_ICONS = {
    "safe":    "✅",
    "medium":  "⚠️ ",
    "high":    "🔴",
    "blocked": "🚫",
}


def detect_language(path: Path) -> str:
    return EXT_MAP.get(path.suffix.lower(), "unknown")


# ── Display helpers ────────────────────────────────────────────────────
def print_result(result: AuralisResult, path: Path):
    tier_color = TIER_COLORS[result.safety_tier]
    tier_icon  = TIER_ICONS[result.safety_tier]

    # Header panel
    console.print(Panel(
        f"[bold]{path.name}[/bold]\n"
        f"[dim]{result.intent}[/dim]\n\n"
        f"Safety: [{tier_color}]{tier_icon} {result.safety_tier.upper()}[/{tier_color}]   "
        f"Confidence: [cyan]{result.confidence}%[/cyan]   "
        f"Complexity: [magenta]{result.complexity}[/magenta]",
        title="[bold cyan]Auralis Analysis[/bold cyan]",
        border_style="cyan",
    ))

    # Risks table
    if result.risks:
        table = Table(
            title="Risks",
            border_style="dim",
            header_style="bold",
            show_lines=True,
        )
        table.add_column("Severity", width=10)
        table.add_column("Label", width=28)
        table.add_column("Category", width=24)
        table.add_column("Description")

        for risk in result.risks:
            color = SEVERITY_COLORS.get(risk.severity, "white")
            table.add_row(
                f"[{color}]{risk.severity.upper()}[/{color}]",
                risk.label,
                f"[dim]{risk.category}[/dim]",
                risk.description,
            )

        console.print(table)
    else:
        console.print("[green]No risks found.[/green]\n")

    # Explanation bullets
    if result.explanation:
        console.print("\n[bold]Findings:[/bold]")
        for point in result.explanation:
            console.print(f"  [cyan]•[/cyan] {point}")

    console.print()


def print_suggestion(result: AuralisResult, language: str):
    if result.suggestion:
        console.print(Panel(
            Syntax(result.suggestion, language, theme="monokai", line_numbers=True),
            title="[bold green]Suggested Fix[/bold green]",
            border_style="green",
        ))


# ── Commands ───────────────────────────────────────────────────────────
async def cmd_analyze(api_key: str, file: Path, show_fix: bool = False):
    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        sys.exit(1)

    language = detect_language(file)
    code     = file.read_text(encoding="utf-8")

    console.print(f"\n[dim]Analyzing [bold]{file}[/bold] ({language})...[/dim]")

    client   = AsyncAuralis(api_key=api_key)
    streamed = Text()

    with Live(streamed, console=console, refresh_per_second=15) as live:
        result_obj = None
        payload    = {"mode": "analyze", "code": code, "language": language}

        async for event in client._stream_sse(payload):
            if "error" in event:
                console.print(f"[red]Error: {event['error']}[/red]")
                sys.exit(1)
            if "token" in event:
                streamed.append(event["token"])
                live.update(streamed)
            if "result" in event:
                from .auralis import AuralisResult
                result_obj = AuralisResult.from_dict(event["result"])

    console.clear()

    if not result_obj:
        console.print("[red]No result returned.[/red]")
        sys.exit(1)

    print_result(result_obj, file)

    if show_fix:
        print_suggestion(result_obj, language)

    return result_obj


async def cmd_fix(api_key: str, file: Path):
    result = await cmd_analyze(api_key, file, show_fix=True)

    if not result.suggestion:
        console.print("[yellow]No suggestion returned.[/yellow]")
        return

    language = detect_language(file)

    if Confirm.ask(f"\n[bold]Apply fix to [cyan]{file}[/cyan]?[/bold]"):
        backup = file.with_suffix(file.suffix + ".bak")
        file.rename(backup)
        file.write_text(result.suggestion, encoding="utf-8")
        console.print(f"[green]✅ Fix applied.[/green] Backup saved to [dim]{backup}[/dim]")
    else:
        console.print("[dim]Fix not applied.[/dim]")


async def cmd_scan(api_key: str, directory: Path):
    files = [
        p for p in directory.rglob("*")
        if p.suffix.lower() in CODE_EXTENSIONS and p.is_file()
    ]

    if not files:
        console.print(f"[yellow]No code files found in {directory}[/yellow]")
        return

    console.print(f"\n[bold cyan]Scanning {len(files)} file(s) in {directory}[/bold cyan]\n")

    client  = AsyncAuralis(api_key=api_key)
    summary = []

    for file in files:
        language = detect_language(file)
        code     = file.read_text(encoding="utf-8", errors="ignore")

        with console.status(f"[dim]Analyzing {file.name}...[/dim]"):
            try:
                result = await client.analyze(code, language=language)
                summary.append((file, result))
            except Exception as e:
                console.print(f"[red]  ✗ {file.name}: {e}[/red]")
                continue

        tier_color = TIER_COLORS[result.safety_tier]
        tier_icon  = TIER_ICONS[result.safety_tier]
        risk_count = len(result.risks)
        console.print(
            f"  [{tier_color}]{tier_icon} {result.safety_tier.upper():8}[/{tier_color}] "
            f"[bold]{file.name}[/bold]  "
            f"[dim]{risk_count} risk(s) · {result.confidence}% confidence[/dim]"
        )

    # Summary table
    console.print()
    table = Table(title="Scan Summary", border_style="cyan", header_style="bold")
    table.add_column("File")
    table.add_column("Safety", width=10)
    table.add_column("Risks", width=8, justify="center")
    table.add_column("Confidence", width=12, justify="center")
    table.add_column("Top Risk")

    for file, result in summary:
        tier_color = TIER_COLORS[result.safety_tier]
        top_risk   = result.risks[0].label if result.risks else "—"
        table.add_row(
            str(file.relative_to(directory)),
            f"[{tier_color}]{result.safety_tier.upper()}[/{tier_color}]",
            str(len(result.risks)),
            f"{result.confidence}%",
            top_risk,
        )

    console.print(table)


async def cmd_chat(api_key: str, file: Path | None = None):
    client   = AsyncAuralis(api_key=api_key)
    messages = []

    context = ""
    if file and file.exists():
        language = detect_language(file)
        code     = file.read_text(encoding="utf-8")
        context  = f"File: {file.name} ({language})\n\n```{language}\n{code}\n```\n\n"
        console.print(Panel(
            f"[dim]Loaded [bold]{file.name}[/bold] as context[/dim]",
            border_style="dim"
        ))

    console.print(Panel(
        "[bold cyan]Auralis Chat[/bold cyan]\n[dim]Type [bold]exit[/bold] to quit · [bold]/analyze[/bold] to analyze loaded file[/dim]",
        border_style="cyan",
    ))

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting.[/dim]")
            break

        if user_input.strip().lower() in ("exit", "quit", "/exit"):
            console.print("[dim]Exiting.[/dim]")
            break

        content = (context + user_input) if context and not messages else user_input
        messages.append({"role": "user", "content": content})
        context = ""  # only prepend context on first message

        console.print("\n[bold green]Auralis[/bold green]", end=" ")
        full = ""

        async for token in client.stream_chat(messages):
            print(token, end="", flush=True)
            full += token

        print()
        messages.append({"role": "assistant", "content": full})


# ── Entry point ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="auralis",
        description="Auralis — AI-powered code analysis CLI by NixAi",
    )
    parser.add_argument(
        "--key", "-k",
        default=os.environ.get("CYLINK_API_KEY"),
        help="cyk_ API key (or set CYLINK_API_KEY env var)",
    )

    sub = parser.add_subparsers(dest="command")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze a file for risks")
    p_analyze.add_argument("file", type=Path)
    p_analyze.add_argument("--fix", action="store_true", help="Also show suggested fix")

    # fix
    p_fix = sub.add_parser("fix", help="Analyze and apply suggested fix")
    p_fix.add_argument("file", type=Path)

    # scan
    p_scan = sub.add_parser("scan", help="Scan all code files in a directory")
    p_scan.add_argument("directory", type=Path, default=Path("."), nargs="?")

    # chat
    p_chat = sub.add_parser("chat", help="Interactive chat with Auralis")
    p_chat.add_argument("file", type=Path, nargs="?", help="Optional file to load as context")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if not args.key:
        console.print("[red]No API key provided. Use --key or set CYLINK_API_KEY.[/red]")
        sys.exit(1)

    if args.command == "analyze":
        asyncio.run(cmd_analyze(args.key, args.file, show_fix=args.fix))
    elif args.command == "fix":
        asyncio.run(cmd_fix(args.key, args.file))
    elif args.command == "scan":
        asyncio.run(cmd_scan(args.key, args.directory))
    elif args.command == "chat":
        asyncio.run(cmd_chat(args.key, getattr(args, "file", None)))


if __name__ == "__main__":
    main()
