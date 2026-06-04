# Bumpkin

![Bumpkin banner](assets/bumpkinb-wide.png)

Bumpkin is a release assistant that analyzes merged PRs, determines version bumps, and writes release notes - no commit conventions required.

Bumpkin is built around release-scoped GitHub Actions.

## What it does

1. finds the previous tag
2. scans merged PRs since that tag
3. prepares release notes
4. computes the next version or `NO_BUMP`
5. optionally publishes the tag and GitHub Release

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

## Provider setup

Bumpkin is provider-agnostic.

The simplest setup is:

- `MODELS_TOKEN`
- optionally `BUMPKIN_MODEL`
- leave `BUMPKIN_MODELS_ENDPOINT` empty

For Gemini or another OpenAI-compatible provider:

- set `BUMPKIN_MODEL`
- set `BUMPKIN_MODELS_ENDPOINT`
- set `MODELS_TOKEN`

See [`bumpkin.yml.example`](bumpkin.yml.example) for a full workflow example.

## Install path

The dedicated Marketplace-style Action repo lives at [trybumpkin/bumpkin-action](https://github.com/trybumpkin/bumpkin-action).

That repo is the clean install target for the Action.

## More

- [ROADMAP.md](ROADMAP.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [CHANGELOG.md](CHANGELOG.md)

## Local preview

You can preview a release locally without any webhook server:

```bash
PYTHONPATH=src python -m bumpkin.release_job \
  --operation preview \
  --repository owner/repo \
  --github-token "$GITHUB_TOKEN" \
  --target-ref main
```
