# Luna controlled task dataset

This directory contains Luna's controlled repair benchmark. It is designed to measure
the complete locate-edit-test loop under deterministic, independently judged failures.
Synthetic tasks are intentionally kept separate from the real-repository case studies in
`eval/real_cases/`.

## Current dataset

| fixture | domain | pristine tests | repair tasks |
|---|---|---:|---:|
| `expression` (`fixture/`) | tokenizer, parser, evaluator | 51 | 12 |
| `config_loader` | nested merge, interpolation, includes, schema validation | 28 | 9 |
| `dependency_planner` | parsing, DAG ordering, planning, critical path | 22 | 9 |
| **total** | 3 independent projects | **101** | **30** |

The two newer fixtures live in `fixtures/<fixture_id>/`. The original expression fixture
keeps its legacy `fixture/` path for backward compatibility.

## Task contract

Each numbered task directory contains exactly:

```text
tasks/<NNN_slug>/
  task.json
  break.patch
```

Example metadata:

```json
{
  "id": "019_config_relative_include",
  "title": "Resolve included files relative to their parent configuration",
  "kind": "fix_bug",
  "description": "Some tests are failing. Fix the full suite without editing tests.",
  "target_tests": ["tests/test_loader.py::test_include_is_resolved_relative_to_parent"],
  "fixture": "config_loader",
  "difficulty": "medium",
  "tags": ["filesystem", "cross-file", "boundary"],
  "source": {"type": "synthetic", "notes": "authored for Luna"}
}
```

Required fields are `id`, `title`, `kind`, `description`, and `target_tests`. New tasks
must also declare `fixture`, `difficulty`, `tags`, and `source`. Legacy tasks without
these fields default to the expression fixture, basic difficulty, and synthetic source.

Allowed values:

- `kind`: `fix_bug` or `implement_stub`;
- `difficulty`: `basic`, `medium`, or `hard`;
- `source.type`: `synthetic` or `upstream`;
- every target node ID starts with `tests/` and exists in the selected fixture.

The task description must describe symptoms and success criteria without naming the
broken line or revealing the repair. Titles and tags are for humans and reports.

## Patch contract

`break.patch` is generated relative to the selected fixture root. Paths therefore look
like `a/parser.py`, not `a/tasks/fixture/parser.py`. The harness applies patches with:

```bash
git apply -p1 /absolute/path/to/break.patch
```

A patch should make the smallest source-only change that creates the intended failure.
Do not modify tests in a break patch. Keep the pristine fixture fully implemented and green.

## Mandatory offline validation

Run this before any paid benchmark:

```bash
python cli.py validate
```

The validator proves all of the following without calling a model:

1. metadata is valid and IDs are unique;
2. every fixture and patch exists;
3. each pristine fixture suite is fully green;
4. every patch applies strictly;
5. every declared target becomes non-passing and at least one test fails;
6. reverse-applying the patch exactly restores pristine per-test outcomes;
7. validation leaves fixture source trees byte-for-byte unchanged.

Any failed gate makes the dataset invalid and must block an official campaign.

## Authoring workflow

1. Add or extend behavior in a pristine fixture and write tests.
2. Confirm the fixture's complete suite is green.
3. Copy the fixture to a temporary directory.
4. Make one minimal source defect in the copy.
5. Generate a fixture-relative `git diff` as `break.patch`.
6. Add task metadata with honest difficulty, tags, and provenance.
7. Run `python cli.py validate` over the full dataset.

Never edit a pristine fixture in order to represent a broken state. The fixture is the
source of truth; broken states exist only as patches applied to disposable workspaces.

## Scoring rule

After the Agent stops, the harness deletes the workspace test tree and restores the
pristine tests, including the root `conftest.py`. It then independently reruns pytest.

A task is solved if and only if:

```text
every declared target test passes
AND
no test that passed in the pristine baseline becomes non-passing
```

Missing, skipped, deleted, or uncollected target tests do not count as passing.

## Repeated campaigns

The legacy `bench` command still supports a single run. Auditable repeated experiments use:

```bash
python cli.py experiment \
  --campaign multi_repo_v1 \
  --attempts 3 \
  --variants baseline,haiku,retrieval \
  --cost-cap 40 \
  --publish
```

Official publish mode requires a clean Git tree and writes a manifest, JSONL attempt log,
statistical summary, and Markdown report under `eval/artifacts/<campaign>/`. Interrupted
campaigns resume without duplicating completed attempt IDs.
