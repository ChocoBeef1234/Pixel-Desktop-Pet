"""
Pixel-art Settings window for the desktop pet.

Every control is bound to the pet's shared tk variables (pet.v), so the window,
the right-click menu and settings.json always agree. Changes apply instantly.
"""
import ctypes
import os
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageOps, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_FILE = os.path.join(HERE, "fonts", "Silkscreen-Regular.ttf")

# Palette taken from the purple/green slimes.
BG = "#1a1020"
PANEL = "#2a1838"
EDGE = "#5a3596"
EDGE_HI = "#d9c2ff"
TEXT = "#f0e8ff"
DIM = "#a99cc0"
ON = "#2f7f46"
ON_TEXT = "#c9f5d3"
DANGER = "#9a3348"
PREVIEW = 104            # preview box size in px


def pixel_font_family():
    """Load the bundled pixel font for this process only; None if unavailable."""
    try:
        if os.path.exists(FONT_FILE) and \
                ctypes.windll.gdi32.AddFontResourceExW(FONT_FILE, 0x10, 0):  # FR_PRIVATE
            return "Silkscreen"
    except Exception:
        pass
    return None


class SettingsWindow(tk.Toplevel):
    def __init__(self, pet, slimes):
        super().__init__(pet.root)
        self.withdraw()                       # build hidden, show when styled
        self.pet = pet
        self.traces = []
        self.anim_id = None
        fam = pixel_font_family()
        # Whole-pixel sizes keep the pixel font crisp.
        self.font = (fam, -16) if fam else ("Consolas", -14, "bold")
        self.big = (fam, -32) if fam else ("Consolas", -26, "bold")

        self.title("Pet Settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())

        self.build_header(slimes)
        self.tab = tk.StringVar(value="Pet")
        tabs = tk.Frame(self, bg=BG)
        tabs.pack(fill="x", padx=16)
        tk.Label(self, text="Changes save by themselves  -  Esc closes",
                 font=self.font, bg=BG, fg=DIM).pack(side="bottom", pady=(8, 12))
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(6, 0))
        self.pages = {}
        for name, build in (("Pet", self.page_pet), ("Monsters", self.page_monsters),
                            ("System", self.page_system)):
            self.choice(tabs, self.tab, name, name, command=self.show_page).pack(
                side="left", padx=(0, 6))
            page = tk.Frame(body, bg=PANEL, highlightthickness=2, highlightbackground=EDGE,
                            padx=16, pady=12)
            page.grid(row=0, column=0, sticky="nsew")   # same cell: no resize on switch
            build(page)
            self.pages[name] = page
        self.show_page()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 3
        self.geometry("+%d+%d" % (x, y))
        self.dark_title_bar()
        self.deiconify()
        self.focus_force()

    # ---- pixel widgets --------------------------------------------------- #
    def watch(self, var, fn):
        """Trace a pet variable; removed again on close so no dead callbacks remain."""
        self.traces.append((var, var.trace_add("write", fn)))
        fn()

    def boxed(self, parent, cls, **kw):
        """Widget inside a 2px pixel border frame; returns the frame (.inner = widget).
        The border lights up on hover; a lilac ring inside shows keyboard focus."""
        box = tk.Frame(parent, bg=EDGE, padx=2, pady=2)
        bg = kw.get("bg", PANEL)
        w = cls(box, font=self.font, fg=TEXT, activebackground=EDGE, activeforeground=TEXT,
                relief="flat", bd=0, highlightthickness=1, highlightbackground=bg,
                highlightcolor=EDGE_HI, cursor="hand2", takefocus=1, **kw)
        w.pack()
        w.bind("<Enter>", lambda _e: box.config(bg=EDGE_HI), add="+")
        w.bind("<Leave>", lambda _e: box.config(bg=EDGE), add="+")
        box.inner = w
        return box

    def button(self, parent, text, command, danger=False):
        return self.boxed(parent, tk.Button, text=text, command=command,
                          bg=DANGER if danger else PANEL, padx=10, pady=2)

    def choice(self, parent, var, value, text, command=None):
        return self.boxed(parent, tk.Radiobutton, text=text, variable=var, value=value,
                          command=command, indicatoron=0, offrelief="flat", bg=PANEL,
                          selectcolor=ON, padx=8, pady=2)

    def choice_bar(self, parent, var, options):
        bar = tk.Frame(parent, bg=PANEL)
        for value, text in options:
            self.choice(bar, var, value, text).pack(side="left", padx=(0, 4))
        return bar

    def toggle(self, parent, var, after=None):
        def flip():
            var.set(not var.get())
            if after:
                after()
        box = self.button(parent, "", flip)

        def sync(*_):
            on = var.get()
            bg = ON if on else PANEL
            box.inner.config(text="[ ON ]" if on else "[ OFF ]", bg=bg,
                             highlightbackground=bg, fg=ON_TEXT if on else DIM)
        self.watch(var, sync)
        return box

    def stepper(self, parent, var, lo, hi):
        f = tk.Frame(parent, bg=PANEL)
        self.button(f, "<", lambda: var.set(max(lo, var.get() - 1))).pack(side="left")
        tk.Label(f, textvariable=var, width=3, font=self.font, bg=PANEL,
                 fg=TEXT).pack(side="left")
        self.button(f, ">", lambda: var.set(min(hi, var.get() + 1))).pack(side="left")
        return f

    def row(self, page, label, widget):
        r = page.grid_size()[1]
        tk.Label(page, text=label, font=self.font, bg=PANEL, fg=TEXT).grid(
            row=r, column=0, sticky="w", pady=5, padx=(0, 16))
        widget.grid(row=r, column=1, sticky="e", pady=5)

    def heading(self, page, text):
        tk.Label(page, text=text, font=self.font, bg=PANEL, fg=ON_TEXT).grid(
            row=page.grid_size()[1], column=0, columnspan=2, sticky="w", pady=(8, 2))

    # ---- header & chrome -------------------------------------------------- #
    def build_header(self, slimes):
        c = tk.Canvas(self, width=520, height=72, bg=BG, highlightthickness=0)
        c.pack(fill="x")
        self.slime_photos = [ImageTk.PhotoImage(s.resize((s.width * 3, s.height * 3),
                                                         Image.NEAREST)) for s in slimes]

        def draw(e):                          # redraw to the window's real width
            w = e.width
            c.delete("all")
            c.create_image(18, 64, image=self.slime_photos[0], anchor="sw")
            c.create_image(w - 18, 64, image=self.slime_photos[1 % len(slimes)], anchor="se")
            c.create_text(w // 2 + 2, 38, text="Settings", font=self.big, fill=EDGE)  # shadow
            c.create_text(w // 2, 36, text="Settings", font=self.big, fill=TEXT)
            c.create_rectangle(16, 68, w - 16, 70, fill=EDGE, width=0)
        c.bind("<Configure>", draw)

    def dark_title_bar(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        except Exception:
            pass

    def show_page(self):
        self.pages[self.tab.get()].tkraise()

    # ---- pages ------------------------------------------------------------ #
    def page_pet(self, p):
        v = self.pet.v
        top = tk.Frame(p, bg=PANEL)
        top.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 6))
        self.preview = tk.Canvas(top, width=PREVIEW, height=PREVIEW, bg=BG,
                                 highlightthickness=2, highlightbackground=EDGE)
        self.preview.pack(side="left")
        side = tk.Frame(top, bg=PANEL)
        side.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(side, text="Character", font=self.font, bg=PANEL, fg=ON_TEXT).pack(anchor="w")
        self.char_list = tk.Listbox(side, height=4, width=18, font=self.font, bg=BG, fg=TEXT,
                                    selectbackground=ON, selectforeground=TEXT,
                                    highlightthickness=2, highlightbackground=EDGE,
                                    highlightcolor=EDGE_HI, relief="flat", bd=0,
                                    activestyle="none", exportselection=False)
        self.char_list.pack(fill="x", pady=(2, 6))
        self.char_list.bind("<<ListboxSelect>>", self.on_pick_character)
        btns = tk.Frame(side, bg=PANEL)
        btns.pack(anchor="w")
        self.button(btns, "Import...", self.pet.import_character).pack(side="left", padx=(0, 6))
        self.button(btns, "Open folder", self.pet.open_char_dir).pack(side="left")
        self.watch(v["character"], self.on_character_changed)

        self.row(p, "Size", self.choice_bar(p, v["size"], [(s, s) for s in
                                                            ("Small", "Medium", "Large", "Huge")]))
        self.row(p, "Nap when I'm away", self.choice_bar(
            p, v["nap_after_min"], [(0, "Off"), (1, "1m"), (3, "3m"), (5, "5m"), (10, "10m")]))
        self.row(p, "Activity", self.choice_bar(
            p, v["activity"], [(a, a) for a in ("Calm", "Normal", "Playful")]))

    def page_monsters(self, p):
        v = self.pet.v
        self.heading(p, "Slimes")
        self.row(p, "Monsters appear", self.toggle(p, v["monsters"]))
        self.row(p, "Spawn rate", self.choice_bar(
            p, v["spawn_rate"], [(r, r) for r in ("Rare", "Normal", "Often")]))
        self.row(p, "Max at once", self.stepper(p, v["max_monsters"], 1, 6))
        self.row(p, "Spawn one now", self.button(p, "Spawn!", self.pet.spawn_monster))
        self.heading(p, "Fighting")
        self.row(p, "Slimes fight back", self.toggle(p, v["fight_back"]))
        self.row(p, "Pet HP", self.stepper(p, v["pet_hp"], 3, 10))
        kills = tk.Frame(p, bg=PANEL)
        tk.Label(kills, textvariable=v["kills"], font=self.font, bg=PANEL, fg=ON_TEXT,
                 width=6, anchor="e").pack(side="left", padx=(0, 8))
        self.button(kills, "Reset", self.reset_kills).pack(side="left")
        self.row(p, "Slimes defeated", kills)

    def page_system(self, p):
        self.row(p, "Start with Windows", self.toggle(p, self.pet.startup_on,
                                                      after=self.pet.toggle_startup))
        self.row(p, "Hide in fullscreen apps", self.toggle(p, self.pet.v["hide_fullscreen"]))
        self.row(p, "Reset all settings", self.button(p, "Reset", self.reset_all, danger=True))
        tk.Label(p, text="Font: Silkscreen by Jason Kottke\n(SIL Open Font License,"
                         " see fonts/OFL.txt)",
                 font=self.font, bg=PANEL, fg=DIM, justify="left").grid(
            row=p.grid_size()[1], column=0, columnspan=2, sticky="w", pady=(16, 0))

    # ---- actions ------------------------------------------------------------ #
    def on_character_changed(self, *_):
        self.char_keys = []
        self.char_list.delete(0, "end")
        for key, name in self.pet.characters():
            self.char_keys.append(key)
            self.char_list.insert("end", name)
        if self.pet.char_key in self.char_keys:
            i = self.char_keys.index(self.pet.char_key)
            self.char_list.selection_set(i)
            self.char_list.see(i)
        self.start_preview()

    def on_pick_character(self, _e):
        sel = self.char_list.curselection()
        if sel and self.char_keys[sel[0]] != self.pet.char_key:
            self.pet.switch_character(self.char_keys[sel[0]])

    def start_preview(self):
        if self.anim_id:
            self.after_cancel(self.anim_id)
        char = self.pet.char
        a = char.anims["idle"]
        w = max(f.width for f in a["frames"])
        h = max(f.height for f in a["frames"])
        s = (PREVIEW - 16) / float(max(w, h))
        if char.pixel_art and s >= 1:
            s = int(s)                         # whole-number scaling keeps pixels crisp
        resample = Image.NEAREST if char.pixel_art else Image.LANCZOS
        self.preview_frames = []
        for f in a["frames"]:
            img = f.resize((max(1, round(f.width * s)), max(1, round(f.height * s))), resample)
            if char.facing == "left":
                img = ImageOps.mirror(img)
            self.preview_frames.append(ImageTk.PhotoImage(img))
        self.icon = self.preview_frames[0]
        self.iconphoto(False, self.icon)
        c = self.preview
        c.delete("all")
        c.create_rectangle(8, PREVIEW - 10, PREVIEW - 8, PREVIEW - 8, fill=EDGE, width=0)
        self.preview_img = c.create_image(PREVIEW // 2 + 2, PREVIEW - 10, anchor="s")
        self.preview_step(0, a["ms"])

    def preview_step(self, i, ms):
        self.preview.itemconfig(self.preview_img, image=self.preview_frames[i])
        nxt = (i + 1) % len(self.preview_frames)
        self.anim_id = self.after(int(max(10, ms[i])), self.preview_step, nxt, ms)

    def reset_kills(self):
        if messagebox.askyesno("Reset counter", "Set slimes defeated back to 0?", parent=self):
            self.pet.v["kills"].set(0)

    def reset_all(self):
        if messagebox.askyesno("Reset all settings",
                               "Put every setting back to its default?\n\n"
                               "Your character and slime count stay.", parent=self):
            self.pet.reset_settings()

    def close(self):
        if self.anim_id:
            self.after_cancel(self.anim_id)
        for var, tid in self.traces:
            try:
                var.trace_remove("write", tid)
            except tk.TclError:
                pass
        self.pet.settings_win = None
        self.destroy()
