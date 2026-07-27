# Contributing

Thanks for your interest in ARIA. Contributions of all kinds are welcome —
issues, bug reports, documentation improvements, and pull requests.

## Reporting issues

Use GitHub Issues for bug reports and feature requests. For security
vulnerabilities, follow [SECURITY.md](SECURITY.md) instead — do **not** open
a public issue.

When reporting a bug, please include:

- A clear description of the expected vs. observed behavior.
- Reproduction steps (the smaller the repro, the better).
- Versions: Node, Python, AWS CDK, and your AWS region.
- Relevant logs or stack traces with sensitive values redacted.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Make focused changes — one logical change per PR.
3. Keep diffs small. Add tests where it makes sense
   (`backend/tests/`, `infra/tests/`).
4. Run the local checks before pushing:
   - Backend: `cd backend && python -m pytest tests/ -v`
   - Infra: `cd infra && npm run build`
   - Frontend: `cd frontend && npm run build`
5. Avoid committing generated artifacts (`dist/`, `cdk.out/`, `node_modules/`)
   or any local secrets (`.env`, `cdk.context.json`).
6. Open a PR with a clear title and description. Link any related issue.

## Pre-commit checks

This repo ships a [pre-commit](https://pre-commit.com/) config that runs the
same security scanners used in CI (gitleaks, bandit, semgrep, checkov) plus a
license-header check. Install it once after cloning:

```bash
pip install pre-commit
pre-commit install
```

The hooks then run automatically on every `git commit`. To run them against the
whole repo on demand:

```bash
pre-commit run --all-files
```

The tools are pinned in [`.pre-commit-config.yaml`](.pre-commit-config.yaml);
`bandit` reads the repo's `.bandit` config and `gitleaks` reads `.gitleaks.toml`.

## Code style

- Match the existing style in each language. Keep changes minimal.
- New source files need the MIT-0 license header. Run
  `python utilities/scripts/add_license_headers.py` to add it (the pre-commit
  `license-headers` hook enforces this).
- Don't add new dependencies without a clear reason.
- Don't introduce new top-level files (READMEs, design docs) unless asked
  in the issue or PR thread.

## Licensing

By contributing, you agree that your contributions will be licensed under the
[MIT-0 License](LICENSE).
