"""Command-line interface for Post-it TUI, Hyprland bottom-layer sticky notes, and Waybar."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Sequence

from rich.console import Console
from rich.table import Table

from .desktop import StickyNoteApp, close_sticky_process, is_sticky_running, spawn_sticky_process, sync_desktop_notes
from .models import COLOR_ORDER, NoteStore
from .tui import PostItApp


def cmd_waybar(store: NoteStore) -> None:
    notes = store.list_notes(include_archived=False)
    total_notes = len(notes)
    pinned = [n for n in notes if n.pinned]
    desktop = [n for n in notes if n.on_desktop]

    done_cb = 0
    total_cb = 0
    for n in notes:
        d, t = n.checklist_stats()
        done_cb += d
        total_cb += t

    if total_notes == 0:
        out = {
            "text": "󰠮 0",
            "tooltip": "Post-it TUI — Nessuna nota attiva\nClicca per aprire la bacheca",
            "class": "empty",
        }
        print(json.dumps(out))
        return

    badge = f"󰠮 {total_notes}"
    if total_cb > 0 and done_cb < total_cb:
        badge += f" ({done_cb}/{total_cb}✓)"

    lines = [f"📌 Post-it TUI — {total_notes} note attive ({len(desktop)} sul Desktop)"]
    if total_cb > 0:
        lines.append(f"✓ Checklist totali: {done_cb}/{total_cb} completati")
    lines.append("────────────────────────────")

    shown = pinned[:5] if pinned else notes[:5]
    for n in shown:
        pin_icon = "📌" if n.pinned else "•"
        desk_icon = " 🖥️" if n.on_desktop else ""
        d, t = n.checklist_stats()
        cb_str = f" [{d}/{t}✓]" if t > 0 else ""
        lines.append(f"{pin_icon} {n.title}{cb_str}{desk_icon}")

    lines.append("────────────────────────────")
    lines.append("Click SX: Apri Bacheca  │  Click DX: Mostra/Nascondi Post-it Desktop")

    css_class = "desktop-active" if desktop else "has-notes"
    out = {
        "text": badge,
        "tooltip": "\n".join(lines),
        "class": css_class,
    }
    print(json.dumps(out, ensure_ascii=False))


def cmd_toggle_desktop_all(store: NoteStore) -> None:
    notes = store.list_notes(include_archived=False)
    desktop_notes = [n for n in notes if n.on_desktop]
    if not desktop_notes:
        # If no note is marked on_desktop yet, stick the first pinned/active note!
        if notes:
            notes[0].on_desktop = True
            store.save(notes[0])
            spawn_sticky_process(notes[0])
        return

    any_running = any(is_sticky_running(n.id) for n in desktop_notes)
    if any_running:
        for n in desktop_notes:
            close_sticky_process(n.id)
    else:
        for n in desktop_notes:
            spawn_sticky_process(n)


def cmd_list(store: NoteStore) -> None:
    console = Console()
    notes = store.list_notes(include_archived=True)
    table = Table(title="📌 Post-it TUI — Note Salvate")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Titolo", style="bold yellow")
    table.add_column("Colore", style="magenta")
    table.add_column("Checklist", style="green")
    table.add_column("Stato", style="bright_blue")
    table.add_column("Tag", style="cyan")

    for n in notes:
        d, t = n.checklist_stats()
        cb = f"{d}/{t}" if t > 0 else "-"
        flags = []
        if n.pinned:
            flags.append("📌 Pin")
        if n.on_desktop:
            flags.append("🖥️ Desktop")
        if n.archived:
            flags.append("📦 Archivio")
        table.add_row(
            n.id,
            n.title,
            n.color_theme.label,
            cb,
            " ".join(flags) or "Attivo",
            " ".join(f"#{tag}" for tag in n.all_tags),
        )
    console.print(table)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="postit-tui",
        description="Dracula Corkboard Post-it Note Manager & Hyprland Bottom-Layer Sticky Notes.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    sub.add_parser("tui", help="Avvia la bacheca TUI principale (default)")
    sub.add_parser("daemon", help="Ripristina i Post-it fissati sullo sfondo del desktop di Hyprland")
    sub.add_parser("toggle-desktop", help="Mostra/nasconde i Post-it sullo sfondo del desktop")
    sub.add_parser("waybar", help="Stampa output JSON per Waybar")
    sub.add_parser("list", help="Elenca tutti i Post-it nel terminale")

    p_sticky = sub.add_parser("sticky", help="Avvia la vista singola per il Post-it sul desktop")
    p_sticky.add_argument("note_id", help="ID del Post-it")

    p_add = sub.add_parser("add", help="Crea rapidamente un nuovo Post-it da riga di comando")
    p_add.add_argument("title", help="Titolo del Post-it")
    p_add.add_argument("-b", "--body", default="- [ ] Da fare", help="Contenuto Markdown / Checklist")
    p_add.add_argument("-c", "--color", choices=COLOR_ORDER, default="yellow", help="Colore del Post-it")
    p_add.add_argument("-p", "--pin", action="store_true", help="Fissa in alto in bacheca")
    p_add.add_argument("-d", "--desktop", action="store_true", help="Attacca subito allo sfondo del desktop")
    p_add.add_argument("-t", "--tag", action="append", default=[], help="Tag da associare")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = NoteStore()

    cmd = args.subcommand or "tui"
    if cmd == "tui":
        app = PostItApp(store=store)
        app.run()
        return 0
    if cmd == "sticky":
        app = StickyNoteApp(store=store, note_id=args.note_id)
        app.run()
        return 0
    if cmd == "daemon":
        sync_desktop_notes(store)
        return 0
    if cmd == "toggle-desktop":
        cmd_toggle_desktop_all(store)
        return 0
    if cmd == "waybar":
        cmd_waybar(store)
        return 0
    if cmd == "list":
        cmd_list(store)
        return 0
    if cmd == "add":
        note = store.create_note(
            title=args.title,
            content=args.body.replace("\\n", "\n"),
            color=args.color,
            tags=args.tag,
            pinned=args.pin,
            on_desktop=args.desktop,
        )
        if note.on_desktop:
            spawn_sticky_process(note)
        print(f"Creato Post-it [{note.id}] '{note.title}'")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
