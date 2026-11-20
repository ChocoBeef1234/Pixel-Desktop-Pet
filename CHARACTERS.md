# Adding your own character

Any character can be the pet. A character is just a **folder of sprite images**,
optionally with a `character.json` file for fine-tuning.

## Quick start (no config needed)

1. Put your sprites in a folder, named by animation:

   ```
   my_hero/
     idle.png      <- required
     run.png
     jump.png
     attack.png    (attack_1.png, attack_2.png ... for several attacks)
     hurt.png
     sleep.png
     dodge.png
   ```

2. Right-click the pet → **Character → Import character folder...** and pick the folder.

The pet copies the files into `characters/`, writes a `character.json` for you,
shows what it found, and switches to the new character.

You can also drop the folder straight into `characters/` yourself. It will appear
in the **Character** menu.

## Sprite requirements

| Requirement | Details |
|---|---|
| **Transparent background** | PNG/GIF/WebP with alpha. Semi-transparent pixels are rounded to fully on or off, so soft glows or shadows will look hard-edged. |
| **Only `idle` is required** | Anything missing falls back automatically (see below). |
| **Facing right** | Draw the character facing right, or set `"facing": "left"` in `character.json`. The pet mirrors it when walking the other way. |
| **Feet at the bottom** | The lowest visible pixel of each frame is treated as the ground. |
| **One animation per file** | Use a sprite sheet, an animated GIF, or a folder of numbered frames. |

### Accepted formats for each animation

- **Horizontal or vertical strip of square frames**, e.g. `idle.png` is 128×32 for 4 frames
  of 32×32. These are detected automatically.
- **Strip with transparent gaps between frames**, with frames of any size. Detected automatically.
- **Animated GIF / WebP**: each GIF frame's own timing is used.
- **Folder of frames**, e.g. `run/` containing `1.png, 2.png, ...`, played in natural number order.
- **Grid sheet** (several rows): set `frame_width` / `frame_height` in `character.json`.
- **Strip of non-square frames with no gaps**: set `frames` (the count) in `character.json`.

### File name detection

Names are matched by words, case-insensitive, so `Hero_Run.png`, `walk.gif`, and
`knightAttack2.png` all work:

| Animation | Recognised words |
|---|---|
| idle | idle, stand, breath |
| run | run, walk, move |
| jump | jump, leap |
| dodge | dodge, roll, dash, evade |
| attack | attack, slash, swing, atk, strike, punch, shoot |
| hurt | hurt, damage, hit, pain |
| sleep | sleep, death, die, dead, rest, nap |

### Fallbacks for missing animations

| Missing | What the pet does |
|---|---|
| run | slides around using idle |
| dodge | uses run |
| jump | jumps in an arc using idle |
| attack | uses idle (it can still defeat slimes) |
| hurt | uses idle when picked up |
| sleep | plays idle slowly with "zzz" |

A **sleep** animation should go from standing to lying down. The pet holds the
last frame while sleeping and plays it backwards to wake up. A death animation
works well for this.

## `character.json` reference

Everything is optional except `animations.idle`.

```json
{
  "name": "My Hero",
  "facing": "right",
  "pixel_art": true,
  "attack_reach": 20,
  "jump_air_frames": [2, 5],
  "fall_frame": 4,
  "animations": {
    "idle": "idle.png",
    "run":  {"file": "run.png", "fps": 12},
    "jump": {"file": "sheet_jump.png", "frames": 6},
    "attack": [
      {"file": "attack1.png", "ms": 70, "hit_frame": 3},
      {"file": "attack_sheet.png", "frame_width": 48, "frame_height": 32, "hit_frame": 2}
    ],
    "sleep": {"file": "death.gif"}
  }
}
```

**Character settings**

| Key | Meaning | Default |
|---|---|---|
| `name` | Shown in the Character menu | folder name |
| `facing` | Direction the sprites face: `"right"` or `"left"` | `"right"` |
| `pixel_art` | `true` = crisp nearest-neighbour scaling; `false` = smooth scaling for high-res art | `true` if idle is ≤ 64 px tall |
| `attack_reach` | How far the attack hits, in source pixels from the body center | 1.6 × body width |
| `jump_air_frames` | `[first, last]` jump frame indexes while in the air | middle of the jump |
| `fall_frame` | Jump frame shown while falling after being dropped | middle of the air frames |

**Animation settings.** An animation can be just a file name, or an object with:

| Key | Meaning |
|---|---|
| `file` | Image, GIF, or folder of frames (relative to the character folder) |
| `ms` / `fps` | Speed: milliseconds per frame, or frames per second |
| `frames` | Number of frames in a strip, to force even slicing |
| `frame_width`, `frame_height` | Cell size for grid sheets (read left→right, top→bottom; empty cells are skipped) |
| `layout` | `"auto"`, `"horizontal"`, `"vertical"`, `"gaps"` (split on transparent gaps), or `"grid"` |
| `merge_gap` | With `gaps`: join pieces closer than this many pixels (for detached effects) |
| `order` | List of frame indexes to play, e.g. `[0,1,2,1]` or to drop frames |
| `hit_frame` | (attack) Frame where the hit lands on a monster |
| `anchor_x` | Pixel column of the body center, if effects confuse auto-centering |

## Troubleshooting

- **Character jitters sideways:** set `anchor_x` for that animation.
- **Frames are cut wrongly:** set `frames`, or `frame_width`/`frame_height`.
- **Too big or too small:** right-click → **Size**. Sizes are based on the idle pose height.
- **Blurry pixel art / jaggy HD art:** set `pixel_art` to `true` or `false`.
- **Error on load:** the message tells you which file or line is wrong. Fix it and pick
  the character again from the menu.

The included **Slime Buddy** (`characters/slime_buddy/`) uses no `character.json`
at all. It's a minimal example of the quick-start format.
