# Security

This kit describes systems that may invoke powerful agents. Its worktree and
state mechanisms provide transactional isolation from ordinary failures; they
do not sandbox malicious code or a compromised model process.

## Required deployment posture

- Separate observer, builder, publisher, and deployer identities.
- Give each role only the credentials and paths it needs.
- Keep candidate builders away from production write credentials.
- Store secrets outside repositories, prompts, events, and run artifacts.
- Treat all model output, suggestions, and retrieved text as untrusted input.
- Require explicit human authorization for credential, spending, identity,
  security-policy, and irreversible production changes.
- Put an external deadman outside the ecosystem's host and delivery channel.

## Reporting a vulnerability

Do not open a public issue containing secrets or exploitable production
details. Use GitHub's private vulnerability reporting for this repository.
