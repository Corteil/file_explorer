# File Explorer

A file manager for the EMF Tildagon badge. Browse the badge's flash and any SD card, view
files, and copy, move, rename and delete them, or make new folders.

## Controls

The six edge buttons, or a USB keyboard (arrows, Enter, Escape; a typed letter jumps to the
next name starting with it).

| Button | Browsing | In a menu | Viewing a file |
|---|---|---|---|
| UP / DOWN | move (hold to repeat) | move | scroll a line |
| LEFT / RIGHT | LEFT: folder menu, RIGHT: item menu | | page up / down |
| OK | open a folder, view a file | choose | |
| CANCEL | up a folder (leaves the app from the storage list) | close | back |

- **Item menu (RIGHT):** Open, Copy, Cut, Rename, Delete (asks first), Info.
- **Folder menu (LEFT):** Paste here / Move here (when something is copied or cut), New folder,
  Refresh, Storage info.
- **Copy and move** show a progress ring and can be stopped with CANCEL (a stopped copy leaves
  the part already written). Moving inside one storage is an instant rename; between flash and
  SD it copies and then deletes. Pasting a name that already exists makes `name (2).ext`.
- **Viewing:** text files show the first 4 KB wrapped to the screen; anything else shows as hex.
- Storages are the badge flash and any mount of 256 KB or more, so the SD card (`/sdcard`) shows
  up and the tiny hexpansion EEPROM mounts do not.

## Files

- `fs.py` - all file operations, with no badge imports so it can be tested on a PC. Copy, move
  and delete are generators that report progress.
- `app.py` - the app: browsing, menus, jobs, viewer, text entry (the firmware's own, which a
  USB keyboard can type into).
- `ui.py` - drawing helpers for the round screen; text is shortened to the width of the screen at
  its height.

## Install

Copy `__init__.py app.py fs.py ui.py tildagon.toml metadata.json` to `/apps/file_explorer/` on the
badge, e.g. with `mpremote fs cp`, then restart the badge.

License: MIT
