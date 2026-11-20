# Meow Knight Desktop Pet

A small knight cat that lives on top of your Windows taskbar. It wanders, jumps,
rolls, naps, and hunts down slimes that drop in from time to time.

## Features
- Idle wandering, jumps, dodge rolls and sword practice
- Slimes spawn randomly (4 colors, occasional big ones) and the knight hunts them
- Click the cat to make it attack; click a slime to squish it yourself
- Drag the cat to pick it up, release to drop or toss it
- Falls asleep when you're away from the computer, wakes when you return
- Right-click menu: kill counter, jump, nap, spawn monster, toggle monsters, size, quit

## Requirements
- Windows
- Python 3.10+ with tkinter
- Pillow: `pip install pillow`

## Sprites (not included)
The cat sprites come from the **Meow Knight** asset pack, whose license does not
allow redistribution, so they are not in this repo. Get the pack yourself and copy
these files into the `assets/` folder:

```
Meow-Knight_Attack_1.png  Meow-Knight_Attack_2.png  Meow-Knight_Attack_3.png
Meow-Knight_Death.png     Meow-Knight_Dodge.png     Meow-Knight_Idle.png
Meow-Knight_Jump.png      Meow-Knight_Run.png       Meow-Knight_Take_Damage.png
```

The slime monsters are drawn in code, so no extra assets are needed for them.

## Run
Double-click `meow_knight_pet.pyw`, or:

```
pythonw meow_knight_pet.pyw
```

Right-click the cat and choose **Goodbye, kitty** to quit.
