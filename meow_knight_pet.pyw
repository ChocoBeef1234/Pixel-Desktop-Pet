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
import traceback
import winreg
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:      # pythonw has no console, so say it in a window
    tk.Tk().withdraw()
    messagebox.showerror("Pillow is missing",
                         "The desktop pet needs the Pillow library.\n\n"
                         "Open a terminal and run:\n\n    pip install pillow")
    raise SystemExit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from character import (MANIFEST, Character, looks_like_character,  # noqa: E402
                       read_display_name)

CHAR_DIR = os.path.join(HERE, "characters")
SETTINGS_FILE = os.path.join(HERE, "settings.json")
ERROR_LOG = os.path.join(HERE, "error.log")
DEFAULT_CHARACTER = "meow_knight"
APP_ID = "MeowKnightPet"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

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

# Slimes fighting back
PET_MAX_HP = 5
INVULN_S = 1.0           # safe time after taking a hit
FAINT_S = (6, 9)         # how long the pet stays knocked out
REGEN_EVERY_S = 20       # +1 HP this often when no slimes are around
DODGE_CHANCE = 0.35      # chance to roll away from an incoming lunge
LUNGE_CHANCE = 0.8       # chance a nearby slime's hop is an attack
GUARD_S = (0.5, 1.1)     # pet's pause between sword swings (gives slimes an opening)
LUNGE_RANGE = 70         # in movement units (* u)

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


def fullscreen_app_active():
    """True while a game, video or slideshow is fullscreen (same check Windows
    uses to hold back notifications)."""
    state = ctypes.c_int()
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except Exception:
        return False
    return state.value in (2, 3, 4)  # QUNS_BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE


def already_running():
    """Holds a named mutex for the life of the process; True if another pet has it."""
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    already_running.handle = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID)
    return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def startup_command():
    if getattr(sys, "frozen", False):          # packaged .exe
        return '"%s"' % sys.executable
    exe = sys.executable
    windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(windowless):
        exe = windowless
    return '"%s" "%s"' % (exe, os.path.abspath(__file__))


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
        return True
    except OSError:
        return False


def set_startup(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass


def log_crash():
    try:
        with open(ERROR_LOG, "w", encoding="utf-8") as fh:
            traceback.print_exc(file=fh)
    except OSError:
        pass
    messagebox.showerror("Desktop Pet stopped",
                         "Something went wrong and the pet had to stop.\n\n"
                         "Details were saved to:\n%s" % ERROR_LOG)


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


class Popup:
    """Floating text (damage numbers, +1, SPLIT!) that rises and fades."""
    LIFE = 0.8

    def __init__(self, pet, x, y, text, color, size=1.0, rise=28):
        self.pet = pet
        u = pet.u
        self.x = x + random.uniform(-4, 4) * u
        self.y0 = y
        self.rise = rise * u
        self.drift = random.uniform(-6, 6) * u
        self.t = 0.0
        self.gone = False
        pt = max(9, int((6 + 2.2 * u) * size))
        font = ("Consolas", pt, "bold")
        self.w = int(pt * (len(text) + 1) * 1.0) + 8
        self.h = int(pt * 2.0)
        self.win = tk.Toplevel(pet.root)
        make_overlay(self.win)
        c = tk.Canvas(self.win, width=self.w, height=self.h, bg=KEY,
                      highlightthickness=0, bd=0)
        c.pack()
        cx, cy = self.w / 2, self.h / 2
        c.create_text(cx + 1, cy + 1, text=text, fill="#140c1c", font=font)
        c.create_text(cx, cy, text=text, fill=color, font=font)
        self.last_alpha = None
        self.update(0)

    def update(self, dt):
        self.t += dt
        p = self.t / self.LIFE
        if p >= 1:
            self.destroy()
            return
        ease = 1 - (1 - p) ** 2
        x = self.x + self.drift * p
        y = self.y0 - self.rise * ease
        self.win.geometry("%dx%d+%d+%d" % (self.w, self.h, int(x - self.w / 2),
                                           int(y - self.h / 2)))
        alpha = round(1.0 if p < 0.55 else max(0.0, 1 - (p - 0.55) / 0.45), 2)
        if alpha != self.last_alpha:
            self.win.attributes("-alpha", alpha)
            self.last_alpha = alpha

    def destroy(self):
        self.gone = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class Slime:
    def __init__(self, pet, x, big=None, colors=None, hp=None, feet_y=None):
        self.pet = pet
        self.colors = colors or random.choice(SLIME_VARIANTS)
        self.big = (random.random() < 0.25) if big is None else big
        self.hp = hp if hp is not None else (4 if self.big else 2)
        self.x = float(x)
        # Normal spawns drop in from above; split children start where told.
        self.feet_y = feet_y if feet_y is not None else pet.ground - random.uniform(220, 380)
        self.vx = self.vy = 0.0
        self.airborne = True
        self.landed = feet_y is not None   # split children are targetable at once
        self.attacking = False             # mid-lunge at the pet
        self.lunge_planned = False
        self.revenge = False               # was knocked back: lunge right after landing
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

    def top_y(self):
        return self.feet_y - self.body_h

    def lunge(self, dist):
        """Jump so as to land right on the pet's current spot."""
        u = self.pet.u
        vy = 110 * u
        flight = 2 * vy / 1500.0
        self.vy = -vy
        self.vx = dist / flight
        self.airborne = True
        self.attacking = True
        self.pet.incoming_lunge(self)

    def bounce_off(self, direction):
        u = self.pet.u
        self.vx = direction * 40 * u
        self.vy = -60 * u
        self.airborne = True

    def hit(self, direction, damage=1, color="#ffffff"):
        if self.dead:
            return
        self.hp -= damage
        self.flash = 0.16
        u = self.pet.u
        self.pet.popup(self.x, self.top_y(), str(damage), color,
                       size=1.0 + 0.25 * (damage - 1))
        winding_up = self.lunge_planned and self.crouch > 0 and not self.airborne
        if winding_up and self.hp > 0:
            return          # committed to its lunge: takes the hit without flinching
        push = 1.0 + 0.4 * (damage - 1)
        self.vx = direction * 55 * u * push
        self.vy = -55 * u * push
        self.airborne = True
        self.crouch = 0.0
        self.attacking = self.lunge_planned = False   # knocked out of its attack
        self.revenge = True
        if self.hp <= 0:
            self.die()
        elif self.big and self.hp <= 2:
            self.split()

    def die(self):
        self.dead = True
        self.pet.on_monster_killed()
        self.pet.popup(self.x, self.top_y() - 6 * self.pet.u, "+1", "#7dff8a", rise=40)
        self.burst(14 if self.big else 10)

    def split(self):
        """Big slime pops into two small 1-HP slimes that jump apart."""
        self.dead = True
        u = self.pet.u
        for direction in (-1, 1):
            child = Slime(self.pet, self.x + direction * self.half_w * 0.5,
                          big=False, colors=self.colors, hp=1,
                          feet_y=min(self.feet_y, self.pet.ground) - 1)
            child.vx = direction * random.uniform(70, 95) * u
            child.vy = -random.uniform(110, 140) * u
            child.flash = 0.1
            self.pet.add_monster(child)
        self.pet.popup(self.x, self.top_y() - 4 * u, "SPLIT!", "#8fd8ff", size=0.9)
        self.burst(8)

    def burst(self, count):
        self.canvas.itemconfig(self.img_id, state="hidden")
        cx, cy = self.cw / 2, self.ch - self.body_h / 2
        colors = [self.colors[1], self.colors[2], self.colors[3], "#ffffff"]
        for _ in range(count):
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
                if self.attacking:
                    self.attacking = False
                    self.pet.slime_landed(self)
                elif self.revenge:          # shake it off and come right back
                    self.revenge = False
                    self.hop_timer = random.uniform(0.2, 0.45)
        elif self.crouch > 0:
            self.crouch -= dt
            if self.crouch <= 0:
                dist = self.pet.x - self.x
                if self.lunge_planned and abs(dist) < LUNGE_RANGE * u * 1.3:
                    self.lunge(dist)
                else:
                    if abs(dist) < 700 and random.random() < 0.7:
                        direction = 1 if dist > 0 else -1     # creep toward the hero
                    else:
                        direction = random.choice((-1, 1))
                    self.vx = direction * random.uniform(25, 45) * u
                    self.vy = -random.uniform(90, 130) * u
                    self.airborne = True
                self.lunge_planned = False
        else:
            self.hop_timer -= dt
            if self.hop_timer <= 0:
                near = abs(self.pet.x - self.x) < LUNGE_RANGE * u
                self.lunge_planned = (self.pet.fight_back.get() and near
                                      and random.random() < LUNGE_CHANCE)
                self.crouch = 0.32 if self.lunge_planned else 0.18  # longer wind-up = tell
                fighting = near and self.pet.fight_back.get()
                self.hop_timer = random.uniform(0.4, 0.9) if fighting else random.uniform(0.9, 2.4)

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
        self.root.report_callback_exception = self.on_crash
        make_overlay(self.root)

        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.z_id = self.canvas.create_text(0, 0, text="", fill="#dfe9ff",
                                            font=("Consolas", 11, "bold"))
        self.bar_bg = self.canvas.create_rectangle(0, 0, 0, 0, fill="#140c1c",
                                                   outline="#cfc6e0", state="hidden")
        self.bar_fg = self.canvas.create_rectangle(0, 0, 0, 0, fill="#5be36b",
                                                   width=0, state="hidden")

        settings = load_settings()
        self.fight_back = tk.BooleanVar(value=settings.get("fight_back", True))
        self.hp = PET_MAX_HP
        self.invuln = 0.0
        self.regen_t = 0.0
        self.hp_show_until = 0.0
        self.faint_until = 0.0
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
        self.popups = []
        self.kills = int(settings.get("kills", 0))
        self.hit_done = True
        self.spawn_timer = random.uniform(*FIRST_SPAWN_S)
        self.monsters_on = tk.BooleanVar(value=settings.get("monsters", True))
        self.startup_on = tk.BooleanVar(value=startup_enabled())
        if self.startup_on.get():
            self.toggle_startup()      # refresh the path in case the folder moved
        self.hidden = False
        self.next_fullscreen_check = 0.0

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
                           "monsters": self.monsters_on.get(),
                           "fight_back": self.fight_back.get(),
                           "kills": self.kills}, fh, indent=2)
        except Exception:
            pass

    def toggle_startup(self):
        try:
            set_startup(self.startup_on.get())
        except OSError as e:
            self.startup_on.set(startup_enabled())
            messagebox.showerror("Start with Windows",
                                 "Couldn't change the startup setting:\n%s" % e,
                                 parent=self.root)

    def on_crash(self, *_exc):
        log_crash()
        self.root.destroy()

    def set_hidden(self, hide):
        if hide == self.hidden:
            return
        self.hidden = hide
        for w in [self.root] + [m.win for m in self.monsters] + [p.win for p in self.popups]:
            try:
                w.withdraw() if hide else w.deiconify()
            except tk.TclError:
                pass

    # ---- menu ------------------------------------------------------------ #
    def build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Slimes defeated: %d" % self.kills, state="disabled")
        self.kills_index = self.menu.index("end")
        self.menu.add_separator()
        self.char_menu = tk.Menu(self.menu, tearoff=0, postcommand=self.fill_char_menu)
        self.menu.add_cascade(label="Character", menu=self.char_menu)
        self.menu.add_command(label="Jump!", command=lambda: self.start_jump(0))
        self.menu.add_command(label="Take a nap", command=self.start_nap)
        self.menu.add_command(label="Spawn a monster", command=self.spawn_monster)
        self.menu.add_checkbutton(label="Monsters appear", variable=self.monsters_on,
                                  command=self.save_settings)
        self.menu.add_checkbutton(label="Slimes fight back", variable=self.fight_back,
                                  command=self.save_settings)
        size = tk.Menu(self.menu, tearoff=0)
        for label, _ in SIZES:
            size.add_radiobutton(label=label, variable=self.size_var, value=label,
                                 command=lambda l=label: self.set_size(l))
        self.menu.add_cascade(label="Size", menu=size)
        self.menu.add_checkbutton(label="Start with Windows", variable=self.startup_on,
                                  command=self.toggle_startup)
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
        idle_h = max(f["h"] for f in self.frames["idle"])
        self.idle_h = idle_h
        self.bar_w = max(16, 14 * self.u)
        self.bar_h = max(3, round(2 * self.u))
        self.bar_y = self.ch - idle_h - 5 * self.u
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
        self.add_monster(Slime(self, x))
        if self.state == "sleep" and self.nap_until:   # casual nap -> wake up
            self.start_wake()

    def add_monster(self, m):
        self.monsters.append(m)

    def popup(self, x, y, text, color, size=1.0, rise=28):
        while len(self.popups) >= 15:
            self.popups.pop(0).destroy()
        self.popups.append(Popup(self, x, y, text, color, size, rise))

    # ---- getting hurt ---------------------------------------------------- #
    def incoming_lunge(self, m):
        if self.state in ("idle", "walk", "hunt", "guard") and random.random() < DODGE_CHANCE:
            self.facing = -1 if m.x > self.x else 1     # roll away from it
            self.set_state("dodge")
            self.play("dodge")

    def slime_landed(self, m):
        dx = m.x - self.x
        overlap = abs(dx) <= m.half_w + self.char.body_w * self.s * 0.5
        on_ground = self.feet_y >= self.ground - 2
        vulnerable = self.state in ("idle", "walk", "hunt", "attack", "land", "guard")
        if overlap and on_ground and vulnerable and self.invuln <= 0 \
                and self.fight_back.get():
            direction = -1 if dx > 0 else 1
            m.bounce_off(-direction)
            self.take_hit(direction)

    def take_hit(self, direction):
        self.hp -= 1
        self.invuln = INVULN_S
        self.hp_show_until = time.monotonic() + 3
        self.popup(self.x, self.feet_y - self.idle_h - 8 * self.u, "-1", "#ff5a5a")
        self.canvas.itemconfig(self.z_id, text="")
        if self.hp <= 0:
            self.hp = 0
            self.faint()
            return
        self.facing = -direction                       # look at the attacker
        self.vx = direction * 90 * self.u
        self.set_state("hurt")
        self.play("hurt")

    def faint(self):
        self.vx = 0.0
        self.feet_y = self.ground
        self.set_state("fainted")
        self.play("sleep", loop=self.char.sleep_loops)
        self.faint_until = time.monotonic() + random.uniform(*FAINT_S)

    def revive(self):
        self.hp = PET_MAX_HP
        self.hp_show_until = time.monotonic() + 3
        self.invuln = INVULN_S
        self.popup(self.x, self.feet_y - self.idle_h - 8 * self.u, "+HP", "#7dff8a")
        self.start_wake()

    def toss_impact(self, speed):
        """Pet landed after being thrown: hurt slimes near the landing spot."""
        if speed < 500:
            return
        damage = 2 if speed > 1400 else 1
        hit_any = False
        for m in [m for m in self.monsters if not m.dead]:
            dx = m.x - self.x
            if abs(dx) - m.half_w <= 14 * self.u:
                m.hit(1 if dx >= 0 else -1, damage, color="#ffb347")
                hit_any = True
        if hit_any:
            self.popup(self.x, self.ground - 26 * self.u, "SLAM", "#ffb347", size=0.9)

    def on_monster_killed(self):
        self.kills += 1
        self.menu.entryconfig(self.kills_index,
                              label="Slimes defeated: %d" % self.kills)
        self.save_settings()

    def update_monsters(self, dt):
        if self.monsters_on.get() and user_idle_seconds() < SLEEP_AFTER_IDLE_S:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_timer = random.uniform(*SPAWN_EVERY_S)
                if sum(not m.dead for m in self.monsters) < MAX_MONSTERS:
                    self.spawn_monster()
        for m in list(self.monsters):
            m.update(dt)
            if not m.gone:
                m.render()
        self.monsters = [m for m in self.monsters if not m.gone]
        for p in self.popups:
            p.update(dt)
        self.popups = [p for p in self.popups if not p.gone]

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
            if m.attacking and m.feet_y < self.ground - 8 * self.u:
                continue        # sword passes under a slime that's high mid-lunge
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
        if seconds is None:          # user went away: a proper rest heals fully
            self.hp = PET_MAX_HP
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
        if not self.press or self.state == "fainted":
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
            elif self.state in ("idle", "walk", "hunt", "guard"):
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
        if now >= self.next_fullscreen_check:
            self.next_fullscreen_check = now + 1.0
            self.set_hidden(fullscreen_app_active())
        try:
            if not self.hidden:          # paused while a fullscreen app is up
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

        self.invuln = max(0.0, self.invuln - dt)
        if self.live_monsters() or st == "fainted" or self.hp >= PET_MAX_HP:
            self.regen_t = 0.0
        else:
            self.regen_t += dt
            if self.regen_t >= REGEN_EVERY_S:
                self.regen_t = 0.0
                self.hp += 1
                self.hp_show_until = time.monotonic() + 3

        if st not in ("sleep", "wake", "held", "fall", "hurt", "fainted") and \
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
                    self.set_state("guard")          # brief stance before the next swing
                    self.play("idle", loop=True)
                    self.timer = random.uniform(*GUARD_S)
                else:
                    self.enter_idle(1.5, 4.0)

        elif st == "guard":
            m = self.nearest_monster()
            if m is None:
                self.enter_idle(1.0, 3.0)
            else:
                if m.x != self.x:
                    self.facing = 1 if m.x > self.x else -1
                self.timer -= dt
                if self.timer <= 0:
                    self.enter_hunt()

        elif st == "fall":
            self.vy += 2200 * dt
            self.vx *= (1 - 0.8 * dt)
            self.x += self.vx * dt
            self.feet_y += self.vy * dt
            if self.vx:
                self.facing = 1 if self.vx > 0 else -1
            if self.feet_y >= self.ground:
                self.feet_y = self.ground
                self.toss_impact(math.hypot(self.vx, self.vy))
                self.vx = self.vy = 0
                self.set_state("land")
                n = len(self.frames["jump"])
                self.play("jump", seq=range(max(0, n - 3), n))

        elif st == "land":
            if self.anim["done"]:
                self.enter_idle()

        elif st == "hurt":
            self.vx *= max(0.0, 1 - 6 * dt)
            self.x += self.vx * dt
            if self.anim["done"]:
                self.vx = 0.0
                if self.live_monsters():
                    self.enter_hunt()
                else:
                    self.enter_idle(1.0, 3.0)

        elif st == "fainted":
            if time.monotonic() > self.faint_until:
                self.revive()

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

        self.render_hp_bar()

        geom = "%dx%d+%d+%d" % (self.cw, self.ch,
                                int(self.x - self.half_w), int(self.feet_y - self.ch))
        if geom != self.last_geom:
            self.root.geometry(geom)
            self.last_geom = geom
        if self.monsters:
            self.root.lift()   # stay above slime windows

    def render_hp_bar(self):
        show = self.fight_back.get() and (
            self.hp < PET_MAX_HP or self.state == "fainted" or bool(self.live_monsters())
            or time.monotonic() < self.hp_show_until)
        if not show:
            self.canvas.itemconfig(self.bar_bg, state="hidden")
            self.canvas.itemconfig(self.bar_fg, state="hidden")
            return
        x0 = self.half_w - self.bar_w / 2
        y0 = self.bar_y
        self.canvas.coords(self.bar_bg, x0 - 1, y0 - 1, x0 + self.bar_w + 1, y0 + self.bar_h + 1)
        frac = self.hp / float(PET_MAX_HP)
        color = "#5be36b" if frac > 0.6 else "#f2d548" if frac > 0.3 else "#ff5a5a"
        self.canvas.itemconfig(self.bar_bg, state="normal")
        if frac > 0:
            self.canvas.coords(self.bar_fg, x0, y0, x0 + self.bar_w * frac, y0 + self.bar_h)
            self.canvas.itemconfig(self.bar_fg, fill=color, state="normal")
        else:
            self.canvas.itemconfig(self.bar_fg, state="hidden")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if already_running():
        tk.Tk().withdraw()
        messagebox.showinfo("Desktop Pet", "Your pet is already running.\n\n"
                            "Right-click it and choose Goodbye to close it.")
        raise SystemExit(0)
    try:
        DesktopPet().run()
    except Exception:
        log_crash()
