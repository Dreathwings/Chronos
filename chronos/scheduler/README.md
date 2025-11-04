# Chronos Scheduler

This package implements a self-contained academic timetable generator backed by
[OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_sat/).
It consumes JSON payloads describing the problem domain and produces feasible
schedules along with diagnostic metrics.

## Directory layout

- `config.py` – configuration dataclasses and defaults.
- `io_schema.py` – Pydantic models documenting the JSON contract.
- `model.py` – internal dataclasses used while building the CP-SAT model.
- `builder.py` – translates the validated payload into CP-SAT variables and
  hard constraints.
- `objective.py` – adds the optimisation objective.
- `solver.py` – configures CP-SAT and executes the search.
- `postprocess.py` – reconstructs human readable sessions and metrics from the
  solver output.
- `validate.py` – helpers to validate JSON payloads and solver results.
- `api.py` – public Python API and CLI entry point.

## Usage

Run the scheduler directly using the module:

```bash
python -m chronos.scheduler.api examples/input_small.json > schedule.json
```

or programmatically:

```python
from chronos.scheduler.api import generate_schedule
from pathlib import Path
import json

data = json.loads(Path("examples/input_small.json").read_text())
result = generate_schedule(data)
```

## Running the tests

The test-suite is located under `tests/scheduler` and can be executed with:

```bash
pytest -q tests/scheduler
```

## JSON contract

The contract is fully specified in `io_schema.py`. A minimal dataset is
available in `examples/input_small.json` and a larger synthetic dataset in
`examples/input_medium.json`.
