# Bumpkin

![Bumpkin banner](assets/hero.svg)

Bumpkin is a release assistant that analyzes merged PRs, determines version bumps, and writes release notes - no commit conventions required.

Built for release-scoped GitHub Actions.

## What it does

1. finds the previous tag
2. scans merged PRs since that tag
3. determines the next version or `NO_BUMP`
4. writes release notes for the batch
5. optionally publishes the tag and GitHub Release

## Setup

Use [trybumpkin/bumpkin-action](https://github.com/trybumpkin/bumpkin-action) when you want to install Bumpkin as a GitHub Action.
Install from GitHub Marketplace: [Bumpkin Release Action](https://github.com/marketplace/actions/bumpkin-release-action).

Before you run it:

- add these repository secrets:
  - `MODELS_TOKEN`
  - `BUMPKIN_MODEL`
  - `BUMPKIN_MODELS_ENDPOINT`
- give the workflow:
  - `contents: write`
  - `pull-requests: read`

Example secret values:

```text
MODELS_TOKEN=your_provider_token
BUMPKIN_MODEL=gemini-2.5-flash
BUMPKIN_MODELS_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/
```

## Quickstart

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
      base_tag:
        description: "Optional previous tag override"
        required: false
        default: ""

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
        uses: trybumpkin/bumpkin-action@v1
        with:
          operation: ${{ inputs.operation }}
          base_tag: ${{ inputs.base_tag }}
          model: ${{ secrets.BUMPKIN_MODEL }}
          fallback_model: ${{ secrets.BUMPKIN_FALLBACK_MODEL || '' }}
          models_endpoint: ${{ secrets.BUMPKIN_MODELS_ENDPOINT }}
          models_token: ${{ secrets.MODELS_TOKEN }}
          request_timeout: "45"
          model_call_min_interval_ms: "4000"

      - uses: actions/upload-artifact@v4
        with:
          name: bumpkin-release-notes
          path: ${{ steps.bumpkin.outputs.release_notes_path }}
```

## What you get back

For each release run, Bumpkin returns:

- the previous tag
- the proposed next tag
- the release type
- the included PR count
- a release notes artifact
- a run summary with `Why this bump`, versioning context, and key evidence

## Release modes

- `release_preview` builds the release plan and notes without publishing.
- `release_publish` creates the tag and GitHub Release.
- `NO_BUMP` means no release is needed.
- `needs_review` means the batch should be reviewed before publishing.

## Maintainer flow

From the Actions tab:

1. run `Bumpkin Release`
2. choose `release_preview`
3. inspect the release notes artifact and summary
4. run it again with `release_publish` when the preview looks right
5. use `base_tag` when you want to preview from a specific release boundary

## More

- [ROADMAP.md](ROADMAP.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [CHANGELOG.md](CHANGELOG.md)
