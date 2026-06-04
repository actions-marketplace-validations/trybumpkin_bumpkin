# Bumpkin

Bumpkin is a release-scoped semantic versioning assistant for GitHub.

It does its work when you are cutting a release:

1. finds the previous tag
2. scans merged PRs since that tag
3. recommends the release bump
4. writes release notes
5. optionally publishes the tag and GitHub Release

The main OSS path is GitHub-native and on-demand.

- no always-on server required
- no Bumpkin database required
- no per-PR comment spam required

## Main workflow

1. Merge PRs normally.
2. Run Bumpkin in `release_preview` mode.
3. Review the generated release notes artifact and either:
   - the next version to publish, or
   - a `NO_BUMP` result telling you no release is needed, or
   - a `needs_review` result telling you the batch should not be published yet.
4. Run Bumpkin in `release_publish` mode when you want to ship.

## Quickstart

Use Bumpkin from a manual GitHub Actions workflow.

```yaml
name: Bumpkin Release

on:
  workflow_dispatch:
    inputs:
      operation:
        description: "What should Bumpkin do?"
        required: true
        default: "release_preview"
        type: choice
        options:
          - release_preview
          - release_publish

permissions:
  contents: write
  pull-requests: read

jobs:
  bumpkin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - id: bumpkin
        uses: ./
        with:
          operation: ${{ inputs.operation }}
          provider: auto
          model: ${{ vars.BUMPKIN_MODEL || 'openai/gpt-4.1-mini' }}
          fallback_model: ${{ vars.BUMPKIN_FALLBACK_MODEL || 'openai/gpt-4o-mini' }}
          models_endpoint: ${{ vars.BUMPKIN_MODELS_ENDPOINT || '' }}
          models_token: ${{ secrets.MODELS_TOKEN }}

      - uses: actions/upload-artifact@v4
        with:
          name: bumpkin-release-notes
          path: ${{ steps.bumpkin.outputs.release_notes_path }}
```

## Marketplace repo

The dedicated Marketplace-style Action repo now lives at [trybumpkin/bumpkin-action](https://github.com/trybumpkin/bumpkin-action).

That means the public OSS story stays:

- Action-first
- release-scoped
- no always-on server
- no Bumpkin database

This repo still contains some experimental App/webhook code, but it is not the product path we are centering.

To support the Marketplace split, Bumpkin now has:

- runtime-only Action dependencies in [`requirements.txt`](requirements.txt)
- dev/test dependencies in [`requirements-dev.txt`](requirements-dev.txt)
- an export script for a dedicated action repo in [`scripts/export_marketplace_action_repo.py`](scripts/export_marketplace_action_repo.py)

The standalone Action repo is published from this development repo's verified export shape.

## Roadmap

Current priorities and support direction live in [`ROADMAP.md`](ROADMAP.md).

## Run locally

You can also preview a release locally without any webhook server:

```bash
PYTHONPATH=src python -m bumpkin.release_job \
  --operation preview \
  --repository owner/repo \
  --github-token "$GITHUB_TOKEN" \
  --target-ref main
```

To publish instead of preview:

```bash
PYTHONPATH=src python -m bumpkin.release_job \
  --operation publish \
  --repository owner/repo \
  --github-token "$GITHUB_TOKEN" \
  --target-ref main
```

## First smoke test

The easiest real-world test looks like this:

1. Create a throwaway repo or branch.
2. Create a starting tag such as `v0.1.0`.
3. Merge one or two PRs after that tag.
4. Run the example workflow in [`.github/workflows/bumpkin.yml`](.github/workflows/bumpkin.yml) with `release_preview`.
5. Confirm the artifact and step summary list the expected PRs and next version.
6. Run the same workflow with `release_publish`.
7. Confirm GitHub now has:
   - the expected tag
   - the expected GitHub Release
   - the same release notes body you previewed

If every merged PR in the batch is `NO_BUMP`, preview should say no release is needed and publish should exit cleanly without creating a tag.

If any PR in the batch cannot be classified safely, preview should return `needs_review`, generate a release-notes artifact, and avoid publishing anything.

## What each operation does

### `release_preview`

- finds the previous release tag
- loads merged PRs since that tag
- runs the recommendation pipeline across the batch
- computes the next version, or determines that no release is needed
- writes a Markdown release-notes artifact
- does not post PR comments in the release-scoped flow
- does not publish anything

### `release_publish`

- does everything in `release_preview`
- creates the new tag and GitHub Release when a release is required
- exits cleanly without publishing when the batch resolves to `NO_BUMP`

### `pr_recommendation`

This is the older per-PR mode.

It still exists for repositories that want PR-level analysis, but it is not the main product story.

## Action outputs

For `release_preview` and `release_publish`, the action exposes:

- `release_status`
- `release_previous_tag`
- `release_next_tag`
- `release_label`
- `release_pr_count`
- `release_notes_path`
- `release_target_sha`
- `release_url`
- `tag_url`

## Required secrets

- `MODELS_TOKEN`: token for your chosen model provider

GitHub's built-in `github.token` is used automatically for repo reads and release publishing.

## Provider setup

Bumpkin is provider-agnostic.

The generic contract is:

- `model`: which model to call
- `models_endpoint`: optional OpenAI-compatible or provider-specific chat-completions endpoint
- `models_token`: secret token or API key for that endpoint

### Default path

If you want the easiest setup, keep the defaults:

- `provider: auto`
- leave `models_endpoint` empty
- set `MODELS_TOKEN`
- optionally set `BUMPKIN_MODEL`

That keeps the workflow simple and lets the repo decide the model through variables.

### Custom provider path

If you want Gemini, OpenRouter, or another OpenAI-compatible provider:

1. set repo/org variable `BUMPKIN_MODEL`
2. set repo/org variable `BUMPKIN_MODELS_ENDPOINT`
3. set secret `MODELS_TOKEN`

### Example: GitHub Models

- `BUMPKIN_MODEL=openai/gpt-4.1-mini`
- `BUMPKIN_MODELS_ENDPOINT=` (leave empty)
- `MODELS_TOKEN=<your GitHub Models token>`

### Example: Gemini OpenAI-compatible endpoint

- `BUMPKIN_MODEL=gemini-2.5-flash`
- `BUMPKIN_MODELS_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/`
- `MODELS_TOKEN=<your Gemini API key>`

### Why this split exists

Bumpkin should not guess which company you use from your token.

The repo defaults stay simple, and custom providers stay explicit.

## Configuration

Use [`bumpkin.yml.example`](bumpkin.yml.example) as the starting point for analysis policy.

Recommended config direction:

- prefer `public_api.paths` and `public_api.entrypoints` for public contract boundaries
- treat `surface_area` as a legacy fallback
- use `low_signal_paths` for tests, docs, and workflow files instead of ignoring them completely
- keep `pr_comment_mode: off` unless you explicitly want PR-level comment behavior

## Experimental app code

Some GitHub App and webhook code still exists in the codebase, but it is experimental and intentionally out of the main product path.

If we revisit a hosted App later, we can rebuild or restore that path separately without changing the Action-first public story here.

## Repo layout

- [`action.yml`](action.yml): composite GitHub Action entrypoint
- [`src/bumpkin/release_job.py`](src/bumpkin/release_job.py): release-scoped planner and publisher
- [`src/main.py`](src/main.py): legacy PR recommendation entrypoint
- [`src/bumpkin/github`](src/bumpkin/github): action-facing GitHub integration helpers
- [`src/bumpkin/orchestrator`](src/bumpkin/orchestrator): recommendation pipeline
- [`scripts/export_marketplace_action_repo.py`](scripts/export_marketplace_action_repo.py): builds a trimmed Marketplace-action repo artifact
- [`tests`](tests): unit, integration, and contract coverage
