"""Mafia game logic and state management."""

import random
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class Role(Enum):
    CIVILIAN = "Tinch aholi"
    MAFIA = "Mafia"
    DOCTOR = "Doktor"
    DETECTIVE = "Detektiv"


class GameState(Enum):
    WAITING = auto()
    NIGHT = auto()
    DAY_DISCUSSION = auto()
    DAY_VOTING = auto()


ROLE_EMOJIS = {
    Role.CIVILIAN: "👤",
    Role.MAFIA: "🔫",
    Role.DOCTOR: "💊",
    Role.DETECTIVE: "🔍",
}

ROLE_DESCRIPTIONS = {
    Role.CIVILIAN: "Sizning maqsadingiz — mafiyani aniqlab, uni kunduzi ovoz berish orqali yo'q qilish.",
    Role.MAFIA: "Tunda qurbonni tanlaysiz. Kunduzi tinch aholi bo'lib ko'rinasiz.",
    Role.DOCTOR: "Tunda kimni qutqarishni tanlaysiz. O'zingizni ham qutqara olasiz.",
    Role.DETECTIVE: "Tunda bir o'yinchini tekshirasiz — u mafiami yoki yo'qligini bilasiz.",
}


@dataclass
class Player:
    user_id: int
    username: str
    full_name: str
    role: Optional[Role] = None
    alive: bool = True
    protected: bool = False

    @property
    def mention(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.full_name

    @property
    def display_name(self) -> str:
        return self.full_name or self.username or str(self.user_id)


@dataclass
class Game:
    chat_id: int
    host_id: int
    state: GameState = GameState.WAITING
    players: dict = field(default_factory=dict)  # user_id -> Player
    round_number: int = 0

    # Night action targets
    mafia_votes: dict = field(default_factory=dict)   # mafia_uid -> target_uid
    doctor_target: Optional[int] = None
    detective_target: Optional[int] = None

    # Day voting
    day_votes: dict = field(default_factory=dict)     # voter_uid -> target_uid

    # Night actions done tracker
    night_actions_done: set = field(default_factory=set)

    # Who was killed last night (for announcement)
    last_killed: Optional[int] = None
    last_saved: bool = False
    last_detective_result: Optional[tuple] = None     # (checked_uid, is_mafia)

    @property
    def alive_players(self) -> dict:
        return {uid: p for uid, p in self.players.items() if p.alive}

    @property
    def alive_mafia(self) -> dict:
        return {uid: p for uid, p in self.alive_players.items() if p.role == Role.MAFIA}

    @property
    def alive_civilians(self) -> dict:
        return {uid: p for uid, p in self.alive_players.items() if p.role != Role.MAFIA}

    @property
    def doctor(self) -> Optional["Player"]:
        for p in self.alive_players.values():
            if p.role == Role.DOCTOR:
                return p
        return None

    @property
    def detective(self) -> Optional["Player"]:
        for p in self.alive_players.values():
            if p.role == Role.DETECTIVE:
                return p
        return None

    def check_win(self) -> Optional[str]:
        """Returns 'mafia', 'civilians', or None."""
        mafia_count = len(self.alive_mafia)
        civilian_count = len(self.alive_civilians)
        if mafia_count == 0:
            return "civilians"
        if mafia_count >= civilian_count:
            return "mafia"
        return None

    def assign_roles(self):
        """Assign roles to all players based on player count."""
        player_ids = list(self.players.keys())
        random.shuffle(player_ids)
        n = len(player_ids)

        if n <= 5:
            mafia_count = 1
        elif n <= 8:
            mafia_count = 2
        else:
            mafia_count = 3

        roles = [Role.MAFIA] * mafia_count + [Role.DETECTIVE, Role.DOCTOR]
        roles += [Role.CIVILIAN] * (n - len(roles))

        for uid, role in zip(player_ids, roles):
            self.players[uid].role = role

    def mafia_kill_target(self) -> Optional[int]:
        """Determine who mafia kills (majority vote among mafia)."""
        if not self.mafia_votes:
            return None
        vote_counts: dict = {}
        for target in self.mafia_votes.values():
            vote_counts[target] = vote_counts.get(target, 0) + 1
        return max(vote_counts, key=lambda k: vote_counts[k])

    def resolve_night(self) -> tuple:
        """
        Resolve night actions.
        Returns (killed_uid_or_None, was_saved: bool, detective_result_or_None)
        """
        kill_target = self.mafia_kill_target()
        was_saved = False

        if kill_target is not None:
            if self.doctor_target == kill_target:
                was_saved = True
                kill_target = None
            else:
                self.players[kill_target].alive = False

        detective_result = None
        if self.detective_target is not None:
            target_player = self.players.get(self.detective_target)
            if target_player:
                is_mafia = target_player.role == Role.MAFIA
                detective_result = (self.detective_target, is_mafia)

        self.last_killed = kill_target
        self.last_saved = was_saved
        self.last_detective_result = detective_result

        # Reset night state
        self.mafia_votes = {}
        self.doctor_target = None
        self.detective_target = None
        self.night_actions_done = set()

        return kill_target, was_saved, detective_result

    def resolve_vote(self) -> Optional[int]:
        """
        Resolve day voting.
        Returns eliminated player uid or None if tied.
        """
        if not self.day_votes:
            return None

        vote_counts: dict = {}
        for target in self.day_votes.values():
            vote_counts[target] = vote_counts.get(target, 0) + 1

        max_votes = max(vote_counts.values())
        leaders = [uid for uid, cnt in vote_counts.items() if cnt == max_votes]

        if len(leaders) == 1:
            loser = leaders[0]
            self.players[loser].alive = False
            self.day_votes = {}
            return loser

        # Tie — no one is eliminated
        self.day_votes = {}
        return None

    def night_actions_expected(self) -> set:
        """Returns set of role names expected to act this night."""
        expected = set()
        if self.alive_mafia:
            expected.add("mafia")
        if self.doctor:
            expected.add("doctor")
        if self.detective:
            expected.add("detective")
        return expected

    def night_complete(self) -> bool:
        return self.night_actions_done >= self.night_actions_expected()

    def player_list_text(self, show_roles: bool = False) -> str:
        lines = []
        for i, (uid, p) in enumerate(self.players.items(), 1):
            status = "" if p.alive else " 💀"
            role_part = f" — {ROLE_EMOJIS[p.role]}{p.role.value}" if show_roles and p.role else ""
            lines.append(f"{i}. {p.display_name}{role_part}{status}")
        return "\n".join(lines)
