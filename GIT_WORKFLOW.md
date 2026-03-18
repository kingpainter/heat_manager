# Git workflow guide for Heat Manager

This guide is written for GitHub Desktop on Windows 11.
Read this before making your first commit.

---

## Commit message format

Every commit message follows this structure:

```
<type>(<scope>): <what you did>
```

The first line is max 72 characters. Add a blank line and more detail below if needed.

### Types

| Type | When to use |
|------|-------------|
| `feat` | New feature, new entity, new service |
| `fix` | Bug fix |
| `docs` | Only README, CHANGELOG, or code comments — no logic changed |
| `test` | Adding or updating tests only |
| `refactor` | Cleaned up code, no behaviour change |
| `chore` | Version bump, manifest update, CI config |
| `trans` | Translation strings only (en.json / da.json) |
| `style` | Formatting only — ran `ruff format`, nothing else |

### Scopes

Use the name of the file or feature you changed:

`controller` · `presence` · `window` · `preheat` · `season` · `waste` ·
`coordinator` · `config_flow` · `entities` · `frontend` · `tests` · `docs` · `ci`

### Real examples

```
feat(controller): add ON/PAUSE/OFF state machine with guard decorator
fix(window): B3 - restore schedule only when presence is active on close
fix(window): B1 - remove leading dot from lukas_vindue_contact entity ID
docs(readme): add HACS installation instructions and service examples
chore(manifest): bump version 0.1.0 → 0.1.1
test(controller): add regression test for auto-off via season trigger
trans(da): add Danish strings for controller_state and season_mode
```

### Rules

- Use the imperative (command) form: "add", "fix", "remove" — not "added" or "fixes"
- No period at the end of the subject line
- Bug fixes reference the bug ID: `fix(window): B1 - ...`
- One logical change per commit — do not bundle unrelated changes
- If the commit closes a GitHub issue, add `Closes #12` on a line in the body

---

## Branching

| Branch | Purpose |
|--------|---------|
| `main` | Always release-ready. Only merge here when releasing a version. |
| `dev` | All work-in-progress merges here first. |
| `feature/<name>` | New features, branched from `dev` |
| `fix/<name>` | Bug fixes, branched from `dev` |
| `docs/<name>` | Documentation only, branched from `dev` |

### Creating a branch in GitHub Desktop

1. Click **Current Branch** at the top.
2. Click **New Branch**.
3. Name it: `feature/preheat-engine` or `fix/b1-lukas-window`.
4. Base it on `dev` (not `main`).

---

## Before every commit — checklist

Run through this list before clicking **Commit** in GitHub Desktop:

- [ ] Code is formatted: `ruff format custom_components/heat_manager`
- [ ] No linting errors: `ruff check custom_components/heat_manager`
- [ ] Tests pass: `pytest tests/`
- [ ] If new string added: both `en.json` and `da.json` updated
- [ ] If version bumped: `CHANGELOG.md` updated in same commit
- [ ] Commit message follows the format above
- [ ] Only one logical change in this commit

---

## Releasing a new version

1. Move all entries from `[Unreleased]` in `CHANGELOG.md` to a new `[X.Y.Z] - YYYY-MM-DD` section.
2. Update `"version"` in `manifest.json`.
3. Commit: `chore(manifest): bump version X.X.X → X.Y.Z`
4. Merge `dev` → `main` via a Pull Request on GitHub.
5. On GitHub: create a new Release, tag it `vX.Y.Z`, paste the CHANGELOG section as release notes.

### Version number rules

```
MAJOR.MINOR.PATCH

MAJOR  Breaking change — config entry schema changed, entities renamed/removed
MINOR  New feature, new entity, new service — backwards compatible
PATCH  Bug fix, translation update, documentation only
```

---

## Version history quick reference

| Version | Type | Description |
|---------|------|-------------|
| 0.1.0 | Initial | Foundation: manifest, const, controller engine, config flow, translations |

