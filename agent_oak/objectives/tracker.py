"""Track objective progress across tool calls and report it to the LLM."""

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from pyboy import PyBoy
from pydantic import BaseModel, Field

from agent_oak.executor.models import GotoStatus, Node, World
from agent_oak.executor.navigation import _get_current_node, goto
from agent_oak.objectives.evaluator import Evaluator, State, primary
from agent_oak.objectives.hints import MAX_TIER, hint_text
from agent_oak.objectives.milestones import Milestone
from agent_oak.objectives.progress import HintPolicy, Position, Progress
from agent_oak.objectives.ram import Ram
from agent_oak.objectives.routing import Route, RouteTarget, plan_route
from agent_oak.parser.models import GameMap
from agent_oak.pyboy_mcp.emulator import running

MAX_STATUS_LEN = 150
MAX_COMPLETED_SHOWN = 3
SAVE_EVERY_CALLS = 20
STATE_VERSION = 1
HINTS_OFF = "Hints are off (--hint-policy off)"


class GoalInfo(BaseModel):
    """A milestone on the frontier."""

    id: str
    label: str
    blurb: str
    target: RouteTarget | None = Field(
        default=None, description="Where it happens, None for menu actions"
    )
    readiness: str | None = Field(
        default=None, description="E.g. the gym leader's strongest Pokemon"
    )


class ObjectiveReport(BaseModel):
    """What to do next, from the story flags in RAM."""

    goal: GoalInfo | None = Field(description="The current goal, None when all done")
    also: list[GoalInfo] = Field(
        default_factory=list, description="Other open goals, in story order"
    )
    hint_tier: int = Field(description=f"0 to {MAX_TIER}, raise it with get_hint")
    hint: str = Field(description="The hint for the goal at the current tier")
    done: int = Field(description="Milestones completed")
    total: int
    party_levels: list[int]
    capabilities: list[str] = Field(description="Field moves usable, e.g. CUT")


class HintResult(BaseModel):
    """The hint for the current goal after raising its tier."""

    goal: str | None
    tier: int
    hint: str
    note: str | None = None


class RouteResult(Route):
    """A route to the current goal, and how walking it went if asked to."""

    walk: GotoStatus | None = Field(
        default=None, description="Set when the route was walked"
    )
    location: Node | None = Field(
        default=None, description="Where the player is afterwards (map, x, y)"
    )
    note: str | None = None


@dataclass
class Observation:
    """What changed since the last action, for the tool response."""

    completed: list[Milestone]
    status: str
    notice: str | None = None
    """Set when the hint was raised because progress stalled."""

    def completed_line(self) -> str | None:
        """'✓ Completed: ...' for the milestones done since the last call."""
        if not self.completed:
            return None
        labels = [m.label for m in self.completed[:MAX_COMPLETED_SHOWN]]
        more = len(self.completed) - len(labels)
        suffix = f" (+{more} more)" if more else ""
        return "✓ Completed: " + ", ".join(labels) + suffix


def _readiness_note(milestone: Milestone, levels: list[int]) -> str | None:
    r = milestone.readiness
    best = max(levels, default=0)
    if r.ace is not None and r.ace_level is not None:
        return f"strongest opponent {r.ace} Lv {r.ace_level}, your best Lv {best}"
    if r.min_level is not None:
        return f"recommended Lv {r.min_level}, your best Lv {best}"
    return None


def _readiness_warning(milestone: Milestone, levels: list[int]) -> str | None:
    r = milestone.readiness
    best = max(levels, default=0)
    if r.ace is not None and r.ace_level is not None and best < r.ace_level:
        return f"⚠ party max Lv {best}, {r.ace} Lv {r.ace_level}"
    if r.min_level is not None and best < r.min_level:
        return f"⚠ party max Lv {best}, recommended Lv {r.min_level}"
    return None


def _target(milestone: Milestone) -> RouteTarget | None:
    if milestone.map is None:
        return None
    t = milestone.target
    if t is None:
        return RouteTarget(map=milestone.map)
    return RouteTarget(map=milestone.map, x=t.x, y=t.y, kind=t.kind, name=t.name)


class ObjectiveTracker:
    """Evaluate the milestones after every action and keep the hint tier.

    The tier belongs to the current goal and goes back to 0 when the goal
    changes. With the auto policy it goes up when progress stalls. Tier,
    stall counters and visited tiles are saved to 'state_path', so a restart
    keeps them.
    """

    def __init__(
        self,
        evaluator: Evaluator,
        world: World,
        pyboy: PyBoy,
        syms: dict[str, int],
        maps_by_id: dict[int, GameMap],
        mem_lock: Lock,
        policy: HintPolicy | None = None,
        state_path: Path | None = None,
    ) -> None:
        """Track the objectives of the game running in 'pyboy'.

        Args:
            evaluator: Evaluates the milestones.
            world: The world model used for routing.
            pyboy: The emulator instance.
            syms: The symbol table mapping names to addresses.
            maps_by_id: Parsed game maps keyed by map id.
            mem_lock: A lock to synchronize access to the emulator's memory.
            policy: How hints are given, auto by default.
            state_path: JSON file to keep the tracker's state in, loaded
                when it exists. None keeps it in memory only.
        """
        self.evaluator = evaluator
        self.world = world
        self.pyboy = pyboy
        self.syms = syms
        self.maps_by_id = maps_by_id
        self.mem_lock = mem_lock
        self.policy = policy or HintPolicy()
        self.state_path = state_path
        self.hint_tier = 0
        self.progress = Progress(policy=self.policy)
        self._goal_id: str | None = None
        self._last_state: State | None = None
        self._calls_since_save = 0
        self._lock = Lock()
        if state_path is not None and state_path.exists():
            self._load(json.loads(state_path.read_text()))

    def _load(self, data: dict[str, Any]) -> None:
        if data.get("version") != STATE_VERSION:
            return
        self._goal_id = data.get("goal")
        self.hint_tier = data.get("hint_tier", 0)
        done = set(data.get("done", []))
        self._last_state = {
            m.id: m.id in done for m in self.evaluator.objectives.milestones
        }
        self.progress = Progress.from_json(data.get("progress", {}), self.policy)

    def save(self) -> None:
        """Write the state to 'state_path', if there is one."""
        if self.state_path is None:
            return
        with self._lock:
            data = {
                "version": STATE_VERSION,
                "goal": self._goal_id,
                "hint_tier": self.hint_tier,
                "done": [k for k, v in (self._last_state or {}).items() if v],
                "progress": self.progress.to_json(),
            }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(self.state_path)

    def _read(self) -> tuple[Ram, State, list[Milestone]]:
        ram = self.evaluator.snapshot(
            pyboy=self.pyboy, syms=self.syms, mem_lock=self.mem_lock
        )
        state = self.evaluator.evaluate(ram)
        frontier = self.evaluator.frontier(state)
        goal = primary(frontier)
        goal_id = goal.id if goal else None
        if goal_id != self._goal_id:
            self._goal_id = goal_id
            self.hint_tier = 0
        return ram, state, frontier

    def _position(self, ram: Ram) -> Position:
        memory = self.pyboy.memory
        with self.mem_lock:
            map_id = memory[self.syms["wCurMap"]]
            x, y = memory[self.syms["wXCoord"]], memory[self.syms["wYCoord"]]
            in_battle = memory[self.syms["wIsInBattle"]] != 0
        game_map = self.maps_by_id.get(map_id)
        return Position(
            map=game_map.const if game_map else f"MAP_{map_id:02X}",
            x=x,
            y=y,
            in_battle=in_battle,
            party_levels=tuple(ram.party_levels()),
            badges=ram.data["wObtainedBadges"][0],
        )

    def observe(self) -> Observation:
        """Evaluate after an action: what got done, stalls and the status line."""
        with self._lock:
            ram, state, frontier = self._read()
            last = self._last_state
            completed = [
                m
                for m in self.evaluator.objectives.milestones
                if last is not None and state[m.id] and not last[m.id]
            ]
            self._last_state = state
            update = self.progress.update(self._position(ram), completed=len(completed))
            notice = self._escalate(
                goal=primary(frontier),
                ram=ram,
                stalled=update.stalled,
                oscillating=update.oscillating,
            )
            observation = Observation(
                completed=completed,
                status=self._status_line(ram=ram, frontier=frontier),
                notice=notice,
            )
            self._calls_since_save += 1
            save = notice is not None or self._calls_since_save >= SAVE_EVERY_CALLS
        if save:
            self._calls_since_save = 0
            self.save()
        return observation

    def _escalate(
        self,
        goal: Milestone | None,
        ram: Ram,
        stalled: bool,
        oscillating: list[str] | None,
    ) -> str | None:
        """Raise the tier when stuck (auto policy), the notice to show."""
        if goal is None or self.policy.mode != "auto":
            return None
        if oscillating:
            reason = f"You keep going between {', '.join(oscillating)}."
        elif stalled:
            reason = f"No progress in the last {self.policy.stall_calls} actions."
        else:
            return None
        if self.hint_tier < min(self.policy.max_auto_tier, MAX_TIER):
            self.hint_tier += 1
        return f"💡 {reason} Hint: {self._hint(goal, ram)}"

    def _status_line(self, ram: Ram, frontier: list[Milestone]) -> str:
        goal = primary(frontier)
        levels = ram.party_levels()
        party = "Party Lv " + ("/".join(map(str, levels)) if levels else "-")
        if goal is None:
            return f"[Goal: none left | {party}]"

        hints = self.policy.mode != "off"
        head = f"Goal: {goal.label}" + (f" @ {goal.map}" if goal.map and hints else "")
        tail = [party]
        if hints and (warning := _readiness_warning(goal, levels)) is not None:
            tail.append(warning)
        if hints:
            tail.append(f"hint {self.hint_tier}")

        others = [m.label for m in frontier[1:]]
        while True:
            parts = [head]
            if others:
                parts.append("also: " + ", ".join(others))
            line = "[" + " | ".join(parts + tail) + "]"
            if len(line) <= MAX_STATUS_LEN or not others:
                break
            others.pop()
        if len(line) > MAX_STATUS_LEN:
            line = line[: MAX_STATUS_LEN - 2] + "…]"
        return line

    def _route(self, goal: Milestone, ram: Ram) -> Route:
        with self.mem_lock:
            start = _get_current_node(
                pyboy=self.pyboy, syms=self.syms, maps_by_id=self.maps_by_id
            )
        return plan_route(
            world=self.world,
            milestone=goal,
            start=start,
            abilities=self.evaluator.capabilities(ram),
        )

    def _hint(self, goal: Milestone, ram: Ram) -> str:
        route = self._route(goal, ram) if self.hint_tier >= MAX_TIER else None
        return hint_text(goal, tier=self.hint_tier, route=route)

    def report(self) -> ObjectiveReport:
        """Report the frontier, the hint at the current tier and readiness notes.

        With hints off only the goals' labels.
        """
        hints = self.policy.mode != "off"
        with self._lock:
            ram, state, frontier = self._read()
            levels = ram.party_levels()
            infos = [
                GoalInfo(
                    id=m.id,
                    label=m.label,
                    blurb=m.blurb if hints else "",
                    target=_target(m) if hints else None,
                    readiness=_readiness_note(m, levels) if hints else None,
                )
                for m in frontier
            ]
            goal = primary(frontier)
            if goal is None:
                hint = "Every milestone is done."
            else:
                hint = self._hint(goal, ram) if hints else goal.label
            return ObjectiveReport(
                goal=infos[0] if infos else None,
                also=infos[1:],
                hint_tier=self.hint_tier,
                hint=hint,
                done=sum(state.values()),
                total=len(state),
                party_levels=levels,
                capabilities=sorted(self.evaluator.capabilities(ram)),
            )

    def bump_hint(self) -> HintResult:
        """Raise the current goal's hint tier by one and return the hint."""
        with self._lock:
            ram, _, frontier = self._read()
            goal = primary(frontier)
            if goal is None:
                return HintResult(goal=None, tier=0, hint="Every milestone is done.")
            if self.policy.mode == "off":
                return HintResult(goal=goal.id, tier=0, hint=goal.label, note=HINTS_OFF)
            note = None
            if self.hint_tier < MAX_TIER:
                self.hint_tier += 1
            else:
                note = f"Already at the most specific hint (tier {MAX_TIER})"
            result = HintResult(
                goal=goal.id,
                tier=self.hint_tier,
                hint=self._hint(goal, ram),
                note=note,
            )
        self.save()
        return result

    def route(self, execute: bool = False) -> RouteResult:
        """Plan a path to the current goal's target, and walk it if asked to.

        Args:
            execute: Walk the path with goto, which stops at battles and
                text boxes like goto_map does.
        """
        with self._lock:
            ram, _, frontier = self._read()
        goal = primary(frontier)
        if goal is None:
            return RouteResult(
                status="no_location", milestone="", note="Every milestone is done."
            )
        if self.policy.mode == "off":
            return RouteResult(status="disabled", milestone=goal.id, note=HINTS_OFF)

        result = RouteResult(**self._route(goal, ram).model_dump())
        if result.status == "no_location":
            result.note = goal.blurb
        if execute and result.status == "route" and result.stand is not None:
            with running(pyboy=self.pyboy, mem_lock=self.mem_lock):
                result.walk = goto(
                    pyboy=self.pyboy,
                    syms=self.syms,
                    maps_by_id=self.maps_by_id,
                    world=self.world,
                    goal=result.stand,
                    any_tile=goal.target is None,
                )
                result.location = _get_current_node(
                    pyboy=self.pyboy, syms=self.syms, maps_by_id=self.maps_by_id
                )
        target = result.target
        if target is not None and target.kind == "npc" and result.note is None:
            result.note = (
                f"Once on {target.map}, talk to it with "
                f"talk_to_tool(x={target.x}, y={target.y})"
            )
        return result
