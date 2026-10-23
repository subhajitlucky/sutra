# Security

## Reporting a vulnerability

Email **subhajitpradhan310@gmail.com** with the details. Please do not open a
public issue for an unpatched vulnerability.

## Scope

- The SUTRA parser, interpreter, runtime, HTTP transport, signing, and encrypted
  messages.
- The optional `crypto` extra, which uses `cryptography`.
- Local key and state storage under `~/.sutra/` by default. Protect that
  directory; signing keys are stored on disk.

## Supported versions

Security fixes target the latest `0.10.x` release.
