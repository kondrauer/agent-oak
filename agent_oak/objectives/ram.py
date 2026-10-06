"""A snapshot of the RAM regions the objective predicates read."""

from dataclasses import dataclass
from hashlib import blake2b

from pyboy import PyBoy

from agent_oak.memory.read import PARTY_STRUCT_LEN

PARTY_LENGTH = 6
BAG_CAPACITY = 20
PC_ITEM_CAPACITY = 50
MOVES_OFFSET = 0x08  # in the party struct
LEVEL_OFFSET = 0x21
NUM_MOVES = 4
LIST_END = 0xFF
STATUS_FLAGS = tuple(f"wStatusFlags{i}" for i in range(1, 8))


def regions(syms: dict[str, int], num_events: int) -> dict[str, tuple[int, int]]:
    """Start address and length of every region a snapshot holds.

    Args:
        syms: The symbol table mapping names to addresses.
        num_events: Number of event flags, wEventFlags has one bit each.
    """
    party_end = syms["wPartyMon1"] + PARTY_LENGTH * PARTY_STRUCT_LEN
    return {
        "wEventFlags": (syms["wEventFlags"], (num_events + 7) // 8),
        "wObtainedBadges": (syms["wObtainedBadges"], 1),
        "wTownVisitedFlag": (syms["wTownVisitedFlag"], 2),
        "wToggleableObjectFlags": (
            syms["wToggleableObjectFlags"],
            syms["wToggleableObjectFlagsEnd"] - syms["wToggleableObjectFlags"],
        ),
        # count, then (item, quantity) pairs and a $ff terminator
        "wNumBagItems": (syms["wNumBagItems"], 1 + 2 * BAG_CAPACITY + 1),
        "wNumBoxItems": (syms["wNumBoxItems"], 1 + 2 * PC_ITEM_CAPACITY + 1),
        # count, species list, then the party structs
        "wPartyCount": (syms["wPartyCount"], party_end - syms["wPartyCount"]),
        **{name: (syms[name], 1) for name in STATUS_FLAGS},
    }


@dataclass(frozen=True)
class Ram:
    """Bytes of the RAM regions the predicates need, read in one go.

    Predicates read from here instead of the emulator, so a whole evaluation
    sees one consistent state and tests can build states by hand.
    """

    data: dict[str, bytes]
    party_mon_offset: int = 0
    """Offset of wPartyMon1 inside the wPartyCount region."""

    @classmethod
    def read(cls, pyboy: PyBoy, syms: dict[str, int], num_events: int) -> "Ram":
        """Copy the regions out of the emulator, hold mem_lock while calling."""
        data = {
            name: bytes(pyboy.memory[addr : addr + length])
            for name, (addr, length) in regions(syms, num_events).items()
        }
        return cls(
            data=data,
            party_mon_offset=syms["wPartyMon1"] - syms["wPartyCount"],
        )

    def key(self) -> bytes:
        """Digest of every byte, equal snapshots evaluate the same."""
        h = blake2b(digest_size=16)
        for name in sorted(self.data):
            h.update(name.encode())
            h.update(self.data[name])
        return h.digest()

    def bit(self, region: str, index: int) -> bool:
        """Bit 'index' of a flag array, bit 0 is the low bit of byte 0."""
        data = self.data[region]
        byte = index // 8
        if byte >= len(data):
            return False
        return bool(data[byte] >> (index % 8) & 1)

    def _items(self, region: str) -> dict[int, int]:
        data = self.data[region]
        out: dict[int, int] = {}
        for i in range(min(data[0], (len(data) - 2) // 2)):
            item, quantity = data[1 + 2 * i], data[2 + 2 * i]
            if item == LIST_END:
                break
            out[item] = out.get(item, 0) + quantity
        return out

    def bag_items(self) -> dict[int, int]:
        """Item id -> quantity in the bag."""
        return self._items("wNumBagItems")

    def box_items(self) -> dict[int, int]:
        """Item id -> quantity in the PC's item storage."""
        return self._items("wNumBoxItems")

    def party_count(self) -> int:
        """Count the Pokemon in the party."""
        return min(self.data["wPartyCount"][0], PARTY_LENGTH)

    def _mon(self, slot: int) -> bytes:
        start = self.party_mon_offset + slot * PARTY_STRUCT_LEN
        return self.data["wPartyCount"][start : start + PARTY_STRUCT_LEN]

    def party_moves(self) -> set[int]:
        """Move ids any party Pokemon knows."""
        moves: set[int] = set()
        for slot in range(self.party_count()):
            mon = self._mon(slot)
            moves.update(m for m in mon[MOVES_OFFSET : MOVES_OFFSET + NUM_MOVES] if m)
        return moves

    def party_levels(self) -> list[int]:
        """Level of every party Pokemon, in party order."""
        return [self._mon(slot)[LEVEL_OFFSET] for slot in range(self.party_count())]
