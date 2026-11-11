#!/usr/bin/env python3
"""Generate the Sidecar demo slides as 1200x900 PNGs.

Quick Look renders the HTML to a 1200x1200 thumbnail; we crop the top 900px.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "slides"
OUT.mkdir(exist_ok=True)

CSS = """
* { box-sizing: border-box; }
html,body { margin:0; width:1200px; height:900px; overflow:hidden; }
body { zoom: 0.8533; font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif;
  color:#e8eef7; background:
  radial-gradient(1000px 650px at 82% -10%, rgba(56,189,248,.20), transparent 62%),
  radial-gradient(900px 600px at -10% 110%, rgba(167,139,250,.14), transparent 60%),
  #080c12; }
.grid { position:absolute; inset:0; opacity:.18; background-image:
  linear-gradient(rgba(148,163,184,.14) 1px, transparent 1px),
  linear-gradient(90deg, rgba(148,163,184,.14) 1px, transparent 1px);
  background-size: 60px 60px; mask-image: radial-gradient(circle at 50% 40%, black, transparent 78%); }
.wrap { position:relative; padding: 70px 80px; height:100%; width:1040px; max-width:1040px; box-sizing:content-box; display:flex; flex-direction:column; }
.kicker { color:#38bdf8; font-size:20px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
.title { font-size:92px; line-height:1.0; font-weight:800; letter-spacing:-.03em; margin:16px 0 18px; }
.title .accent { color:#38bdf8; }
.title .thin { color:#cbd5e1; }
.sub { font-size:34px; color:#d7e2ee; line-height:1.25; max-width:980px; font-weight:600; }
.lede { font-size:25px; color:#9fb0c5; line-height:1.42; max-width:900px; margin-top:14px; }
.foot { margin-top:auto; display:flex; justify-content:space-between; align-items:center; color:#7f8ea3; font-size:19px; }
.badge { display:inline-flex; align-items:center; gap:10px; padding:10px 16px; border:1px solid rgba(56,189,248,.38);
  background:rgba(56,189,248,.10); border-radius:999px; color:#bae6fd; font-size:18px; font-weight:600; }
h2 { font-size:54px; line-height:1.08; letter-spacing:-.02em; margin:10px 0 24px; width:1040px; max-width:1040px; }
h2 .accent { color:#38bdf8; }
p { font-size:27px; line-height:1.42; color:#b6c2d1; }
.cards { display:grid; grid-template-columns: 333px 333px 333px; gap:20px; margin-top:16px; width:1040px; }
.card { border:1px solid rgba(148,163,184,.20); background:rgba(15,23,42,.58); border-radius:20px; padding:24px 26px; min-width:0; overflow-wrap:anywhere; }
.card h3 { margin:0 0 8px; font-size:26px; color:#f1f5f9; }
.card p { margin:0; font-size:21px; line-height:1.4; color:#9fb0c5; }
.card .ico { font-size:30px; display:block; margin-bottom:10px; }
.split { display:grid; grid-template-columns: 450px 100px 450px; align-items:center; gap:15px; margin-top:14px; width:1040px; }
.box { border:1px solid rgba(148,163,184,.24); background:rgba(15,23,42,.62); border-radius:22px; padding:28px 30px; min-height:250px; }
.box.remote { border-color: rgba(56,189,248,.40); }
.box.local { border-color: rgba(167,139,250,.42); }
.box h3 { margin:0 0 10px; font-size:28px; color:#f8fafc; }
.box .tag { font-size:18px; letter-spacing:.12em; text-transform:uppercase; color:#7dd3fc; font-weight:700; }
.box.local .tag { color:#c4b5fd; }
.box ul { margin:12px 0 0; padding-left:20px; color:#a9b8ca; font-size:21px; line-height:1.55; }
.arrow { text-align:center; color:#7dd3fc; font-size:18px; line-height:1.4; font-weight:700; }
.arrow .line { font-size:38px; line-height:1; }
.quote { margin-top:auto; border-left:4px solid #38bdf8; padding:14px 22px; color:#cbd5e1; font-size:24px; font-style:italic; width:1040px; }
.checks { display:grid; grid-template-columns: 500px 500px; gap:12px 28px; margin-top:12px; width:1040px; }
.check { font-size:24px; color:#d5deea; }
.check .tick { color:#4ade80; font-weight:800; margin-right:10px; }
.code { margin-top:14px; border:1px solid rgba(148,163,184,.22); background:#05080d; border-radius:16px; padding:22px 26px; width:1040px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:22px; line-height:1.65; color:#d1fae5; }
.code .prompt { color:#38bdf8; }
.code .dim { color:#7f8ea3; }
.note { color:#8fa1b6; font-size:20px; margin-top:12px; }
.terminal-shot { width:100%; height:560px; object-fit:cover; object-position:top center; border-radius:18px;
  border:1px solid rgba(148,163,184,.26); background:#05080d; }
.links { margin-top:26px; display:flex; flex-direction:column; gap:14px; font-size:27px; color:#cbd5e1; }
.links code { color:#bae6fd; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:25px; }
"""


def page(body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=1200"><style>{CSS}</style></head>
<body><div class="grid"></div><div class="wrap">{body}</div></body></html>"""


SLIDES = {
    "01-title": page("""
      <div class="kicker">Hermes Agent Plugin Hackathon · 2026</div>
      <div class="title">HERMES<br><span class="accent">SIDECAR</span></div>
      <div class="sub">Remote brain. Local hands.</div>
      <div class="lede">A paired execution backend that lets a remote Hermes use your local
      terminal, files, and code — with a local approval prompt and an audit trail.</div>
      <div style="margin-top:30px"><span class="badge">◆ local approval &nbsp;·&nbsp; sanitized env &nbsp;·&nbsp; zero dependencies</span></div>
      <div class="foot"><span>rkfshakti / hermes-sidecar</span><span>MIT · 2026</span></div>
    """),
    "02-problem": page("""
      <div class="kicker">Why</div>
      <h2>The agent has your skills and memory.<br><span class="accent">It does not have your laptop.</span></h2>
      <div class="cards">
        <div class="card"><span class="ico">🧠</span><h3>Remote Hermes</h3><p>Skills, memory, sessions, model configuration and a persistent place to run.</p></div>
        <div class="card"><span class="ico">💻</span><h3>The workspace</h3><p>Files, local services, internal network, build tools and the credentials that never leave the machine.</p></div>
        <div class="card"><span class="ico">🔀</span><h3>SSH moves the problem</h3><p>The command still runs on the wrong machine. Copying secrets to the VPS is worse.</p></div>
      </div>
      <div class="quote">“Remote brain, local hands.” — hermes-agent #18715, the top-voted split-runtime request</div>
    """),
    "03-split": page("""
      <div class="kicker">The split</div>
      <h2>Split the runtime, <span class="accent">not the trust.</span></h2>
      <div class="split">
        <div class="box remote"><div class="tag">Remote Hermes</div><h3>the brain</h3>
          <ul><li>model · skills · memory</li><li>sessions · provider config</li><li>terminal.backend: sidecar</li></ul></div>
        <div class="arrow"><div class="line">⇄</div>paired HTTP<br>bearer token</div>
        <div class="box local"><div class="tag">Local Sidecar</div><h3>the hands</h3>
          <ul><li>approval prompt</li><li>workspace + sanitized env</li><li>local audit log</li></ul></div>
      </div>
      <p style="margin-top:22px">The remote agent never gets a shell. It gets <b style="color:#f8fafc">one command at a time</b>, and you decide.</p>
    """),
    "04-demo": page("""
      <div class="kicker">Live demo</div>
      <h2 style="margin-bottom:12px">A remote brain writes a file <span class="accent">on this Mac.</span></h2>
      <img class="terminal-shot" src="file://__DEMO_FRAME__">
      <div class="note">Real terminal · real approval prompt · real audit. The remote agent only receives the output.</div>
    """),
    "05-security": page("""
      <div class="kicker">The boundary</div>
      <h2>Every command is <span class="accent">a decision.</span></h2>
      <div class="cards">
        <div class="card"><span class="ico">🔑</span><h3>Pairing token</h3><p>32 random bytes, mode 0600, constant-time compare, required on every request.</p></div>
        <div class="card"><span class="ico">⛔</span><h3>Local deny list</h3><p>sudo, root deletes, disk erase, Apple Events, keychain access, download-to-shell, outbound shells.</p></div>
        <div class="card"><span class="ico">✋</span><h3>Approval prompt</h3><p>Anything that is not side-effect-free waits for a person. No TTY means deny.</p></div>
        <div class="card"><span class="ico">🧼</span><h3>Sanitized env</h3><p>Provider keys and SSH agent sockets are not passed to the local command.</p></div>
        <div class="card"><span class="ico">🧾</span><h3>Audit log</h3><p>Command, cwd, decision, exit code and duration. Local only; output is never stored.</p></div>
        <div class="card"><span class="ico">🛡️</span><h3>Not a sandbox</h3><p>Approved commands run as you. Pair with Glassbox when you need kernel enforcement.</p></div>
      </div>
    """),
    "06-verify": page("""
      <div class="kicker">Trust, but verify</div>
      <h2>Eight checks. <span class="accent">One command.</span></h2>
      <div class="code"><span class="prompt">$</span> hermes sidecar verify<br>
      <span class="dim">✓ daemon health &nbsp; ✓ token accepted &nbsp; ✓ wrong token rejected<br>
      ✓ exit code preserved &nbsp; ✓ deny list blocks GUI automation<br>
      ✓ workspace escape blocked &nbsp; ✓ timeout enforced &nbsp; ✓ audit recorded</span></div>
      <div class="checks">
        <div class="check"><span class="tick">✓</span> 42 tests, zero Python dependencies</div>
        <div class="check"><span class="tick">✓</span> 8-check self-test, local ephemeral daemon</div>
        <div class="check"><span class="tick">✓</span> terminal, file, patch, search, execute_code</div>
        <div class="check"><span class="tick">✓</span> catalog PR pinned by SHA</div>
      </div>
      <div class="code" style="margin-top:18px"><span class="prompt">$</span> hermes plugins install rkfshakti/hermes-sidecar<br>
      <span class="prompt">$</span> hermes sidecar serve --workspace ~/Projects/acme</div>
    """),
    "07-cta": page("""
      <div class="kicker">Remote brain. Local hands.</div>
      <div class="title" style="font-size:100px">Sidecar</div>
      <div class="sub">Let the agent live where your skills and memory live.<br>Let the work happen where your workspace lives.</div>
      <div class="links">
        <span>Repo &nbsp; <code>github.com/rkfshakti/hermes-sidecar</code></span>
        <span>Install &nbsp; <code>hermes plugins install rkfshakti/hermes-sidecar</code></span>
        <span>Verify &nbsp; <code>hermes sidecar verify</code></span>
      </div>
      <div class="foot"><span>Hermes Agent Plugin Hackathon · 2026</span><span>MIT</span></div>
    """),
}


def render(name: str, html: str) -> Path:
    import uuid

    token = uuid.uuid4().hex[:8]
    src = OUT / f"_{name}-{token}.html"
    src.write_text(html, encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["qlmanage", "-t", "-s", "1200", "-o", tmp, str(src)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            thumbs = list(Path(tmp).glob("*.png"))
            if not thumbs:
                raise SystemExit(f"no thumbnail for {name}")
            image = Image.open(thumbs[0]).convert("RGB")
            # Quick Look renders 1200x1200; the slide is the top 1200x900.
            image = image.crop((0, 0, 1200, 900))
            dest = OUT / f"{name}.png"
            image.save(dest)
            return dest
    finally:
        src.unlink(missing_ok=True)


def main() -> None:
    frame_src = HERE.parent / "demo" / "demo.gif"
    frame = HERE / "demo-frame.png"
    if frame_src.exists():
        image = Image.open(frame_src)
        image.seek(min(10, image.n_frames - 1))
        image.convert("RGB").save(frame)
    for name, html in SLIDES.items():
        if "__DEMO_FRAME__" in html:
            html = html.replace("__DEMO_FRAME__", str(frame))
        path = render(name, html)
        print(path)


if __name__ == "__main__":
    main()
