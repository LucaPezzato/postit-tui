"""Hyprland wlr-layer-shell (bottom layer) desktop sticky Post-it widget with mouse dragging & checklists."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Static, TextArea

from .models import CHECKBOX_RE, NoteStore, PostItNote, _now_iso


def get_socket_path(note_id: str) -> Path:
    return Path(f"/tmp/postit-tui-{note_id}.sock")


def is_sticky_running(note_id: str) -> bool:
    sock_path = get_socket_path(note_id)
    if not sock_path.exists():
        return False
    res = subprocess.run(
        ["pgrep", "-f", f"postit-desktop-{note_id}"],
        capture_output=True,
    )
    if res.returncode != 0:
        try:
            sock_path.unlink()
        except Exception:
            pass
        return False
    return True


def move_or_resize_panel(
    note_id: str,
    x: int | None = None,
    y: int | None = None,
    w: int | None = None,
    h: int | None = None,
) -> bool:
    """Sends zero-overhead Kitty remote control JSON command over the panel's UNIX socket."""
    sock_path = get_socket_path(note_id)
    if not sock_path.exists():
        return False

    panel_args: list[str] = []
    if x is not None:
        panel_args.append(f"margin-left={max(0, int(x))}")
    if y is not None:
        panel_args.append(f"margin-top={max(0, int(y))}")
    if w is not None:
        panel_args.append(f"columns={max(180, int(w))}px")
    if h is not None:
        panel_args.append(f"lines={max(140, int(h))}px")

    if not panel_args:
        return False

    cmd = {
        "cmd": "resize-os-window",
        "version": [0, 36, 0],
        "no_response": True,
        "payload": {
            "action": "os-panel",
            "incremental": True,
            "os_panel": panel_args,
        },
    }
    payload = b"\x1bP@kitty-cmd" + json.dumps(cmd).encode("utf-8") + b"\x1b\\"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.15)
            s.connect(str(sock_path))
            s.sendall(payload)
        return True
    except Exception:
        return False


def get_hypr_cursor_pos() -> tuple[int, int] | None:
    """Returns global (x, y) cursor position from Hyprland."""
    hyprctl = shutil.which("hyprctl")
    if not hyprctl:
        return None
    try:
        raw = subprocess.check_output([hyprctl, "cursorpos", "-j"], timeout=0.2).decode("utf-8")
        data = json.loads(raw)
        return int(data["x"]), int(data["y"])
    except Exception:
        return None


def spawn_sticky_process(note: PostItNote) -> bool:
    if is_sticky_running(note.id):
        return True

    kitty_bin = shutil.which("kitty")
    if not kitty_bin:
        return False

    sock_path = get_socket_path(note.id)
    if sock_path.exists():
        try:
            sock_path.unlink()
        except Exception:
            pass

    cli_bin = str(Path.home() / ".local" / "bin" / "postit-tui")
    if not Path(cli_bin).exists():
        cli_bin = sys.argv[0]

    cmd = [
        kitty_bin,
        "+kitten",
        "panel",
        "--edge=none",
        "--layer=bottom",
        "--focus-policy=on-demand",
        f"--lines={max(160, note.desktop_h)}px",
        f"--columns={max(200, note.desktop_w)}px",
        f"--margin-top={max(0, note.desktop_y)}",
        f"--margin-left={max(0, note.desktop_x)}",
        "-o",
        "allow_remote_control=yes",
        "-o",
        "font_size=10.5",
        "-o",
        "window_padding_width=0",
        "-o",
        "background_opacity=0.94",
        f"--listen-on=unix:{sock_path}",
        f"--app-id=postit-desktop-{note.id}",
        cli_bin,
        "sticky",
        note.id,
    ]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def close_sticky_process(note_id: str) -> None:
    subprocess.run(
        ["pkill", "-f", f"postit-desktop-{note_id}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sock_path = get_socket_path(note_id)
    if sock_path.exists():
        try:
            sock_path.unlink()
        except Exception:
            pass


def sync_desktop_notes(store: NoteStore) -> int:
    count = 0
    for note in store.list_notes(include_archived=False):
        if note.on_desktop:
            if spawn_sticky_process(note):
                count += 1
        elif is_sticky_running(note.id):
            close_sticky_process(note.id)
    return count


class StickyNoteApp(App[None]):
    """Single Desktop Post-it Note running on Wayland bottom layer behind all windows."""

    AUTO_FOCUS = None

    CSS = """
    Screen {
        background: #2b2c24;
        color: #f8f8f2;
        padding: 0;
    }

    #sticky-card {
        width: 100%;
        height: 1fr;
        border: heavy #f1fa8c;
        padding: 0 1;
    }

    #sticky-header {
        width: 100%;
        height: 1;
        text-style: bold;
    }

    #sticky-body {
        width: 100%;
        height: 1fr;
    }

    #sticky-footer {
        width: 100%;
        height: 1;
        color: #6272a4;
    }

    #edit-title {
        height: 3;
        width: 100%;
        display: none;
    }

    #edit-title.visible {
        display: block;
    }

    #edit-body {
        height: 1fr;
        width: 100%;
        display: none;
    }

    #edit-body.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "unstick_and_close", "Unstick", show=False),
        Binding("s", "unstick_and_close", "Unstick", show=False),
        Binding("escape", "cancel_or_save_edit", "Save/Cancel", show=False),
        Binding("ctrl+s", "save_edit", "Save", show=False),
        Binding("c", "cycle_color", "Color", show=False),
        Binding("e", "toggle_edit", "Edit", show=False),
        Binding("space", "toggle_first_checkbox", "Check", show=False),
        Binding("1", "toggle_cb_1", "1", show=False),
        Binding("2", "toggle_cb_2", "2", show=False),
        Binding("3", "toggle_cb_3", "3", show=False),
        Binding("4", "toggle_cb_4", "4", show=False),
        Binding("5", "toggle_cb_5", "5", show=False),
        Binding("h", "move_left", "Left", show=False),
        Binding("left", "move_left", "Left", show=False),
        Binding("l", "move_right", "Right", show=False),
        Binding("right", "move_right", "Right", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("j", "move_down", "Down", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("plus", "grow_note", "Grow", show=False),
        Binding("equal", "grow_note", "Grow", show=False),
        Binding("minus", "shrink_note", "Shrink", show=False),
    ]

    def __init__(self, store: NoteStore, note_id: str) -> None:
        super().__init__()
        self.store = store
        self.note_id = note_id
        self.note: PostItNote = store.get(note_id) or store.create_note(title="Post-it")
        self.editing: bool = False

        self._dragging: bool = False
        self._drag_moved: bool = False
        self._drag_start_cursor: tuple[int, int] | None = None
        self._drag_start_pos: tuple[int, int] = (self.note.desktop_x, self.note.desktop_y)
        self._last_mtime: float = self._get_file_mtime()

    def _get_file_mtime(self) -> float:
        if self.note.file_path and self.note.file_path.exists():
            try:
                return self.note.file_path.stat().st_mtime
            except Exception:
                return 0.0
        return 0.0

    def compose(self) -> ComposeResult:
        with Vertical(id="sticky-card"):
            yield Static(id="sticky-header")
            yield Input(id="edit-title", placeholder="Titolo Post-it…", disabled=True)
            yield Static(id="sticky-body")
            yield TextArea(id="edit-body", disabled=True)
            yield Static(id="sticky-footer")

    def on_mount(self) -> None:
        self.set_focus(None)
        self._refresh_note_view()
        self.set_interval(1.2, self._check_disk_reload)

    def _check_disk_reload(self) -> None:
        if self.editing or self._dragging:
            return
        fresh = self.store.get(self.note_id)
        if not fresh:
            self.exit()
            return
        if not fresh.on_desktop:
            self.exit()
            return
        mtime = self._get_file_mtime()
        if mtime > self._last_mtime or fresh.updated_at != self.note.updated_at or fresh.color != self.note.color:
            self.note = fresh
            self._last_mtime = mtime
            self._refresh_note_view()

    def _refresh_note_view(self) -> None:
        theme = self.note.color_theme
        try:
            self.screen.styles.background = theme.bg_card
            card = self.query_one("#sticky-card", Vertical)
            card.styles.background = theme.bg_card
            card.styles.border = ("heavy", theme.accent)
        except Exception:
            pass

        hdr = Text()
        pin = "📌 " if self.note.pinned else "📝 "
        hdr.append(f"{pin}{self.note.title}", style=f"bold {theme.accent}")
        done, total = self.note.checklist_stats()
        if total > 0:
            hdr.append(f" ({done}/{total})", style="bold #50fa7b" if done == total else "#6272a4")

        body = Text()
        cb_counter = 0
        for line in self.note.content.splitlines():
            m = CHECKBOX_RE.match(line)
            if m:
                cb_counter += 1
                checked = m.group(2).lower() == "x"
                txt = m.group(3)
                num_hint = f"{cb_counter}." if cb_counter <= 9 else "•"
                if checked:
                    body.append(f"{num_hint} [✓] ", style="bold #50fa7b")
                    body.append(f"{txt}\n", style="strike #6272a4")
                else:
                    body.append(f"{num_hint} [ ] ", style=f"bold {theme.accent}")
                    body.append(f"{txt}\n", style=theme.text_color)
            else:
                body.append(f"{line}\n", style=theme.text_color)

        ftr = Text()
        if self.editing:
            ftr.append("[Esc/Ctrl+S] Salva", style=f"bold {theme.accent}")
        else:
            ftr.append("✥ Trascina  [Spazio] ✓  [e] Modifica  [c] Colore  [s] Stacca", style="#6272a4")

        try:
            self.query_one("#sticky-header", Static).update(hdr)
            self.query_one("#sticky-body", Static).update(body)
            self.query_one("#sticky-footer", Static).update(ftr)
        except Exception:
            pass

    # --- Mouse Dragging & Clicking ---

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self.editing or event.button != 1:
            return
        self._dragging = True
        self._drag_moved = False
        self._drag_start_pos = (self.note.desktop_x, self.note.desktop_y)
        self._drag_start_cursor = get_hypr_cursor_pos()
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging or not self._drag_start_cursor:
            return
        cur = get_hypr_cursor_pos()
        if not cur:
            return
        dx = cur[0] - self._drag_start_cursor[0]
        dy = cur[1] - self._drag_start_cursor[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_moved = True
            new_x = max(0, self._drag_start_pos[0] + dx)
            new_y = max(0, self._drag_start_pos[1] + dy)
            if (new_x, new_y) != (self.note.desktop_x, self.note.desktop_y):
                self.note.desktop_x = new_x
                self.note.desktop_y = new_y
                move_or_resize_panel(self.note.id, x=new_x, y=new_y)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.release_mouse()
        if self._drag_moved:
            self.store.save(self.note)
            self._last_mtime = self._get_file_mtime()
        else:
            # Clicked without dragging: check if clicked on a checkbox line in sticky-body!
            content_row = event.screen_y - 2
            if content_row >= 0 and self.note.toggle_checkbox_at_content_line(content_row):
                self.store.save(self.note)
                self._last_mtime = self._get_file_mtime()
                self._refresh_note_view()

    # --- Actions ---

    def action_cycle_color(self) -> None:
        if self.editing:
            return
        self.note.cycle_color()
        self.store.save(self.note)
        self._last_mtime = self._get_file_mtime()
        self._refresh_note_view()

    def action_toggle_first_checkbox(self) -> None:
        if self.editing:
            return
        if self.note.toggle_checkbox_index(-1):
            self.store.save(self.note)
            self._last_mtime = self._get_file_mtime()
            self._refresh_note_view()

    def _toggle_nth(self, idx: int) -> None:
        if self.editing:
            return
        if self.note.toggle_checkbox_index(idx):
            self.store.save(self.note)
            self._last_mtime = self._get_file_mtime()
            self._refresh_note_view()

    def action_toggle_cb_1(self) -> None:
        self._toggle_nth(0)

    def action_toggle_cb_2(self) -> None:
        self._toggle_nth(1)

    def action_toggle_cb_3(self) -> None:
        self._toggle_nth(2)

    def action_toggle_cb_4(self) -> None:
        self._toggle_nth(3)

    def action_toggle_cb_5(self) -> None:
        self._toggle_nth(4)

    def action_move_left(self) -> None:
        if self.editing:
            return
        self.note.desktop_x = max(0, self.note.desktop_x - 24)
        move_or_resize_panel(self.note.id, x=self.note.desktop_x)
        self.store.save(self.note)

    def action_move_right(self) -> None:
        if self.editing:
            return
        self.note.desktop_x += 24
        move_or_resize_panel(self.note.id, x=self.note.desktop_x)
        self.store.save(self.note)

    def action_move_up(self) -> None:
        if self.editing:
            return
        self.note.desktop_y = max(0, self.note.desktop_y - 24)
        move_or_resize_panel(self.note.id, y=self.note.desktop_y)
        self.store.save(self.note)

    def action_move_down(self) -> None:
        if self.editing:
            return
        self.note.desktop_y += 24
        move_or_resize_panel(self.note.id, y=self.note.desktop_y)
        self.store.save(self.note)

    def action_grow_note(self) -> None:
        if self.editing:
            return
        self.note.desktop_w += 30
        self.note.desktop_h += 24
        move_or_resize_panel(self.note.id, w=self.note.desktop_w, h=self.note.desktop_h)
        self.store.save(self.note)

    def action_shrink_note(self) -> None:
        if self.editing:
            return
        self.note.desktop_w = max(200, self.note.desktop_w - 30)
        self.note.desktop_h = max(150, self.note.desktop_h - 24)
        move_or_resize_panel(self.note.id, w=self.note.desktop_w, h=self.note.desktop_h)
        self.store.save(self.note)

    def action_toggle_edit(self) -> None:
        if self.editing:
            self.action_save_edit()
            return
        self.editing = True
        self.query_one("#sticky-body", Static).styles.display = "none"
        t_inp = self.query_one("#edit-title", Input)
        b_inp = self.query_one("#edit-body", TextArea)
        t_inp.value = self.note.title
        b_inp.text = self.note.content
        t_inp.disabled = False
        b_inp.disabled = False
        t_inp.add_class("visible")
        b_inp.add_class("visible")
        b_inp.focus()
        self._refresh_note_view()

    def action_save_edit(self) -> None:
        if not self.editing:
            return
        t_inp = self.query_one("#edit-title", Input)
        b_inp = self.query_one("#edit-body", TextArea)
        self.note.title = t_inp.value.strip() or "Post-it"
        self.note.content = b_inp.text
        self.note.updated_at = _now_iso()
        self.store.save(self.note)
        self._last_mtime = self._get_file_mtime()

        t_inp.remove_class("visible")
        b_inp.remove_class("visible")
        t_inp.disabled = True
        b_inp.disabled = True
        self.query_one("#sticky-body", Static).styles.display = "block"
        self.editing = False
        self.set_focus(None)
        self._refresh_note_view()

    def action_cancel_or_save_edit(self) -> None:
        if self.editing:
            self.action_save_edit()

    def action_unstick_and_close(self) -> None:
        if self.editing:
            return
        self.note.on_desktop = False
        self.store.save(self.note)
        self.exit()
