# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a blank starting point. Keep the root limited to
project configuration and top-level documentation. As the project takes shape,
use a predictable layout:

- `src/` for application or library source code.
- `tests/` for automated tests, mirroring `src/` where practical.
- `docs/` for user-facing or architectural documentation.
- `assets/` for static, non-code resources.
- `scripts/` for repeatable development and maintenance tasks.

Avoid placing generated output, local caches, credentials, or one-off scratch
files under version control. Document any intentional deviation from this
layout in the relevant directory's README.

## Build, Test, and Development Commands

No build system or package manifest has been committed yet. When one is added,
record the canonical commands in `README.md` and keep them deterministic. A
typical interface should include commands equivalent to:

```sh
# install dependencies
# run the application locally
# run the full test suite
# run formatter and linter checks
```

Prefer a single documented command per task (for example, `npm test` or
`make test`) over manual multi-step instructions. Run formatting, linting, and
tests before requesting review.

## Coding Style & Naming Conventions

Follow the formatter and linter configured for the chosen language; do not
hand-format files that a formatter owns. Use 2 spaces for JSON, YAML, and
Markdown nesting unless the language's formatter specifies otherwise. Name
directories and ordinary files in lowercase kebab-case (for example,
`request-parser.ts`); use the language's conventional casing for symbols.

Keep modules focused, avoid unrelated refactors in the same change, and add
comments only where intent is not apparent from the code.

## Testing Guidelines

Place tests in `tests/` or beside their module when the selected framework
expects co-located tests. Use descriptive test names that state behavior, such
as `rejects an expired access token`. Cover new behavior, boundary cases, and
fixed regressions. Do not lower coverage thresholds without an explicit reason
in the pull request.

## Commit & Pull Request Guidelines

There is no Git history yet, so adopt concise imperative commit subjects, such
as `Add token validation`. Keep commits small and independently reviewable.
Pull requests should explain the change and its motivation, link related
issues, list validation performed, and include screenshots for user-interface
changes. Call out configuration, migration, or security implications clearly.
