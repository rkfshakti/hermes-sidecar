---
name: sidecar
description: Explain and operate the Sidecar split runtime — a remote Hermes whose terminal and file tools execute on the user's local machine through a paired, approval-gated daemon. Use when the user asks where a command ran, why a command was denied, how to inspect the local audit log, or how to work with a local workspace from a remote agent.
version: 1.0.0
metadata:
  hermes:
    tags: [remote, terminal, local, approval, audit]
---

# Sidecar

When `terminal.backend` is `sidecar`, this Hermes process is the **brain**; the
**hands** are a separate Sidecar daemon running on the user's local machine. The
agent's skills, memory, sessions and model configuration stay on the remote host.
Terminal, file, patch and search operations travel over the paired HTTP
connection and run locally.

## Ground rules

1. **Say where things run.** A `pwd`, `ls`, `read_file` or `write_file` result
   describes the user's local machine, not the server. Be explicit about that
   distinction whenever it matters.
2. **A denial is a decision, not a transient error.** When the local user denies a
   command, do not retry it verbatim, do not rephrase it to work around the policy,
   and do not look for another tool that performs the same write. Ask what they
   would prefer, or propose a narrower command.
3. **The local daemon owns the policy.** The approval mode, workspace, timeout and
   deny list are set on the local machine. Changing the remote plugin settings
   cannot loosen them. If a command is blocked by the workspace boundary, ask the
   user to restart the daemon with the right `--workspace` or to approve the
   specific path; do not edit the remote config to bypass it.
4. **Secrets stay local.** The daemon runs commands with a small environment that
   excludes provider keys and SSH agent sockets. Reading a credential file still
   requires the local user's approval; do not ask for it unless the task truly
   needs it, and explain why.
5. **Use the inspection tools instead of guessing.** `sidecar_status` reports the
   daemon, workspace and effective policy. `sidecar_audit` shows recent decisions
   and exit codes. Neither tool can approve a command or change the policy.

## Failure messages

- **Cannot reach the daemon** — the local machine is offline, the daemon is not
  running, or the tunnel/URL is wrong. Ask the user to run `hermes sidecar serve`
  locally and check `hermes sidecar status` on this side.
- **HTTP 401** — the pairing token changed. Ask the user to run
  `hermes sidecar pair` locally and update the remote token.
- **HTTP 403** — the local user denied the command or the deny list matched. Read
  the reason in the error; do not retry.
- **Timed out** — the local command exceeded its timeout, or the local person did
  not answer the approval prompt in time. The command may have been killed; check
  the audit before assuming it did not run.

## Limits

Sidecar is a consent and transport layer, not a sandbox. An approved command runs
with the local user's privileges. For kernel-enforced containment on macOS, pair
Sidecar with Glassbox and run the daemon on the same Mac. Do not claim that
Sidecar alone contains a malicious command.
