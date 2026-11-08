import pycsmm
import os
from FortuneStreetFixesCommon import Asm, Dol

MODID = __name__

# Boom Street addresses
PROC_NUMBER_START = 0x800AE564        # Game::GameInputCpu::procNumber   li r29, 0x0

# Game::GameInputCpu::procNumber(stream, target) enters a number for the AI, one digit per frame: it
# compares the displayed number with the target, then changes or moves past the digit under the cursor.
# The number input only has a few digits (3 for stock), so a target with more digits is never reached,
# and the AI moves the cursor forever (for example selling all of 1188 stock: 188 is shown). Limit the
# target to the largest number the input can show, so the AI enters 999 instead.
NUMBER_DIGITS = 0xBC                  # Game::GameNumberUI: digit count (Game::UIGameNumber at +0x60, +0x5C)

# (Boom Street address, original instruction, hook label, link)
HOOKS = [
	(PROC_NUMBER_START, 0x3BA00000, 'number_limit', True),
]


def assemble(base, std):
	"""std converts a Boom Street address to this main.dol's address."""
	a = Asm(base)

	# r3 = Game::GameNumberUI, r31 = target; r4, ctr and cr0 are set again after the hook
	a.label('number_limit')
	a.lwz(4, NUMBER_DIGITS, 3)
	a.cmpwi(4, 0)
	a.ble('number_limit_done')
	a.mtctr(4)
	a.li(4, 1)
	a.label('number_limit_power')
	a.mulli(4, 4, 10)
	a.bdnz('number_limit_power')   # r4 = 10^digits
	a.cmpw(31, 4)
	a.blt('number_limit_done')
	a.addi(31, 4, -1)
	a.label('number_limit_done')
	a.li(29, 0)
	a.blr()
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
