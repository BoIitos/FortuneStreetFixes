import pycsmm
import os
from FortuneStreetFixesCommon import Asm, Dol, ha

MODID = __name__

# (Boom Street virtual address, original instruction, patched instruction)
PATCHES = [
	# Ai::Player::SearchRoute() builds a tree of all reachable routes from a fixed arena (Ai::SimpleMem).
	# On boards with many branches the arena runs out; the allocation then yields NULL, but the node is
	# still written to (crash at 0x8009D238 writing to 0x10). Skip the branch instead; the tree
	# traversal already ignores missing children.
	(0x8009D234, 0x3BA00000, 0x4800004C),  # li r29, 0x0              -> b 0x8009D280 (next branch)
]

# Boom Street addresses
CALC_DISTANCE_4_SALARY = 0x8009CD84   # Ai::Player::CalcDistance4Salary(int, int, int, int) const
GET_NEXT_PLACE = 0x8008FFA4           # Gm::Place::GetNextPlace(int*, int, bool) const
G_BOARD = 0x8054D018                  # Gm::g_board

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
	(CALC_DISTANCE_4_SALARY, 0x9421FB90, 'calc_distance', False),
]


def assemble(base, std):
	"""std converts a Boom Street address to this main.dol's address."""
	a = Asm(base)

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
			dol.install(assemble, HOOKS)

mod = Mod()
