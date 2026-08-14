# Contributing

DEG requires Python 3.11 or newer.

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
```

Contributions should preserve these boundaries:

- core decisions remain deterministic and explainable;
- goals and semantic search never grant ownership;
- unknown inputs expand validation;
- checker commands never use a shell;
- governed products remain independent from DEG;
- persisted format changes require a new schema version and migration notes.

Add tests for both successful routing and fail-closed behavior. Update the Entry
Slicing guide when a change affects how users choose or interpret an entry.
