# Security

## Reporting

If you find a security issue, please do not open a public issue with exploit
details. Email the maintainer at `hugo2001xk@gmail.com` with a description and a
minimal reproduction.

## Scope

Janus is local-first research software. It does not execute trades and does not
store broker credentials in V1.

## Secrets

- Never commit `.env` files or API keys.
- Prefer environment variables or a local secret store.
- The repository ignores `.env`, `*.pem`, and `*.key`.

## Data

- Respect each provider's terms of service.
- Do not redistribute licensed market data.
- Cache politely and identify your client with a descriptive `User-Agent`.

## Dependencies

- **Python** is floor-constrained in `pyproject.toml` (`>=2.2` and friends) and
  there is no lockfile, so no resolved Python version is recorded anywhere.
  The SBOM's Python entries are therefore declared constraints, not pinned
  builds, and the dependency allowlist is the `[project] dependencies` plus
  `optional-dependencies` (`dev`, `mcp`, `data`) set.
- **npm** development dependencies are pinned by
  `dsh-plugin/package-lock.json` (lockfileVersion 3), and the SBOM records
  those resolved versions.
- **GitHub Actions** are pinned to major tags (`actions/checkout@v4`,
  `astral-sh/setup-uv@v3`, and so on).
- **Updates** are owned by dependabot (`.github/dependabot.yml`): pip at `/`,
  npm at `/dsh-plugin`, and GitHub Actions at `/`, weekly, with
  `open-pull-requests-limit: 5` per ecosystem. That is a ceiling, not the
  current number of open pull requests.
- **Scanning:** `gitleaks` is a blocking job and `pip-audit` runs as an
  advisory job (`continue-on-error: true`) in
  `.github/workflows/security.yml`.
- **Inventory:** `scripts/generate_sbom.py` writes a deterministic CycloneDX
  1.5 subset (`uv run python scripts/generate_sbom.py --output sbom.json`);
  CI uploads it as the advisory `sbom-cyclonedx` artifact.

See `docs/SECURITY-THREAT-MODEL.md` for the threat model and the honest status
of each control.
