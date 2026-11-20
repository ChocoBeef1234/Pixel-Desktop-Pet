"""
Character packs for the desktop pet.

A character is a folder containing sprite images and (optionally) a
``character.json`` manifest. Without a manifest, animations are detected from
file names such as ``idle.png``, ``Run.png``, ``hero_attack_1.png``.
See CHARACTERS.md for the full format.
"""
import json
import os
import re

from PIL import Image, ImageSequence

MANIFEST = "character.json"
IMAGE_EXTS = {".png", ".gif", ".webp", ".bmp"}
ROLES = ("idle", "run", "jump", "dodge", "attack", "hurt", "sleep")
DEFAULT_MS = {"idle": 150, "run": 95, "jump": 80, "dodge": 75,
              "attack": 85, "hurt": 110, "sleep": 160}

# Checked in order; a file name token starting with a keyword picks the role.
KEYWORDS = [
    ("attack", ("attack", "slash", "swing", "atk", "strike", "punch", "shoot")),
    ("hurt",   ("hurt", "damage", "hit", "pain")),
    ("dodge",  ("dodge", "roll", "dash", "evade")),
    ("jump",   ("jump", "leap")),
    ("sleep",  ("sleep", "death", "die", "dead", "rest", "nap")),
    ("run",    ("run", "walk", "move")),
    ("idle",   ("idle", "stand", "breath")),
]


class CharacterError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _tokens(name):
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return [t for t in re.split(r"[^A-Za-z]+", name.lower()) if t]


def guess_role(filename):
    toks = _tokens(os.path.splitext(filename)[0])
    for role, words in KEYWORDS:
        if any(t.startswith(w) for t in toks for w in words):
            return role
    return None


def pretty_name(folder):
    base = os.path.basename(os.path.normpath(folder))
    return re.sub(r"[_\-]+", " ", base).strip().title() or "Character"


def _is_image(path):
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in IMAGE_EXTS


def _images_in(folder):
    return sorted((f for f in os.listdir(folder) if _is_image(os.path.join(folder, f))),
                  key=_natural_key)


def read_display_name(folder):
    """Cheap name lookup for menus (doesn't load images)."""
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as fh:
            name = json.load(fh).get("name")
            if name:
                return str(name)
    except Exception:
        pass
    return pretty_name(folder)


def looks_like_character(folder):
    if not os.path.isdir(folder):
        return False
    if os.path.isfile(os.path.join(folder, MANIFEST)):
        return True
    return any(guess_role(f) for f in os.listdir(folder))


# --------------------------------------------------------------------------- #
# Auto-detection
# --------------------------------------------------------------------------- #
def detect_manifest(folder):
    anims = {}
    for entry in sorted(os.listdir(folder), key=_natural_key):
        path = os.path.join(folder, entry)
        if not (_is_image(path) or (os.path.isdir(path) and _images_in(path))):
            continue
        role = guess_role(entry)
        if role == "attack":
            anims.setdefault("attack", []).append({"file": entry})
        elif role and role not in anims:
            anims[role] = {"file": entry}
    if "idle" not in anims:
        imgs = _images_in(folder)
        if len(imgs) == 1:                     # a lone image becomes the idle pose
            anims["idle"] = {"file": imgs[0]}
    return {"name": pretty_name(folder), "facing": "right", "animations": anims}


# --------------------------------------------------------------------------- #
# Slicing
# --------------------------------------------------------------------------- #
def _runs(alpha, horizontal, merge_gap):
    w, h = alpha.size
    n = w if horizontal else h
    filled = []
    for i in range(n):
        box = (i, 0, i + 1, h) if horizontal else (0, i, w, i + 1)
        filled.append(alpha.crop(box).getbbox() is not None)
    filled.append(False)
    runs, start = [], None
    for i, f in enumerate(filled):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append([start, i - 1])
            start = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return merged


def _split_sheet(im, entry):
    W, H = im.size
    layout = entry.get("layout", "auto")
    n = entry.get("frames")
    fw, fh = entry.get("frame_width"), entry.get("frame_height")

    if layout == "grid" or fw or fh:
        fw, fh = int(fw or W), int(fh or H)
        cells = [im.crop((x, y, x + fw, y + fh))
                 for y in range(0, H - fh + 1, fh)
                 for x in range(0, W - fw + 1, fw)]
        cells = [c for c in cells if c.getchannel("A").getbbox()]
        return cells[:int(n)] if n else cells

    if layout == "horizontal":
        horizontal = True
    elif layout == "vertical":
        horizontal = False
    else:
        horizontal = W >= H
    long_side, short_side = (W, H) if horizontal else (H, W)

    if not n and layout != "gaps":
        if long_side == short_side and layout == "auto":
            return [im]
        if long_side % short_side == 0:          # square frames side by side
            n = long_side // short_side
    if n:
        n = int(n)
        step = long_side / n
        if horizontal:
            return [im.crop((round(i * step), 0, round((i + 1) * step), H)) for i in range(n)]
        return [im.crop((0, round(i * step), W, round((i + 1) * step))) for i in range(n)]

    runs = _runs(im.getchannel("A"), horizontal, int(entry.get("merge_gap", 3)))
    if horizontal:
        return [im.crop((a, 0, b + 1, H)) for a, b in runs]
    return [im.crop((0, a, W, b + 1)) for a, b in runs]


def _normalize(frames):
    """Put frames on a shared canvas (bottom-center aligned) and trim padding."""
    if len({f.size for f in frames}) > 1:
        mw = max(f.width for f in frames)
        mh = max(f.height for f in frames)
        out = []
        for f in frames:
            c = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
            c.paste(f, ((mw - f.width) // 2, mh - f.height))
            out.append(c)
        frames = out
    boxes = [b for b in (f.getchannel("A").getbbox() for f in frames) if b]
    if not boxes:
        return []
    box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
           max(b[2] for b in boxes), max(b[3] for b in boxes))
    return [f.crop(box) for f in frames]


def _load_anim(folder, entry, role):
    rel = entry.get("file")
    if not rel:
        raise CharacterError("An animation for '%s' has no \"file\"." % role)
    path = os.path.join(folder, rel)
    if not os.path.exists(path):
        raise CharacterError("File not found for '%s': %s" % (role, rel))

    durations = None
    if os.path.isdir(path):
        frames = [Image.open(os.path.join(path, f)).convert("RGBA") for f in _images_in(path)]
    else:
        im = Image.open(path)
        if getattr(im, "n_frames", 1) > 1:       # animated GIF / WebP
            frames, durations = [], []
            for fr in ImageSequence.Iterator(im):
                frames.append(fr.convert("RGBA"))
                durations.append(fr.info.get("duration") or 100)
        else:
            frames = _split_sheet(im.convert("RGBA"), entry)

    order = entry.get("order")
    if order:
        frames = [frames[i] for i in order if 0 <= i < len(frames)]
        if durations:
            durations = [durations[i] for i in order if 0 <= i < len(durations)]

    frames = _normalize(frames)
    if not frames:
        raise CharacterError("No visible frames in %s ('%s')." % (rel, role))

    if "ms" in entry:
        ms = [float(entry["ms"])] * len(frames)
    elif "fps" in entry:
        ms = [1000.0 / float(entry["fps"])] * len(frames)
    elif durations and len(durations) == len(frames):
        ms = [float(d) for d in durations]
    else:
        ms = [float(DEFAULT_MS[role])] * len(frames)

    anim = {"frames": frames, "ms": ms, "width": frames[0].width}
    if role == "attack":
        anim["hit_frame"] = int(entry.get("hit_frame", len(frames) // 2))
    if "anchor_x" in entry:
        anim["anchor"] = float(entry["anchor_x"])
    return anim


def _body_anchor(frames, band):
    """Horizontal center of the densest column band = the body (not effects)."""
    w = frames[0].width
    if w <= band:
        return w / 2.0
    dens = [0] * w
    for f in frames:
        a = f.getchannel("A").point(lambda v: 255 if v > 127 else 0)
        for x in range(w):
            dens[x] += a.crop((x, 0, x + 1, f.height)).histogram()[255]
    window = sum(dens[:band])
    best, best_i = window, 0
    for i in range(1, w - band + 1):
        window += dens[i + band - 1] - dens[i - 1]
        if window > best:
            best, best_i = window, i
    return best_i + band / 2.0


# --------------------------------------------------------------------------- #
# Character
# --------------------------------------------------------------------------- #
class Character:
    def __init__(self, folder):
        self.folder = folder
        mpath = os.path.join(folder, MANIFEST)
        self.detected = not os.path.isfile(mpath)
        if self.detected:
            manifest = detect_manifest(folder)
        else:
            try:
                with open(mpath, encoding="utf-8") as fh:
                    manifest = json.load(fh)
            except json.JSONDecodeError as e:
                raise CharacterError("character.json has a mistake on line %d: %s"
                                     % (e.lineno, e.msg))
        self.manifest = manifest
        self.name = str(manifest.get("name") or pretty_name(folder))
        self.facing = "left" if manifest.get("facing") == "left" else "right"
        self.warnings = []

        spec = manifest.get("animations") or {}
        for key in spec:
            if key not in ROLES:
                self.warnings.append("Unknown animation '%s' ignored (use: %s)."
                                     % (key, ", ".join(ROLES)))
        if "idle" not in spec:
            raise CharacterError(
                "No 'idle' animation found.\n\nName an image idle.png (or add it "
                "to character.json). It's the only required animation.")

        self.anims, self.found = {}, {}
        for role in ROLES:
            if role not in spec:
                continue
            entries = spec[role] if isinstance(spec[role], list) else [spec[role]]
            entries = [{"file": e} if isinstance(e, str) else dict(e) for e in entries]
            if role != "attack":
                entries = entries[:1]
            loaded = [_load_anim(folder, e, role) for e in entries]
            if role == "attack":
                for i, a in enumerate(loaded):
                    self.anims["attack%d" % i] = a
            else:
                self.anims[role] = loaded[0]
            self.found[role] = [len(a["frames"]) for a in loaded]

        idle = self.anims["idle"]
        widths = sorted(b[2] - b[0] for b in
                        (f.getchannel("A").getbbox() for f in idle["frames"]) if b)
        self.body_w = widths[len(widths) // 2]
        self.body_h = max(f.height for f in idle["frames"])
        band = max(2, round(self.body_w * 0.7))
        for a in self.anims.values():
            if "anchor" not in a:
                a["anchor"] = _body_anchor(a["frames"], band)

        # Fallbacks for anything missing.
        self.fallbacks = []

        def alias(role, src, **override):
            a = dict(self.anims[src])
            a.update(override)
            self.anims[role] = a
            self.fallbacks.append((role.rstrip("0123456789"), src))

        if "run" not in self.anims:
            alias("run", "idle")
        if "dodge" not in self.anims:
            alias("dodge", "run")
        if "hurt" not in self.anims:
            alias("hurt", "idle")
        self.sleep_loops = "sleep" not in self.anims
        if self.sleep_loops:
            alias("sleep", "idle", ms=[m * 2 for m in idle["ms"]])
        has_jump = "jump" in self.anims
        if not has_jump:
            alias("jump", "idle")
        self.attacks = sorted(k for k in self.anims if k.startswith("attack"))
        if not self.attacks:
            alias("attack0", "idle", hit_frame=len(idle["frames"]) // 2)
            self.attacks = ["attack0"]

        n_jump = len(self.anims["jump"]["frames"])
        default_air = ([round(n_jump * 0.25), max(round(n_jump * 0.25), round(n_jump * 0.7) - 1)]
                       if has_jump else [0, n_jump - 1])
        air = manifest.get("jump_air_frames", default_air)
        self.air_frames = (max(0, min(int(air[0]), n_jump - 1)),
                           max(0, min(int(air[1]), n_jump - 1)))
        self.fall_frame = int(manifest.get("fall_frame",
                                           (self.air_frames[0] + self.air_frames[1] + 1) // 2))
        self.fall_frame = max(0, min(self.fall_frame, n_jump - 1))
        self.attack_reach = float(manifest.get("attack_reach", self.body_w * 1.6))
        self.pixel_art = bool(manifest.get("pixel_art", self.body_h <= 64))

    def summary(self):
        lines = ["%s" % self.name, ""]
        lines.append("Found: " + ", ".join(
            "%s (%s frames)" % (r, "+".join(str(n) for n in ns)) for r, ns in self.found.items()))
        if self.fallbacks:
            lines.append("Missing, using fallback: " + ", ".join(
                "%s -> %s" % (r, s.rstrip("0123456789")) for r, s in self.fallbacks))
        lines += self.warnings
        return "\n".join(lines)

    def files_used(self):
        files = []
        for v in (self.manifest.get("animations") or {}).values():
            for e in (v if isinstance(v, list) else [v]):
                f = e if isinstance(e, str) else e.get("file")
                if f:
                    files.append(f)
        return files
