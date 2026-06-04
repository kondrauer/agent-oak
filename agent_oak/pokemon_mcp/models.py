"""Data models for Pokemon MCP memory parsing."""

from enum import Enum

from pydantic import BaseModel


class StatusFlags(int, Enum):
    """Status flags enumeration."""

    NONE = 0x00
    POISONED = 0x08
    BURNED = 0x10
    FROZEN = 0x20
    PARALYZED = 0x40
    SLEEP_MASK = 0x07


class PokemonSpecies(int, Enum):
    """Pokemon species enumeration."""

    NO_MON = 0
    RHYDON = 1
    KANGASKHAN = 2
    NIDORAN_M = 3
    CLEFAIRY = 4
    SPEAROW = 5
    VOLTORB = 6
    NIDOKING = 7
    SLOWBRO = 8
    IVYSAUR = 9
    EXEGGUTOR = 10
    LICKITUNG = 11
    EXEGGCUTE = 12
    GRIMER = 13
    GENGAR = 14
    NIDORAN_F = 15
    NIDOQUEEN = 16
    CUBONE = 17
    RHYHORN = 18
    LAPRAS = 19
    ARCANINE = 20
    MEW = 21
    GYARADOS = 22
    SHELLDER = 23
    TENTACOOL = 24
    GASTLY = 25
    SCYTHER = 26
    STARYU = 27
    BLASTOISE = 28
    PINSIR = 29
    TANGELA = 30
    GROWLITHE = 33
    ONIX = 34
    FEAROW = 35
    PIDGEY = 36
    SLOWPOKE = 37
    KADABRA = 38
    GRAVELER = 39
    CHANSEY = 40
    MACHOKE = 41
    MR_MIME = 42
    HITMONLEE = 43
    HITMONCHAN = 44
    ARBOK = 45
    PARASECT = 46
    PSYDUCK = 47
    DROWZEE = 48
    GOLEM = 49
    MAGMAR = 51
    ELECTABUZZ = 53
    MAGNETON = 54
    KOFFING = 55
    MANKEY = 57
    SEEL = 58
    DIGLETT = 59
    TAUROS = 60
    FARFETCHD = 64
    VENONAT = 65
    DRAGONITE = 66
    DODUO = 70
    POLIWAG = 71
    JYNX = 72
    MOLTRES = 73
    ARTICUNO = 74
    ZAPDOS = 75
    DITTO = 76
    MEOWTH = 77
    KRABBY = 78
    VULPIX = 82
    NINETALES = 83
    PIKACHU = 84
    RAICHU = 85
    DRATINI = 88
    DRAGONAIR = 89
    KABUTO = 90
    KABUTOPS = 91
    HORSEA = 92
    SEADRA = 93
    SANDSHREW = 96
    SANDSLASH = 97
    OMANYTE = 98
    OMASTAR = 99
    JIGGLYPUFF = 100
    WIGGLYTUFF = 101
    EEVEE = 102
    FLAREON = 103
    JOLTEON = 104
    VAPOREON = 105
    MACHOP = 106
    ZUBAT = 107
    EKANS = 108
    PARAS = 109
    POLIWHIRL = 110
    POLIWRATH = 111
    WEEDLE = 112
    KAKUNA = 113
    BEEDRILL = 114
    DODRIO = 116
    PRIMEAPE = 117
    DUGTRIO = 118
    VENOMOTH = 119
    DEWGONG = 120
    CATERPIE = 123
    METAPOD = 124
    BUTTERFREE = 125
    MACHAMP = 126
    GOLDUCK = 128
    HYPNO = 129
    GOLBAT = 130
    MEWTWO = 131
    SNORLAX = 132
    MAGIKARP = 133
    MUK = 136
    KINGLER = 138
    CLOYSTER = 139
    ELECTRODE = 141
    CLEFABLE = 142
    WEEZING = 143
    PERSIAN = 144
    MAROWAK = 145
    HAUNTER = 147
    ABRA = 148
    ALAKAZAM = 149
    PIDGEOTTO = 150
    PIDGEOT = 151
    STARMIE = 152
    BULBASAUR = 153
    VENUSAUR = 154
    TENTACRUEL = 155
    GOLDEEN = 157
    SEAKING = 158
    PONYTA = 163
    RAPIDASH = 164
    RATTATA = 165
    RATICATE = 166
    NIDORINO = 167
    NIDORINA = 168
    GEODUDE = 169
    PORYGON = 170
    AERODACTYL = 171
    MAGNEMITE = 173
    CHARMANDER = 176
    SQUIRTLE = 177
    CHARMELEON = 178
    WARTORTLE = 179
    CHARIZARD = 180
    FOSSIL_KABUTOPS = 182
    FOSSIL_AERODACTYL = 183
    MON_GHOST = 184
    ODDISH = 185
    GLOOM = 186
    VILEPLUME = 187
    BELLSPROUT = 188
    WEEPINBELL = 189
    VICTREEBEL = 190


class PokemonStats(BaseModel):
    """Pokemon stats data model."""

    attack: int
    defense: int
    speed: int
    special: int


class Pokemon(BaseModel):
    """Pokemon data model."""

    species_id: int
    species: PokemonSpecies
    nickname: str
    original_trainer: str
    original_trainer_id: int
    level: int
    hp: int
    max_hp: int
    status: StatusFlags
    type1: int
    type2: int
    moves: list[int]
    pp: list[int]
    stats: PokemonStats
    experience: int
