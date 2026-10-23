"""Dracula-themed Corkboard Post-it Note Manager TUI built with Textual."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Footer, Input, Static, TextArea

from .desktop import close_sticky_process, is_sticky_running, spawn_sticky_process, sync_desktop_notes
from .models import CHECKBOX_RE, COLOR_ORDER, POSTIT_COLORS, NoteStore, PostItNote, _now_iso
from .widgets import ChecklistTextArea


GRID_COLS = 3


class PostItCard(Static):
    """A colored Post-it card rendered inside the Corkboard Grid."""

    class Selected(Message):
        def __init__(self, note_id: str, double_click: bool = False) -> None:
            super().__init__()
            self.note_id = note_id
            self.double_click = double_click

    def __init__(self, note: PostItNote, selected: bool = False) -> None:
        super().__init__(classes="postit-card")
        self.note = note
        self.is_selected = selected

    def on_mount(self) -> None:
        self.refresh_card()

    def refresh_card(self, note: PostItNote | None = None, selected: bool | None = None) -> None:
        if note is not None:
            self.note = note
        if selected is not None:
            self.is_selected = selected

        theme = self.note.color_theme
        bg = theme.bg_selected if self.is_selected else theme.bg_card
        border_type = "heavy" if self.is_selected else "round"
        border_color = theme.accent if self.is_selected else theme.accent

        self.styles.background = bg
        self.styles.border = (border_type, border_color)

        txt = Text()
        # Top line: Pin/Desktop badges + Title
        badges = ""
        if self.note.pinned:
            badges += "📌 "
        if self.note.on_desktop:
            badges += "🖥️ "
        if self.note.archived:
            badges += "📦 "

        title_str = self.note.title
        if len(title_str) > 22:
            title_str = title_str[:21] + "…"
        txt.append(f"{badges}{title_str}\n", style=f"bold {theme.accent}")

        # Body preview (up to 4 lines)
        lines = [ln for ln in self.note.content.splitlines() if ln.strip()][:4]
        if not lines:
            txt.append("  (vuoto)\n", style="italic #6272a4")
        else:
            for ln in lines:
                m = CHECKBOX_RE.match(ln)
                if m:
                    checked = m.group(2).lower() == "x"
                    item_txt = m.group(3)
                    if len(item_txt) > 21:
                        item_txt = item_txt[:20] + "…"
                    if checked:
                        txt.append(" ✓ ", style="bold #50fa7b")
                        txt.append(f"{item_txt}\n", style="strike #6272a4")
                    else:
                        txt.append(" ☐ ", style=f"bold {theme.accent}")
                        txt.append(f"{item_txt}\n", style=theme.text_color)
                else:
                    clean = ln.strip()
                    if len(clean) > 25:
                        clean = clean[:24] + "…"
                    txt.append(f" {clean}\n", style=theme.text_color)

        # Pad remaining lines to keep uniform card feel
        for _ in range(max(0, 4 - len(lines))):
            txt.append("\n")

        # Footer line: Checklist progress + Tags
        done, total = self.note.checklist_stats()
        if total > 0:
            pct_style = "bold #50fa7b" if done == total else f"bold {theme.accent}"
            txt.append(f"[{done}/{total} ✓] ", style=pct_style)

        tags = self.note.all_tags[:2]
        if tags:
            txt.append(" ".join(f"#{t}" for t in tags), style="#8be9fd")
        else:
            txt.append(self.note.updated_at[-5:], style="#6272a4")

        self.update(txt)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Selected(self.note.id, double_click=(event.chain >= 2)))


class PostItApp(App[None]):
    """Main Dracula Corkboard Post-it Note Manager TUI."""

    TITLE = "Post-it TUI"
    SUB_TITLE = "Dracula Corkboard & Hyprland Desktop Sticky Notes"
    AUTO_FOCUS = None

    CSS = """
    Screen {
        background: #1e1f29;
        color: #f8f8f2;
    }

    #top-bar {
        height: 3;
        width: 100%;
        background: #282a36;
        border-bottom: solid #44475a;
        padding: 0 2;
        content-align: left middle;
    }

    #search-bar {
        height: 3;
        width: 100%;
        background: #282a36;
        border: solid #bd93f9;
        padding: 0 1;
        display: none;
    }

    #search-bar.visible {
        display: block;
    }

    #main-split {
        width: 100%;
        height: 1fr;
    }

    #board-pane {
        width: 58%;
        height: 100%;
        border: round #44475a;
        background: #1e1f29;
        padding: 0 1;
    }

    #board-pane.editing {
        width: 40%;
    }

    #corkboard-scroll {
        width: 100%;
        height: 1fr;
    }

    #corkboard-grid {
        width: 100%;
        height: auto;
        grid-size: 3;
        grid-gutter: 1 1;
        padding: 1 0;
    }

    .postit-card {
        width: 100%;
        height: 9;
        padding: 0 1;
        border: round #f1fa8c;
        background: #2b2c24;
    }

    #detail-pane {
        width: 42%;
        height: 100%;
        border: heavy #bd93f9;
        background: #282a36;
        padding: 0 1;
    }

    #detail-pane.editing {
        width: 60%;
    }

    #detail-header {
        width: 100%;
        height: auto;
    }

    #detail-meta {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #detail-body {
        width: 100%;
        height: 1fr;
        padding: 1 1;
        border: round #44475a;
        background: #1e1f29;
    }

    #detail-help {
        width: 100%;
        height: auto;
        color: #6272a4;
    }

    #editor-box {
        width: 100%;
        height: 1fr;
        display: none;
    }

    #editor-box.visible {
        display: block;
    }

    #editor-top-row {
        width: 100%;
        height: 3;
        margin-bottom: 0;
    }

    #edit-title-input {
        width: 64%;
        height: 3;
        border: solid #f1fa8c;
    }

    #edit-tags-input {
        width: 36%;
        height: 3;
        border: solid #8be9fd;
    }

    #edit-content-area {
        width: 100%;
        height: 1fr;
        border: solid #bd93f9;
    }

    #status-bar {
        height: 1;
        width: 100%;
        background: #191a21;
        color: #8be9fd;
        padding: 0 2;
    }

    Footer {
        background: #282a36;
        color: #f8f8f2;
    }
    """

    BINDINGS = [
        Binding("n", "new_note", "Nuovo", show=True),
        Binding("e", "edit_note", "Modifica", show=True),
        Binding("enter", "edit_note", "Modifica", show=False),
        Binding("s", "toggle_desktop_sticky", "Stick Desktop", show=True),
        Binding("c", "cycle_color", "Colore", show=True),
        Binding("p", "toggle_pin", "Pin", show=True),
        Binding("space", "toggle_first_checkbox", "Spunta ✓", show=True),
        Binding("a", "toggle_archive", "Archivia", show=True),
        Binding("A", "toggle_show_archived", "Vedi Archivio", show=True),
        Binding("d", "delete_note", "Elimina", show=True),
        Binding("slash", "open_search", "Cerca", show=True),
        Binding("t", "cycle_tag_filter", "Tag", show=True),
        Binding("ctrl+s", "save_editor", "Salva", show=False),
        Binding("escape", "escape_action", "Indietro", show=False),
        Binding("h", "nav_left", "Left", show=False),
        Binding("left", "nav_left", "Left", show=False),
        Binding("l", "nav_right", "Right", show=False),
        Binding("right", "nav_right", "Right", show=False),
        Binding("k", "nav_up", "Up", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("j", "nav_down", "Down", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("1", "cb_1", "1", show=False),
        Binding("2", "cb_2", "2", show=False),
        Binding("3", "cb_3", "3", show=False),
        Binding("4", "cb_4", "4", show=False),
        Binding("5", "cb_5", "5", show=False),
        Binding("6", "cb_6", "6", show=False),
        Binding("7", "cb_7", "7", show=False),
        Binding("8", "cb_8", "8", show=False),
        Binding("9", "cb_9", "9", show=False),
        Binding("r", "reload_board", "Aggiorna", show=False),
        Binding("q", "quit", "Esci", show=True),
    ]

    def __init__(self, store: NoteStore | None = None) -> None:
        super().__init__()
        self.store = store or NoteStore()
        self.notes: list[PostItNote] = []
        self.selected_idx: int = 0
        self.show_archived: bool = False
        self.search_query: str = ""
        self.active_tag: str = ""
        self.editing: bool = False

    def compose(self) -> ComposeResult:
        yield Static(id="top-bar")
        yield Input(
            placeholder="🔍 Cerca testo o #tag nei Post-it (Invio per confermare, Esc per annullare)…",
            id="search-bar",
            disabled=True,
        )
        with Horizontal(id="main-split"):
            with Vertical(id="board-pane"):
                with VerticalScroll(id="corkboard-scroll"):
                    yield Grid(id="corkboard-grid")
            with Vertical(id="detail-pane"):
                yield Static(id="detail-header")
                yield Static(id="detail-meta")
                yield Static(id="detail-body")
                with Vertical(id="editor-box"):
                    with Horizontal(id="editor-top-row"):
                        yield Input(placeholder="Titolo del Post-it…", id="edit-title-input", disabled=True)
                        yield Input(placeholder="Tag (es. dev, urgent)…", id="edit-tags-input", disabled=True)
                    yield ChecklistTextArea(id="edit-content-area", disabled=True)
                yield Static(id="detail-help")
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.set_focus(None)
        self.query_one("#board-pane", Vertical).border_title = " 📌 Bacheca Post-it (Corkboard) "
        self.query_one("#detail-pane", Vertical).border_title = " 📝 Dettaglio & Checklist "
        sync_desktop_notes(self.store)
        self._load_and_render_board()
        self._set_status("Pronto — [n] Nuovo  [e] Modifica  [s] Attacca al Desktop (dietro le finestre)  [c] Colore  [Spazio/1-9] Checklist")
        self.set_interval(2.0, self._poll_external_changes)

    def _poll_external_changes(self) -> None:
        """Reloads notes if modified by a desktop sticky widget."""
        if self.editing:
            return
        search_bar = self.query_one("#search-bar", Input)
        if search_bar.has_class("visible"):
            return
        cur = self.selected_note
        if not cur:
            return
        fresh = self.store.get(cur.id)
        if fresh and (
            fresh.updated_at != cur.updated_at
            or fresh.color != cur.color
            or fresh.on_desktop != cur.on_desktop
        ):
            self._load_and_render_board(keep_id=cur.id)

    @property
    def selected_note(self) -> PostItNote | None:
        if 0 <= self.selected_idx < len(self.notes):
            return self.notes[self.selected_idx]
        return None

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status-bar", Static).update(f"💡 {msg}")
        except Exception:
            pass

    def _collect_all_tags(self) -> list[str]:
        tags: list[str] = []
        for n in self.store.list_notes(include_archived=self.show_archived):
            for t in n.all_tags:
                if t not in tags:
                    tags.append(t)
        return sorted(tags)

    def _load_and_render_board(self, keep_id: str | None = None) -> None:
        if keep_id is None and self.selected_note:
            keep_id = self.selected_note.id

        all_notes = self.store.list_notes(include_archived=True)
        filtered: list[PostItNote] = []
        for n in all_notes:
            if self.show_archived != n.archived:
                continue
            if self.active_tag and self.active_tag not in n.all_tags:
                continue
            if self.search_query:
                q = self.search_query.lower()
                haystack = f"{n.title} {n.content} {' '.join(n.all_tags)}".lower()
                if q not in haystack:
                    continue
            filtered.append(n)

        self.notes = filtered
        if keep_id:
            for i, n in enumerate(self.notes):
                if n.id == keep_id:
                    self.selected_idx = i
                    break
            else:
                self.selected_idx = min(self.selected_idx, max(0, len(self.notes) - 1))
        else:
            self.selected_idx = min(self.selected_idx, max(0, len(self.notes) - 1))

        self._render_top_bar()
        self._rebuild_grid()
        self._render_detail_pane()

    def _render_top_bar(self) -> None:
        all_active = [n for n in self.store.list_notes(include_archived=False)]
        desktop_count = sum(1 for n in all_active if n.on_desktop)
        pinned_count = sum(1 for n in all_active if n.pinned)
        done_tasks = sum(n.checklist_stats()[0] for n in all_active)
        total_tasks = sum(n.checklist_stats()[1] for n in all_active)

        bar = Text()
        bar.append(" 🟨 POST-IT TUI ", style="bold #282a36 on #f1fa8c")
        mode_lbl = " 📦 ARCHIVIO " if self.show_archived else " 📌 BACHECA ATTIVA "
        mode_style = "bold #282a36 on #ffb86c" if self.show_archived else "bold #282a36 on #bd93f9"
        bar.append(f" {mode_lbl}", style=mode_style)
        bar.append(f"  Note: {len(self.notes)} ", style="bold #f8f8f2")
        bar.append(f"│ 📌 Pin: {pinned_count} ", style="#ff79c6")
        bar.append(f"│ 🖥️ Desktop: {desktop_count} ", style="bold #50fa7b" if desktop_count else "#6272a4")
        if total_tasks > 0:
            bar.append(f"│ ✓ Task: {done_tasks}/{total_tasks} ", style="#8be9fd")
        if self.active_tag:
            bar.append(f"│ 🏷️ #{self.active_tag} ", style="bold #f1fa8c")
        if self.search_query:
            bar.append(f"│ 🔍 \"{self.search_query}\" ", style="bold #ffb86c")

        self.query_one("#top-bar", Static).update(bar)

    def _rebuild_grid(self) -> None:
        grid = self.query_one("#corkboard-grid", Grid)
        cards = list(grid.query(PostItCard))
        for idx, note in enumerate(self.notes):
            is_sel = idx == self.selected_idx
            if idx < len(cards):
                cards[idx].refresh_card(note=note, selected=is_sel)
            else:
                grid.mount(PostItCard(note, selected=is_sel))
        for extra in cards[len(self.notes) :]:
            extra.remove()

    def _update_selection_visuals(self, prev_idx: int, new_idx: int) -> None:
        grid = self.query_one("#corkboard-grid", Grid)
        cards = list(grid.query(PostItCard))
        if 0 <= prev_idx < len(cards):
            cards[prev_idx].refresh_card(selected=False)
        if 0 <= new_idx < len(cards):
            cards[new_idx].refresh_card(selected=True)
            cards[new_idx].scroll_visible()
        self._render_detail_pane()

    def _render_detail_pane(self) -> None:
        pane = self.query_one("#detail-pane", Vertical)
        hdr = self.query_one("#detail-header", Static)
        meta = self.query_one("#detail-meta", Static)
        body = self.query_one("#detail-body", Static)
        help_txt = self.query_one("#detail-help", Static)

        note = self.selected_note
        if not note:
            pane.styles.border = ("heavy", "#6272a4")
            hdr.update(Text("Nessun Post-it selezionato", style="bold #6272a4"))
            meta.update(Text("Premi [n] per creare un nuovo Post-it.", style="#6272a4"))
            body.update(Text(""))
            help_txt.update(Text("[n] Nuovo Post-it   [A] Cambia Vista Archivio   [/] Cerca", style="#6272a4"))
            return

        theme = note.color_theme
        pane.styles.border = ("heavy", theme.accent)
        pane.border_title = f" 📝 Post-it ({theme.label}) "

        # Header
        h_text = Text()
        if note.pinned:
            h_text.append("📌 ", style="bold #ff79c6")
        h_text.append(note.title, style=f"bold {theme.accent}")
        hdr.update(h_text)

        # Meta badges
        m_text = Text()
        m_text.append(f"🎨 {theme.label}  ", style=f"bold {theme.accent}")
        if note.on_desktop:
            m_text.append("🖥️ Su Desktop (Layer Bottom)  ", style="bold #50fa7b")
        else:
            m_text.append("🖥️ Solo Bacheca  ", style="#6272a4")
        done, total = note.checklist_stats()
        if total > 0:
            m_text.append(f"✓ {done}/{total}  ", style="bold #50fa7b" if done == total else "#8be9fd")
        if note.all_tags:
            m_text.append(" ".join(f"#{t}" for t in note.all_tags), style="bold #8be9fd")
        meta.update(m_text)

        # Formatted Markdown & Interactive Checklists
        b_text = Text()
        cb_idx = 0
        for line in note.content.splitlines():
            m = CHECKBOX_RE.match(line)
            if m:
                cb_idx += 1
                checked = m.group(2).lower() == "x"
                item = m.group(3)
                key_hint = f"[{cb_idx}]" if cb_idx <= 9 else " • "
                if checked:
                    b_text.append(f"{key_hint} [✓] ", style="bold #50fa7b")
                    b_text.append(f"{item}\n", style="strike #6272a4")
                else:
                    b_text.append(f"{key_hint} [ ] ", style=f"bold {theme.accent}")
                    b_text.append(f"{item}\n", style="#f8f8f2")
            elif line.startswith("#"):
                b_text.append(f"{line}\n", style=f"bold {theme.accent}")
            else:
                b_text.append(f"{line}\n", style="#f8f8f2")

        body.styles.border = ("round", theme.accent)
        body.styles.background = theme.bg_card
        body.update(b_text)

        if self.editing:
            help_txt.update(
                Text("💾 [Ctrl+S / Esc] Salva modifiche  │  Usa '- [ ] task' per creare checklist!", style="bold #50fa7b")
            )
        else:
            help_txt.update(
                Text(
                    "[e/Invio] Modifica  [s] Stick Desktop  [c] Colore  [p] Pin\n"
                    "[Spazio / 1-9] Spunta task  [a] Archivia  [d] Elimina",
                    style="#6272a4",
                )
            )

    # --- Card Mouse Events ---

    def on_post_it_card_selected(self, message: PostItCard.Selected) -> None:
        for idx, n in enumerate(self.notes):
            if n.id == message.note_id:
                prev = self.selected_idx
                self.selected_idx = idx
                self._update_selection_visuals(prev, idx)
                if message.double_click:
                    self.action_edit_note()
                break

    # --- Grid Navigation ---

    def action_nav_left(self) -> None:
        if self.editing or not self.notes:
            return
        if self.selected_idx > 0:
            prev = self.selected_idx
            self.selected_idx -= 1
            self._update_selection_visuals(prev, self.selected_idx)

    def action_nav_right(self) -> None:
        if self.editing or not self.notes:
            return
        if self.selected_idx + 1 < len(self.notes):
            prev = self.selected_idx
            self.selected_idx += 1
            self._update_selection_visuals(prev, self.selected_idx)

    def action_nav_up(self) -> None:
        if self.editing or not self.notes:
            return
        if self.selected_idx - GRID_COLS >= 0:
            prev = self.selected_idx
            self.selected_idx -= GRID_COLS
            self._update_selection_visuals(prev, self.selected_idx)

    def action_nav_down(self) -> None:
        if self.editing or not self.notes:
            return
        if self.selected_idx + GRID_COLS < len(self.notes):
            prev = self.selected_idx
            self.selected_idx += GRID_COLS
            self._update_selection_visuals(prev, self.selected_idx)

    # --- Note Operations ---

    def action_new_note(self) -> None:
        if self.editing:
            return
        used_colors = [n.color for n in self.notes]
        next_color = COLOR_ORDER[len(used_colors) % len(COLOR_ORDER)]
        note = self.store.create_note(
            title="Nuovo Post-it",
            content="- [ ] Task 1\n- [ ] Task 2",
            color=next_color,
        )
        self.show_archived = False
        self._load_and_render_board(keep_id=note.id)
        self._set_status(f"Creato nuovo Post-it '{note.title}' ({note.color_theme.label})")
        self.action_edit_note()

    def action_edit_note(self) -> None:
        if self.editing:
            self.action_save_editor()
            return
        note = self.selected_note
        if not note:
            return
        self.editing = True
        self.query_one("#board-pane", Vertical).add_class("editing")
        self.query_one("#detail-pane", Vertical).add_class("editing")
        self.query_one("#detail-header", Static).styles.display = "none"
        self.query_one("#detail-meta", Static).styles.display = "none"
        self.query_one("#detail-body", Static).styles.display = "none"

        editor_box = self.query_one("#editor-box", Vertical)
        t_inp = self.query_one("#edit-title-input", Input)
        tags_inp = self.query_one("#edit-tags-input", Input)
        c_area = self.query_one("#edit-content-area", ChecklistTextArea)

        t_inp.border_title = " 📌 Titolo "
        tags_inp.border_title = " 🏷️ Tag "
        c_area.border_title = " ☑️ Contenuto Markdown & Checklist (Invio crea '- [ ]') "

        t_inp.value = note.title
        tags_inp.value = ", ".join(note.tags)
        c_area.text = note.content

        t_inp.disabled = False
        tags_inp.disabled = False
        c_area.disabled = False
        editor_box.add_class("visible")
        c_area.focus()
        self._render_detail_pane()
        self._set_status("Modalità Modifica — [Tab/Shift+Tab] Titolo/Tag/Testo, [Ctrl+S] o [Esc] per salvare")

    def action_save_editor(self) -> None:
        if not self.editing:
            return
        note = self.selected_note
        editor_box = self.query_one("#editor-box", Vertical)
        t_inp = self.query_one("#edit-title-input", Input)
        tags_inp = self.query_one("#edit-tags-input", Input)
        c_area = self.query_one("#edit-content-area", ChecklistTextArea)

        if note:
            note.title = t_inp.value.strip() or "Post-it"
            note.tags = [t.strip().lower().lstrip("#") for t in tags_inp.value.split(",") if t.strip()]
            note.content = c_area.text
            note.updated_at = _now_iso()
            self.store.save(note)

        editor_box.remove_class("visible")
        t_inp.disabled = True
        tags_inp.disabled = True
        c_area.disabled = True
        self.query_one("#board-pane", Vertical).remove_class("editing")
        self.query_one("#detail-pane", Vertical).remove_class("editing")
        self.query_one("#detail-header", Static).styles.display = "block"
        self.query_one("#detail-meta", Static).styles.display = "block"
        self.query_one("#detail-body", Static).styles.display = "block"
        self.editing = False
        self.set_focus(None)

        if note:
            self._load_and_render_board(keep_id=note.id)
            self._set_status(f"Salvato Post-it '{note.title}'")

    def action_cycle_color(self) -> None:
        if self.editing:
            return
        note = self.selected_note
        if not note:
            return
        note.cycle_color()
        self.store.save(note)
        self._load_and_render_board(keep_id=note.id)
        self._set_status(f"Colore cambiato in {note.color_theme.label}")

    def action_toggle_pin(self) -> None:
        if self.editing:
            return
        note = self.selected_note
        if not note:
            return
        note.pinned = not note.pinned
        note.updated_at = _now_iso()
        self.store.save(note)
        self._load_and_render_board(keep_id=note.id)
        state = "fissato in alto 📌" if note.pinned else "rimosso dai pin"
        self._set_status(f"Post-it '{note.title}' {state}")

    def action_toggle_desktop_sticky(self) -> None:
        if self.editing:
            return
        note = self.selected_note
        if not note:
            return
        note.on_desktop = not note.on_desktop
        note.updated_at = _now_iso()
        self.store.save(note)
        if note.on_desktop:
            ok = spawn_sticky_process(note)
            if ok:
                self._set_status(
                    f"🖥️ Post-it '{note.title}' attaccato allo sfondo del Desktop (dietro le finestre)! Trascinalo col mouse."
                )
            else:
                self._set_status("Impossibile avviare kitty panel per il desktop sticky.")
        else:
            close_sticky_process(note.id)
            self._set_status(f"🖥️ Post-it '{note.title}' staccato dallo sfondo del Desktop.")
        self._load_and_render_board(keep_id=note.id)

    def action_toggle_archive(self) -> None:
        if self.editing:
            return
        note = self.selected_note
        if not note:
            return
        note.archived = not note.archived
        if note.archived and note.on_desktop:
            note.on_desktop = False
            close_sticky_process(note.id)
        note.updated_at = _now_iso()
        self.store.save(note)
        msg = f"📦 Post-it '{note.title}' archiviato" if note.archived else f"📌 Post-it '{note.title}' ripristinato in bacheca"
        self._load_and_render_board()
        self._set_status(msg)

    def action_toggle_show_archived(self) -> None:
        if self.editing:
            return
        self.show_archived = not self.show_archived
        self.selected_idx = 0
        self._load_and_render_board()
        view_name = "Archivio Post-it" if self.show_archived else "Bacheca Attiva"
        self._set_status(f"Vista passata a: {view_name}")

    def action_delete_note(self) -> None:
        if self.editing:
            return
        note = self.selected_note
        if not note:
            return
        title = note.title
        close_sticky_process(note.id)
        self.store.delete(note.id)
        self._load_and_render_board()
        self._set_status(f"🗑️ Eliminato Post-it '{title}'")

    # --- Interactive Checklist Toggling ---

    def _toggle_cb(self, idx: int) -> None:
        if self.editing:
            return
        note = self.selected_note
        if not note:
            return
        if note.toggle_checkbox_index(idx):
            self.store.save(note)
            self._load_and_render_board(keep_id=note.id)
            done, total = note.checklist_stats()
            self._set_status(f"✓ Checklist aggiornata ({done}/{total} completati)")
        else:
            self._set_status("Nessuna checklist '- [ ]' trovata in questo Post-it (premi [e] per aggiungerla)")

    def action_toggle_first_checkbox(self) -> None:
        self._toggle_cb(-1)

    def action_cb_1(self) -> None:
        self._toggle_cb(0)

    def action_cb_2(self) -> None:
        self._toggle_cb(1)

    def action_cb_3(self) -> None:
        self._toggle_cb(2)

    def action_cb_4(self) -> None:
        self._toggle_cb(3)

    def action_cb_5(self) -> None:
        self._toggle_cb(4)

    def action_cb_6(self) -> None:
        self._toggle_cb(5)

    def action_cb_7(self) -> None:
        self._toggle_cb(6)

    def action_cb_8(self) -> None:
        self._toggle_cb(7)

    def action_cb_9(self) -> None:
        self._toggle_cb(8)

    # --- Search & Tag Filter ---

    def action_open_search(self) -> None:
        if self.editing:
            return
        sb = self.query_one("#search-bar", Input)
        sb.disabled = False
        sb.value = self.search_query
        sb.add_class("visible")
        sb.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-bar":
            self.search_query = event.value.strip()
            event.input.remove_class("visible")
            event.input.disabled = True
            self.set_focus(None)
            self.selected_idx = 0
            self._load_and_render_board()
            if self.search_query:
                self._set_status(f"Filtro attivo: '{self.search_query}' (premi [Esc] per mostrare tutti)")
            else:
                self._set_status("Filtro rimosso")
        elif event.input.id in ("edit-title-input", "edit-tags-input"):
            self.query_one("#edit-content-area", ChecklistTextArea).focus()

    def action_cycle_tag_filter(self) -> None:
        if self.editing:
            return
        tags = self._collect_all_tags()
        if not tags:
            self._set_status("Nessun #tag presente nelle note.")
            return
        if not self.active_tag:
            self.active_tag = tags[0]
        else:
            try:
                idx = tags.index(self.active_tag)
                self.active_tag = tags[idx + 1] if idx + 1 < len(tags) else ""
            except ValueError:
                self.active_tag = ""
        self.selected_idx = 0
        self._load_and_render_board()
        if self.active_tag:
            self._set_status(f"🏷️ Filtro Tag: #{self.active_tag} (premi [t] per cambiare o [Esc] per azzerare)")
        else:
            self._set_status("🏷️ Filtro Tag rimosso (tutte le note)")

    def action_escape_action(self) -> None:
        if self.editing:
            self.action_save_editor()
            return
        sb = self.query_one("#search-bar", Input)
        if sb.has_class("visible"):
            sb.remove_class("visible")
            sb.disabled = True
            self.set_focus(None)
            return
        if self.search_query or self.active_tag:
            self.search_query = ""
            self.active_tag = ""
            self._load_and_render_board()
            self._set_status("Filtri azzerati")

    def action_reload_board(self) -> None:
        if self.editing:
            return
        sync_desktop_notes(self.store)
        self._load_and_render_board()
        self._set_status("Bacheca e Post-it sul desktop sincronizzati!")
