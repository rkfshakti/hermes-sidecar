# Security

Sidecar lets a remote Hermes Agent run commands on your local machine. That is a
deliberately powerful capability, so the trust model is small and explicit.

## What Sidecar is

- A **consent gate**: by default, a command that is not a side-effect-free
  read-only command waits for a person at the local keyboard.
- A **transport**: one command per authenticated HTTP request, no shell exposed
  to the remote, no persistent remote session.
- An **audit log**: local metadata for every decision, rotated and capped.

## What it is not

- Not an OS sandbox. An approved command runs with your user's privileges and can
  read anything you can read. Use Glassbox, a container, or a separate user/VM
  when you need kernel enforcement or isolation.
- Not a defense against a compromised local account or a kernel exploit.
- Not a public service. Bind to loopback, or put it behind Tailscale/SSH. The
  token is a bearer credential; plain HTTP on a non-loopback address sends it in
  cleartext.

## Controls

| Control | Behavior |
|---|---|
| Pairing token | 32 random bytes, mode `0600`, constant-time compare, required on every request. |
| Bind address | `127.0.0.1` by default. Non-loopback prints a warning. |
| Approval | `ask` by default; no TTY means deny. `allow` and `read-only` are explicit local choices. |
| Deny list | `sudo`, destructive root/home deletes, filesystem formats, disk erase, power control, launchd, Apple Events, keychain access, download-to-shell, outbound network shells, history clearing. |
| Workspace | Requests whose cwd is outside the local workspace are denied unless the operator explicitly opts in. |
| Environment | Only `PATH`, `HOME`, `USER`, `SHELL`, `LANG`, `TERM`, `TMPDIR`; provider keys and `SSH_AUTH_SOCK` are excluded. |
| Output | Capped at 2 MB (head/tail with a marker); process group killed on timeout. |
| Audit | Local JSONL, mode `0600`, 5 MB cap + one rotation; command text redacted for common secret shapes; output not stored. |
| Concurrency | Bounded semaphore; excess requests get HTTP 429. |

## Reporting

Open a private security advisory on the repository, or email the maintainer
listed in `plugin.yaml`. Please include the version, the platform, and a minimal
reproduction. Do not include real secrets or tokens.
