# Contributing

Thanks for wanting to contribute to Bumpkin.

## What kind of repo this is

This repo is the main public OSS home for Bumpkin.

The install target for GitHub Actions is:

- `trybumpkin/bumpkin-action`

This repo is where the source, tests, roadmap, and release logic evolve.

## Good first contribution areas

- release workflow docs
- versioning edge cases
- public API boundary config
- Python support
- fixture quality and eval coverage
- release note rendering

## Before opening a larger change

If the change is big, behavioral, or architectural, please open an issue first so we can align on:

- the user problem
- the expected SemVer behavior
- how the change should be tested

## Local setup

Use Python 3.11 if possible.

Install dev dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the main checks:

```bash
ruff check src tests
ruff format --check src tests
pyright
PYTHONPATH=src python -m pytest -q
```

## Workflow expectations

Please keep the public product story clear:

- Action-first
- release-scoped
- no required hosted server
- no required Bumpkin database

Do not re-center the repo around the old app shell or webhook path unless there is a very deliberate product decision to do that.

## Evals

Default CI is intentionally small.

Heavy eval workflows live separately in:

- `.github/workflows/evals.yml`

That means:

- normal code health checks belong in `ci.yml`
- eval/canary/research-style checks belong in `evals.yml`

## Docs surface

We keep the public markdown surface intentionally small.

Public root docs should stay focused and useful:

- `README.md`
- `CHANGELOG.md`
- `SECURITY.md`
- `ROADMAP.md`
- `CONTRIBUTING.md`

If a doc is mostly internal planning or experiment scaffolding, it should not live as a public-facing root markdown file.

## Testing expectations

If you change behavior, try to add or update tests close to the affected layer:

- unit tests for narrow logic changes
- integration tests for release flow changes
- eval fixtures only when they help lock real product behavior

## Pull requests

Good PRs here usually include:

- a clear reason for the change
- the user-facing behavior impact
- test coverage or an explanation for why tests were not changed

If the change affects versioning logic, API-boundary detection, or release notes, call that out explicitly in the PR description.
