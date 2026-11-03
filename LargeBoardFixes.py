import pycsmm
import os
import struct

MODID = __name__

# (Boom Street virtual address, original instruction, patched instruction)
PATCHES = [
	# Game::GameBoard::GameBoard() creates the board scene with Scene::Board::Init(task, 400, 400).
	# The scene's nw4r::g3d::ScnRoot can only gather 400 visible objects per frame; everything
	# beyond that is silently not drawn (squares with the highest IDs, their buildings, the cursor).
	# Raise both limits (max children / max gathered objects) to 1024.
	(0x8007A68C, 0x38800190, 0x38800400),  # li r4, 0x190 -> li r4, 0x400
	(0x8007A690, 0x38A00190, 0x38A00400),  # li r5, 0x190 -> li r5, 0x400
	# Game::MiniMapMap::MiniMapMap() allocates 0x1E0 bytes for 6 bytes per square (80 squares).
	# Larger boards overflow into the next heap block's header and crash on free.
	# Allocate room for 256 squares (the size of Gm::Board's square array).
	(0x800B00F4, 0x386001E0, 0x38600600),  # li r3, 0x1e0 -> li r3, 0x600
	# Game::GameManager::GetSuspendDataIdx() picks the quick save slot from the board's rule set,
	# but GameSequenceDataAdapter::IsSuspendDataEnable() (Free Play prompt) checks the slot from
	# GameSelectInfo+0x226, which CSMM repurposes as the map set. Both disagree, so quick saves
	# are never offered for resuming. Pick the slot from GameSelectInfo+0x226 as well.
	# 0x228 == 0: slot = (gsi[0x226] == 1) ? 2 : 0
	(0x800D29BC, 0x3C608055, 0x88630226),  # lis r3, g_board@ha       -> lbz r3, 0x226(r3)
	(0x800D29C4, 0x3863D018, 0x68630001),  # addi r3, r3, g_board@l   -> xori r3, r3, 1
	(0x800D29C8, 0x806353F4, 0x60000000),  # lwz r3, 0x53f4(r3)       -> nop
	(0x800D29D8, 0x7C031878, 0x7C031838),  # andc r3, r0, r3          -> and r3, r0, r3
	# 0x228 == 1: slot = (gsi[0x226] == 1) ? 3 : 1
	(0x800D29E8, 0x3C808055, 0x88830226),  # lis r4, g_board@ha       -> lbz r4, 0x226(r3)
	(0x800D29F0, 0x3884D018, 0x60000000),  # addi r4, r4, g_board@l   -> nop
	(0x800D29F4, 0x800453F4, 0x60000000),  # lwz r0, 0x53f4(r4)       -> nop
	(0x800D29F8, 0x2C000000, 0x2C040001),  # cmpwi r0, 0              -> cmpwi r4, 1
	(0x800D29FC, 0x40820010, 0x41820010),  # bne end                  -> beq end
	# Ai::Player::SearchRoute() builds a tree of all reachable routes from a fixed arena (Ai::SimpleMem).
	# On boards with many branches the arena runs out; the allocation then yields NULL, but the node is
	# still written to (crash at 0x8009D238 writing to 0x10). Skip the branch instead; the tree
	# traversal already ignores missing children.
	(0x8009D234, 0x3BA00000, 0x4800004C),  # li r29, 0x0              -> b 0x8009D280 (next branch)
]

# Board save data (Gm::Board::SaveGame/LoadGame) has a fixed 0x2254 byte header followed by 0x28 bytes
# per square. Quick saves and turn restoration only provide 0x3000 bytes, which fits at most 87 squares.
# For boards with more squares, use a compact format with only the 13 dynamic bytes per square; the
# static bytes (position, waypoints, district, ...) are restored from the current switch layout of the
# map file. Boards with up to 87 squares keep the original format, so existing saves stay compatible.
MAX_FULL_SQUARES = 87
COMPACT_SIZE = 13

# Boom Street addresses
CALC_SAVE_SIZE_MULLI = 0x80083818     # Gm::Board::CalcSaveSize       mulli r3, r0, 0x28
SAVE_GAME = 0x80083824                # Gm::Board::SaveGame
SAVE_GAME_MULLI = 0x8008384C          # Gm::Board::SaveGame           mulli r3, r0, 0x28
SAVE_GAME_SQUARES = 0x80083BE8        # Gm::Board::SaveGame           mr r4, r29 (start of square loop)
SAVE_GAME_SQUARES_NEXT = 0x80083BEC
SAVE_GAME_SQUARES_END = 0x80083CEC    # Gm::Board::SaveGame           mr r3, r31 (after square loop)
LOAD_GAME_MULLI = 0x80083DE8          # Gm::Board::LoadGame           mulli r3, r0, 0x28
LOAD_GAME_SQUARE = 0x800840C0         # Gm::Board::LoadGame           lha r17, 0x0(r31) (top of square loop)
SETUP_SUSPEND_SAVE = 0x80012D2C       # Flag::SaveData::SetupSuspendData  bl Gm::Board::SaveGame
STOP_SWITCH_MAP_ARRAY_HA = 0x8007F138 # Gm::Board::StopSwitch         lis r4, s_map_data_array@ha
STOP_SWITCH_MAP_ARRAY_L = 0x8007F144  # Gm::Board::StopSwitch         addi r4, r4, s_map_data_array@l
CALC_DISTANCE_4_SALARY = 0x8009CD84   # Ai::Player::CalcDistance4Salary(int, int, int, int) const
GET_NEXT_PLACE = 0x8008FFA4           # Gm::Place::GetNextPlace(int*, int, bool) const
G_BOARD = 0x8054D018                  # Gm::g_board
AREA_UI_SHOP_COUNT = 0x80114054       # Game::AreaUI::exec            lwz r0, 0x10(r25) (shop row loop condition)

# Game::AreaUI (district overview) has exactly 6 shop boxes (Game::UIAreaShopStatus, 0x48 bytes each,
# at +0x4C), but fills one box per shop of the district (Gm::Area holds up to 8). Boxes 7+ lie past the
# array (inside Game::UIPlayerStock): a 7th shop silently writes into the wrong UI object, an 8th crashes
# (NULL layout, 0x8006EB4C). Move the array to the end of a larger Game::AreaUI with room for 8 boxes,
# link them to the panes n_shop01-08 (see relayout_shops) and never fill more boxes than exist.
AREA_UI_ROWS = 8
AREA_UI_SIZE = 0xB08                  # original sizeof(Game::AreaUI)
AREA_UI_BOX_SIZE = 0x48
AREA_UI_BOXES = AREA_UI_SIZE          # new offset of the box array
AREA_UI_DELTA = AREA_UI_BOXES - 0x4C
AREA_UI_NAMES = 0x80475C40            # const char* names[6] = {"n_shop01", ...}
AREA_UI_NAMES_HOOK = 0x80112090       # Game::AreaUI::AreaUI          addi r25, r31, 0x38 (= names)


def one(emit):
	a = Asm(0)
	emit(a)
	return a.items[0]


def area_ui_patches(names):
	"""(Boom Street address, original, patched) for 8 shop boxes at AREA_UI_BOXES; names = new name table."""
	n, off, delta = AREA_UI_ROWS, AREA_UI_BOXES, AREA_UI_DELTA
	return [
		# GameScene: new Game::AreaUI
		(0x800BF60C, one(lambda a: a.li(3, AREA_UI_SIZE)), one(lambda a: a.li(3, AREA_UI_SIZE + n * AREA_UI_BOX_SIZE))),
		# Game::AreaUI::AreaUI: __construct_array(this + 0x4C, ..., 0x48, 6) and the Create() loop
		(0x80111BDC, one(lambda a: a.addi(3, 26, 0x4C)), one(lambda a: a.addi(3, 26, off))),
		(0x80111BF0, one(lambda a: a.li(7, 6)), one(lambda a: a.li(7, n))),
		(0x801120F4, one(lambda a: a.addi(3, 3, 0x4C)), one(lambda a: a.addi(3, 3, off))),
		(0x80112104, 0x2C940006, 0x2C940000 | n),  # cmpwi cr1, r20, 6
		# Game::AreaUI::~AreaUI: unlink loop (this + r28 + 0x80) and __destroy_arr(this + 0x4C, ..., 0x48, 6)
		(0x801125F0, one(lambda a: a.li(28, 0)), one(lambda a: a.li(28, delta))),
		(0x80112624, one(lambda a: a.cmpwi(27, 6)), one(lambda a: a.cmpwi(27, n))),
		(0x80112750, one(lambda a: a.addi(3, 30, 0x4C)), one(lambda a: a.addi(3, 30, off))),
		(0x8011275C, one(lambda a: a.li(6, 6)), one(lambda a: a.li(6, n))),
		# Game::AreaUI::HighlightOn / HighlightOff: loops over this + i * 0x48 + 0x80
		(0x8011288C, one(lambda a: a.mr(30, 3)), one(lambda a: a.addi(30, 3, delta))),
		(0x801128B4, one(lambda a: a.cmplwi(31, 6)), one(lambda a: a.cmplwi(31, n))),
		(0x801128D4, one(lambda a: a.mr(30, 3)), one(lambda a: a.addi(30, 3, delta))),
		(0x80112900, one(lambda a: a.cmplwi(29, 6)), one(lambda a: a.cmplwi(29, n))),
		(0x80112940, one(lambda a: a.mr(30, 3)), one(lambda a: a.addi(30, 3, delta))),
		(0x8011298C, one(lambda a: a.cmplwi(29, 6)), one(lambda a: a.cmplwi(29, n))),
		# Game::AreaUI::Open, StartClose: loops over the boxes
		(0x80112DE4, one(lambda a: a.addi(24, 29, 0x4C)), one(lambda a: a.addi(24, 29, off))),
		(0x80112E14, one(lambda a: a.cmpwi(25, 6)), one(lambda a: a.cmpwi(25, n))),
		(0x80113390, one(lambda a: a.addi(31, 30, 0x4C)), one(lambda a: a.addi(31, 30, off))),
		(0x801133C0, one(lambda a: a.cmpwi(30, 6)), one(lambda a: a.cmpwi(30, n))),
		# Game::AreaUI::exec: update loops, pane visibility loop, fill loop (r21 = this + i * 0x48)
		(0x8011375C, one(lambda a: a.addi(17, 15, 0x4C)), one(lambda a: a.addi(17, 15, off))),
		(0x80113788, one(lambda a: a.cmpwi(16, 6)), one(lambda a: a.cmpwi(16, n))),
		(0x80114084, one(lambda a: a.cmpwi(14, 6)), one(lambda a: a.cmpwi(14, n))),
		(0x80113C64, one(lambda a: a.lis(14, ha(AREA_UI_NAMES))), one(lambda a: a.lis(14, ha(names)))),
		(0x80113C74, one(lambda a: a.addi(14, 14, AREA_UI_NAMES)), one(lambda a: a.addi(14, 14, names))),
		(0x80113C98, one(lambda a: a.cmpwi(16, 6)), one(lambda a: a.cmpwi(16, n))),
		(0x80113CC4, one(lambda a: a.lis(22, ha(AREA_UI_NAMES))), one(lambda a: a.lis(22, ha(names)))),
		(0x80113CEC, one(lambda a: a.addi(22, 22, AREA_UI_NAMES)), one(lambda a: a.addi(22, 22, names))),
		(0x80113CE4, one(lambda a: a.mr(21, 15)), one(lambda a: a.addi(21, 15, delta))),
	]

# District overview layout (ui_game_018_scene.brlyt in game_board*.arc): shop boxes are linked to the
# placeholder panes n_shop01-06, the legend (shop value, prices, max. capital) is n_sub. Add n_shop07/08
# and move the whole row left so that 8 boxes fit (original: n_sub at -280, n_shop0i at -123 + 74 * i).
SHOP_LAYOUT = 'arc/blyt/ui_game_018_scene.brlyt'
SHOP_PANES = 8
SHOP_SHIFT = -80.0
SHOP_LEGEND_X = -280.0 + SHOP_SHIFT
SHOP_X0 = -123.0 + SHOP_SHIFT
SHOP_STEP = 74.0
SHOP_SCALE = 1.0

# The row above is too wide for 4:3 (visible area about +-284). There, Game::AreaUI::AreaUI scales the
# boxes and the legend by 0.8 at run time and moves them closer together. The legend window w_01 is
# right aligned at n_sub + 121 and is 122 wide; the box rows are centered at y = -158.
AREA_UI_4X3_HOOK = 0x80112110         # Game::AreaUI::AreaUI          addi r25, r31, 0x10 (after shop box loop)
RENDER_GET = 0x80019594               # System::Render::Get()
RENDER_IS_4X3 = 0x8001981C            # System::Render::Is4x3() const
LAYOUT_SET_TRANSLATE = 0x80072064     # Scene::Layout::Obj::SetTranslate(const char*, const VEC3&)
LAYOUT_SCALE = 0x80072288             # Scene::Layout::Obj::Scale(const char*, const VEC2&)
SHOP_4X3_SCALE = 0.8
SHOP_4X3_STEP = SHOP_STEP * SHOP_4X3_SCALE
SHOP_4X3_X0 = 284.0 - 35.0 * SHOP_4X3_SCALE - (SHOP_PANES - 1) * SHOP_4X3_STEP
SHOP_4X3_LEGEND_X = SHOP_4X3_X0 - 35.0 * SHOP_4X3_SCALE - 1.0 - 121.0 * SHOP_4X3_SCALE
SHOP_4X3_LEGEND_Y = -158.0 - 35.0 * SHOP_4X3_SCALE
SHOP_4X3_Y = 0x20                     # layout data offsets
SHOP_4X3_SCALES = 0x28
SHOP_4X3_LEGEND = 0x30
SHOP_4X3_LEGEND_NAME = 0x3C


def shop_4x3_data():
	"""x of each box, box y and z, scale (x, y), legend translate (x, y, z), legend pane name."""
	return (struct.pack('>8f', *(SHOP_4X3_X0 + SHOP_4X3_STEP * i for i in range(SHOP_PANES)))
		+ struct.pack('>7f', -158.0, 0.0, SHOP_4X3_SCALE, SHOP_4X3_SCALE, SHOP_4X3_LEGEND_X, SHOP_4X3_LEGEND_Y, 0.0)
		+ b'n_sub'.ljust(8, b'\0'))


def shop_pane_name(i):
	return b'n_shop%02d' % (i + 1)


def relayout_shops(data):
	"""Returns the brlyt with SHOP_PANES shop placeholder panes, evenly spaced and scaled."""
	sections = []
	o = 0x10
	for _ in range(struct.unpack('>H', data[0xE:0x10])[0]):
		size = struct.unpack('>I', data[o + 4:o + 8])[0]
		sections.append(bytearray(data[o:o + size]))
		o += size
	def pane_name(sec):
		return bytes(sec[0xC:0x1C]).split(b'\0')[0] if sec[:4] == b'pan1' else None
	names = [pane_name(sec) for sec in sections]
	if shop_pane_name(5) not in names:
		raise RuntimeError(f'{MODID}: {SHOP_LAYOUT} has no {shop_pane_name(5).decode()} pane')
	last = max(i for i, name in enumerate(names) if name and name.startswith(b'n_shop0'))
	for i in range(SHOP_PANES):
		if shop_pane_name(i) not in names:
			sec = bytearray(sections[names.index(shop_pane_name(5))])
			sec[0xC:0x1C] = shop_pane_name(i).ljust(0x10, b'\0')
			last += 1
			sections.insert(last, sec)
			names.insert(last, shop_pane_name(i))
	for i in range(SHOP_PANES):
		sec = sections[names.index(shop_pane_name(i))]
		struct.pack_into('>f', sec, 0x24, SHOP_X0 + SHOP_STEP * i)
		struct.pack_into('>2f', sec, 0x3C, SHOP_SCALE, SHOP_SCALE)
	struct.pack_into('>f', sections[names.index(b'n_sub')], 0x24, SHOP_LEGEND_X)
	body = b''.join(sections)
	header = bytearray(data[:0x10])
	struct.pack_into('>I', header, 0x8, 0x10 + len(body))
	struct.pack_into('>H', header, 0xE, len(sections))
	return bytes(header) + body


def modify_shop_layout(root, gameInstance, modList, extractedPath):
	path = os.path.join(extractedPath, SHOP_LAYOUT)
	with open(path, 'rb') as f:
		data = f.read()
	with open(path, 'wb') as f:
		f.write(relayout_shops(data))

# Ai::Player::CalcDistance4Salary() computes how many steps the AI still needs to collect the missing
# suits and reach the bank. The original walks every possible route with a depth first search (up to
# squares + 10 steps deep, without remembering visited squares), which takes exponential time: on large
# boards with many branches, the game freezes for seconds. Replace it with a breadth first search over
# (square, entry direction, collected suits) that visits each state once. Same result, linear time.
DIST_QUEUE_SIZE = 1024                # queue entries (power of 2); a full queue drops states
DIST_VISITED = 0x18                   # stack frame layout
DIST_VISITED_SIZE = 128 * 5 * 16 // 8
DIST_QUEUE = DIST_VISITED + DIST_VISITED_SIZE + 8
DIST_SAVE = DIST_QUEUE + 4 * DIST_QUEUE_SIZE
DIST_FRAME = DIST_SAVE + 0x40

# (Boom Street address, original instruction, hook label, link)
HOOKS = [
	(CALC_SAVE_SIZE_MULLI, 0x1C600028, 'calc_save_size', False),
	(SAVE_GAME_MULLI, 0x1C600028, 'save_size', True),
	(LOAD_GAME_MULLI, 0x1C600028, 'save_size', True),
	(SAVE_GAME_SQUARES, 0x7FA4EB78, 'save_squares', False),
	(LOAD_GAME_SQUARE, 0xAA3F0000, 'load_square', True),
	(SETUP_SUSPEND_SAVE, 0x48070AF9, 'suspend_save', True),
	(CALC_DISTANCE_4_SALARY, 0x9421FB90, 'calc_distance', False),
	(AREA_UI_SHOP_COUNT, 0x80190010, 'area_ui_shop_count', True),
	(AREA_UI_NAMES_HOOK, 0x3B3F0038, 'area_ui_names', True),
	(AREA_UI_4X3_HOOK, 0x3B3F0010, 'area_ui_4x3', True),
]


class Asm:
	"""Minimal PowerPC assembler for the instructions used below."""
	def __init__(self, base):
		self.base = base
		self.items = []
		self.labels = {}
	def addr(self):
		return self.base + 4 * len(self.items)
	def label(self, name):
		self.labels[name] = self.addr()
	def emit(self, word):
		self.items.append(word & 0xFFFFFFFF)
	def words(self):
		return [item(self.base + 4 * i) if callable(item) else item for i, item in enumerate(self.items)]
	def target(self, t):
		return self.labels[t] if isinstance(t, str) else t
	def d(self, op, rd, ra, imm):
		self.emit(op << 26 | rd << 21 | ra << 16 | imm & 0xFFFF)
	def x(self, rd, ra, rb, xo):
		self.emit(31 << 26 | rd << 21 | ra << 16 | rb << 11 | xo << 1)
	def addi(self, rd, ra, v): self.d(14, rd, ra, v)
	def li(self, rd, v): self.d(14, rd, 0, v)
	def lis(self, rd, v): self.d(15, rd, 0, v)
	def lwz(self, rd, off, ra): self.d(32, rd, ra, off)
	def lbz(self, rd, off, ra): self.d(34, rd, ra, off)
	def stw(self, rs, off, ra): self.d(36, rs, ra, off)
	def stwu(self, rs, off, ra): self.d(37, rs, ra, off)
	def stb(self, rs, off, ra): self.d(38, rs, ra, off)
	def lha(self, rd, off, ra): self.d(42, rd, ra, off)
	def sth(self, rs, off, ra): self.d(44, rs, ra, off)
	def lfs(self, frt, off, ra): self.d(48, frt, ra, off)
	def stfs(self, frs, off, ra): self.d(52, frs, ra, off)
	def mulli(self, rd, ra, v): self.d(7, rd, ra, v)
	def cmpwi(self, ra, v): self.d(11, 0, ra, v)
	def cmplwi(self, ra, v): self.d(10, 0, ra, v)
	def andi_(self, ra, rs, v): self.d(28, rs, ra, v)
	def lmw(self, rd, off, ra): self.d(46, rd, ra, off)
	def stmw(self, rs, off, ra): self.d(47, rs, ra, off)
	def cmpw(self, ra, rb): self.x(0, ra, rb, 0)
	def subf(self, rd, ra, rb): self.x(rd, ra, rb, 40)
	def or_(self, ra, rs, rb): self.x(rs, ra, rb, 444)
	def and_(self, ra, rs, rb): self.emit(31 << 26 | rs << 21 | ra << 16 | rb << 11 | 28 << 1 | 1)
	def slw(self, ra, rs, rb): self.x(rs, ra, rb, 24)
	def lbzx(self, rd, ra, rb): self.x(rd, ra, rb, 87)
	def stbx(self, rs, ra, rb): self.x(rs, ra, rb, 215)
	def lwzx(self, rd, ra, rb): self.x(rd, ra, rb, 23)
	def add(self, rd, ra, rb): self.x(rd, ra, rb, 266)
	def mr(self, ra, rs): self.x(rs, ra, rs, 444)
	def extsb(self, ra, rs): self.x(rs, ra, 0, 954)
	def slwi(self, ra, rs, n): self.emit(21 << 26 | rs << 21 | ra << 16 | n << 11 | (31 - n) << 1)
	def srwi(self, ra, rs, n): self.emit(21 << 26 | rs << 21 | ra << 16 | (32 - n) % 32 << 11 | n << 6 | 31 << 1)
	def mflr(self, rd): self.emit(0x7C0802A6 | rd << 21)
	def mtlr(self, rs): self.emit(0x7C0803A6 | rs << 21)
	def mtctr(self, rs): self.emit(0x7C0903A6 | rs << 21)
	def blr(self): self.emit(0x4E800020)
	def b(self, t, link=False):
		self.items.append(lambda pc, t=t: 18 << 26 | (self.target(t) - pc) & 0x03FFFFFC | int(link))
	def bl(self, t): self.b(t, True)
	def bc(self, bo, bi, t):
		self.items.append(lambda pc, t=t: 16 << 26 | bo << 21 | bi << 16 | (self.target(t) - pc) & 0xFFFC)
	def blt(self, t): self.bc(12, 0, t)
	def bgt(self, t): self.bc(12, 1, t)
	def ble(self, t): self.bc(4, 1, t)
	def bne(self, t): self.bc(4, 2, t)
	def bge(self, t): self.bc(4, 0, t)
	def beq(self, t): self.bc(12, 2, t)
	def bdnz(self, t): self.bc(16, 0, t)


def ha(v):
	return (v + 0x8000) >> 16 & 0xFFFF


def assemble(base, std, vars_addr, map_array, names_addr=0, layout_addr=0):
	"""std converts a Boom Street address to this main.dol's address."""
	a = Asm(base)

	# r0 = squares - 1 -> r3 = save data size - 0x227C (called from SaveGame/LoadGame)
	a.label('save_size')
	a.cmpwi(0, MAX_FULL_SQUARES - 1)
	a.bgt('save_size_compact')
	a.mulli(3, 0, 0x28)
	a.blr()
	a.label('save_size_compact')
	a.mulli(3, 0, COMPACT_SIZE)
	a.addi(3, 3, COMPACT_SIZE - 0x28)
	a.blr()

	# tail of Gm::Board::CalcSaveSize (leaf function, reached via b)
	a.label('calc_save_size')
	a.cmpwi(0, MAX_FULL_SQUARES - 1)
	a.bgt('calc_save_size_compact')
	a.mulli(3, 0, 0x28)
	a.addi(3, 3, 0x227C)
	a.blr()
	a.label('calc_save_size_compact')
	a.mulli(3, 0, COMPACT_SIZE)
	a.addi(3, 3, 0x227C + COMPACT_SIZE - 0x28)
	a.blr()

	# SaveGame square loop: r29 = board, r30 = save buffer, r31 = save size (keep)
	a.label('save_squares')
	a.lwz(0, 0x5414, 29)
	a.cmpwi(0, MAX_FULL_SQUARES)
	a.bgt('save_squares_compact')
	a.mr(4, 29)
	a.b(std(SAVE_GAME_SQUARES_NEXT))
	a.label('save_squares_compact')
	a.mtctr(0)
	a.mr(4, 29)
	a.addi(3, 30, 0x2254)
	a.label('save_squares_loop')
	a.lbz(5, 0x4D, 4)              # type
	a.stb(5, 0, 3)
	for dst, src in ((1, 0x24), (3, 0x28), (5, 0x2C), (7, 0x20), (9, 0x30)):
		a.lwz(5, src, 4)           # stored as big endian halfword, byte by byte (dst is unaligned)
		a.stb(5, dst + 1, 3)
		a.srwi(5, 5, 8)
		a.stb(5, dst, 3)
	a.lbz(5, 0x51, 4)
	a.stb(5, 11, 3)
	a.lha(5, 0x48, 4)              # clamped to 0xFF like the original
	a.cmpwi(5, 0xFF)
	a.ble('save_squares_clamped')
	a.li(5, 0xFF)
	a.label('save_squares_clamped')
	a.stb(5, 12, 3)
	a.addi(3, 3, COMPACT_SIZE)
	a.addi(4, 4, 0x54)
	a.bdnz('save_squares_loop')
	a.b(std(SAVE_GAME_SQUARES_END))

	# LoadGame square loop top: r26 = board, r27 = square index, r31 = original 0x28 byte record.
	# For compact saves, rebuild the original record in a scratch buffer and point r31 to it.
	# r0, r3-r12 are free here; the replaced lha r17, 0x0(r31) is executed at the end.
	a.label('load_square')
	a.lwz(3, 0x5414, 26)
	a.cmpwi(3, MAX_FULL_SQUARES)
	a.ble('load_square_done')
	a.lis(4, ha(vars_addr))
	a.addi(4, 4, vars_addr)
	a.cmpwi(27, 0)
	a.bne('load_square_base')
	a.stw(31, 0, 4)                # first square: remember start of compact records
	a.label('load_square_base')
	a.lwz(5, 0, 4)
	a.mulli(6, 27, COMPACT_SIZE)
	a.add(5, 5, 6)                 # r5 = compact record
	a.lwz(6, 0x53F8, 26)           # switch layout index
	a.slwi(6, 6, 2)
	a.lis(7, ha(map_array))
	a.addi(7, 7, map_array)
	a.lwzx(7, 7, 6)
	a.addi(7, 7, 0x40)
	a.slwi(6, 27, 5)
	a.add(7, 7, 6)                 # r7 = _FRB_PLACE_DATA of this square
	a.addi(31, 4, 8)               # r31 = scratch record
	a.li(6, 2)
	a.label('load_square_static')
	a.lbzx(8, 7, 6)                # record bytes 0x2-0x19 = Place 0x2-0x19
	a.stbx(8, 31, 6)
	a.addi(6, 6, 1)
	a.cmpwi(6, 0x1A)
	a.blt('load_square_static')
	a.lbz(8, 0, 5)
	a.extsb(8, 8)
	a.sth(8, 0, 31)
	for src, dst in ((1, 0x1A), (3, 0x1C), (5, 0x1E), (7, 0x20), (9, 0x22)):
		a.lbz(8, src, 5)
		a.stb(8, dst, 31)
		a.lbz(8, src + 1, 5)
		a.stb(8, dst + 1, 31)
	a.lbz(8, 11, 5)
	a.stb(8, 0x24, 31)
	a.lbz(8, 12, 5)
	a.stb(8, 0x26, 31)
	a.label('load_square_done')
	a.lha(17, 0, 31)
	a.blr()

	# Flag::SaveData::SetupSuspendData: r28 = quick save slot. If Gm::Board::SaveGame fails, mark the
	# slot as empty (map id < 0) instead of leaving stale board data that would be resumed later.
	a.label('suspend_save')
	a.stwu(1, -0x10, 1)
	a.mflr(0)
	a.stw(0, 0x14, 1)
	a.bl(std(SAVE_GAME))
	a.cmpwi(3, 0)
	a.bne('suspend_save_done')
	a.li(0, -1)
	a.stb(0, 0x3008, 28)
	a.label('suspend_save_done')
	a.lwz(0, 0x14, 1)
	a.mtlr(0)
	a.addi(1, 1, 0x10)
	a.blr()

	# Game::AreaUI::exec: r25 = Gm::Area -> r0 = min(shop count, rows)
	a.label('area_ui_shop_count')
	a.lwz(0, 0x10, 25)
	a.cmpwi(0, AREA_UI_ROWS)
	a.ble('area_ui_shop_count_done')
	a.li(0, AREA_UI_ROWS)
	a.label('area_ui_shop_count_done')
	a.blr()

	# Game::AreaUI::AreaUI: r25 = shop box pane names
	a.label('area_ui_names')
	a.lis(25, ha(names_addr))
	a.addi(25, 25, names_addr)
	a.blr()

	# Game::AreaUI::AreaUI: r26 = this, layout at this+0x34; compact shop row in 4:3
	a.label('area_ui_4x3')
	a.stwu(1, -0x30, 1)
	a.mflr(0)
	a.stw(0, 0x34, 1)
	a.stmw(29, 0x24, 1)
	a.bl(std(RENDER_GET))
	a.bl(std(RENDER_IS_4X3))
	a.cmpwi(3, 0)
	a.beq('area_ui_4x3_done')
	a.lis(31, ha(layout_addr))
	a.addi(31, 31, layout_addr)
	a.lis(29, ha(names_addr))
	a.addi(29, 29, names_addr)
	a.li(30, 0)
	a.label('area_ui_4x3_box')
	a.add(3, 31, 30)
	a.lfs(0, 0, 3)
	a.stfs(0, 0x8, 1)
	a.lfs(0, SHOP_4X3_Y, 31)
	a.stfs(0, 0xC, 1)
	a.lfs(0, SHOP_4X3_Y + 4, 31)
	a.stfs(0, 0x10, 1)
	a.lwz(3, 0x34, 26)
	a.lwzx(4, 29, 30)
	a.addi(5, 1, 0x8)
	a.bl(std(LAYOUT_SET_TRANSLATE))
	a.lwz(3, 0x34, 26)
	a.lwzx(4, 29, 30)
	a.addi(5, 31, SHOP_4X3_SCALES)
	a.bl(std(LAYOUT_SCALE))
	a.addi(30, 30, 4)
	a.cmpwi(30, 4 * SHOP_PANES)
	a.blt('area_ui_4x3_box')
	a.lwz(3, 0x34, 26)
	a.addi(4, 31, SHOP_4X3_LEGEND_NAME)
	a.addi(5, 31, SHOP_4X3_LEGEND)
	a.bl(std(LAYOUT_SET_TRANSLATE))
	a.lwz(3, 0x34, 26)
	a.addi(4, 31, SHOP_4X3_LEGEND_NAME)
	a.addi(5, 31, SHOP_4X3_SCALES)
	a.bl(std(LAYOUT_SCALE))
	a.label('area_ui_4x3_done')
	a.lmw(29, 0x24, 1)
	a.lwz(0, 0x34, 1)
	a.mtlr(0)
	a.addi(1, 1, 0x30)
	a.addi(25, 31, 0x10)
	a.blr()

	# Ai::Player::CalcDistance4Salary(this, place, prev place, suit bits, wild suits) -> steps
	# Queue entry: place, prev place, suit bits, steps (one byte each).
	F = DIST_FRAME
	a.label('calc_distance')
	a.stwu(1, -F, 1)
	a.mflr(0)
	a.stw(0, F + 4, 1)
	a.stmw(18, DIST_SAVE, 1)
	a.lis(31, ha(G_BOARD))
	a.addi(31, 31, G_BOARD)        # r31 = board
	a.lwz(30, 0x5414, 31)
	a.addi(30, 30, 10)             # r30 = search limit (squares + 10), returned if the bank is unreachable
	a.extsb(29, 7)                 # r29 = wild suits
	a.addi(28, 1, DIST_QUEUE)      # r28 = queue
	a.addi(24, 1, DIST_VISITED)    # r24 = visited bits
	a.li(0, 0)
	a.li(3, DIST_VISITED_SIZE // 4)
	a.mtctr(3)
	a.addi(3, 24, -4)
	a.label('cd_clear')
	a.stwu(0, 4, 3)
	a.bdnz('cd_clear')
	a.stb(4, 0, 28)                # push start state
	a.stb(5, 1, 28)
	a.andi_(6, 6, 0xF)
	a.stb(6, 2, 28)
	a.stb(0, 3, 28)
	a.li(27, 0)                    # r27 = queue head
	a.li(26, 1)                    # r26 = queue tail
	a.label('cd_pop')
	a.cmpw(27, 26)
	a.bge('cd_not_found')
	a.andi_(3, 27, DIST_QUEUE_SIZE - 1)
	a.slwi(3, 3, 2)
	a.add(3, 28, 3)
	a.lbz(23, 0, 3)
	a.extsb(23, 23)                # r23 = place
	a.lbz(22, 1, 3)
	a.extsb(22, 22)                # r22 = prev place
	a.lbz(21, 2, 3)                # r21 = suit bits
	a.lbz(20, 3, 3)                # r20 = steps
	a.addi(27, 27, 1)
	a.mulli(3, 23, 0x54)
	a.add(25, 31, 3)               # r25 = Gm::Place
	a.lbz(3, 0x4D, 25)
	a.extsb(3, 3)                  # square type
	a.addi(4, 3, -3)               # 3-6: suit
	a.cmplwi(4, 3)
	a.ble('cd_add_suit')
	a.addi(4, 3, -7)               # 7-10: changing suit, only predictable for the next 3 steps
	a.cmplwi(4, 3)
	a.bgt('cd_not_suit')
	a.cmpwi(20, 3)
	a.bgt('cd_expand')
	a.label('cd_add_suit')
	a.li(0, 1)
	a.slw(0, 0, 4)
	a.or_(21, 21, 0)
	a.b('cd_expand')
	a.label('cd_not_suit')
	a.cmpwi(3, 1)                  # 1: bank
	a.bne('cd_expand')
	a.andi_(4, 21, 5)
	a.andi_(5, 21, 0xA)
	a.srwi(5, 5, 1)
	a.add(4, 4, 5)
	a.andi_(5, 4, 3)
	a.srwi(4, 4, 2)
	a.add(4, 4, 5)
	a.add(4, 4, 29)
	a.cmpwi(4, 4)                  # all 4 suits?
	a.blt('cd_expand')
	a.mr(3, 20)                    # breadth first: the first hit is the shortest
	a.b('cd_return')
	a.label('cd_expand')
	a.addi(0, 20, 1)
	a.cmpw(0, 30)
	a.bge('cd_pop')
	a.mr(3, 25)
	a.addi(4, 1, 0x8)
	a.mr(5, 22)
	a.li(6, 0)
	a.bl(std(GET_NEXT_PLACE))
	a.mr(18, 3)                    # r18 = number of next places
	a.li(19, 0)                    # r19 = index
	a.label('cd_next')
	a.cmpw(19, 18)
	a.bge('cd_pop')
	a.slwi(3, 19, 2)
	a.addi(4, 1, 0x8)
	a.lwzx(5, 4, 3)                # r5 = next place
	a.addi(19, 19, 1)
	# GetNextPlace() of the next place only depends on which of its 4 entries we come from (or none)
	a.mulli(6, 5, 0x54)
	a.add(6, 31, 6)
	a.li(7, 0)
	a.label('cd_entry')
	a.lbz(8, 0x8, 6)
	a.extsb(8, 8)
	a.cmpw(8, 23)
	a.beq('cd_entry_found')
	a.addi(6, 6, 4)
	a.addi(7, 7, 1)
	a.cmpwi(7, 4)
	a.blt('cd_entry')
	a.label('cd_entry_found')
	a.mulli(8, 5, 5)
	a.add(8, 8, 7)
	a.slwi(8, 8, 4)
	a.add(8, 8, 21)                # r8 = state index
	a.srwi(9, 8, 3)
	a.lbzx(10, 24, 9)
	a.andi_(11, 8, 7)
	a.li(12, 1)
	a.slw(12, 12, 11)
	a.and_(0, 10, 12)
	a.bne('cd_next')               # already visited
	a.or_(10, 10, 12)
	a.stbx(10, 24, 9)
	a.subf(0, 27, 26)
	a.cmpwi(0, DIST_QUEUE_SIZE)
	a.bge('cd_next')               # queue full
	a.andi_(3, 26, DIST_QUEUE_SIZE - 1)
	a.slwi(3, 3, 2)
	a.add(3, 28, 3)
	a.stb(5, 0, 3)
	a.stb(23, 1, 3)
	a.stb(21, 2, 3)
	a.addi(0, 20, 1)
	a.stb(0, 3, 3)
	a.addi(26, 26, 1)
	a.b('cd_next')
	a.label('cd_not_found')
	a.mr(3, 30)
	a.label('cd_return')
	a.lmw(18, DIST_SAVE, 1)
	a.lwz(0, F + 4, 1)
	a.mtlr(0)
	a.addi(1, 1, F)
	a.blr()
	return a


class Mod(pycsmm.CSMMMod, pycsmm.GeneralInterface, pycsmm.ArcFileInterface):
	def __init__(self):
		pycsmm.CSMMMod.__init__(self)
		pycsmm.GeneralInterface.__init__(self)
		pycsmm.ArcFileInterface.__init__(self)
	def modId(self):
		return MODID
	def priority(self):
		# load late so other main.dol writers do not overwrite the patch
		return -1000
	def modifyArcFile(self):
		arcs = {}
		for locale in pycsmm.FS_LOCALES:
			upper = pycsmm.localeToUpper(locale)
			arc = f'files/game/lang{upper}/game_board_{upper}.arc' if upper else 'files/game/game_board.arc'
			arcs[arc] = modify_shop_layout
		return arcs
	def saveFiles(self, root, gameInstance, modList):
		mapper = gameInstance.addressMapper()
		def std(addr):
			return mapper.boomStreetToStandard(addr)
		def file_offset(addr):
			return mapper.boomToFileAddress(mapper.standardToBoomStreet(addr))
		def read(dol, addr):
			dol.seek(file_offset(addr))
			return int.from_bytes(dol.read(4), 'big')
		def write(dol, addr, word):
			dol.seek(file_offset(addr))
			dol.write(word.to_bytes(4, 'big'))
		with open(os.path.join(root, 'sys', 'main.dol'), 'r+b') as dol:
			for addr, orig, new in PATCHES:
				current = read(dol, std(addr))
				if current not in (orig, new):
					raise RuntimeError(f'{MODID}: unexpected instruction {current:08X} at {addr:08X} (expected {orig:08X})')
				write(dol, std(addr), new)

			# CSMM relocates s_map_data_array; take its address from Gm::Board::StopSwitch
			lis = read(dol, std(STOP_SWITCH_MAP_ARRAY_HA))
			addi = read(dol, std(STOP_SWITCH_MAP_ARRAY_L))
			if lis >> 16 != 0x3C80 or addi >> 16 != 0x3884:
				raise RuntimeError(f'{MODID}: unexpected s_map_data_array access {lis:08X} {addi:08X}')
			map_array = ((lis & 0xFFFF) << 16) + ((addi & 0xFFFF) ^ 0x8000) - 0x8000

			fsm = gameInstance.freeSpaceManager()
			# scratch data: compact record base + 0x28 byte record
			vars_addr = fsm.allocateUnusedSpace(bytes(0x30), dol, mapper, f'{MODID} save data scratch', False)

			# shop box pane names n_shop01-08: the 6 original strings + 2 new ones
			strings = b''.join(shop_pane_name(i).ljust(12, b'\0') for i in range(6, AREA_UI_ROWS))
			strings_addr = fsm.allocateUnusedSpace(strings, dol, mapper, f'{MODID} shop pane names', False)
			names = [read(dol, std(AREA_UI_NAMES) + 4 * i) for i in range(6)]
			names += [strings_addr + 12 * i for i in range(AREA_UI_ROWS - 6)]
			names_data = b''.join(x.to_bytes(4, 'big') for x in names)
			names_addr = fsm.allocateUnusedSpace(names_data, dol, mapper, f'{MODID} shop pane name table', False)
			for addr, data in ((strings_addr, strings), (names_addr, names_data)):
				dol.seek(file_offset(addr))
				dol.write(data)
			for addr, orig, new in area_ui_patches(names_addr):
				current = read(dol, std(addr))
				if current not in (orig, new):
					raise RuntimeError(f'{MODID}: unexpected instruction {current:08X} at {addr:08X} (expected {orig:08X})')
				write(dol, std(addr), new)

			layout = shop_4x3_data()
			layout_addr = fsm.allocateUnusedSpace(layout, dol, mapper, f'{MODID} 4:3 shop row layout', False)
			dol.seek(file_offset(layout_addr))
			dol.write(layout)

			size = len(assemble(0, lambda addr: 0, vars_addr, map_array).items) * 4
			code_addr = fsm.allocateUnusedSpace(bytes(size), dol, mapper, f'{MODID} routines', False)
			code = assemble(code_addr, std, vars_addr, map_array, names_addr, layout_addr)
			for i, word in enumerate(code.words()):
				write(dol, code_addr + 4 * i, word)

			for addr, orig, label, link in HOOKS:
				site = std(addr)
				current = read(dol, site)
				if current != orig and current >> 26 != 18:
					raise RuntimeError(f'{MODID}: unexpected instruction {current:08X} at {addr:08X} (expected {orig:08X})')
				write(dol, site, 18 << 26 | (code.labels[label] - site) & 0x03FFFFFC | int(link))

mod = Mod()
