# Contributing

AutoGovern2Code is a Windows product. Development requires Python 3.11 or newer. On Windows, AG2C uses Git from PATH when present and otherwise downloads MinGit into its data directory.

```bash
python -m venv .venv
python -m pip install -e .[test]
python -m pytest tests/ -n auto --dist loadgroup
python -m build
```

Tests are standard `unittest.TestCase` suites collected and parallelized by
pytest + pytest-xdist; `tests/suites.py` maps suite names to modules and is
what policy checker commands invoke. `--dist loadgroup` honours the
`xdist_group("gui")` pin in `tests/conftest.py`, so the gui suite tests
stay on one worker (serial) even in a full parallel run. On Windows the
suite cost is dominated by process spawn: pointing `TEMP` at a RAM disk and
excluding the temp directory from real-time antivirus scanning both cut
suite wall-clock time substantially.

Contributions should preserve these boundaries:

- enrolled projects enter AG2C automatically before the first write;
- the canonical checkout is an integration target, never a construction directory;
- only evidence for the exact verified bytes can authorize integration;
- core decisions remain deterministic and explainable;
- goals and semantic search never grant ownership;
- unknown inputs expand validation;
- checker commands never use a shell;
- governed products remain independent from AG2C;
- persisted format changes require a new schema version and migration notes.

Add tests for successful operation, interventions, and fail-closed behavior.
Update the automatic governance contract when a change affects enrollment, task
state, verification, evidence, or integration.

Validate `src/ag2c/skills/ag2c-governed-development` with compatible Agent Skills tooling when changing its metadata or instructions.
