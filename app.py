"""File Explorer for the Tildagon badge: browse the badge's flash and any SD card, view
files, and copy, move, rename, delete and create folders and files.

Keys (the six edge buttons, or a USB keyboard's arrows, Enter and Escape):
  UP / DOWN     move through the list (hold to repeat); a typed letter jumps to a name
  OK            open a folder, or view a file
  CANCEL        up one folder; on the storage list, leave the app
  RIGHT         menu for the highlighted item (Open, Copy, Cut, Rename, Delete, Info)
  LEFT          menu for this folder (Paste here, New folder, New file, Refresh, Storage info)

License: MIT
"""
import time

import app

from app_components.dialog import TextDialog
from app_components.tokens import clear_background
from events.input import Buttons, BUTTON_TYPES, ButtonDownEvent
from system.eventbus import eventbus

from . import fs, ui

try:
    from events.keyboard import KEYBOARD_BUTTONS
except ImportError:
    KEYBOARD_BUTTONS = {}

ROWS = 5
ROW_H = 24
ROW_Y0 = -50
TOAST_MS = 2500
HOLD_MS = 400      # how long UP/DOWN is held before it repeats
REPEAT_MS = 70
JOB_SLICE_MS = 40  # how long a copy/delete works per frame before drawing again
VIEW_LINES = 6
HEX_BYTES = 6      # bytes per hex line
TEXT_LIMIT = 4096  # how much of a text file is shown


class FileExplorer(app.App):
    def __init__(self):
        super().__init__()
        self.buttons = Buttons(self)
        self.keyboard = KEYBOARD_BUTTONS
        self.mode = "browse"      # browse | menu | job | view | info
        self.path = None          # None = the list of storages
        self.entries = []         # (name, full path, is_dir, size)
        self.cur = 0
        self.top = 0
        self.stores = None        # cached fs.storages(): the flash's statvfs is slow
        self.clipboard = None     # (path, "copy" | "cut")
        self.menu_title = ""
        self.menu_items = []      # (label, function)
        self.menu_cur = 0
        self.job = None
        self.job_label = ""
        self.job_done = 0
        self.job_total = 1
        self.job_then = None
        self.view_path = ""
        self.view_mode = "text"
        self.view_lines = []
        self.view_pos = 0
        self.view_size = 0
        self.info_lines = []
        self._held = 0
        self._toast = ""
        self._toast_ms = 0
        self._tdlg = None
        self._tdlg_done = None
        self._load(None)
        self.note("Menus: RIGHT, LEFT")

    # --- small services ---

    def note(self, msg):
        self._toast, self._toast_ms = msg, TOAST_MS

    def _fail(self, e):
        self.note(str(e)[:40] or type(e).__name__)

    def ask_text(self, prompt, initial, on_done):
        """Firmware text entry: the badge's buttons pick letters, a USB keyboard types."""
        dlg = TextDialog(prompt, self, on_complete=self._text_done, on_cancel=self._text_close)
        dlg.text = initial
        self._tdlg, self._tdlg_done = dlg, on_done
        self.overlays.append(dlg)
        eventbus.on(ButtonDownEvent, self._text_extra_keys, self)

    def _text_close(self):
        if self._tdlg is not None:
            if self._tdlg in self.overlays:
                self.overlays.remove(self._tdlg)
            eventbus.remove(ButtonDownEvent, self._text_extra_keys, self)
            self._tdlg = None
        self.buttons.clear()

    def _text_done(self):
        text, done = (self._tdlg.text if self._tdlg else ""), self._tdlg_done
        self._text_close()
        if done:
            done(text)

    def _text_extra_keys(self, event):
        """Enter and Escape on a USB keyboard: the firmware dialog doesn't act on those."""
        dlg = self._tdlg
        if dlg is None or dlg._result is not None or "ENTER" not in self.keyboard:
            return
        if self.keyboard["ENTER"] in event.button and event.button.find_parent_in_group("Keyboard"):
            dlg._cleanup()
            dlg._result = dlg.text
            self._text_done()
        elif self.keyboard["ESCAPE"] in event.button and event.button.find_parent_in_group("Keyboard"):
            dlg._cleanup()
            dlg._result = False
            self._text_close()

    # --- browsing ---

    def _load(self, path, select=None, refresh=False):
        """Show a folder (or the storage list for None). Returns False if it can't be read."""
        try:
            if path is None:
                if self.stores is None or refresh:
                    self.stores = fs.storages()
                entries = [(label, p, True, total) for label, p, total, _free in self.stores]
            else:
                entries = [(n, fs.join(path, n), d, s) for n, d, s in fs.listdir(path)]
        except OSError:
            self.note("Cannot read folder")
            return False
        self.path, self.entries, self.cur, self.top = path, entries, 0, 0
        if select:
            for i, e in enumerate(entries):
                if e[0] == select:
                    self._goto(i)
                    break
        return True

    def _goto(self, i):
        self.cur = i
        self.top = max(0, min(i - ROWS // 2, len(self.entries) - ROWS))

    def _move(self, d):
        n = len(self.entries)
        if not n:
            return
        self.cur = (self.cur + d) % n
        if self.cur < self.top:
            self.top = self.cur
        elif self.cur >= self.top + ROWS:
            self.top = self.cur - ROWS + 1

    def _jump(self, ch):
        n = len(self.entries)
        for k in range(1, n + 1):
            i = (self.cur + k) % n
            if self.entries[i][0].lower().startswith(ch):
                self._move(i - self.cur)
                return

    def _selected(self):
        return self.entries[self.cur] if self.entries else None

    def _enter(self):
        e = self._selected()
        if e is None:
            return
        if e[2]:
            self._load(e[1])
        else:
            self._open_file(e[1])

    def _up(self):
        if self.path is None:
            self.minimise()
        elif self.path in fs.mounts():   # the top of a storage
            name = "Flash" if self.path == "/" else self.path[1:]
            self._load(None, select=name)
        else:
            self._load(fs.parent(self.path), select=fs.basename(self.path))

    def _reload(self, select=None):
        if self.path is not None and not fs.exists(self.path):
            self._load(None)
        else:
            self._load(self.path, select=select, refresh=self.path is None)

    # --- menus ---

    def _open_menu(self, title, items):
        self.menu_title, self.menu_items, self.menu_cur, self.mode = title, items, 0, "menu"
        self.buttons.clear()

    def _close_menu(self):
        self.mode = "browse"
        self.buttons.clear()

    def _item_menu(self):
        e = self._selected()
        if e is None:
            return
        name, full, is_dir, _size = e
        if self.path is None:
            self._open_menu(name, [("Open", lambda: self._after(self._enter)),
                                   ("Info", lambda: self._info(e))])
            return
        self._open_menu(name, [
            ("Open", lambda: self._after(self._enter)),
            ("Copy", lambda: self._clip(full, "copy")),
            ("Cut", lambda: self._clip(full, "cut")),
            ("Rename", lambda: self._after(lambda: self._rename(e))),
            ("Delete", lambda: self._confirm_delete(e)),
            ("Info", lambda: self._info(e)),
        ])

    def _folder_menu(self):
        if self.path is None:
            self._open_menu("Storage", [("Refresh", lambda: self._after(lambda: self._reload()))])
            return
        items = []
        if self.clipboard:
            verb = "Paste" if self.clipboard[1] == "copy" else "Move"
            items.append((verb + " here", lambda: self._after(self._paste)))
        items += [("New folder", lambda: self._after(self._new_folder)),
                  ("New file", lambda: self._after(self._new_file)),
                  ("Refresh", lambda: self._after(lambda: self._reload())),
                  ("Storage info", self._storage_info)]
        self._open_menu(fs.basename(self.path), items)

    def _after(self, fn):
        """Close the menu, then do fn (which may open another mode)."""
        self._close_menu()
        fn()

    def _clip(self, full, mode):
        self.clipboard = (full, mode)
        self._close_menu()
        self.note(("Copied " if mode == "copy" else "Cut ") + fs.basename(full))

    # --- actions ---

    def _rename(self, e):
        def done(text):
            try:
                self._reload(select=fs.basename(fs.rename(e[1], text)))
            except fs.FSError as err:
                self._fail(err)
        self.ask_text("Rename", e[0], done)

    def _new_folder(self):
        def done(text):
            try:
                name = fs.check_name(text)
                fs.mkdir(fs.join(self.path, name))
                self._reload(select=name)
            except fs.FSError as err:
                self._fail(err)
        self.ask_text("New folder", "", done)

    def _new_file(self):
        def done(text):
            try:
                name = fs.check_name(text)
                fs.mkfile(fs.join(self.path, name))
                self._reload(select=name)
                self.note("Created " + name)
            except fs.FSError as err:
                self._fail(err)
        self.ask_text("New file", "", done)

    def _confirm_delete(self, e):
        self._open_menu("Delete %s?" % e[0], [("No", self._close_menu),
                                              ("Yes, delete", lambda: self._after(lambda: self._delete(e)))])

    def _delete(self, e):
        def then():
            if self.clipboard and self.clipboard[0] == e[1]:
                self.clipboard = None
            self._reload()
            self.note("Deleted " + e[0])
        self._start_job(fs.delete(e[1]), "Deleting " + e[0], then)

    def _paste(self):
        if not self.clipboard:
            self.note("Nothing to paste")
            return
        src, mode = self.clipboard
        if not fs.exists(src):
            self.clipboard = None
            self.note("Item no longer exists")
            return
        if mode == "cut" and fs.parent(src) == self.path:
            self.note("Already in this folder")
            return
        try:
            dst = fs.unique(fs.join(self.path, fs.basename(src)))
        except fs.FSError as err:
            self._fail(err)
            return
        name = fs.basename(dst)

        def then():
            if mode == "cut":
                self.clipboard = None
            self._reload(select=name)
            self.note(("Copied " if mode == "copy" else "Moved ") + name)
        gen = fs.copy(src, dst) if mode == "copy" else fs.move(src, dst)
        self._start_job(gen, ("Copying " if mode == "copy" else "Moving ") + name, then)

    def _info(self, e):
        name, full, is_dir, size = e
        lines = [name, full]
        try:
            if self.path is None:
                free = [s for s in self.stores if s[1] == full][0][3]
                lines += ["Size " + fs.human(size), "Free " + fs.human(free)]
            elif is_dir:
                lines.append("%d items" % len(fs.listdir(full)))
            else:
                lines.append(fs.human(size))
        except OSError:
            pass
        self._show_info(lines)

    def _storage_info(self):
        try:
            v = fs.free_space(self.path)
            mount = fs.mount_of(self.path)
            total = [s for s in (self.stores or fs.storages()) if s[1] == mount][0][2]
            self._show_info([("Flash" if mount == "/" else mount[1:]), "Size " + fs.human(total), "Free " + fs.human(v)])
        except (OSError, IndexError):
            self._close_menu()
            self.note("No storage info")

    def _show_info(self, lines):
        self.info_lines, self.mode = lines, "info"
        self.buttons.clear()

    # --- jobs (copy, move, delete) ---

    def _start_job(self, gen, label, then):
        self.job, self.job_label, self.job_then = gen, label, then
        self.job_done, self.job_total, self.mode = 0, 1, "job"
        self.buttons.clear()

    def _end_job(self, ok):
        self.job = None
        self.mode = "browse"
        self.buttons.clear()
        if ok and self.job_then:
            self.job_then()
        else:
            self._reload()

    def _run_job(self):
        t = time.ticks_ms()
        try:
            while time.ticks_diff(time.ticks_ms(), t) < JOB_SLICE_MS:
                self.job_done, self.job_total = next(self.job)
        except StopIteration:
            self._end_job(True)
        except Exception as e:   # FSError, or the card going away
            self._end_job(False)
            self._fail(e)

    # --- viewing ---

    def _open_file(self, path):
        try:
            is_text, text = fs.sniff(path, TEXT_LIMIT)
            self.view_size = fs.size_of(path)
        except OSError:
            self.note("Cannot read file")
            return
        self.view_path, self.view_pos = path, 0
        if is_text:
            self.view_mode, self.view_lines = "text", fs.wrap(text, 24)
        else:
            self.view_mode, self.view_lines = "hex", []
            self._hex_read()
        self.mode = "view"
        self.buttons.clear()

    def _hex_read(self):
        try:
            data = fs.read_at(self.view_path, self.view_pos, HEX_BYTES * VIEW_LINES)
        except OSError:
            data = b""
        self.view_lines = ["%04X: %s" % (self.view_pos + i * HEX_BYTES,
                                         " ".join("%02X" % c for c in data[i * HEX_BYTES:(i + 1) * HEX_BYTES]))
                           for i in range((len(data) + HEX_BYTES - 1) // HEX_BYTES)]

    def _view_scroll(self, lines):
        if self.view_mode == "text":
            top = max(0, len(self.view_lines) - VIEW_LINES)
            self.view_pos = max(0, min(top, self.view_pos + lines))
        else:
            last = max(0, self.view_size - 1) // HEX_BYTES * HEX_BYTES
            self.view_pos = max(0, min(last, self.view_pos + lines * HEX_BYTES))
            self._hex_read()

    # --- input ---

    def _repeat(self, b, delta):
        """-1 / +1 when UP / DOWN is pressed, or repeats while held; otherwise 0."""
        for name, step in (("UP", -1), ("DOWN", 1)):
            t = BUTTON_TYPES[name]
            if b.pressed(t):
                self._held = 0
                return step
            if b.get(t):
                self._held += delta
                if self._held >= HOLD_MS:
                    self._held -= REPEAT_MS
                    return step
                return 0
        self._held = 0
        return 0

    def update(self, delta):
        if self._toast_ms > 0:
            self._toast_ms -= delta
        if self._tdlg is not None:   # the dialog owns the buttons
            return
        b = self.buttons
        cancel = b.pressed(BUTTON_TYPES["CANCEL"])
        if self.mode == "job":
            if cancel:
                self.job.close()
                self._end_job(False)
                self.note("Stopped")
            else:
                self._run_job()
        elif self.mode == "menu":
            step = self._repeat(b, delta)
            if cancel:
                self._close_menu()
            elif step:
                self.menu_cur = (self.menu_cur + step) % len(self.menu_items)
            elif b.pressed(BUTTON_TYPES["CONFIRM"]):
                self.menu_items[self.menu_cur][1]()
        elif self.mode == "info":
            if cancel or b.pressed(BUTTON_TYPES["CONFIRM"]):
                self._close_menu()
        elif self.mode == "view":
            step = self._repeat(b, delta)
            if cancel:
                self._close_menu()
            elif step:
                self._view_scroll(step)
            elif b.pressed(BUTTON_TYPES["RIGHT"]):
                self._view_scroll(VIEW_LINES)
            elif b.pressed(BUTTON_TYPES["LEFT"]):
                self._view_scroll(-VIEW_LINES)
        else:
            step = self._repeat(b, delta)
            if cancel:
                self._up()
            elif step:
                self._move(step)
            elif b.pressed(BUTTON_TYPES["CONFIRM"]):
                self._enter()
            elif b.pressed(BUTTON_TYPES["RIGHT"]):
                self._item_menu()
            elif b.pressed(BUTTON_TYPES["LEFT"]):
                self._folder_menu()
            else:
                for ch in "abcdefghijklmnopqrstuvwxyz":
                    key = self.keyboard.get(ch.upper())
                    if key is not None and b.pressed(key):
                        self._jump(ch)
                        break

    # --- drawing ---

    def draw(self, ctx):
        ctx.save()
        clear_background(ctx)
        if self.mode == "job":
            self._draw_job(ctx)
        elif self.mode == "view":
            self._draw_view(ctx)
        else:
            self._draw_browse(ctx)
            if self.mode == "menu":
                self._draw_menu(ctx)
            elif self.mode == "info":
                self._draw_info(ctx)
        if self._toast_ms > 0:
            ui.toast(ctx, self._toast)
        ctx.restore()
        self.draw_overlays(ctx)

    def _draw_browse(self, ctx):
        title = "Storage" if self.path is None else self.path
        ui.text(ctx, title, 0, -92, ui.ACCENT, ui.tiny_font_size, tail=14)
        if not self.entries:
            ui.text(ctx, "Empty folder", 0, -2, ui.MUTED)
        for r in range(ROWS):
            i = self.top + r
            if i >= len(self.entries):
                break
            name, full, is_dir, _size = self.entries[i]
            y = ROW_Y0 + r * ROW_H
            if i == self.cur:
                ctx.rgb(*ui.DIM).rectangle(-96, y - 11, 192, 22).fill()
            if self.path is None:
                (ui.chip if full == "/" else ui.card)(ctx, -84, y, 6)
            elif is_dir:
                ui.folder(ctx, -84, y, 6)
            else:
                ui.file(ctx, -84, y, 6)
            colour = ui.FOLDER if is_dir else ui.TEXT
            ui.text(ctx, name + ("/" if is_dir and self.path is not None else ""), -68, y, colour, align="l", tail=0 if is_dir else 7)
        self._draw_footer(ctx)

    def _draw_footer(self, ctx):
        e = self._selected()
        if e is None:
            return
        name, full, is_dir, size = e
        if self.path is None:
            free = [s[3] for s in self.stores if s[1] == full]
            detail = "%s free of %s" % (fs.human(free[0]) if free else "?", fs.human(size))
        else:
            detail = "folder" if is_dir else fs.human(size)
        ui.text(ctx, detail, 0, 70, ui.MUTED, ui.tiny_font_size)
        count = "%d/%d" % (self.cur + 1, len(self.entries))
        if self.clipboard:
            count += "  " + ("Copy: " if self.clipboard[1] == "copy" else "Cut: ") + fs.basename(self.clipboard[0])
        ui.text(ctx, count, 0, 88, ui.WARN if self.clipboard else ui.MUTED, ui.tiny_font_size)

    def _panel(self, ctx):
        ctx.rgba(0, 0, 0, 0.93).rectangle(-82, -68, 164, 158).fill()

    def _draw_menu(self, ctx):
        self._panel(ctx)
        ui.text(ctx, self.menu_title, 0, -57, ui.ACCENT, ui.tiny_font_size, tail=6)
        for i, (label, _fn) in enumerate(self.menu_items):
            y = -34 + i * 22
            if i == self.menu_cur:
                ctx.rgb(*ui.DIM).rectangle(-70, y - 10, 140, 20).fill()
            ui.text(ctx, label, 0, y, ui.TEXT if i == self.menu_cur else ui.MUTED, ui.tiny_font_size)

    def _draw_info(self, ctx):
        self._panel(ctx)
        for i, line in enumerate(self.info_lines[:6]):
            ui.text(ctx, line, 0, -52 + i * 22, ui.TEXT if i == 0 else ui.MUTED, ui.tiny_font_size, tail=8)

    def _draw_job(self, ctx):
        frac = self.job_done / self.job_total
        ui.ring(ctx, frac, ui.ACCENT)
        ctx.font_size = ui.tiny_font_size   # keep inside the progress ring
        ui.text(ctx, ui.fit(ctx, self.job_label, 170, 8), 0, -34, ui.TEXT, ui.tiny_font_size)
        ui.text(ctx, "%d%%" % int(frac * 100), 0, 0, ui.ACCENT, ui.label_font_size)
        ui.bar(ctx, -70, 20, 140, 8, frac, ui.ACCENT)
        ui.text(ctx, "Cancel to stop", 0, 46, ui.MUTED, ui.tiny_font_size)

    def _draw_view(self, ctx):
        ui.text(ctx, fs.basename(self.view_path), 0, -92, ui.ACCENT, ui.tiny_font_size, tail=7)
        if self.view_mode == "text":
            shown = self.view_lines[self.view_pos:self.view_pos + VIEW_LINES]
            more = len(self.view_lines)
            foot = "line %d of %d" % (self.view_pos + 1, more) if more else "empty file"
            if self.view_size > TEXT_LIMIT:
                foot += "  (first 4 KB)"
        else:
            shown = self.view_lines
            foot = "%s  offset %X" % (fs.human(self.view_size), self.view_pos)
        for i, line in enumerate(shown):
            ui.text(ctx, line, 0, -62 + i * 20, ui.TEXT, ui.tiny_font_size)
        ui.text(ctx, foot, 0, 70, ui.MUTED, ui.tiny_font_size)


__app_export__ = FileExplorer
