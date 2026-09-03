from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar


T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class WorkerLimits:
    ligand: int = 1
    vina: int = 1
    boltz: int = 1
    plip: int = 1

    def for_stage(self, stage: str) -> int:
        value = getattr(self, stage)
        if value < 1:
            raise ValueError("worker limits must be positive")
        return value


class BoundedScheduler(Generic[T, R]):
    def __init__(self, max_workers: int) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.max_workers = max_workers

    def map(self, function: Callable[[T], R], items: Iterable[T]) -> list[R]:
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures: list[Future[R]] = [pool.submit(function, item) for item in items]
            return [future.result() for future in futures]

