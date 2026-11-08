# FortuneStreetFixes

A [Custom Street Map Manager](https://github.com/FortuneStreetModding/csmm-qt) (CSMM) modpack that fixes original-game bugs which show up with large custom boards (many squares, many intersections).

Developed and tested with the PAL version Boom Street (ST7P01). All addresses go through the CSMM address mapper, so Fortune Street (ST7E01) and Itadaki Street (ST7JGD) should work as well, but neither has been tested.

## Usage

Add this modpack to CSMM like any other modpack. The fixes are split into four independent mods; remove a line from `modlist.txt` to leave one out.

| Mod | Purpose | Fixes |
|---|---|---|
| `Board128Squares` | Boards with up to 128 squares, including quick saves | 1–4, 8–9 |
| `AiPathing` | AI crash and freezes on boards with many branches | 5–6 |
| `AiNumberInput` | AI stuck when entering a number with more digits than the input has | 10 |
| `EightShopDistricts` | District overview with up to 8 shops | 7 |

`FortuneStreetFixesCommon.py` holds the assembler and patch helpers shared by the mods. It is not a mod itself, so it is not listed in `modlist.txt`, but it must stay in the modpack.

The mods patch `main.dol` at build time, and `EightShopDistricts` also changes the district overview layout in `game_board*.arc`. They check every original instruction before they write and run late (priority −1000).

## Findings and fixes

| # | Problem | Cause | Fix | Status |
|---|---|---|---|---|
| 1 | High-ID squares, their buildings and the cursor disappear depending on camera position | The board scene (`Scene::Board::Init(task, 400, 400)`) can only gather 400 visible objects; anything beyond is silently not drawn | Raise both limits to 1024 (0x8007A68C, 0x8007A690) | Confirmed in game |
| 2 | Crash at 88+ squares (`Memory::Heap::free_sub`, 0x80007E58) | `Game::MiniMapMap` allocates 0x1E0 bytes (6 bytes per square, so 80 squares) and overwrites the next heap block header | Allocate 0x600 bytes (0x800B00F4) | Confirmed in game |
| 3 | Quick save is never offered for resuming in CSMM builds | `GetSuspendDataIdx` picks the slot from the board rule, but `IsSuspendDataEnable` uses GameSelectInfo+0x226, which CSMM repurposes as the map set | Both now use GSI+0x226 (0x800D29BC–0x800D29FC) | Confirmed in game |
| 4 | Board save data only fits 87 squares (0x3000-byte buffers, 0x2254 header + 0x28 per square). `SaveGame` fails silently, and a stale save of another map gets resumed | Fixed buffer size | Above 87 squares, a compact format stores 13 dynamic bytes per square; static data is restored from the current switch layout of the map file. Maps with 87 squares or fewer keep the original format. If saving still fails, the quick-save slot is marked empty | Confirmed in game, including after a restart and on switch maps |
| 5 | AI crash at 0x8009D238 (write to 0x10) on maps with many branches | `Ai::Player::SearchRoute` runs out of its 0x20000 node arena, gets NULL and writes to it anyway | Skip the branch when allocation fails (0x8009D234); the tree traversal already ignores NULL children | Confirmed in game |
| 6 | Game freezes for seconds during AI turns, especially on high dice rolls | `Ai::Player::CalcDistance4Salary` is an exhaustive depth-first search over all routes up to squares + 10 steps, with no visited set, so its cost is exponential | Replaced with a breadth-first search over (square, entry direction, suit bits); each state is visited once | Confirmed in game on maps with many intersections; also emulator-verified against the original code: identical results, avg 5.9M → 3.3K instructions per call |
| 7 | Crash at 0x8006EB4C (read from 0x50) when a district has 8 shops; a 7th shop is silently written into the wrong UI object and is not shown | `Game::AreaUI` (district overview) has exactly 6 shop boxes (`Game::UIAreaShopStatus`, 0x48 bytes each, at +0x4C), but `Game::AreaUI::exec` fills one box per shop; boxes 7+ lie past the array | The overview now has 8 boxes: the object is allocated with 0xD48 instead of 0xB08 bytes (0x800BF60C) and the box array moves to the new tail at +0xB08, so all other members keep their offsets. All loops over the boxes (constructor, destructor, `Open`, `StartClose`, `HighlightOn`/`HighlightOff`, `exec`) run to 8, and a new pane name table adds `n_shop07`/`n_shop08`. `exec` fills at most 8 boxes (hook at 0x80114054). In `ui_game_018_scene.brlyt` (all `game_board*.arc`), two copies of `n_shop06` are added, the boxes are placed at x = −203 + 74·i, and the legend `n_sub` moves 80 units to the left. That row is too wide for 4:3, so there a hook in the `Game::AreaUI` constructor (0x80112110) checks `System::Render::Is4x3()`, scales boxes and legend to 0.8 and moves them closer together (`Scene::Layout::Obj::SetTranslate`/`Scale`) | Confirmed in game (16:9 and 4:3) |
| 8 | Crash at 0x80348254 (read from 0x4), 0x80348200 (write to 0x4) or in the panel animation when the venture card selection opens on large boards, not on every opening | All models (`Resource::Model::Obj`) share a fixed 3 MB heap in MEM2 (`Memory::Init`). When it is full, `ChanceCardSelector::Open` cannot create the last card panels (`ScnMdl` stays NULL), and `Open` and `exec` use them without checking | When a model does not fit, create it with `Memory::Wii::Allocator()` instead (hooks at 0x800527F0, 0x80052818), which uses the MEM1 heap and then the task heap. The heap size stays unchanged: with 4 MB, the crash was gone in two autopilot games of over 300 rounds, but the game hung before the title screen together with a character pack | Confirmed in game: autopilot game of 802 rounds on a 128-square map together with a character pack. Each venture card selection created about 40–55 panels with the fallback, and the star animation on Boon and Boom squares sometimes needed it too |
| 9 | Same crash addresses as fix 8, should a model still be missing | `CopiedMatAccess::GetResMatChan` returns NULL for a missing model, but `ChanceCardSelector` and others use the result without checking | `ResMatChan::GXGetChanMatColor` and `GXSetChanMatColor` ignore NULL (hooks at 0x80348244, 0x803481EC). This is only a safety net: the panel animation in `Open` would still crash | Emulator-verified against the original code; never triggered in game since fix 8 |
| 10 | The AI gets stuck in the stock sale: the cursor moves through the digits forever (for example 188 shown when selling all of 1188 stock) | `Game::GameInputCpu::procNumber` enters the target number digit by digit and only confirms when the display equals the target. The stock input has 3 digits, so a target above 999 is never reached. Vanilla code; it shows up in long games, especially with AI mods that sell all stock | Limit the target to the largest number the input can show (10^digits − 1, hook at 0x800AE564), so the AI sells 999 | Emulator-verified (routine only); not yet tested in game |

Addresses are Boom Street (ST7P01) virtual addresses.

## Hard limits and open points

- **128 squares is a hard limit.** `Gm::Board` has room for 128 places. Square 129 onward overlaps the district data, so maps that large crash on load (`Gm::Area::AddPlace`, 0x8009203C). Moving the array is not practical (200+ code sites). Ideally CSMM would reject such maps on import.
- **12 districts is a hard limit.** The 12 areas sit at a fixed place in `Gm::Board` (0x2A00–0x2FA0, followed by the players), each player has 12 stock counters (0x414–0x443), the save format has fixed slots for 12, and the UI is laid out for districts A–L.
- **8 shops per district is a hard limit.** `Gm::Area` stores its shops in 8 bytes (0x08–0x0F), followed by the shop count. `Gm::Area::AddPlace` has no bounds check, so a 9th shop overwrites the count. With fix 7, the overview shows all 8.- **Weaker AI on very branchy maps:** with fix 5, the AI evaluates fewer routes on such maps. It is slightly weaker, but no longer crashes.

## Disclaimer

<img src="AI.svg" alt="AI" width="32" height="32">This modpack has been made with the help of Claude Opus.