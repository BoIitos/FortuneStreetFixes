# Working notes

Handover notes for continuing this work, also in a new Claude Code session. The README describes the fixes. This file holds what is needed to continue: state, methods and conventions.

## Conventions

- Answer in German unless the user writes English. Repository files stay in English.
- Commit or push only when asked. The user usually commits.
- The user tests in Dolphin and reports results. Do not call a fix confirmed before that.
- Never commit game files, `main.dol` files or decompiled game code. Mods contain patches only.

## Workspace

Expected next to each other, paths differ per machine:

- `FortuneStreetFixes`: this repository, used as a CSMM modpack.
- `boom-street-decomp`: decompilation project for PAL ST7P01. Game code is not decompiled, but the disassembly in `build/ST7P01/asm` and the symbols in `config/ST7P01/symbols.txt` are the main reference. Build it to get `build/`; it needs the game image in `orig/`.
- `csmm`: CSMM source (csmm-qt). Useful files: `lib/gameinstance.cpp` (address tables), `lib/mods/modloader.cpp`, `lib/importexportutils.cpp`, `lib/configuration.cpp`.
- CSMM 7.4.0 install with `csmmpython` and `wit`.
- Test modpack with the maps `glitch86`-`glitch88`, `large`, `max_paths` and `Borg`. `max_paths` has 128 squares and theme DragonQuest.
- A patched `main.dol` of the US version (`ST7E01`) from Fortune Street 2. It is useful for checking addresses, but it is not an original file.

## Open points

- **Fix 8 (model heap 3 MB -> 4 MB):** two autopilot games on `max_paths` finished without a crash, after 347 and 330 rounds. Before the fix, the same map crashed twice. Confirmed by the user, and the README says so.
- **Possible leak:** it is not checked whether `ChanceCardSelector::Close` frees everything. A crash that returns much later would point to a leak or steady growth. Two clean games of more than 300 rounds speak against a large leak.
- **Heap fill level:** never measured directly. The cause is derived from code and registers.
- **Selector tiles:** `r20` was 60 in the crash, the tile count was not confirmed (probably 64), and the user saw a complete selection after ignoring the exceptions. This is unexplained.
- **Both crashes happened on square 6 of `max_paths`** (spade suit square). `Open` does not depend on the square as far as read, so this may be chance.
- **Optional hardening:** skip tiles in `ChanceCardSelector::exec` when `GetResMatChan` returns NULL, so a full heap no longer crashes. Not implemented, because it would hide the warning.
- **Fortune Street:** patch sites match in the patched US `main.dol`, not tested in game. Itadaki Street is only checked by calculation.
- **Real hardware:** nothing has been tested there.
- **More than 12 districts:** judged not worthwhile. It touches about 277 stock accesses, 89 area base references, 67 places with stride 0x78, save format, UI and possibly CSMM.

## Findings not in the README

Memory:

- `Memory::Wii::Allocator()`: `Memory::Heap` in MEM1. `ScnRoot` of the board scene comes from here.
- `Memory::Wii::Allocator4NW()`: separate expanded heap in MEM2, used only by `Resource::Model::Obj::init`. `Memory::Init` sets its size. The task heap gets the rest of MEM2.
- The main stack is 128 KB (0x8081F018-0x8083F018).

`Gm::Area` (0x78 bytes, 12 at `g_board`+0x2A00):

| Offset | Content |
|---|---|
| 0x00 | Stock price related value |
| 0x04 | id |
| 0x08-0x0F | Shop squares (maximum 8) |
| 0x10 | Shop count |
| 0x14-0x63 | Table of 20 values, read by `CalcSellStockLimit`; looks derived, unconfirmed |
| 0x64, 0x68, 0x6C | Values used for prices; 0x68 is the current stock price as used in `BuyStock`, 0x6C its previous value |
| 0x74 | Stock traded this turn |

`Gm::Player` (0x4DC bytes, array at `g_board`+0x2FA0): stock counters at 0x414-0x443, 4 bytes per district.

`Game::AreaUI`: `UIAreaShopStatus` boxes were at +0x4C (0x48 bytes each, layout pointer at box+0x34), layout at +0x34, game manager at +0x30, `UIPlayerStock` x4 at +0x1FC. The boxes now live at +0xB08.

`ChanceCardSelector`: tile pointers at +0x2C + 4i, grid size +0x148 x +0x14C. Tile +0x14 is the `Resource::Model::Obj`; its +0x50 is the `ResMdl`, its +0x54 the `ScnMdl`. The panels come from `game/ui_game_chance_panel.cmpres` (`obj_ui_panel`, or `obj_ui_panel_b` for theme 1), material `MT_panel`.

Layouts: pane name at +0xC, translate at +0x24, scale at +0x3C, size at +0x44. Header: file size at 0x8, section count at 0xE. The legend window `w_01` is right aligned (base position 5). `ui_game_018_scene.brlyt` is identical in PAL and US, in all language archives.

CSMM:

- User mods are imported with the modpack directory on `sys.path`, so `FortuneStreetFixesCommon.py` can be imported. Changing it needs a CSMM restart, because only the mods themselves are reloaded.
- `mapList.yaml` entries may point to a `.zip` or directly to a `.yaml`. A direct `.yaml` needs all files next to it. `.background.zip` and `.music.zip` are only read for `.zip` maps.
- The mapper is `standard = boom - delta`. Data addresses in generated code must go through `std()`, otherwise they are PAL only. Expected instructions that contain data addresses must be computed from the mapped address.
- Landing directly on a suit square always opens the venture card selection.

## Debugging in Dolphin

- Crash reports give `PC`. Find the function with a search for the address in `build/ST7P01/asm`, then the callers.
- The warning blocks the debugger. Use an instruction breakpoint on the crashing address with a condition such as `r4 == 0`, so registers are still intact.
- For a leaf function `LR` gives the caller.
- The Dolphin title shows `ST7P02` for CSMM builds of the PAL game.
- A Dolphin exception on a low address means a NULL pointer plus a field offset.

## Tools

See the comments in each script. All run with plain Python unless noted.

- `tools/offline_check.py`: compares all patch sites with a `main.dol` and runs the mods with a simulated mapper, for Boom Street, Fortune Street or Itadaki Street.
- `tools/test_ai_distance.py`: compares the BFS with the original function in unicorn, on a `main.dol` without `AiPathing`.
- `tools/u8.py <arc> <output dir> <name filter>`: extracts files from a U8 archive.
- `tools/brlyt.py <file>`: dumps the panes of a layout.
- `tools/pycsmm.py`: stub of the CSMM Python module for running mods outside CSMM.

Python pitfalls on Windows: paths with non-ASCII characters may fail as arguments under Git Bash, so copy such files first or use PowerShell. Remove `__pycache__` after running mods from a modpack directory.
