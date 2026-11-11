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

- **Fix 8 (model heap):** confirmed: an autopilot game of 802 rounds on `max_paths` with the Mario Character Pack finished without a crash, and the breakpoints for a failed fallback and for fix 9 never hit. History: a 4 MB heap removed the crash but hung before the title screen with the pack; 3.25 MB started but later crashed. Now the heap stays at 3 MB and `Resource::Model::Obj::init` retries with `Memory::Wii::Allocator()` when `Construct` returns NULL. The first crash read in `exec` without a write in `Open` first, which is not explained yet.
  Measured with the Mario Character Pack on `max_paths` (logging breakpoint on the fallback path, `r4` = requested size, `r7`/`r10` = free block at the end of the model heap, which ends at 0x935E0010): each selector opening falls back for about 40-55 panels of 0x1B20 bytes (about 340 KiB). The count varies with fragmentation. The free block at the end shrank twice early (0x5A0, 0x480 bytes, probably board models) and then stayed at 0xDB0 over four openings, so no leak in the model heap. A second model of 0x1E100 bytes (about 120 KiB) also falls back: the star animation on Boon and Boom squares. The fallback models come from MEM1 and their addresses are reused across openings, so they are freed; the task heap was never needed.
- **Hang before Memory Blocks (fix 11, confirmed):** in an autopilot game after 545 rounds (FeelFree, Mario Character Pack, wolfs_ai_mod, cswt) the minigame title stayed up forever. `Game::GameManager::exec` waited in state 9 (+0x4CC = 9, handler at 0x800D1498) for `Resource::Async::IsReady` on GameManager+0x21C + 8 × kind (kind +0x218 = 1, `game/mg_block.brres`). The `Resource::Async` had +0xC = NULL: the first `File::Async::Access::Read` (0x8000A39C) in `Resource::Async::Async` (0x800511B0) failed because the read buffer (task heap, `File::Allocator::Default`, tag `FILE`) found no free block, and the game never retries. Memory dumps (`tools/heapdump.py`): the task heap had 6.25 MB free in 994 blocks, the largest 2.53 MB. Between the free blocks lay one 2.5 MB `TNMB` block: the font vector of a `Scene::Layout::ResourceHolder` (owner 0x8159B860 in both dumps, vector at +0xBC) with 101,984 copies of the same `{shared_ptr<FontHolder>, empty FontRefLink}`, appended by `Scene::Layout::Manager::SetExtraFont`. After 25 rounds of a new game it held 4,179 entries and the task heap had 42 free blocks, the largest 6.63 MB. Fix 11 skips duplicate appends. If the hang comes back: `Memory::Heap::Malloc` falls back from the MEM1 heap to the task heap, but not the other way round; the MEM1 heap had a free block of 4.28 MB, so a reverse fallback would be the next step. To check the fix, dump memory after many rounds and look at the vector size at ResourceHolder+0xC0. With fix 11, after 244 rounds: 10 entries, task heap 8.62 MB free in 32 blocks, largest 6.63 MB (same as after 25 rounds without the fix). `TNMB` grew from 17,762 to 18,287 blocks between round 25 and 244, but its bytes fell slightly; a later dump should show whether that is noise. It was: after 470 rounds 17,923 blocks, at the end of the game (486 rounds) 13,763; the font vectors stayed at 9-10 entries and the largest free block of the task heap at 6.6 MB. The game ended at 486 rounds without a hang, so no game has passed 545 rounds yet, but the heap shows no growth that could lead there.
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
| 0x14-0x63 | Table of 20 values, read by `CalcSellStockLimit`. 0x14 + 4 × player is the stock that player holds in the district (`GPProcStock::ProcSell` uses it as the sell maximum, capped at 999) |
| 0x64, 0x68, 0x6C | Values used for prices; 0x68 is the current stock price as used in `BuyStock`, 0x6C its previous value |
| 0x74 | Stock traded this turn |

`Gm::Player` (0x4DC bytes, array at `g_board`+0x2FA0, `g_board` = 0x8054D018): completed turns at 0x404 (`Gm::Board::GetAroundTurn` returns the minimum over active players, +0x470 != 0 and +0x464 <= 0, as the completed rounds; `tools/heapdump.py` prints it), stock counters at 0x414-0x443, 4 bytes per district.

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
- `tools/heapdump.py <dump dir> [suffix] [suffix B]`: free memory, largest free blocks and usage by tag of the task heap and the MEM1 heap in Dolphin dumps (`mem1<suffix>.raw`, `mem2<suffix>.raw`); with two suffixes it compares two dumps.
- `tools/test_font_leak.py`, `tools/test_number_limit.py`: unicorn tests of the routines of `LayoutFontLeak` and `AiNumberInput` (`pip install unicorn`).

Python pitfalls on Windows: paths with non-ASCII characters may fail as arguments under Git Bash, so copy such files first or use PowerShell. Remove `__pycache__` after running mods from a modpack directory.
