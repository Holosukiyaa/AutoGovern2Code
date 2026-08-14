# Contributing

DEG requires Python 3.11 or newer.

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
```

Contributions should preserve these boundaries:

- enrolled projects enter DEG automatically before the first write;
- the canonical checkout is an integration target, never a construction directory;
- only evidence for the exact verified bytes can authorize integration;
- core decisions remain deterministic and explainable;
- goals and semantic search never grant ownership;
- unknown inputs expand validation;
- checker commands never use a shell;
- governed products remain independent from DEG;
- persisted format changes require a new schema version and migration notes.

Add tests for successful operation, interventions, and fail-closed behavior.
Update the automatic governance contract when a change affects enrollment, task
state, verification, evidence, or integration.
