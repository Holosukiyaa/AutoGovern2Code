from __future__ import annotations

from typing import Any


def render_slice_markdown(value: dict[str, Any]) -> str:
    route = value["route"]
    lines = [
        f"# AG2C entry slice: {value['project']}",
        "",
        f"- State: `{route['state']}`",
        f"- Slice digest: `{value['slice_digest']}`",
    ]
    if value.get("goal"):
        lines.append(f"- Goal (advisory): {value['goal']}")
    if route["fallback_reasons"]:
        lines.extend(["", "## Conservative expansion", ""])
        lines.extend(f"- `{reason}`" for reason in route["fallback_reasons"])
    lines.extend(["", "## Entries", ""])
    for item in value["entries"]["paths"]:
        lines.append(f"- Path `{item['id']}` ({item['state']})")
    for item in value["entries"]["contracts"]:
        lines.append(f"- Contract `{item['key']}` ({item['status']})")
    lines.extend(["", "## Responsibility closure", ""])
    for card in value["cards"]:
        reasons = ", ".join(f"`{reason}`" for reason in card["selection_reasons"])
        lines.append(f"### {card['title']} (`{card['id']}`)")
        lines.extend(["", card["summary"], "", f"Selected by: {reasons}"])
        if card["references"]:
            lines.extend(["", "Read next:"])
            lines.extend(f"- `{reference}`" for reference in card["references"])
        lines.append("")
    lines.extend(["## Check plan", ""])
    if not value["check_plan"]:
        lines.append("No checkers are selected. Treat the slice as incomplete until policy coverage is added.")
    for checker in value["check_plan"]:
        command = " ".join(checker["command"])
        lines.append(f"- `{checker['stage']}` / `{checker['id']}`: `{command}`")
    lines.extend(
        [
            "",
            "## Scope rule",
            "",
            "This slice expands the reading and validation scope. It does not authorize unrelated code changes.",
            "",
        ]
    )
    return "\n".join(lines)
