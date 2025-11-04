"""Public API for the Chronos scheduling engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .builder import build_model
from .config import DEFAULT_CONFIG, ObjectiveWeights, SchedulerConfig, SolverConfig
from .objective import apply_objective
from .postprocess import build_schedule_result
from .solver import solve_model
from .validate import validate_input, validate_output


def _config_from_payload(data) -> SchedulerConfig:
    solver_limits = data.limits
    weights = data.weights
    return SchedulerConfig(
        solver=SolverConfig(
            time_limit_seconds=solver_limits.time_limit_seconds,
            random_seed=solver_limits.random_seed,
            num_search_workers=solver_limits.num_search_workers,
            max_solutions=solver_limits.num_solutions,
        ),
        weights=ObjectiveWeights(
            teacher_compactness=weights.teacher_compactness,
            group_compactness=weights.group_compactness,
            early_slot_penalty=weights.early_slot_penalty,
            late_slot_penalty=weights.late_slot_penalty,
            room_change_penalty=weights.room_change_penalty,
            teacher_overload_penalty=weights.teacher_overload_penalty,
            group_overload_penalty=weights.group_overload_penalty,
            preference_miss_penalty=weights.preference_miss_penalty,
        ),
        enable_soft_limits_as_hard=DEFAULT_CONFIG.enable_soft_limits_as_hard,
    )


def generate_schedule(payload: Dict[str, Any] | str, config: SchedulerConfig | None = None) -> Dict[str, Any]:
    """Generate a schedule from a validated JSON payload."""

    if isinstance(payload, str):
        raw = json.loads(payload)
    else:
        raw = payload
    data = validate_input(raw)
    effective_config = config or _config_from_payload(data)
    scheduler_model = build_model(data, effective_config)
    apply_objective(scheduler_model, effective_config)
    solver = solve_model(scheduler_model, effective_config)
    result = build_schedule_result(scheduler_model, solver)
    output = validate_output({"sessions": result.sessions, "metrics": result.metrics})
    return output.dict()


def main() -> None:
    """CLI entry point used in the documentation examples."""

    import argparse

    parser = argparse.ArgumentParser(description="Generate an academic schedule")
    parser.add_argument("input_json", type=Path, help="Path to the input JSON file")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path")
    args = parser.parse_args()

    payload = json.loads(args.input_json.read_text())
    result = generate_schedule(payload)
    output_json = json.dumps(result, indent=2, default=str)
    if args.output:
        args.output.write_text(output_json)
    else:
        print(output_json)


if __name__ == "__main__":  # pragma: no cover
    main()
