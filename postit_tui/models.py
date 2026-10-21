"""Data model and Markdown+Frontmatter storage for Post-it notes."""

from __future__ import annotations

import datetime
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


NOTES_DIR = Path.home() / ".local" / "share" / "postit-tui" / "notes"


@dataclass(frozen=True)
class PostItColor:
    key: str
    label: str
    accent: str
    bg_card: str
    bg_selected: str
    text_color: str


POSTIT_COLORS: dict[str, PostItColor] = {
    "yellow": PostItColor(
        key="yellow",
        label="Giallo",
        accent="#f1fa8c",
        bg_card="#2b2c24",
        bg_selected="#383a2c",
        text_color="#f8f8f2",
    ),
    "pink": PostItColor(
        key="pink",
        label="Rosa",
        accent="#ff79c6",
        bg_card="#2d232e",
        bg_selected="#3c2d3e",
        text_color="#f8f8f2",
    ),
    "purple": PostItColor(
        key="purple",
        label="Viola",
        accent="#bd93f9",
        bg_card="#272433",
        bg_selected="#342f46",
        text_color="#f8f8f2",
    ),
    "green": PostItColor(
        key="green",
        label="Verde",
        accent="#50fa7b",
        bg_card="#212d28",
        bg_selected="#2b3c34",
        text_color="#f8f8f2",
    ),
    "cyan": PostItColor(
        key="cyan",
        label="Azzurro",
        accent="#8be9fd",
        bg_card="#212b32",
        bg_selected="#2b3942",
        text_color="#f8f8f2",
    ),
    "orange": PostItColor(
        key="orange",
        label="Arancione",
        accent="#ffb86c",
        bg_card="#2e2722",
        bg_selected="#3d332c",
        text_color="#f8f8f2",
    ),
}

COLOR_ORDER = ["yellow", "pink", "purple", "green", "cyan", "orange"]

CHECKBOX_RE = re.compile(r"^(\s*(?:[-*•]\s+)?)\[([ xX])\]\s+(.*)$")
INLINE_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z0-9_-]{2,24})\b")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:28] or "note"


def _now_iso() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


@dataclass
class PostItNote:
    id: str
    title: str
    content: str
    color: str = "yellow"
    pinned: bool = False
    archived: bool = False
    on_desktop: bool = False
    desktop_x: int = 80
    desktop_y: int = 70
    desktop_w: int = 310
    desktop_h: int = 250
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    file_path: Path | None = None

    @property
    def color_theme(self) -> PostItColor:
        return POSTIT_COLORS.get(self.color, POSTIT_COLORS["yellow"])

    def cycle_color(self) -> str:
        idx = COLOR_ORDER.index(self.color) if self.color in COLOR_ORDER else 0
        self.color = COLOR_ORDER[(idx + 1) % len(COLOR_ORDER)]
        self.updated_at = _now_iso()
        return self.color

    @property
    def all_tags(self) -> list[str]:
        combined = list(self.tags)
        for m in INLINE_TAG_RE.finditer(f"{self.title} {self.content}"):
            tag = m.group(1).lower()
            if tag not in combined:
                combined.append(tag)
        return combined

    def checklist_stats(self) -> tuple[int, int]:
        """Returns (done_count, total_count) of checklist items in content."""
        done = 0
        total = 0
        for line in self.content.splitlines():
            m = CHECKBOX_RE.match(line)
            if m:
                total += 1
                if m.group(2).lower() == "x":
                    done += 1
        return done, total

    def get_checkbox_lines(self) -> list[tuple[int, bool, str]]:
        """Returns list of (line_index, is_checked, item_text)."""
        items: list[tuple[int, bool, str]] = []
        for idx, line in enumerate(self.content.splitlines()):
            m = CHECKBOX_RE.match(line)
            if m:
                items.append((idx, m.group(2).lower() == "x", m.group(3)))
        return items

    def toggle_checkbox_index(self, checkbox_idx: int = 0) -> bool:
        """Toggles the Nth checkbox in the note (or first unchecked if checkbox_idx == -1)."""
        lines = self.content.splitlines()
        cbs = self.get_checkbox_lines()
        if not cbs:
            return False

        if checkbox_idx < 0:
            # Find first unchecked, or wrap to first checkbox
            target = next((item for item in cbs if not item[1]), cbs[0])
        elif checkbox_idx < len(cbs):
            target = cbs[checkbox_idx]
        else:
            return False

        line_no, is_checked, _ = target
        m = CHECKBOX_RE.match(lines[line_no])
        if not m:
            return False
        new_mark = " " if is_checked else "x"
        lines[line_no] = f"{m.group(1)}[{new_mark}] {m.group(3)}"
        self.content = "\n".join(lines)
        self.updated_at = _now_iso()
        return True

    def toggle_checkbox_at_content_line(self, content_line_idx: int) -> bool:
        lines = self.content.splitlines()
        if not (0 <= content_line_idx < len(lines)):
            return False
        m = CHECKBOX_RE.match(lines[content_line_idx])
        if not m:
            return False
        new_mark = " " if m.group(2).lower() == "x" else "x"
        lines[content_line_idx] = f"{m.group(1)}[{new_mark}] {m.group(3)}"
        self.content = "\n".join(lines)
        self.updated_at = _now_iso()
        return True

    def to_markdown(self) -> str:
        meta = {
            "id": self.id,
            "title": self.title,
            "color": self.color,
            "pinned": self.pinned,
            "archived": self.archived,
            "on_desktop": self.on_desktop,
            "desktop_x": self.desktop_x,
            "desktop_y": self.desktop_y,
            "desktop_w": self.desktop_w,
            "desktop_h": self.desktop_h,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        frontmatter = json.dumps(meta, indent=2, ensure_ascii=False)
        return f"---\n{frontmatter}\n---\n{self.content.rstrip()}\n"

    @classmethod
    def from_markdown(cls, raw: str, path: Path | None = None) -> PostItNote:
        meta: dict[str, Any] = {}
        body = raw
        if raw.startswith("---\n"):
            parts = raw.split("\n---\n", 1)
            if len(parts) == 2:
                header_str = parts[0][4:].strip()
                body = parts[1].rstrip("\n")
                try:
                    meta = json.loads(header_str)
                except Exception:
                    # Simple key: value fallback
                    for ln in header_str.splitlines():
                        if ":" in ln:
                            k, v = ln.split(":", 1)
                            meta[k.strip()] = v.strip().strip('"')

        note_id = str(meta.get("id") or (path.stem.split("-")[0] if path else uuid.uuid4().hex[:8]))
        title = str(meta.get("title") or (path.stem if path else "Nuovo Post-it"))
        color = str(meta.get("color") or "yellow")
        if color not in POSTIT_COLORS:
            color = "yellow"

        raw_tags = meta.get("tags") or []
        tags = [str(t).lower().lstrip("#") for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []

        return cls(
            id=note_id,
            title=title,
            content=body,
            color=color,
            pinned=bool(meta.get("pinned", False)),
            archived=bool(meta.get("archived", False)),
            on_desktop=bool(meta.get("on_desktop", False)),
            desktop_x=int(meta.get("desktop_x", 80)),
            desktop_y=int(meta.get("desktop_y", 70)),
            desktop_w=int(meta.get("desktop_w", 310)),
            desktop_h=int(meta.get("desktop_h", 250)),
            tags=tags,
            created_at=str(meta.get("created_at") or _now_iso()),
            updated_at=str(meta.get("updated_at") or _now_iso()),
            file_path=path,
        )


class NoteStore:
    """Manages reading, writing, and searching Markdown Post-it notes on disk."""

    def __init__(self, notes_dir: Path = NOTES_DIR) -> None:
        self.notes_dir = notes_dir
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_seed_notes()

    def _ensure_seed_notes(self) -> None:
        marker = self.notes_dir.parent / ".seeded"
        if marker.exists() or list(self.notes_dir.glob("*.md")):
            marker.touch(exist_ok=True)
            return

        samples = [
            PostItNote(
                id="p101",
                title="Benvenuto su Post-it TUI!",
                content=(
                    "- [x] Sviluppare bacheca Post-it Dracula\n"
                    "- [ ] Premi [s] per attaccare questo Post-it allo sfondo di Hyprland!\n"
                    "- [ ] Premi [Spazio] o [1-9] per spuntare i task\n"
                    "- [ ] Premi [c] per cambiare colore"
                ),
                color="yellow",
                pinned=True,
                tags=["welcome", "hyprland"],
                desktop_x=80,
                desktop_y=70,
            ),
            PostItNote(
                id="p102",
                title="Idee & Progetti TUI",
                content=(
                    "- [x] yt-music-tui (YouTube Music)\n"
                    "- [x] twitch-tui (Live + IRC Chat)\n"
                    "- [x] postit-tui (Sticky Notes)\n"
                    "- [ ] Prossimo tool da TUI-ficare!"
                ),
                color="purple",
                pinned=True,
                tags=["dev", "tui"],
                desktop_x=420,
                desktop_y=70,
            ),
            PostItNote(
                id="p103",
                title="Promemoria Veloce",
                content=(
                    "I Post-it attaccati al desktop con [s] vivono sul layer 'bottom' di Wayland:\n"
                    "restano sempre DIETRO le finestre normali e puoi trascinarli col mouse!"
                ),
                color="pink",
                pinned=False,
                tags=["tips"],
                desktop_x=80,
                desktop_y=350,
            ),
        ]
        for s in samples:
            self.save(s)
        marker.touch(exist_ok=True)

    def list_notes(self, include_archived: bool = True) -> list[PostItNote]:
        notes: list[PostItNote] = []
        for path in self.notes_dir.glob("*.md"):
            try:
                raw = path.read_text(encoding="utf-8")
                note = PostItNote.from_markdown(raw, path=path)
                if not include_archived and note.archived:
                    continue
                notes.append(note)
            except Exception:
                continue

        notes.sort(
            key=lambda n: (
                n.archived,
                not n.pinned,
                -self._parse_ts(n.updated_at),
                n.title.lower(),
            )
        )
        return notes

    @staticmethod
    def _parse_ts(ts_str: str) -> float:
        try:
            dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
            return dt.timestamp()
        except Exception:
            return 0.0

    def get(self, note_id: str) -> PostItNote | None:
        for n in self.list_notes(include_archived=True):
            if n.id == note_id:
                return n
        return None

    def save(self, note: PostItNote) -> Path:
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        expected_name = f"{note.id}-{_slugify(note.title)}.md"
        target_path = self.notes_dir / expected_name

        # Remove old file if title slug changed
        if note.file_path and note.file_path.exists() and note.file_path != target_path:
            try:
                note.file_path.unlink()
            except Exception:
                pass
        else:
            for existing in self.notes_dir.glob(f"{note.id}-*.md"):
                if existing != target_path:
                    try:
                        existing.unlink()
                    except Exception:
                        pass

        target_path.write_text(note.to_markdown(), encoding="utf-8")
        note.file_path = target_path
        return target_path

    def delete(self, note_id: str) -> bool:
        deleted = False
        for existing in self.notes_dir.glob(f"{note_id}-*.md"):
            try:
                existing.unlink()
                deleted = True
            except Exception:
                pass
        return deleted

    def create_note(
        self,
        title: str = "Nuovo Post-it",
        content: str = "- [ ] Nuovo task",
        color: str = "yellow",
        tags: list[str] | None = None,
        pinned: bool = False,
        on_desktop: bool = False,
    ) -> PostItNote:
        existing = self.list_notes()
        offset = (len(existing) % 5) * 40
        note = PostItNote(
            id=uuid.uuid4().hex[:6],
            title=title.strip() or "Nuovo Post-it",
            content=content,
            color=color if color in POSTIT_COLORS else "yellow",
            pinned=pinned,
            on_desktop=on_desktop,
            desktop_x=80 + offset,
            desktop_y=70 + offset,
            tags=tags or [],
        )
        self.save(note)
        return note
