# Sidecar — Hermes Agent Plugin Hackathon submission

**Status: catalog PR is open. Two manual steps remain: post the demo on X, then submit the form.**

| Item | Value |
|---|---|
| Plugin | **Sidecar** — remote brain, local hands |
| Repo | https://github.com/rkfshakti/hermes-sidecar |
| Catalog PR | https://github.com/NousResearch/hermes-agent/pull/153541 |
| Pinned SHA | `2a14649b57c6f267fbdcb859ac35957a61e0ee0f` |
| Demo video | `video/sidecar-demo.mp4` (82.0 s, 1200×900, narrated) |
| Silent cut | `video/sidecar-demo-silent.mp4` (same footage, no voiceover) |
| Thumbnail | `video/slides/01-title.png` |
| X post (to publish) | _add the URL here after posting_ |
| Form | https://form.typeform.com/to/FwJLvOln |
| Deadline | **5:00 PM EST, 11 Nov 2026** = **3:30 AM IST, 12 Nov 2026** |

---

## 1. Post the demo on X

1. Open X and create a new post.
2. Attach `video/sidecar-demo.mp4` (82 s, narrated). Use
   `video/slides/01-title.png` as the thumbnail.
3. Paste this short version (fits the 280-character limit):

   > Sidecar gives @NousResearch Hermes a split runtime: the agent keeps its cloud skills and memory, while terminal and file tools run on your laptop through a paired daemon, a local approval prompt, and an audit log. Remote brain, local hands. #HermesAgent

   Longer version if your account allows it:

   > Your Hermes agent lives on a VPS with your skills and memory — but your workspace is on your laptop. Sidecar splits the runtime, not the trust: a paired local daemon runs each terminal and file command on your machine, asks you before anything risky, blocks privilege escalation and Apple Events, sanitizes the environment, and writes a local audit log. `hermes sidecar verify` proves the bridge. Built for the @NousResearch Hermes Agent Plugin Hackathon. #HermesAgent

4. **Tag `@NousResearch` in the post.** This is an explicit entry requirement.
5. Copy the post URL into the form and into the table above.
6. Reply to your own post with the links so the main post stays clean:

   > Repo: github.com/rkfshakti/hermes-sidecar
   > Catalog PR: github.com/NousResearch/hermes-agent/pull/153541

Pre-filled X compose link (text only; attach the video in the composer):

```
https://x.com/intent/post?text=Sidecar%20gives%20%40NousResearch%20Hermes%20a%20split%20runtime%3A%20the%20agent%20keeps%20its%20cloud%20skills%20and%20memory%2C%20while%20terminal%20and%20file%20tools%20run%20on%20your%20laptop%20through%20a%20paired%20daemon%2C%20a%20local%20approval%20prompt%2C%20and%20an%20audit%20log.%20Remote%20brain%2C%20local%20hands.%20%23HermesAgent
```

**Demo storyboard (already in the video):**

- Title: Sidecar — remote brain, local hands.
- Problem: the agent has skills and memory; it does not have your laptop.
- The split: remote Hermes (brain) ⇄ paired local daemon (hands).
- Live terminal: `pwd` → `ls` → `cat` → write a file → read it back →
  Apple Events attempt denied; four local approval prompts.
- Boundary: token, deny list, approval, sanitized env, audit, not a sandbox.
- Verify: eight checks, 44 tests, zero dependencies.
- CTA: repo + install + verify.

**Voiceover script** (the video uses a synthetic Samantha voice; re-record if you prefer):

> Hermes is at its best when it lives on a server with your skills and your
> memory. But the work is on your laptop: the files, the local services, the
> credentials that never leave the machine. SSH just moves the command to the
> wrong machine. Copying secrets to the VPS is worse. Sidecar splits the runtime,
> not the trust. The remote Hermes keeps the brain; a paired local daemon is the
> hands. Every terminal and file-tool command travels over an authenticated
> connection, one command at a time. By default, anything that is not a harmless
> read-only command waits for you. You see the exact command, and you approve or
> deny it. A deny list stops privilege escalation, root deletes, Apple Events,
> keychain access and download-to-shell. The local command gets a sanitized
> environment: no provider keys, no SSH agent. Every decision is written to a
> local audit log. Here is the real demo: a remote brain lists the local
> workspace, reads a local file, writes a new one, and tries an Apple Events
> escape hatch. The first four commands wait for approval on this Mac; the last
> is denied outright. The remote agent only receives the output. Verify it with
> `hermes sidecar verify`: eight checks, one command, forty-four tests, and zero
> Python dependencies. Remote brain, local hands. Sidecar, for the Hermes Agent
> Plugin Hackathon.

---

## 2. Submit the Typeform (manual)

Open https://form.typeform.com/to/FwJLvOln and fill:

| Field | Value |
|---|---|
| **Plugin Title** | `Sidecar` |
| **Plugin Description** | `Remote brain, local hands. A paired execution backend that lets a remote Hermes run terminal and file tools on your local machine, with a local approval prompt, a deny list, a sanitized environment, and an audit log.` |
| **Email Address** | `rkfshakti@gmail.com` (change if you prefer another) |
| **Discord Username** | *fill in your Nous Research Discord username* |
| **X Demo Post Link** | *paste the published post URL* |
| **GitHub PR Link** | `https://github.com/NousResearch/hermes-agent/pull/153541` |

The thank-you screen says winners are posted from `@nousresearch` after the
deadline. No separate developer sign-in is required beyond GitHub (for the PR)
and X (for the demo).

---

## 3. After submitting

- **CI gate:** the PR workflows are currently blocked on the maintainer
  approval gate because this is a fork contribution. A maintainer must approve
  the workflow run. A polite comment is already on the PR. If you are in the
  Nous Research Discord, mention the PR and ask for an approval.
- **Catalog review:** the entry is one file (`plugin-catalog/sidecar.yaml`) and
  pins the exact SHA above. The plugin repo's `tests` workflow is green at that
  SHA.
- **PR slot cap:** this repository allows 5 concurrent open PRs for accounts
  without write access. To open #153541, **#67426** was closed temporarily
  (the branch is intact; reopen it when a slot frees). Current open PRs:
  #153541, #153483, #125611, #125593, #92402.
- **Reopening later:** `gh pr reopen 67426 --repo NousResearch/hermes-agent`.

---

## 4. Sanity check

- [x] Catalog PR open: https://github.com/NousResearch/hermes-agent/pull/153541
- [x] One catalog file, pinned SHA `2a14649b57c6f267fbdcb859ac35957a61e0ee0f`
- [x] `requires_hermes` matches in `plugin.yaml` and the catalog entry (`>=0.22.3`)
- [x] `hermes plugins validate . --install-deps` passes at the pinned SHA
- [x] `hermes plugins doctor . --ci` passes
- [x] 44/44 pytest tests pass at the pinned SHA (live daemon/BaseEnvironment
      integration included)
- [x] `hermes sidecar verify` 8/8
- [x] `hermes sidecar demo` all checks pass
- [x] Pinned-source clone validates at the exact SHA
- [x] Plugin repo tests workflow green at the pinned SHA
- [x] Demo video is 82.0 s (< 90 s), shows the plugin working
- [ ] X post published and tagged `@NousResearch`
- [ ] Typeform submitted with both links
- [ ] Maintainer approved the `action_required` workflow runs

---

## 5. Useful links

- Plugin developer guide: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
- Catalog submission guide: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission
- Hackathon announcement: https://x.com/NousResearch/status/2118094256438936062
- Issue #18715 (split runtime): https://github.com/NousResearch/hermes-agent/issues/18715
- Nous Research Discord: https://discord.gg/NousResearch
