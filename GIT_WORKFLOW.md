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
| `feat` | New feature, new entity, new service, new engine |
| `fix` | Bug fix |
| `docs` | Only README, CHANGELOG, GIT_WORKFLOW, STATUS, or code comments — no logic changed |
| `test` | Adding or updating tests only |
| `refactor` | Cleaned up code, no behaviour change |
| `chore` | Version bump, manifest update, hacs.json, CI config |
| `trans` | Translation strings only (en.json / da.json / strings.json) |
| `style` | Formatting only — ran `ruff format`, nothing else |

### Scopes

Use the name of the file or feature you changed:

`controller` · `presence` · `window` · `preheat` · `season` · `waste` ·
`coordinator` · `config_flow` · `entities` · `frontend` · `panel` · `card` ·
`websocket` · `diagnostics` · `tests` · `docs` · `ci`

### Real examples

```
feat(controller): add ON/PAUSE/OFF state machine with guard decorator
feat(season): add SeasonEngine — AUTO resolves to WINTER/SUMMER from outdoor temp
feat(waste): add WasteCalculator — proper kWh estimation with midnight reset
feat(preheat): add PreheatEngine — fires on travel_time_home below lead time
feat(diagnostics): add async_get_config_entry_diagnostics for Gold IQS
feat(frontend): serve logo as static HTTP path, remove idle Energi i dag section
fix(window): B3 - restore schedule only when presence is active on close
fix(window): B1 - remove leading dot from lukas_vindue_contact entity ID
fix(frontend): eliminate FOUC — style-once pattern + replaceWith() in panel
fix(panel): deduplicate Lovelace resources, fix CARDS_FILE typo
fix(card): rewrite as vanilla JS — card now appears in Lovelace picker
docs(readme): add pre-heat setup section and updated entity table
chore(manifest): bump version 0.1.0 → 0.2.0
test(season): add regression test for same-day double-count guard
trans(da): add exceptions section with Danish error messages
```

### Rules

- Use the imperative (command) form: "add", "fix", "remove" — not "added" or "fixes"
- No period at the end of the subject line
- Bug fixes reference the bug ID: `fix(window): B1 - ...`
- One logical change per commit — do not bundle unrelated changes
- If the commit closes a GitHub issue, add `Closes #12` on a line in the body
- Never bump the version without updating CHANGELOG.md in the same commit

---

## Branching

| Branch | Purpose |
|--------|---------
| `main` | Always release-ready. Only merge here when releasing a version. |
| `dev` | All work-in-progress merges here first. |
| `feature/<n>` | New features, branched from `dev` |
| `fix/<n>` | Bug fixes, branched from `dev` |
| `docs/<n>` | Documentation only, branched from `dev` |

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
- [ ] If new translation string added: both `en.json` and `da.json` updated in same commit
- [ ] If new entity added: `icons.json` updated with icon entry
- [ ] If exception raised: `strings.json` / `en.json` / `da.json` have `exceptions` entry
- [ ] If version bumped: `CHANGELOG.md` updated in same commit
- [ ] `quality_scale.yaml` updated if an IQS rule was completed
- [ ] Commit message follows the format above
- [ ] Only one logical change in this commit

---

## Releasing a new version

1. Move all entries from `[Unreleased]` in `CHANGELOG.md` to a new `[X.Y.Z] - YYYY-MM-DD` section.
2. Update `"version"` in `manifest.json`.
3. Update `VERSION` in `const.py`.
4. Commit on `dev`: `chore(manifest): bump version X.X.X → X.Y.Z`
5. Merge `dev` → `main` via a Pull Request on GitHub.
6. On GitHub: create a new Release, tag it `vX.Y.Z`, paste the CHANGELOG section as release notes.

### Version number rules

```
MAJOR.MINOR.PATCH

MAJOR  Breaking change — config entry schema changed, entities renamed/removed
MINOR  New feature, new entity, new service, new engine — backwards compatible
PATCH  Bug fix, translation update, documentation only
```

---

## Version history quick reference

| Version | Date | Type | Highlights |
|---------|------|------|-----------|
| 0.1.0 | 2026-03-20 | Initial | Foundation: controller, presence, window engines, config flow, translations, 36 tests |
| 0.2.0 | 2026-03-21 | Minor | Season, waste, preheat engines; Gold IQS; diagnostics; HACS; FOUC fixes; 58 tests |
| 0.2.9 | 2026-03-28 | Patch | PID controller, anti-windup, per-room temp sensor, Netatmo HAP local writes, energy tracking |
| 0.3.0 | 2026-03-29 | Minor | Frontend redesign (Indeklima design system), panel sidebar, Lovelace card resource registration, SVG rings |
| 0.3.1 | 2026-03-28 | Patch | Fixed B-CARD-IAH (insertAdjacentHTML in card picker), entity ID resolution after reinstall |
| 0.3.2 | 2026-03-29 | Patch | Fixed B-429 (Netatmo API rate limit on concurrent calls via asyncio.Lock), meteorological seasons (Spring/Autumn) |
| 0.3.3 | 2026-04-21 | Patch | Logo served as static HTTP path (shadow DOM fix), removed "Energi i dag" overview section (always-zero clutter) |
