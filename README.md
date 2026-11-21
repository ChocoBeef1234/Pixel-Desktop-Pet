# Pixel Desktop Pet

A small character that lives on top of your Windows taskbar. It wanders, jumps,
rolls, naps, and hunts down slimes that drop in from time to time.
**Bring your own character:** any sprite set can be the pet.

## Features
- Idle wandering, jumps, dodge rolls and attack practice
- Slimes spawn randomly (4 colors, occasional big ones) and your character hunts them
- Click the character to make it attack; click a slime to squish it yourself
- Drag the character to pick it up, release to drop or toss it
- Falls asleep when you're away from the computer, wakes when you return
- Right-click menu: kill counter, character picker and importer, jump, nap,
  spawn monster, toggle monsters, size, quit
- Remembers your character, size and monster setting

## Requirements
- Windows
- Python 3.10+ with tkinter
- Pillow: `pip install pillow`

## Run
Double-click `meow_knight_pet.pyw`, or:

```
pythonw meow_knight_pet.pyw
```

Right-click the character and choose **Goodbye** to quit.

## Add your own character
The pet comes with **Slime Buddy**, but any sprite set can be the pet.

1. **Put your sprites in a folder**, one file per animation, named by what it does:

   ```
   my_hero/
     idle.png      <- the only required one
     run.png
     jump.png
     attack.png    (or attack_1.png, attack_2.png ... for several attacks)
     hurt.png
     sleep.png
     dodge.png
   ```

   Names like `Hero_Walk.gif` or `knightAttack2.png` are recognised too.

2. **Check the sprites meet these requirements:**
   - Transparent background (PNG, GIF or WebP)
   - Drawn facing right, or set `"facing": "left"` in `character.json`
   - Each file is a strip of frames, an animated GIF, or a folder of numbered frames.
     Square frames, or frames separated by transparent gaps, are sliced automatically.

3. **Import it:** right-click the pet → **Character → Import character folder...**
   and pick your folder. The pet shows which animations it found and switches to
   your character. Anything missing falls back to another animation, so even a
   single idle image works.

4. **Fine-tune (optional):** the import creates a `character.json` in
   `characters/<your_character>/`. Edit it to change speed, facing, attack range
   or frame sizes, then pick the character again from the menu.

You can also copy a folder straight into `characters/` and it will appear in the
**Character** menu. Switch characters any time from the same menu.

See [CHARACTERS.md](CHARACTERS.md) for every option and troubleshooting tips.
`characters/slime_buddy/` is a minimal example with no config file at all.

The slime monsters are drawn in code, so they need no image files.
