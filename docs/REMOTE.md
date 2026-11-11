# Reaching a local daemon from a remote Hermes

The daemon binds to `127.0.0.1` by default. If Hermes runs on another machine,
put the two ends on a private network. Never expose the daemon port directly to
the public internet.

## Tailscale (recommended)

On the local machine:

```bash
tailscale ip -4                     # e.g. 100.101.102.103
hermes sidecar serve --host 100.101.102.103 --port 8765
```

On the remote:

```bash
hermes config set plugins.entries.sidecar.settings.url http://100.101.102.103:8765
```

Tailscale encrypts the link. Restrict access with a tailnet ACL if other devices
share the tailnet. If you use Tailscale Serve for HTTPS, point the URL at the
HTTPS name instead.

## SSH tunnel

From the **remote** machine, open a local forward to the local machine's SSH
server:

```bash
ssh -N -L 8765:127.0.0.1:8765 you@your-laptop
```

Then leave the remote URL at `http://127.0.0.1:8765`. The tunnel is encrypted and
the daemon never listens on a public interface.

Alternative, from the **local** machine, a remote forward:

```bash
ssh -N -R 8765:127.0.0.1:8765 you@remote-vps
```

The remote's `127.0.0.1:8765` now reaches the local daemon.

## HTTPS reverse proxy

If you need HTTPS without a tunnel, terminate TLS with Caddy or nginx in front of
the loopback daemon and set the URL to the HTTPS name. Keep the daemon itself on
loopback. The plugin rejects non-HTTP(S) URLs but does not validate certificates
beyond Python's standard `urllib` checks.

## Checklist

- [ ] Daemon bound to loopback or a private interface.
- [ ] URL uses a private network or HTTPS.
- [ ] Token stored in the remote profile or `SIDECAR_TOKEN`, not in shell history.
- [ ] `hermes sidecar status` shows `Daemon reachable`.
- [ ] `hermes sidecar test` passes.
- [ ] The local approval prompt is visible when a command needs it.
- [ ] The local audit log is where you expect it (`hermes sidecar log --local`).
