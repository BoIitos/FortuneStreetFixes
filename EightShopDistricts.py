import pycsmm
import os
import struct
from FortuneStreetFixesCommon import Asm, Dol, ha, one

MODID = __name__

# Boom Street addresses
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


def area_ui_patches(names, old_names):
	"""(Boom Street address, original, patched) for 8 shop boxes at AREA_UI_BOXES; names = new name table, old_names = AREA_UI_NAMES in this main.dol."""
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
		(0x80113C64, one(lambda a: a.lis(14, ha(old_names))), one(lambda a: a.lis(14, ha(names)))),
		(0x80113C74, one(lambda a: a.addi(14, 14, old_names)), one(lambda a: a.addi(14, 14, names))),
		(0x80113C98, one(lambda a: a.cmpwi(16, 6)), one(lambda a: a.cmpwi(16, n))),
		(0x80113CC4, one(lambda a: a.lis(22, ha(old_names))), one(lambda a: a.lis(22, ha(names)))),
		(0x80113CEC, one(lambda a: a.addi(22, 22, old_names)), one(lambda a: a.addi(22, 22, names))),
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


# (Boom Street address, original instruction, hook label, link)
HOOKS = [
	(AREA_UI_SHOP_COUNT, 0x80190010, 'area_ui_shop_count', True),
	(AREA_UI_NAMES_HOOK, 0x3B3F0038, 'area_ui_names', True),
	(AREA_UI_4X3_HOOK, 0x3B3F0010, 'area_ui_4x3', True),
]


def assemble(base, std, names_addr, layout_addr):
	"""std converts a Boom Street address to this main.dol's address."""
	a = Asm(base)

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
		with open(os.path.join(root, 'sys', 'main.dol'), 'r+b') as file:
			dol = Dol(file, gameInstance, MODID)

			# shop box pane names n_shop01-08: the 6 original strings + 2 new ones
			strings = b''.join(shop_pane_name(i).ljust(12, bytes(1)) for i in range(6, AREA_UI_ROWS))
			strings_addr = dol.allocate(strings, 'shop pane names')
			names = [dol.read(dol.std(AREA_UI_NAMES) + 4 * i) for i in range(6)]
			names += [strings_addr + 12 * i for i in range(AREA_UI_ROWS - 6)]
			names_addr = dol.allocate(b''.join(x.to_bytes(4, 'big') for x in names), 'shop pane name table')
			dol.patch(area_ui_patches(names_addr, dol.std(AREA_UI_NAMES)))

			layout_addr = dol.allocate(shop_4x3_data(), '4:3 shop row layout')
			dol.install(lambda base, std: assemble(base, std, names_addr, layout_addr), HOOKS)

mod = Mod()
