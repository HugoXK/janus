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

CI runs lint and tests. Security scanning is planned for V1.1.
