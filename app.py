"""
Udhaar Cashflow Brain — backend  (FINAL)
========================================
  1. /dashboard          live merchant dashboard, speaks aloud on its own
  2. /whatsapp/send      real delivery (freeform, or an approved template)
  3. /statement/generate PDF udhaar statement
  4. /voice/say          Hindi TTS for the Soundbox
 
Deploy:  uvicorn app:app --host 0.0.0.0 --port $PORT
 
Environment variables (all optional — the service degrades gracefully):
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_WHATSAPP_FROM   e.g. whatsapp:+17372508034
  TWILIO_CONTENT_SID     set ONLY if your sandbox requires an approved
                         template; the template must be a single {{1}} variable
"""
 
import io
import os
import json
from datetime import datetime, timedelta, timezone
 
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
 
IST = timezone(timedelta(hours=5, minutes=30))
 
app = FastAPI(title="Udhaar Cashflow Brain")
 
# --------------------------------------------------------------------------
# STATE
# --------------------------------------------------------------------------
 
STATE = {
    "merchant": "Sharma General Store",
    "updated_at": None,
    "total_outstanding": 0,
    "customers_with_dues": 0,
    "concentration_pct": 0,
    "concentration_amount": 0,
    "collections_queue": [],
    "reconciliation": None,
    "cash_position": None,
    "pending_approval": None,
    "last_spoken": "",
    "activity": [],
    "messages_sent": [],
}
 
 
def _now():
    return datetime.now(IST)
 
 
def _stamp():
    STATE["updated_at"] = _now().strftime("%H:%M:%S IST")
 
 
def _log(agent, text, kind="info"):
    STATE["activity"].insert(0, {
        "agent": agent,
        "text": text,
        "kind": kind,                       # info | success | warn | block
        "at": _now().strftime("%H:%M:%S"),
    })
    del STATE["activity"][40:]
 
 
# --------------------------------------------------------------------------
# WRITE API — Phinite tools call these
# --------------------------------------------------------------------------
 
@app.post("/api/update")
async def update(request: Request):
    body = await request.json()
    agent = body.pop("_agent", "system")
    note = body.pop("_note", None)
    kind = body.pop("_kind", "info")
 
    for key, value in body.items():
        if key in STATE:
            STATE[key] = value
 
    if note:
        _log(agent, note, kind)
    _stamp()
    return {"ok": True, "updated_at": STATE["updated_at"]}
 
 
@app.post("/api/event")
async def event(request: Request):
    body = await request.json()
    _log(body.get("agent", "system"),
         body.get("text", ""),
         body.get("kind", "info"))
    _stamp()
    return {"ok": True}
 
 
@app.get("/api/state")
async def state():
    return JSONResponse(STATE)
 
 
@app.post("/api/reset")
async def reset():
    STATE.update({
        "total_outstanding": 0, "customers_with_dues": 0,
        "concentration_pct": 0, "concentration_amount": 0,
        "collections_queue": [], "reconciliation": None,
        "cash_position": None, "pending_approval": None,
        "last_spoken": "", "activity": [], "messages_sent": [],
    })
    _stamp()
    return {"ok": True}
 
 
# --------------------------------------------------------------------------
# 2 · WHATSAPP
# --------------------------------------------------------------------------
 
@app.post("/whatsapp/send")
async def whatsapp_send(request: Request):
    body = await request.json()
    to = (body.get("to") or "").strip()
    text = (body.get("message") or "").strip()
    customer = body.get("customer_name", "")
 
    if not to or not text:
        return {"success": False, "error": "to and message are required"}
 
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    content_sid = os.getenv("TWILIO_CONTENT_SID")
 
    def _record(status, extra=None):
        STATE["messages_sent"].insert(0, {
            "to": to, "customer": customer, "text": text,
            "at": _now().strftime("%H:%M IST"), "status": status,
        })
        _log("WhatsApp", f"{status.title()} — {customer or to}",
             "success" if status == "delivered" else "warn")
        _stamp()
        return {"success": True, "status": status, **(extra or {})}
 
    if not sid or not token:
        return _record("simulated", {"note": "No Twilio credentials set."})
 
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        dest = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
 
        if content_sid:
            # sandbox requires an approved template — pass the agent's own
            # wording through as variable 1
            msg = client.messages.create(
                from_=sender, to=dest,
                content_sid=content_sid,
                content_variables=json.dumps({"1": text}),
            )
        else:
            msg = client.messages.create(from_=sender, to=dest, body=text)
 
        return _record("delivered", {"sid": msg.sid, "delivered": True})
 
    except Exception as exc:
        # a Twilio failure must never break the demo — record and carry on
        return _record("logged", {"delivered": False, "error": str(exc)})
 
 
# --------------------------------------------------------------------------
# 3 · PDF STATEMENT
# --------------------------------------------------------------------------
 
@app.post("/statement/generate")
async def statement(request: Request):
    body = await request.json()
    name = body.get("customer_name", "Customer")
    entries = body.get("entries", [])
    open_amount = body.get("open_amount", 0)
    link = body.get("payment_link", "")
 
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
 
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    ss = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=ss["Title"], fontSize=17, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9,
                         textColor=colors.HexColor("#666"))
 
    flow = [
        Paragraph(STATE["merchant"], h),
        Paragraph("Udhaar Statement", sub),
        Spacer(1, 10 * mm),
        Paragraph(f"<b>{name}</b>", ss["Normal"]),
        Paragraph(f"Generated {_now().strftime('%d %b %Y, %H:%M IST')}", sub),
        Spacer(1, 6 * mm),
    ]
 
    rows = [["Date", "Item", "Amount", "Status"]]
    for e in entries[:40]:
        rows.append([
            e.get("date", ""),
            (e.get("notes") or "-")[:28],
            f"Rs {e.get('amount', 0):,}",
            e.get("status", ""),
        ])
 
    table = Table(rows, colWidths=[28 * mm, 70 * mm, 32 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1c2b4d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f6fa")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5d9e2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow += [table, Spacer(1, 8 * mm)]
 
    total = Table([["Total outstanding", f"Rs {open_amount:,}"]],
                  colWidths=[130 * mm, 28 * mm])
    total.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf0f7")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#e22a90")),
    ]))
    flow.append(total)
 
    if link:
        flow += [Spacer(1, 8 * mm),
                 Paragraph(f"Pay online: <b>{link}</b>", ss["Normal"])]
 
    flow += [Spacer(1, 12 * mm),
             Paragraph("Generated by Udhaar Cashflow Brain. "
                       "Please verify against your own records.", sub)]
 
    doc.build(flow)
    buf.seek(0)
    _log("Statement", f"PDF statement generated for {name}", "success")
    _stamp()
    fname = f"udhaar-{name.replace(' ', '-').lower()}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'})
 
 
# --------------------------------------------------------------------------
# 4 · VOICE
# --------------------------------------------------------------------------
 
@app.post("/voice/say")
async def voice_say(request: Request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    lang = body.get("lang", "hi")
    silent = bool(body.get("silent"))     # dashboard replays without re-logging
 
    if not text:
        return {"success": False, "error": "text is required"}
 
    if not silent:
        STATE["last_spoken"] = text
        _log("Soundbox", text[:90], "success")
        _stamp()
 
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text, lang=lang).write_to_fp(buf)
        buf.seek(0)
        return StreamingResponse(buf, media_type="audio/mpeg")
    except Exception as exc:
        return {"success": True, "audio": False, "error": str(exc),
                "note": "Text logged to dashboard; audio unavailable."}
 
 
@app.get("/voice/latest")
async def voice_latest():
    return {"text": STATE.get("last_spoken", "")}
 
 
# --------------------------------------------------------------------------
# 1 · DASHBOARD
# --------------------------------------------------------------------------
 
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)
 
 
DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Udhaar Cashflow Brain</title>
<style>
  :root{
    --navy:#1c2b4d; --blue:#3c5ba4; --purple:#52289f; --magenta:#e22a90;
    --bg:#0d1424; --card:#141d33; --line:#243052;
    --txt:#e8ecf5; --mut:#8492b4; --ok:#35c48a; --warn:#f2b13c; --bad:#ef5a6f;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--txt);
       font:15px/1.5 ui-sans-serif,system-ui,'Segoe UI',sans-serif;padding:22px}
  header{display:flex;align-items:center;gap:14px;margin-bottom:20px;flex-wrap:wrap}
  h1{font-size:21px;font-weight:650;
     background:linear-gradient(90deg,#3c5ba4,#52289f 34%,#e22a90);
     -webkit-background-clip:text;background-clip:text;color:transparent}
  .live{font-size:12px;color:var(--mut)}
  .dot{display:inline-block;width:7px;height:7px;border-radius:50%;
       background:var(--ok);margin-right:5px;animation:p 1.6s infinite}
  @keyframes p{50%{opacity:.25}}
  #armed{font-size:11px;border:1px solid var(--line);border-radius:20px;
         padding:3px 11px;color:var(--mut);cursor:pointer;background:none;
         font-family:inherit}
  #armed.on{color:var(--ok);border-color:#1e5c44}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}
  .card{background:var(--card);border:1px solid var(--line);
        border-radius:13px;padding:16px}
  .card h2{font-size:11px;letter-spacing:.9px;text-transform:uppercase;
           color:var(--mut);font-weight:600;margin-bottom:12px}
  .big{font-size:31px;font-weight:680;letter-spacing:-.5px}
  .sm{font-size:12.5px;color:var(--mut);margin-top:3px}
  .bar{height:7px;border-radius:4px;background:#1d2740;overflow:hidden;margin:11px 0 7px}
  .bar i{display:block;height:100%;transition:width .6s ease;
         background:linear-gradient(90deg,var(--purple),var(--magenta))}
  .row{display:flex;justify-content:space-between;gap:10px;
       padding:9px 0;border-bottom:1px solid var(--line);font-size:13.5px}
  .row:last-child{border:0}
  .nm{font-weight:560}
  .meta{font-size:11.5px;color:var(--mut)}
  .amt{font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}
  .tag{font-size:10px;padding:2px 7px;border-radius:20px;font-weight:600;
       display:inline-block}
  .l1{background:#123a2c;color:var(--ok)} .l2{background:#153055;color:#6aa8e8}
  .l3{background:#41330f;color:var(--warn)} .l4{background:#451a22;color:var(--bad)}
  .feed{max-height:310px;overflow:auto}
  .ev{display:flex;gap:9px;padding:7px 0;font-size:12.5px;
      border-bottom:1px solid var(--line)}
  .ev b{color:var(--mut);font-weight:600;min-width:104px;font-size:11.5px}
  .k-success{color:var(--ok)} .k-warn{color:var(--warn)}
  .k-block{color:var(--bad)} .k-info{color:var(--txt)}
  .empty{color:var(--mut);font-size:13px;padding:14px 0;text-align:center}
  .speak{background:linear-gradient(135deg,#52289f22,#e22a9022);
         border:1px solid #52289f66;border-radius:10px;padding:13px;
         font-size:14px;line-height:1.55}
  .speak.playing{border-color:var(--magenta);box-shadow:0 0 0 3px #e22a9022}
  .pill{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;
        color:var(--mut);margin-top:9px}
</style></head><body>
 
<header>
  <h1>Udhaar Cashflow Brain</h1>
  <span class="live"><span class="dot"></span><span id="clock">waiting…</span></span>
  <button id="armed">🔇 click to enable sound</button>
</header>
 
<div class="grid">
  <div class="card">
    <h2>Total outstanding</h2>
    <div class="big" id="tot">₹0</div>
    <div class="sm" id="cnt">no data yet</div>
    <div class="bar"><i id="conc" style="width:0%"></i></div>
    <div class="sm" id="concTxt">concentration —</div>
  </div>
 
  <div class="card">
    <h2>Cash position · 30 days</h2>
    <div class="big" id="cash">—</div>
    <div class="sm" id="cashSub">not yet analysed</div>
    <div class="sm" id="verdict" style="margin-top:9px;color:var(--txt)"></div>
  </div>
 
  <div class="card">
    <h2>Last reconciliation</h2>
    <div class="big" id="cred">—</div>
    <div class="sm" id="recSub">no settlements processed</div>
    <div id="recDetail" style="margin-top:10px"></div>
  </div>
 
  <div class="card" style="grid-column:span 2">
    <h2>Collections queue</h2>
    <div id="queue"><div class="empty">Ask “kaun baaki hai” to build the queue</div></div>
  </div>
 
  <div class="card">
    <h2>Soundbox · last spoken</h2>
    <div class="speak" id="spoke">—</div>
    <div class="pill">🔊 plays on the counter device</div>
  </div>
 
  <div class="card" style="grid-column:span 2">
    <h2>Agent activity</h2>
    <div class="feed" id="feed"><div class="empty">No agent activity yet</div></div>
  </div>
 
  <div class="card">
    <h2>Messages sent</h2>
    <div id="msgs"><div class="empty">Nothing sent yet</div></div>
  </div>
</div>
 
<script>
const inr = n => '₹' + (n||0).toLocaleString('en-IN');
 
/* browsers block autoplay until the page is interacted with, so arm it once */
let armed = false;
const armBtn = document.getElementById('armed');
function arm(){
  if (armed) return;
  armed = true;
  armBtn.textContent = '🔊 sound on';
  armBtn.classList.add('on');
  new Audio().play().catch(()=>{});
}
armBtn.addEventListener('click', arm);
document.body.addEventListener('click', arm, {once:true});
 
function speak(text){
  if (!armed) return;
  const box = document.getElementById('spoke');
  box.classList.add('playing');
  fetch('/voice/say', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text: text, lang:'hi', silent:true})
  }).then(r => r.ok ? r.blob() : Promise.reject())
    .then(b => {
      const a = new Audio(URL.createObjectURL(b));
      a.onended = () => box.classList.remove('playing');
      return a.play();
    })
    .catch(() => box.classList.remove('playing'));
}
 
async function tick(){
  let s; try { s = await (await fetch('/api/state')).json(); } catch { return; }
 
  document.getElementById('clock').textContent = s.updated_at || 'waiting…';
  document.getElementById('tot').textContent = inr(s.total_outstanding);
  document.getElementById('cnt').textContent =
    s.customers_with_dues ? s.customers_with_dues + ' customers with open dues' : 'no data yet';
 
  const pct = s.concentration_pct || 0;
  document.getElementById('conc').style.width = Math.min(pct,100) + '%';
  document.getElementById('concTxt').textContent = pct
    ? `top 3 hold ${inr(s.concentration_amount)} — ${pct}% of everything owed`
    : 'concentration —';
 
  const c = s.cash_position;
  document.getElementById('cash').textContent = c ? inr(c.expected_30d) : '—';
  document.getElementById('cashSub').textContent = c
    ? 'realistically collectable in 30 days' : 'not yet analysed';
  document.getElementById('verdict').textContent = c ? (c.verdict || '') : '';
 
  const r = s.reconciliation;
  document.getElementById('cred').textContent = r ? inr(r.credited) : '—';
  document.getElementById('recSub').textContent = r
    ? `${r.matched||0} matched · ${r.partial||0} partial · ${r.unmatched||0} unmatched`
    : 'no settlements processed';
  document.getElementById('recDetail').innerHTML = (r && r.unmatched)
    ? `<div class="row" style="border:0"><span class="meta" style="color:var(--warn)">
       ⚠ ${r.unmatched} payment could not be matched — flagged, not guessed</span></div>` : '';
 
  const q = s.collections_queue || [];
  document.getElementById('queue').innerHTML = q.length ? q.map(x => `
    <div class="row">
      <div><div class="nm">${x.name}</div>
        <div class="meta">${x.days} days · reliability ${x.score}/100</div></div>
      <div style="text-align:right">
        <div class="amt">${inr(x.amount)}</div>
        <span class="tag l${x.level||1}">level ${x.level||1}</span></div>
    </div>`).join('')
    : '<div class="empty">Ask “kaun baaki hai” to build the queue</div>';
 
  const f = s.activity || [];
  document.getElementById('feed').innerHTML = f.length ? f.map(e => `
    <div class="ev"><b>${e.agent}</b>
      <span class="k-${e.kind}">${e.text}</span>
      <span class="meta" style="margin-left:auto">${e.at}</span></div>`).join('')
    : '<div class="empty">No agent activity yet</div>';
 
  const m = s.messages_sent || [];
  document.getElementById('msgs').innerHTML = m.length ? m.map(x => `
    <div class="row"><div><div class="nm">${x.customer||x.to}</div>
      <div class="meta">${x.text.slice(0,58)}…</div></div>
      <span class="meta">${x.status} · ${x.at}</span></div>`).join('')
    : '<div class="empty">Nothing sent yet</div>';
 
  /* speak only when the line is new */
  const spoken = s.last_spoken || '';
  const box = document.getElementById('spoke');
  box.textContent = spoken || '—';
  if (spoken && spoken !== window._lastSpoken) {
    window._lastSpoken = spoken;
    speak(spoken);
  }
}
tick(); setInterval(tick, 1500);
</script>
</body></html>"""