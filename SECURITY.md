# Security Policy

## Model

Atelier is a **local, single-user, loopback-only** tool. The server binds
`127.0.0.1` only and has **no authentication by design**. It is not built to be
exposed to a network, and you should never put it behind a public interface or a
reverse proxy that makes it reachable by other machines.

## Supported versions

Only the **latest release** is supported with security fixes.

## Reporting a vulnerability

If you find a vulnerability, please **do not** open a public issue. Instead:

- Open a [GitHub security advisory](https://github.com/bharathksunil/atelier/security/advisories/new), or
- Contact the maintainer via <https://bharathksunil.com>.

Please include reproduction steps and the affected version. You'll get a response
as soon as reasonably possible.
