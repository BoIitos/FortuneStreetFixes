import pycsmm
import os
from FortuneStreetFixesCommon import Asm, Dol

MODID = __name__

# Boom Street addresses
SET_EXTRA_FONT_APPEND = 0x8006C9EC    # Scene::Layout::Manager::SetExtraFont   lwz r29, 0x48(r28)
SET_EXTRA_FONT_NEXT = 0x8006C9F0      # the append to the font vector
SET_EXTRA_FONT_DONE = 0x8006CF28      # after the append: TagProcessor::SetExtraFont, then cleanup

# Scene::Layout::Manager::SetExtraFont(Obj*, name) gives a layout the extra font (Game::SetLayoutExtraFont,
# called by about 60 UI constructors, speech balloons and menus). To keep the font alive, it appends a
# pair {shared_ptr<FontHolder>, shared_ptr<FontRefLink>()} to a vector of the layout's ResourceHolder
# (+0xBC begin, +0xC0 size, +0xC4 capacity) on every call, without checking for an existing entry. The
# common UI holder lives for the whole game, so the vector grows steadily (4179 entries after 25
# rounds; 101984 = 1.6 MB, capacity 2.5 MB, after 545 rounds in a game that hung). Every
# growth copies it to a new block 1.6 times the size, which fragments the task heap until a file such as
# game/mg_block.brres can no longer be loaded and the game hangs before the minigame. Vanilla code.
# Skip the append when the vector already holds the same FontHolder without a FontRefLink: one entry
# keeps the font alive as long as all copies would. Entries from RegistFont carry a FontRefLink and
# are left alone.
HOLDER = 0x48                         # Scene::Layout::Obj: ResourceHolder*
FONTS_BEGIN = 0xBC                    # Scene::Layout::ResourceHolder: vector of 16-byte pairs
FONTS_SIZE = 0xC0
PAIR = 0x30                           # stack: the pair to append, FontHolder pointer first

# (Boom Street address, original instruction, hook label, link)
HOOKS = [
	(SET_EXTRA_FONT_APPEND, 0x83BC0048, 'extra_font', False),
]


def assemble(base, std):
	"""std converts a Boom Street address to this main.dol's address."""
	a = Asm(base)

	# r28 = Scene::Layout::Obj; r0, r3, r4 and ctr are set again on both paths
	a.label('extra_font')
	a.lwz(29, HOLDER, 28)
	a.lwz(4, FONTS_SIZE, 29)
	a.cmpwi(4, 0)
	a.ble('extra_font_append')
	a.mtctr(4)
	a.lwz(4, FONTS_BEGIN, 29)
	a.lwz(3, PAIR, 1)
	a.label('extra_font_loop')
	a.lwz(0, 0, 4)
	a.cmpw(0, 3)
	a.bne('extra_font_next')
	a.lwz(0, 8, 4)
	a.cmpwi(0, 0)
	a.beq('extra_font_skip')
	a.label('extra_font_next')
	a.addi(4, 4, 0x10)
	a.bdnz('extra_font_loop')
	a.label('extra_font_append')
	a.b(std(SET_EXTRA_FONT_NEXT))
	a.label('extra_font_skip')
	a.b(std(SET_EXTRA_FONT_DONE))
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
			dol.install(assemble, HOOKS)

mod = Mod()
