## Outcome

Describe the user-visible or maintainer-visible result.

## Governance impact

State whether this changes enrollment, routing, worktree isolation, verification, integration, evidence, persisted schemas, or the packaged Skill.

## Proof

List the exact tests and checks run. Include failure-path coverage for changes to a fail-closed boundary.

## Checklist

- [ ] The canonical checkout remains an integration target, not a construction path.
- [ ] Passing evidence is still bound to the exact committed bytes.
- [ ] Persisted contract changes have a new version and explicit migration decision.
- [ ] User documentation describes outcomes without requiring governance knowledge.
