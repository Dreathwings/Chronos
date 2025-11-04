"""CP-SAT solver orchestration for the Chronos scheduler."""
from __future__ import annotations

from ortools.sat.python import cp_model

from .builder import SchedulerModel
from .config import SchedulerConfig, DEFAULT_CONFIG


class SolverError(RuntimeError):
    """Raised when the solver fails to find a feasible schedule."""


def solve_model(
    scheduler_model: SchedulerModel,
    config: SchedulerConfig | None = None,
) -> cp_model.CpSolver:
    """Solve the CP-SAT model and return the configured solver instance."""

    cfg = config or DEFAULT_CONFIG
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.solver.time_limit_seconds
    if cfg.solver.random_seed is not None:
        solver.parameters.random_seed = cfg.solver.random_seed
    solver.parameters.num_search_workers = cfg.solver.num_search_workers
    solver.parameters.log_search_progress = False

    status = solver.Solve(scheduler_model.model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SolverError("Unable to compute a feasible schedule within the limits")
    return solver
