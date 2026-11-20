"""
Meow Knight desktop pet.

A little character that lives on top of your taskbar.
  - Wanders, jumps, rolls and practises attacks on its own
  - Slimes drop in now and then; your character hunts them down
  - Left-click the character: it attacks (or wakes up if napping)
  - Left-click a slime: squish it yourself
  - Drag the character: pick it up; let go to drop / toss it
  - Right-click the character: menu (character, jump, nap, monsters, size, quit)
  - Falls asleep when you stop using the computer for a while

Characters live in the "characters" folder. See CHARACTERS.md to add your own.
Double-click this .pyw file to run without a console window.
"""
import ctypes
import json
import math
import os
import random
import re
import shutil
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageOps, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from character import (MANIFEST, Character, looks_like_character,  # noqa: E402
                       read_display_name)

CHAR_DIR = os.path.join(HERE, "characters")
SETTINGS_FILE = os.path.join(HERE, "settings.json")
DEFAULT_CHARACTER = "meow_knight"

KEY = "#010203"          # transparent color key
KEY_RGB = (1, 2, 3)
TICK_MS = 30
SLEEP_AFTER_IDLE_S = 180  # user inactivity before the character naps

# On-screen height of the idle pose for each size option.
SIZES = (("Small", 30), ("Medium", 45), ("Large", 60), ("Huge", 90))
DEFAULT_SIZE = "Medium"

FIRST_SPAWN_S = (10, 25)    # first monster arrives soon after launch
SPAWN_EVERY_S = (45, 150)   # then every so often
MAX_MONSTERS = 3

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# --------------------------------------------------------------------------- #
# Windows helpers
# --------------------------------------------------------------------------- #
def make_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def work_area():
    """Primary monitor area excluding the taskbar."""
    r = _RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def user_idle_seconds():
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return ((kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def make_overlay(window):
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.attributes("-transparentcolor", KEY)
    window.config(bg=KEY)


def key_photo(img):
    """RGBA image -> PhotoImage on the transparent key color (hard edges)."""
    bg = Image.new("RGB", img.size, KEY_RGB)
    mask = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bg.paste(img.convert("RGB"), (0, 0), mask)
    return ImageTk.PhotoImage(bg)


def list_characters():
    if not os.path.isdir(CHAR_DIR):
        return []
    return sorted(d for d in os.listdir(CHAR_DIR)
                  if looks_like_character(os.path.join(CHAR_DIR, d)))


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Slime monster
# --------------------------------------------------------------------------- #
SLIME_ART = [
    "....oooooo....",
    "..oobbbbbboo..",
    ".obbhhbbbbbbo.",
    ".obhhbbbbbbbo.",
    "obbbwkbbbwkbbo",
    "obbbkkbbbkkbbo",
    "obbbbbbbbbbbbo",
    "obllbbbbbbbllo",
    ".ollllllllllo.",
    "..oooooooooo..",
]
# (outline, body, shade, highlight)
SLIME_VARIANTS = [
    ("#2a1838", "#7b4fc0", "#5a3596", "#d9c2ff"),  # purple
    ("#13301c", "#4fb36a", "#2f7f46", "#c9f5d3"),  # green
    ("#3a1420", "#d25a6e", "#9a3348", "#ffd0d8"),  # red
    ("#10283a", "#3fa7c9", "#2a7393", "#c8f0ff"),  # blue
]


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def slime_image(colors):
    outline, body, shade, hi = colors
    pal = {"o": outline, "b": body, "l": shade, "h": hi,
           "w": "#ffffff", "k": "#1a1020"}
    w, h = len(SLIME_ART[0]), len(SLIME_ART)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(SLIME_ART):
        for x, ch in enumerate(row.ljust(w, ".")):
            if ch in pal:
                px[x, y] = _hex(pal[ch]) + (255,)
    return img


class Slime:
    def __init__(self, pet, x):
        self.pet = pet
        self.colors = random.choice(SLIME_VARIANTS)
        self.big = random.random() < 0.25
        self.hp = 4 if self.big else 2
        self.x = float(x)
        self.feet_y = pet.ground - random.uniform(220, 380)  # drops in from above
        self.vx = self.vy = 0.0
        self.airborne = True
        self.landed = False          # becomes True after first touchdown
        self.crouch = 0.0
        self.squash = 0.0
        self.flash = 0.0
        self.hop_timer = random.uniform(0.8, 2.0)
        self.t = random.uniform(0, 3)
        self.dead = False
        self.gone = False
        self.dead_t = 0.0
        self.particles = []
        self.last_geom = None

        self.win = tk.Toplevel(pet.root)
        make_overlay(self.win)
        self.canvas = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self.on_click)
        self.build()

    def build(self):
        s = max(1, round(self.pet.u * (1.5 if self.big else 1.0)))
        base = slime_image(self.colors)
        w, h = base.size
        white = Image.new("RGBA", base.size, (255, 255, 255, 255))
        white.putalpha(base.getchannel("A"))

        def mk(img, sx, sy):
            size = (max(1, round(w * s * sx)), max(1, round(h * s * sy)))
            return key_photo(img.resize(size, Image.NEAREST)), size

        self.frames = {
            "normal": mk(base, 1.0, 1.0),
            "breathe": mk(base, 1.06, 0.92),
            "squash": mk(base, 1.25, 0.72),
            "stretch": mk(base, 0.82, 1.22),
            "flash": mk(white, 1.1, 0.9),
        }
        self.half_w = w * s / 2.0
        self.body_h = h * s
        self.px_scale = s
        self.cw = int(w * s * 3.2)
        self.ch = int(h * s * 3.0)
        self.canvas.config(width=self.cw, height=self.ch)
        self.last_geom = None

    # ---- interaction ----------------------------------------------------- #
    def on_click(self, _e):
        self.hit(1 if self.x >= self.pet.x else -1)

    def hit(self, direction):
        if self.dead:
            return
        self.hp -= 1
        self.flash = 0.16
        u = self.pet.u
        self.vx = direction * 55 * u
        self.vy = -55 * u
        self.airborne = True
        self.crouch = 0.0
        if self.hp <= 0:
            self.die()

    def die(self):
        self.dead = True
        self.pet.on_monster_killed()
        self.canvas.itemconfig(self.img_id, state="hidden")
        cx, cy = self.cw / 2, self.ch - self.body_h / 2
        colors = [self.colors[1], self.colors[2], self.colors[3], "#ffffff"]
        for _ in range(14 if self.big else 10):
            size = random.choice((1, 1, 2)) * self.px_scale
            ang = random.uniform(math.pi * 1.05, math.pi * 1.95)
            spd = random.uniform(80, 200) * self.pet.u / 3
            rid = self.canvas.create_rectangle(cx, cy, cx + size, cy + size,
                                               fill=random.choice(colors), width=0)
            self.particles.append([rid, cx, cy, math.cos(ang) * spd,
                                   math.sin(ang) * spd, size])

    def destroy(self):
        self.gone = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # ---- simulation ------------------------------------------------------ #
    def update(self, dt):
        if self.dead:
            self.dead_t += dt
            for p in self.particles:
                p[4] += 500 * dt
                p[1] += p[3] * dt
                p[2] = min(p[2] + p[4] * dt, self.ch - p[5])
                shrink = max(0.0, 1 - self.dead_t / 0.9) * p[5]
                self.canvas.coords(p[0], p[1], p[2], p[1] + shrink, p[2] + shrink)
            if self.dead_t > 0.9:
                self.destroy()
            return

        u = self.pet.u
        ground = self.pet.ground
        self.t += dt
        self.flash = max(0.0, self.flash - dt)
        self.squash = max(0.0, self.squash - dt)

        if self.airborne:
            self.vy += 1500 * dt
            self.x += self.vx * dt
            self.feet_y += self.vy * dt
            if self.feet_y >= ground:
                self.feet_y = ground
                self.airborne = False
                self.landed = True
                self.vx = self.vy = 0.0
                self.squash = 0.14
        elif self.crouch > 0:
            self.crouch -= dt
            if self.crouch <= 0:
                dist = self.pet.x - self.x
                if abs(dist) < 700 and random.random() < 0.7:
                    direction = 1 if dist > 0 else -1     # creep toward the hero
                else:
                    direction = random.choice((-1, 1))
                self.vx = direction * random.uniform(25, 45) * u
                self.vy = -random.uniform(90, 130) * u
                self.airborne = True
        else:
            self.hop_timer -= dt
            if self.hop_timer <= 0:
                self.crouch = 0.18
                self.hop_timer = random.uniform(0.9, 2.4)

        left, _, right, _ = work_area()
        lo, hi = left + self.half_w, right - self.half_w
        if self.x < lo:
            self.x, self.vx = lo, abs(self.vx)
        elif self.x > hi:
            self.x, self.vx = hi, -abs(self.vx)

    def render(self):
        if self.dead:
            return
        if self.flash > 0:
            key = "flash"
        elif self.crouch > 0 or self.squash > 0:
            key = "squash"
        elif self.airborne:
            key = "stretch" if self.vy < 0 else "normal"
        else:
            key = "breathe" if int(self.t / 0.45) % 2 else "normal"
        photo, (w, h) = self.frames[key]
        self.canvas.itemconfig(self.img_id, image=photo)
        self.canvas.coords(self.img_id, (self.cw - w) / 2, self.ch - h)
        geom = "%dx%d+%d+%d" % (self.cw, self.ch, int(self.x - self.cw / 2),
                                int(self.feet_y - self.ch))
        if geom != self.last_geom:
            self.win.geometry(geom)
            self.last_geom = geom


# --------------------------------------------------------------------------- #
# The pet
# --------------------------------------------------------------------------- #
class DesktopPet:
    def __init__(self):
        make_dpi_aware()
        self.root = tk.Tk()
        self.root.title("Desktop Pet")
        make_overlay(self.root)

        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.z_id = self.canvas.create_text(0, 0, text="", fill="#dfe9ff",
                                            font=("Consolas", 11, "bold"))

        settings = load_settings()
        self.size_name = settings.get("size", DEFAULT_SIZE)
        if self.size_name not in dict(SIZES):
            self.size_name = DEFAULT_SIZE
        self.char = None
        self.char_key = None
        self.char_var = tk.StringVar()
        self.size_var = tk.StringVar(value=self.size_name)
        if not self.load_initial_character(settings.get("character")):
            self.root.destroy()
            raise SystemExit(1)

        left, top, right, bottom = work_area()
        self.ground = bottom
        self.x = random.uniform(left + 150, right - 150)
        self.feet_y = float(bottom)
        self.facing = random.choice((-1, 1))
        self.vx = self.vy = 0.0

        self.anim = None
        self.state = None
        self.state_t = 0.0
        self.timer = 0.0
        self.target_x = self.x
        self.nap_until = None
        self.last_time = time.perf_counter()

        self.press = None
        self.dragging = False
        self.grab_off = (0, 0)
        self.drag_hist = []

        self.monsters = []
        self.kills = 0
        self.hit_done = True
        self.spawn_timer = random.uniform(*FIRST_SPAWN_S)
        self.monsters_on = tk.BooleanVar(value=settings.get("monsters", True))

        self.build_menu()
        self.build_frames()

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_menu)

        self.enter_idle()
        self.root.after(TICK_MS, self.tick)

    # ---- characters ------------------------------------------------------ #
    def load_initial_character(self, wanted):
        keys = list_characters()
        order = [k for k in (wanted, DEFAULT_CHARACTER) if k in keys]
        order += [k for k in keys if k not in order]
        errors = []
        for key in order:
            try:
                self.char = Character(os.path.join(CHAR_DIR, key))
                self.char_key = key
                self.char_var.set(key)
                return True
            except Exception as e:
                errors.append("%s: %s" % (key, e))
        os.makedirs(CHAR_DIR, exist_ok=True)
        messagebox.showerror(
            "No character",
            "No usable character was found in:\n%s\n\n%s\n\nAdd a character folder "
            "(see CHARACTERS.md) and start again." % (CHAR_DIR, "\n".join(errors)))
        try:
            os.startfile(CHAR_DIR)
        except Exception:
            pass
        return False

    def switch_character(self, key):
        try:
            char = Character(os.path.join(CHAR_DIR, key))
        except Exception as e:
            messagebox.showerror("Can't load character", "%s\n\n%s" % (key, e),
                                 parent=self.root)
            self.char_var.set(self.char_key)
            return
        self.char = char
        self.char_key = key
        self.char_var.set(key)
        self.build_frames()
        self.enter_idle()
        self.save_settings()

    def import_character(self):
        src = filedialog.askdirectory(parent=self.root,
                                      title="Choose the folder with your character's sprites")
        if not src:
            return
        try:
            char = Character(src)
        except Exception as e:
            messagebox.showerror(
                "Can't use that folder",
                "%s\n\nRequirements:\n- At least an idle animation (e.g. idle.png)\n"
                "- PNG/GIF/WebP sprite sheets, animated GIFs, or folders of frames\n"
                "- Transparent background\n\nSee CHARACTERS.md for details." % e,
                parent=self.root)
            return
        base = re.sub(r"[^A-Za-z0-9_-]+", "_",
                      os.path.basename(os.path.normpath(src))).strip("_").lower() or "character"
        dest, i = os.path.join(CHAR_DIR, base), 2
        while os.path.exists(dest):
            dest, i = os.path.join(CHAR_DIR, "%s_%d" % (base, i)), i + 1
        os.makedirs(dest)
        for rel in set(char.files_used()):
            s, d = os.path.join(src, rel), os.path.join(dest, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        mpath = os.path.join(dest, MANIFEST)
        if char.detected:
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump(char.manifest, fh, indent=2)
        else:
            shutil.copy2(os.path.join(src, MANIFEST), mpath)
        messagebox.showinfo(
            "Character imported",
            "%s\n\nTo fine-tune it (speed, facing, frame sizes), edit:\n%s"
            % (char.summary(), mpath), parent=self.root)
        self.switch_character(os.path.basename(dest))

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump({"character": self.char_key, "size": self.size_name,
                           "monsters": self.monsters_on.get()}, fh, indent=2)
        except Exception:
            pass

    # ---- menu ------------------------------------------------------------ #
    def build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Slimes defeated: 0", state="disabled")
        self.kills_index = self.menu.index("end")
        self.menu.add_separator()
        self.char_menu = tk.Menu(self.menu, tearoff=0, postcommand=self.fill_char_menu)
        self.menu.add_cascade(label="Character", menu=self.char_menu)
        self.menu.add_command(label="Jump!", command=lambda: self.start_jump(0))
        self.menu.add_command(label="Take a nap", command=self.start_nap)
        self.menu.add_command(label="Spawn a monster", command=self.spawn_monster)
        self.menu.add_checkbutton(label="Monsters appear", variable=self.monsters_on,
                                  command=self.save_settings)
        size = tk.Menu(self.menu, tearoff=0)
        for label, _ in SIZES:
            size.add_radiobutton(label=label, variable=self.size_var, value=label,
                                 command=lambda l=label: self.set_size(l))
        self.menu.add_cascade(label="Size", menu=size)
        self.menu.add_separator()
        self.menu.add_command(label="Goodbye", command=self.root.destroy)

    def fill_char_menu(self):
        m = self.char_menu
        m.delete(0, "end")
        for key in list_characters():
            m.add_radiobutton(label=read_display_name(os.path.join(CHAR_DIR, key)),
                              variable=self.char_var, value=key,
                              command=lambda k=key: self.switch_character(k))
        m.add_separator()
        m.add_command(label="Import character folder...", command=self.import_character)
        m.add_command(label="Open characters folder", command=self.open_char_dir)

    def open_char_dir(self):
        os.makedirs(CHAR_DIR, exist_ok=True)
        os.startfile(CHAR_DIR)

    # ---- frames ---------------------------------------------------------- #
    def build_frames(self):
        c = self.char
        target = dict(SIZES)[self.size_name]
        s = target / float(c.body_h)
        if c.pixel_art and s >= 1:
            s = max(1, round(s))           # whole-number scaling keeps pixels crisp
        self.s = s
        self.u = c.body_h * s / 15.0       # movement unit (1.0 ~ a 15px sprite at 1x)
        resample = Image.NEAREST if c.pixel_art else Image.LANCZOS
        src_left = c.facing == "left"

        cache, self.frames = {}, {}
        half_w, max_h = 0, 0
        for name, a in c.anims.items():
            out = []
            for f in a["frames"]:
                if id(f) not in cache:
                    size = (max(1, round(f.width * s)), max(1, round(f.height * s)))
                    img = f.resize(size, resample)
                    mir = ImageOps.mirror(img)
                    cache[id(f)] = (key_photo(mir if src_left else img),
                                    key_photo(img if src_left else mir), size)
                right, left, (w, h) = cache[id(f)]
                anchor = a["anchor"] * w / f.width
                ar = (w - anchor) if src_left else anchor
                out.append({"r": right, "l": left, "h": h, "ar": ar, "al": w - ar})
                half_w = max(half_w, ar, w - ar)
                max_h = max(max_h, h)
            self.frames[name] = out
        self.half_w = int(math.ceil(half_w)) + 2
        self.cw = self.half_w * 2
        self.ch = int(max_h + 18 * self.u)
        self.canvas.config(width=self.cw, height=self.ch)
        self.last_geom = None
        for m in getattr(self, "monsters", []):
            if not m.dead:
                m.build()

    def set_size(self, label):
        self.size_name = label
        self.size_var.set(label)
        self.build_frames()
        self.save_settings()

    # ---- animation ------------------------------------------------------- #
    def play(self, name, loop=False, seq=None):
        n = len(self.frames[name])
        self.anim = {
            "name": name,
            "seq": list(seq) if seq is not None else list(range(n)),
            "pos": 0,
            "t": 0.0,
            "loop": loop,
            "done": False,
            "ms": self.char.anims[name]["ms"],
        }

    def advance(self, dt):
        a = self.anim
        if a["done"]:
            return
        a["t"] += dt * 1000
        while True:
            ms = max(10.0, a["ms"][a["seq"][a["pos"]]])
            if a["t"] < ms:
                break
            a["t"] -= ms
            if a["pos"] + 1 < len(a["seq"]):
                a["pos"] += 1
            elif a["loop"]:
                a["pos"] = 0
            else:
                a["done"] = True
                break

    def frame_index(self):
        return self.anim["seq"][self.anim["pos"]]

    # ---- monsters -------------------------------------------------------- #
    def live_monsters(self):
        return [m for m in self.monsters if not m.dead and m.landed]

    def nearest_monster(self):
        live = self.live_monsters()
        return min(live, key=lambda m: abs(m.x - self.x)) if live else None

    def spawn_monster(self):
        left, _, right, _ = work_area()
        x = random.uniform(left + 80, right - 80)
        for _ in range(12):  # prefer somewhere not right on top of the hero
            if abs(x - self.x) > 250:
                break
            x = random.uniform(left + 80, right - 80)
        self.monsters.append(Slime(self, x))
        if self.state == "sleep" and self.nap_until:   # casual nap -> wake up
            self.start_wake()

    def on_monster_killed(self):
        self.kills += 1
        self.menu.entryconfig(self.kills_index,
                              label="Slimes defeated: %d" % self.kills)

    def update_monsters(self, dt):
        if self.monsters_on.get() and user_idle_seconds() < SLEEP_AFTER_IDLE_S:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_timer = random.uniform(*SPAWN_EVERY_S)
                if sum(not m.dead for m in self.monsters) < MAX_MONSTERS:
                    self.spawn_monster()
        for m in self.monsters:
            m.update(dt)
            if not m.gone:
                m.render()
        self.monsters = [m for m in self.monsters if not m.gone]

    def reach(self):
        return self.char.attack_reach * self.s

    def check_hit(self):
        a = self.anim
        if self.hit_done or a["name"] not in self.char.attacks:
            return
        if a["pos"] < self.char.anims[a["name"]].get("hit_frame", 0) and not a["done"]:
            return
        self.hit_done = True
        for m in self.live_monsters():
            dx = m.x - self.x
            if abs(dx) - m.half_w <= self.reach() and dx * self.facing >= -m.half_w:
                m.hit(self.facing)

    # ---- states ---------------------------------------------------------- #
    def set_state(self, st):
        self.state = st
        self.state_t = 0.0

    def enter_idle(self, min_s=2.5, max_s=7.0):
        self.set_state("idle")
        self.play("idle", loop=True)
        self.timer = random.uniform(min_s, max_s)
        self.feet_y = self.ground
        self.vx = 0.0
        self.canvas.itemconfig(self.z_id, text="")

    def enter_hunt(self):
        self.set_state("hunt")
        self.play("run", loop=True)

    def choose_action(self):
        left, _, right, _ = work_area()
        actions = [("walk", 45), ("idle", 22), ("jump", 10), ("dodge", 8),
                   ("attack", 12), ("nap", 3)]
        pick = random.choices([a for a, _ in actions],
                              weights=[w for _, w in actions])[0]
        if pick == "walk":
            dist = random.uniform(120, 500) * random.choice((-1, 1))
            self.target_x = min(max(self.x + dist, left + self.half_w),
                                right - self.half_w)
            if abs(self.target_x - self.x) < 30:
                self.enter_idle()
                return
            self.facing = 1 if self.target_x > self.x else -1
            self.set_state("walk")
            self.play("run", loop=True)
        elif pick == "jump":
            self.start_jump(random.choice((0, 0, 1)) * self.facing)
        elif pick == "dodge":
            if random.random() < 0.4:
                self.facing *= -1
            self.set_state("dodge")
            self.play("dodge")
        elif pick == "attack":
            self.start_attack()
        elif pick == "nap":
            self.start_nap(random.uniform(20, 45))
        else:
            if random.random() < 0.3:
                self.facing *= -1
            self.enter_idle()

    def start_jump(self, direction):
        self.set_state("jump")
        self.play("jump")
        self.vx = direction * 70 * self.u

    def start_attack(self):
        self.set_state("attack")
        self.play(random.choice(self.char.attacks))
        self.hit_done = False

    def start_nap(self, seconds=None):
        self.feet_y = self.ground
        self.set_state("sleep")
        self.play("sleep", loop=self.char.sleep_loops)
        self.nap_until = (time.monotonic() + seconds) if seconds else None

    def start_wake(self):
        self.canvas.itemconfig(self.z_id, text="")
        if self.char.sleep_loops:
            self.enter_idle()
            return
        self.set_state("wake")
        n = len(self.frames["sleep"])
        self.play("sleep", seq=range(n - 1, -1, -1))

    # ---- input ----------------------------------------------------------- #
    def on_press(self, e):
        self.press = (e.x_root, e.y_root)
        self.dragging = False
        self.grab_off = (e.x_root - self.x, e.y_root - self.feet_y)
        self.drag_hist = [(time.perf_counter(), e.x_root, e.y_root)]

    def on_drag(self, e):
        if not self.press:
            return
        if not self.dragging:
            if abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1]) < 6:
                return
            self.dragging = True
            self.canvas.itemconfig(self.z_id, text="")
            self.set_state("held")
            self.play("hurt")
        self.x = e.x_root - self.grab_off[0]
        self.feet_y = e.y_root - self.grab_off[1]
        now = time.perf_counter()
        self.drag_hist.append((now, e.x_root, e.y_root))
        self.drag_hist = [p for p in self.drag_hist if now - p[0] < 0.1]

    def on_release(self, e):
        if self.dragging:
            vx = vy = 0.0
            if len(self.drag_hist) >= 2:
                (t0, x0, y0), (t1, x1, y1) = self.drag_hist[0], self.drag_hist[-1]
                if t1 - t0 > 0.005:
                    vx = (x1 - x0) / (t1 - t0)
                    vy = (y1 - y0) / (t1 - t0)
            lim = 1500
            self.vx = max(-lim, min(lim, vx))
            self.vy = max(-lim, min(lim, vy))
            self.set_state("fall")
            self.play("jump", seq=[self.char.fall_frame])
        else:
            if self.state == "sleep":
                self.start_wake()
            elif self.state in ("idle", "walk", "hunt"):
                self.start_attack()
        self.press = None
        self.dragging = False

    def on_menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ---- main loop ------------------------------------------------------- #
    def tick(self):
        now = time.perf_counter()
        dt = min(now - self.last_time, 0.1)
        self.last_time = now
        try:
            self.update(dt)
            self.render()
        except tk.TclError:
            return
        self.root.after(TICK_MS, self.tick)

    def update(self, dt):
        left, _, right, bottom = work_area()
        self.ground = bottom
        self.state_t += dt
        self.advance(dt)
        self.update_monsters(dt)
        u = self.u
        st = self.state

        if st not in ("sleep", "wake", "held", "fall") and \
                user_idle_seconds() > SLEEP_AFTER_IDLE_S:
            self.start_nap()
            return

        if st in ("idle", "walk") and self.live_monsters():
            self.enter_hunt()
            st = self.state

        if st == "idle":
            self.timer -= dt
            if self.timer <= 0:
                self.choose_action()

        elif st == "walk":
            step = 28 * u * dt
            if abs(self.target_x - self.x) <= step:
                self.x = self.target_x
                self.enter_idle()
            else:
                self.x += step * self.facing

        elif st == "hunt":
            m = self.nearest_monster()
            if m is None:
                self.enter_idle(1.0, 3.0)
            else:
                dx = m.x - self.x
                if dx:
                    self.facing = 1 if dx > 0 else -1
                if abs(dx) - m.half_w <= self.reach() * 0.45:
                    self.start_attack()
                else:
                    self.x += self.facing * min(48 * u * dt, abs(dx))

        elif st == "jump":
            ms = self.char.anims["jump"]["ms"]
            a, b = self.char.air_frames
            air_start = sum(ms[:a]) / 1000.0
            air_len = max(0.05, sum(ms[a:b + 1]) / 1000.0)
            p = (self.state_t - air_start) / air_len
            if 0 <= p <= 1:
                self.feet_y = self.ground - 4 * 22 * u * p * (1 - p)
                self.x += self.vx * dt
            else:
                self.feet_y = self.ground
            if self.anim["done"]:
                self.enter_idle()

        elif st == "dodge":
            if not self.anim["done"]:
                self.x += self.facing * 55 * u * dt
            else:
                self.enter_idle()

        elif st == "attack":
            self.check_hit()
            if self.anim["done"]:
                if self.live_monsters():
                    self.enter_hunt()
                else:
                    self.enter_idle(1.5, 4.0)

        elif st == "fall":
            self.vy += 2200 * dt
            self.vx *= (1 - 0.8 * dt)
            self.x += self.vx * dt
            self.feet_y += self.vy * dt
            if self.vx:
                self.facing = 1 if self.vx > 0 else -1
            if self.feet_y >= self.ground:
                self.feet_y = self.ground
                self.vx = self.vy = 0
                self.set_state("land")
                n = len(self.frames["jump"])
                self.play("jump", seq=range(max(0, n - 3), n))

        elif st == "land":
            if self.anim["done"]:
                self.enter_idle()

        elif st == "sleep":
            if self.anim["done"] or (self.char.sleep_loops and self.state_t > 0.8):
                phase = self.state_t * 1.2
                zs = "z" * (1 + int(phase) % 3)
                self.canvas.itemconfig(self.z_id, text=zs)
            woke_by_timer = self.nap_until and time.monotonic() > self.nap_until
            woke_by_user = (self.nap_until is None and self.state_t > 3
                            and user_idle_seconds() < 1.0)
            if woke_by_timer or woke_by_user:
                self.start_wake()

        elif st == "wake":
            if self.anim["done"]:
                self.enter_idle()

        # Keep on screen; bounce off edges.
        lo, hi = left + self.half_w * 0.5, right - self.half_w * 0.5
        if self.x < lo:
            self.x = lo
            self.vx = abs(self.vx) * 0.5
            if st == "walk":
                self.enter_idle()
        elif self.x > hi:
            self.x = hi
            self.vx = -abs(self.vx) * 0.5
            if st == "walk":
                self.enter_idle()
        if st == "held":
            self.feet_y = min(self.feet_y, self.ground)

    def render(self):
        f = self.frames[self.anim["name"]][self.frame_index()]
        if self.facing >= 0:
            img, anchor = f["r"], f["ar"]
        else:
            img, anchor = f["l"], f["al"]
        self.canvas.itemconfig(self.img_id, image=img)
        self.canvas.coords(self.img_id, self.half_w - anchor, self.ch - f["h"])

        if self.canvas.itemcget(self.z_id, "text"):
            bob = math.sin(self.state_t * 2.0) * self.u
            zx = self.half_w + 8 * self.u * self.facing
            self.canvas.coords(self.z_id, zx, self.ch - f["h"] - 6 * self.u + bob)

        geom = "%dx%d+%d+%d" % (self.cw, self.ch,
                                int(self.x - self.half_w), int(self.feet_y - self.ch))
        if geom != self.last_geom:
            self.root.geometry(geom)
            self.last_geom = geom
        if self.monsters:
            self.root.lift()   # stay above slime windows

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DesktopPet().run()
