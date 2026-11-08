import pycsmm
import os
from FortuneStreetFixesCommon import Asm, Dol, ha, one

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
]


def quick_save_patches(g_board):
	"""(Boom Street address, original, patched); g_board = address of Gm::g_board in this main.dol."""
	return [
		# Game::GameManager::GetSuspendDataIdx() picks the quick save slot from the board's rule set,
		# but GameSequenceDataAdapter::IsSuspendDataEnable() (Free Play prompt) checks the slot from
		# GameSelectInfo+0x226, which CSMM repurposes as the map set. Both disagree, so quick saves
		# are never offered for resuming. Pick the slot from GameSelectInfo+0x226 as well.
		# 0x228 == 0: slot = (gsi[0x226] == 1) ? 2 : 0
		(0x800D29BC, one(lambda a: a.lis(3, ha(g_board))), 0x88630226),      # lis r3, g_board@ha     -> lbz r3, 0x226(r3)
		(0x800D29C4, one(lambda a: a.addi(3, 3, g_board)), 0x68630001),      # addi r3, r3, g_board@l -> xori r3, r3, 1
		(0x800D29C8, 0x806353F4, 0x60000000),  # lwz r3, 0x53f4(r3)       -> nop
		(0x800D29D8, 0x7C031878, 0x7C031838),  # andc r3, r0, r3          -> and r3, r0, r3
		# 0x228 == 1: slot = (gsi[0x226] == 1) ? 3 : 1
		(0x800D29E8, one(lambda a: a.lis(4, ha(g_board))), 0x88830226),      # lis r4, g_board@ha     -> lbz r4, 0x226(r3)
		(0x800D29F0, one(lambda a: a.addi(4, 4, g_board)), 0x60000000),      # addi r4, r4, g_board@l -> nop
		(0x800D29F4, 0x800453F4, 0x60000000),  # lwz r0, 0x53f4(r4)       -> nop
		(0x800D29F8, 0x2C000000, 0x2C040001),  # cmpwi r0, 0              -> cmpwi r4, 1
		(0x800D29FC, 0x40820010, 0x41820010),  # bne end                  -> beq end
	]


# Board save data (Gm::Board::SaveGame/LoadGame) has a fixed 0x2254 byte header followed by 0x28 bytes
# per square. Quick saves and turn restoration only provide 0x3000 bytes, which fits at most 87 squares.
# For boards with more squares, use a compact format with only the 13 dynamic bytes per square; the
# static bytes (position, waypoints, district, ...) are restored from the current switch layout of the
# map file. Boards with up to 87 squares keep the original format, so existing saves stay compatible.
MAX_FULL_SQUARES = 87
COMPACT_SIZE = 13

# Boom Street addresses
G_BOARD = 0x8054D018                  # Gm::g_board
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

# Memory::Init() creates a fixed 3 MB heap in MEM2 for all models (Resource::Model::Obj). Large boards fill
# it. ChanceCardSelector::Open() then fails to create the last card panels and uses the missing models
# (crashes at 0x80348200, 0x80348254 and in the panel animation). A larger heap is no solution: the task
# heap gets the rest of MEM2, and with 4 MB the game hangs before the title screen with a character pack.
# When a model does not fit, create it with Memory::Wii::Allocator() instead, which uses the MEM1 heap and
# then the task heap. Models remember their allocator, and Memory::Heap::Free() handles both heaps.
MODEL_SIMPLE_STORE = 0x800527F0       # Resource::Model::Obj::init    stw r3, 0x54(r31) (ScnMdlSimple)
MODEL_STORE = 0x80052818              # Resource::Model::Obj::init    stw r3, 0x54(r31) (ScnMdl)
MEMORY_ALLOCATOR = 0x8000D380         # Memory::Wii::Allocator()
SCN_MDL_SIMPLE_CONSTRUCT = 0x80363AD0 # nw4r::g3d::ScnMdlSimple::Construct(MEMAllocator*, ulong*, ResMdl, int)
SCN_MDL_CONSTRUCT = 0x80366160        # nw4r::g3d::ScnMdl::Construct(MEMAllocator*, ulong*, ResMdl, ulong, int)

# If a model is missing anyway, CopiedMatAccess::GetResMatChan() returns NULL, and ChanceCardSelector and
# others use the result without checking. Ignore NULL in both functions.
MAT_COLOR_SET = 0x803481EC            # ResMatChan::GXSetChanMatColor lwz r3, 0x0(r3)
MAT_COLOR_SET_NEXT = 0x803481F0
MAT_COLOR_GET = 0x80348244            # ResMatChan::GXGetChanMatColor lwz r4, 0x0(r3)
MAT_COLOR_GET_NEXT = 0x80348248

# (Boom Street address, original instruction, hook label, link)
HOOKS = [
	(CALC_SAVE_SIZE_MULLI, 0x1C600028, 'calc_save_size', False),
	(SAVE_GAME_MULLI, 0x1C600028, 'save_size', True),
	(LOAD_GAME_MULLI, 0x1C600028, 'save_size', True),
	(SAVE_GAME_SQUARES, 0x7FA4EB78, 'save_squares', False),
	(LOAD_GAME_SQUARE, 0xAA3F0000, 'load_square', True),
	(SETUP_SUSPEND_SAVE, 0x48070AF9, 'suspend_save', True),
	(MODEL_SIMPLE_STORE, 0x907F0054, 'model_simple_fallback', True),
	(MODEL_STORE, 0x907F0054, 'model_fallback', True),
	(MAT_COLOR_SET, 0x80630000, 'mat_color_set', False),
	(MAT_COLOR_GET, 0x80830000, 'mat_color_get', False),
]


def assemble(base, std, vars_addr, map_array):
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

	# Resource::Model::Obj::init: r3 = new model, r30 = buffer options, r31 = this; the ResMdl for
	# Construct is at r1+0xC (ScnMdlSimple) or r1+0x8 (ScnMdl)
	for label, construct, res_mdl, args in (
			('model_simple_fallback', SCN_MDL_SIMPLE_CONSTRUCT, 0xC, lambda: a.li(6, 1)),
			('model_fallback', SCN_MDL_CONSTRUCT, 0x8, lambda: (a.mr(6, 30), a.li(7, 1)))):
		a.label(label)
		a.cmpwi(3, 0)
		a.bne(label + '_store')
		a.stwu(1, -0x10, 1)
		a.mflr(0)
		a.stw(0, 0x14, 1)
		a.bl(std(MEMORY_ALLOCATOR))
		a.li(4, 0)
		a.addi(5, 1, 0x10 + res_mdl)
		args()
		a.bl(std(construct))
		a.lwz(0, 0x14, 1)
		a.mtlr(0)
		a.addi(1, 1, 0x10)
		a.label(label + '_store')
		a.stw(3, 0x54, 31)
		a.blr()

	# ResMatChan::GXSetChanMatColor (leaf function, reached via b): keep cr0, it is tested after the hook
	a.label('mat_color_set')
	a.lwz(3, 0, 3)
	a.emit(0x2C830000)             # cmpwi cr1, r3, 0
	a.emit(0x4D860020)             # beqlr cr1
	a.b(std(MAT_COLOR_SET_NEXT))

	# ResMatChan::GXGetChanMatColor (leaf function, reached via b)
	a.label('mat_color_get')
	a.lwz(4, 0, 3)
	a.cmpwi(4, 0)
	a.bne('mat_color_get_ok')
	a.li(3, 0)
	a.blr()
	a.label('mat_color_get_ok')
	a.b(std(MAT_COLOR_GET_NEXT))
	return a


class Mod(pycsmm.CSMMMod, pycsmm.GeneralInterface):
	def __init__(self):
		pycsmm.CSMMMod.__init__(self)
		pycsmm.GeneralInterface.__init__(self)
	def modId(self):
		return MODID
	def priority(self):
		# load late so other main.dol writers do not overwrite the patch
		return -1000
	def saveFiles(self, root, gameInstance, modList):
		with open(os.path.join(root, 'sys', 'main.dol'), 'r+b') as file:
			dol = Dol(file, gameInstance, MODID)
			dol.patch(PATCHES)
			dol.patch(quick_save_patches(dol.std(G_BOARD)))

			# CSMM relocates s_map_data_array; take its address from Gm::Board::StopSwitch
			lis = dol.read(dol.std(STOP_SWITCH_MAP_ARRAY_HA))
			addi = dol.read(dol.std(STOP_SWITCH_MAP_ARRAY_L))
			if lis >> 16 != 0x3C80 or addi >> 16 != 0x3884:
				raise RuntimeError(f'{MODID}: unexpected s_map_data_array access {lis:08X} {addi:08X}')
			map_array = ((lis & 0xFFFF) << 16) + ((addi & 0xFFFF) ^ 0x8000) - 0x8000

			# scratch data: compact record base + 0x28 byte record
			vars_addr = dol.allocate(bytes(0x30), 'save data scratch')
			dol.install(lambda base, std: assemble(base, std, vars_addr, map_array), HOOKS)

mod = Mod()
