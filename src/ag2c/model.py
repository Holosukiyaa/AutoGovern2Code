from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    target_id: str
    path: str
    governed_roots: tuple[str, ...]
    excludes: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    path: Path
    project_root: Path
    project_id: str
    policy_path: Path
    state_dir: Path
    ledger_path: Path
    targets: tuple[Target, ...]

    def target(self, target_id: str) -> Target:
        return next(target for target in self.targets if target.target_id == target_id)

    def target_root(self, target_id: str) -> Path:
        return (self.project_root / self.target(target_id).path).resolve()


@dataclass(frozen=True)
class Scope:
    target_id: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    ownership: str


@dataclass(frozen=True)
class Card:
    card_id: str
    card_type: str
    title: str
    summary: str
    scopes: tuple[Scope, ...]
    checkers: tuple[str, ...]
    references: tuple[str, ...]
    jurisdiction: dict | None = None


@dataclass(frozen=True)
class Relation:
    source: str
    relation_type: str
    target: str


@dataclass(frozen=True)
class ContractBinding:
    target_id: str
    contract_id: str
    version: str
    boundary: str
    scenarios: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.target_id}:{self.contract_id}@{self.version}"


@dataclass(frozen=True)
class Checker:
    checker_id: str
    stage: str
    target_id: str | None
    command: tuple[str, ...]
    cwd: str
    timeout: int
    implementation: str = ""


@dataclass(frozen=True)
class Coverage:
    level: str
    strategy: str
    managed_by: str
    areas: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    path: Path
    cards: tuple[Card, ...]
    relations: tuple[Relation, ...]
    contracts: tuple[ContractBinding, ...]
    checkers: tuple[Checker, ...]
    coverage: Coverage
    household_required: bool = False

    def card(self, card_id: str) -> Card:
        return next(card for card in self.cards if card.card_id == card_id)

    def checker(self, checker_id: str) -> Checker:
        return next(checker for checker in self.checkers if checker.checker_id == checker_id)
