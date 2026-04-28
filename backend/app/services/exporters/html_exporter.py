"""HTML exporter — single-file interactive web viewer.

Renders the spec bundle as a self-contained .html file:
    • Tabs:  Overview / Specification / Cost / Manufacturing / MEP / Drawings
    • <model-viewer> web component slot for an inline 3D preview
      (the GLTF bytes can be dropped next to the file or a URL passed in;
      no local network call is required to open the file)
    • Cost-calculator widget — reactive sliders re-run the BRD walk
      (manufacturer margin / designer margin / retail markup /
      customization premium) entirely client-side
    • Customization options block — shows which BRD bands the studio
      can move within
    • A shareable link section for client review

No external assets are inlined except a single CDN script for
<model-viewer>. The HTML opens in any modern browser without a build
step.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


def _e(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _money(v: object) -> str:
    if v in (None, "", "—"):
        return "—"
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return _e(v)


def _payload(spec: dict, graph: dict) -> dict:
    """The JSON the client-side script reads to drive the calculator."""
    meta = spec.get("meta") or {}
    cost = spec.get("cost") or {}
    totals = cost.get("totals") or {}
    return {
        "project": meta.get("project_name", "KATHA Project"),
        "theme": meta.get("theme"),
        "room_type": meta.get("room_type"),
        "dimensions_m": meta.get("dimensions_m") or {},
        "currency": cost.get("currency", "INR"),
        "manufacturing_cost_inr": float(totals.get("base") or totals.get("low") or 0),
        "totals": totals,
        "objects_count": spec.get("objects_count", 0),
        "brd_bands": {
            "manufacturer_margin_by_volume": {
                "one_off": [50.0, 60.0],
                "small_batch": [40.0, 55.0],
                "production": [35.0, 45.0],
                "mass_production": [30.0, 40.0],
            },
            "designer_margin": [25.0, 50.0],
            "retail_markup": [40.0, 100.0],
            "customization_premium_by_level": {
                "none": [0.0, 0.0],
                "light_finish": [5.0, 10.0],
                "moderate": [10.0, 15.0],
                "heavy": [15.0, 20.0],
                "fully_bespoke": [20.0, 25.0],
            },
        },
    }


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta") or {}
    project_raw = meta.get("project_name", "KATHA Project")
    project = _safe_name(project_raw)
    today = datetime.now(timezone.utc).date().isoformat()

    payload = _payload(spec, graph or {})
    payload_json = json.dumps(payload, ensure_ascii=False)

    material = spec.get("material") or {}
    manufacturing = spec.get("manufacturing") or {}
    mep = spec.get("mep") or {}
    cost = spec.get("cost") or {}
    primary_struct = (material.get("primary_structure") or [])

    # ── Specification rows ──
    material_rows = "".join(
        f"<tr><td>{_e(m.get('name'))}</td><td>{_e(m.get('grade'))}</td>"
        f"<td>{_e(m.get('finish'))}</td><td>{_e(m.get('lead_time_weeks'))}</td>"
        f"<td>{_e(m.get('cost_inr'))}</td></tr>"
        for m in primary_struct
    )
    if not material_rows:
        material_rows = "<tr><td colspan='5' class='muted'>No material lines yet.</td></tr>"

    cost_rows = "".join(
        f"<tr><td>{_e(line.get('category'))}</td><td>{_e(line.get('quantity'))}</td>"
        f"<td>{_e(line.get('unit'))}</td><td>{_money(line.get('total_inr'))}</td></tr>"
        for line in (cost.get("line_items") or [])
    )
    if not cost_rows:
        cost_rows = "<tr><td colspan='4' class='muted'>No cost line items yet.</td></tr>"

    hvac = (mep.get("hvac") or {})
    plumbing = (mep.get("plumbing") or {})
    electrical = (mep.get("electrical") or {})

    wood = (manufacturing.get("woodworking_notes") or {})
    metal = (manufacturing.get("metal_fabrication_notes") or {})

    # ── HTML body ──
    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{_e(project_raw)} — KATHA spec viewer</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js" type="module"></script>
<style>
:root {{
  --bg:#efe9df; --ink:#3d3a36; --accent:#8c6a4f; --rule:#d9cdb8;
  --soft:#f5f0e6; --warn:#a85a2c;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--ink); }}
header {{ padding:32px 48px 16px; border-bottom:1px solid var(--rule); }}
header h1 {{ margin:0; font-size:30px; font-weight:300; letter-spacing:0.5px; }}
header p {{ margin:6px 0 0; color:var(--accent); font-size:14px; }}
nav {{ padding:0 48px; border-bottom:1px solid var(--rule); display:flex; gap:6px; flex-wrap:wrap; }}
nav button {{ background:none; border:0; padding:14px 18px; font-size:14px; color:var(--ink); cursor:pointer; opacity:0.6; border-bottom:2px solid transparent; }}
nav button.active {{ opacity:1; border-bottom-color:var(--accent); }}
main {{ padding:32px 48px 48px; max-width:1280px; }}
section {{ display:none; }}
section.active {{ display:block; }}
section h2 {{ font-weight:400; font-size:22px; margin:0 0 14px; }}
.card {{ background:var(--soft); border:1px solid var(--rule); border-radius:6px; padding:18px 22px; margin-bottom:18px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:14px; }}
.kv {{ display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px dashed var(--rule); font-size:14px; }}
.kv:last-child {{ border-bottom:0; }}
.kv span:first-child {{ color:var(--accent); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--rule); }}
th {{ color:var(--accent); font-weight:500; }}
td.muted, .muted {{ color:#888; font-style:italic; }}
.calc-row {{ display:flex; align-items:center; gap:12px; margin:10px 0; font-size:13px; }}
.calc-row label {{ width:200px; color:var(--accent); }}
.calc-row input[type=range] {{ flex:1; }}
.calc-row select {{ flex:1; padding:6px; }}
.calc-row .val {{ width:100px; text-align:right; font-variant-numeric:tabular-nums; }}
.total {{ margin-top:18px; padding:14px 18px; background:var(--ink); color:var(--bg); border-radius:6px; }}
.total .big {{ font-size:28px; font-weight:300; }}
model-viewer {{ width:100%; height:420px; background:#1f1d1a; border-radius:6px; }}
.share {{ background:var(--ink); color:var(--bg); padding:14px 18px; border-radius:6px; font-size:13px; }}
.share input {{ width:100%; padding:8px 10px; margin-top:6px; border:0; border-radius:4px; background:#3d3a36; color:#efe9df; font-family:inherit; }}
.warning {{ color:var(--warn); font-size:12px; margin-top:6px; }}
footer {{ padding:18px 48px; border-top:1px solid var(--rule); font-size:12px; color:var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>{_e(project_raw)}</h1>
  <p>{_e(meta.get('theme', '—'))} · {_e(meta.get('room_type', '—'))} · generated {today}</p>
</header>
<nav id="tabs">
  <button data-tab="overview" class="active">Overview</button>
  <button data-tab="spec">Specification</button>
  <button data-tab="manufacturing">Manufacturing</button>
  <button data-tab="mep">MEP</button>
  <button data-tab="cost">Cost & Calculator</button>
  <button data-tab="model">3D Model</button>
  <button data-tab="share">Share</button>
</nav>
<main>

<section id="overview" class="active">
  <h2>Overview</h2>
  <div class="grid">
    <div class="card">
      <div class="kv"><span>Theme</span><span>{_e(meta.get('theme', '—'))}</span></div>
      <div class="kv"><span>Room type</span><span>{_e(meta.get('room_type', '—'))}</span></div>
      <div class="kv"><span>Dimensions (m)</span><span>{_e(payload['dimensions_m'].get('length','—'))} × {_e(payload['dimensions_m'].get('width','—'))} × {_e(payload['dimensions_m'].get('height','—'))}</span></div>
      <div class="kv"><span>Objects in graph</span><span>{_e(payload['objects_count'])}</span></div>
    </div>
    <div class="card">
      <div class="kv"><span>Currency</span><span>{_e(cost.get('currency', 'INR'))}</span></div>
      <div class="kv"><span>Manufacturing cost (base)</span><span>{_money(cost.get('totals',{}).get('base'))}</span></div>
      <div class="kv"><span>Range low</span><span>{_money(cost.get('totals',{}).get('low'))}</span></div>
      <div class="kv"><span>Range high</span><span>{_money(cost.get('totals',{}).get('high'))}</span></div>
    </div>
  </div>
</section>

<section id="spec">
  <h2>Material specification</h2>
  <div class="card">
    <table>
      <thead><tr><th>Material</th><th>Grade</th><th>Finish</th><th>Lead time (wks)</th><th>₹/unit</th></tr></thead>
      <tbody>{material_rows}</tbody>
    </table>
  </div>
</section>

<section id="manufacturing">
  <h2>Manufacturing notes</h2>
  <div class="card">
    <div class="kv"><span>Woodwork precision</span><span>{_e((wood.get('machine_precision_required') or {{}}).get('level','—'))} ±{_e((wood.get('machine_precision_required') or {{}}).get('tolerance_mm','—'))} mm</span></div>
    <div class="kv"><span>Lead time</span><span>{_e((wood.get('lead_time') or {{}}).get('low_weeks','—'))}–{_e((wood.get('lead_time') or {{}}).get('high_weeks','—'))} weeks ({_e((wood.get('lead_time') or {{}}).get('complexity','—'))})</span></div>
    <div class="kv"><span>Joinery methods</span><span>{_e(', '.join(j.get('method','') for j in (wood.get('joinery_methods') or [])[:4]) or '—')}</span></div>
    <div class="kv"><span>Metal fab applies to</span><span>{_e(', '.join(metal.get('applies_to') or []) or '—')}</span></div>
  </div>
</section>

<section id="mep">
  <h2>MEP snapshot</h2>
  <div class="grid">
    <div class="card">
      <h3 style="margin:0 0 8px; font-size:14px; color:var(--accent); text-transform:uppercase; letter-spacing:1px;">HVAC</h3>
      <div class="kv"><span>Air changes / hr</span><span>{_e(hvac.get('ach_target','—'))}</span></div>
      <div class="kv"><span>Fresh-air CFM</span><span>{_e(hvac.get('cfm_fresh_air','—'))}</span></div>
      <div class="kv"><span>Cooling tonnage</span><span>{_e((hvac.get('cooling') or {{}}).get('tonnage','—'))}</span></div>
    </div>
    <div class="card">
      <h3 style="margin:0 0 8px; font-size:14px; color:var(--accent); text-transform:uppercase; letter-spacing:1px;">Electrical</h3>
      <div class="kv"><span>Ambient lux target</span><span>{_e(electrical.get('ambient_lux_target','—'))}</span></div>
      <div class="kv"><span>Lighting load (W)</span><span>{_e(electrical.get('total_lighting_load_w','—'))}</span></div>
      <div class="kv"><span>Lighting circuits</span><span>{_e(electrical.get('lighting_circuits','—'))}</span></div>
    </div>
    <div class="card">
      <h3 style="margin:0 0 8px; font-size:14px; color:var(--accent); text-transform:uppercase; letter-spacing:1px;">Plumbing</h3>
      <div class="kv"><span>Total DFU</span><span>{_e(plumbing.get('total_dfu','—'))}</span></div>
      <div class="kv"><span>Main drain (mm)</span><span>{_e(plumbing.get('main_drain_size_mm','—'))}</span></div>
      <div class="kv"><span>Slope (per m)</span><span>{_e(plumbing.get('slope_per_metre','—'))}</span></div>
    </div>
  </div>
</section>

<section id="cost">
  <h2>Cost line items</h2>
  <div class="card">
    <table>
      <thead><tr><th>Category</th><th>Qty</th><th>Unit</th><th>Total</th></tr></thead>
      <tbody>{cost_rows}</tbody>
    </table>
  </div>
  <h2 style="margin-top:24px;">Pricing calculator (BRD bands, client-side)</h2>
  <div class="card">
    <div class="calc-row">
      <label>Volume tier</label>
      <select id="volume_tier">
        <option value="one_off">1 — one-off</option>
        <option value="small_batch" selected>5 — small batch</option>
        <option value="production">25 — production</option>
        <option value="mass_production">250+ — mass production</option>
      </select>
      <span class="val" id="volume_pct"></span>
    </div>
    <div class="calc-row">
      <label><input type="checkbox" id="outsource"/> Studio outsources fabrication</label>
      <span></span>
    </div>
    <div class="calc-row">
      <label>Designer margin (%)</label>
      <input type="range" id="designer_pct" min="25" max="50" step="0.5" value="37.5"/>
      <span class="val" id="designer_val">37.5%</span>
    </div>
    <div class="calc-row">
      <label><input type="checkbox" id="direct"/> Selling direct to end client</label>
      <span></span>
    </div>
    <div class="calc-row">
      <label>Retail markup (%)</label>
      <input type="range" id="retail_pct" min="40" max="100" step="1" value="70"/>
      <span class="val" id="retail_val">70%</span>
    </div>
    <div class="calc-row">
      <label>Customization level</label>
      <select id="cust_level">
        <option value="none" selected>None</option>
        <option value="light_finish">Light finish (5–10%)</option>
        <option value="moderate">Moderate (10–15%)</option>
        <option value="heavy">Heavy (15–20%)</option>
        <option value="fully_bespoke">Fully bespoke (20–25%)</option>
      </select>
      <span class="val" id="cust_val">0%</span>
    </div>
    <div class="total">
      <div class="kv" style="border-color:#5c5853;"><span>Manufacturing cost</span><span id="mfg_inr"></span></div>
      <div class="kv" style="border-color:#5c5853;"><span>Manufacturer margin</span><span id="mm_amt"></span></div>
      <div class="kv" style="border-color:#5c5853;"><span>Designer margin</span><span id="dm_amt"></span></div>
      <div class="kv" style="border-color:#5c5853;"><span>Retail markup</span><span id="rm_amt"></span></div>
      <div class="kv" style="border-color:transparent;"><span>Customization premium</span><span id="cp_amt"></span></div>
      <div class="big">Final retail price &nbsp;<span id="final_inr"></span></div>
    </div>
    <p class="warning">All bands snap to the BRD knowledge base. This calculator runs entirely in your browser — nothing leaves the page.</p>
  </div>
</section>

<section id="model">
  <h2>3D model</h2>
  <div class="card">
    <model-viewer id="viewer" src="" alt="3D model" auto-rotate camera-controls shadow-intensity="1" exposure="1.0">
    </model-viewer>
    <p class="warning">Drop the GLTF (e.g. <code>{_e(project)}-scene.gltf</code>) next to this HTML file or set its URL on the &lt;model-viewer&gt; src.</p>
  </div>
</section>

<section id="share">
  <h2>Shareable link</h2>
  <div class="card share">
    <p>Send this single .html file to any client; it works offline. To embed in a portal, host the file and copy the URL below:</p>
    <input id="link" readonly value=""/>
  </div>
</section>

</main>
<footer>
  KATHA AI — interactive specification viewer · {today}
</footer>

<script>
const PAYLOAD = {payload_json};

const $ = id => document.getElementById(id);
const fmt = v => v == null || isNaN(v) ? '—' : '₹' + Math.round(v).toLocaleString('en-IN');

// Tabs.
document.querySelectorAll('#tabs button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  }});
}});

// Calculator.
const bands = PAYLOAD.brd_bands;
function recalc() {{
  const mfg = PAYLOAD.manufacturing_cost_inr;
  const tier = $('volume_tier').value;
  const tierBand = bands.manufacturer_margin_by_volume[tier];
  const mmPct = (tierBand[0] + tierBand[1]) / 2;
  $('volume_pct').textContent = mmPct.toFixed(1) + '%';

  const mmAmt = Math.round(mfg * mmPct / 100);
  let runningTotal = mfg + mmAmt;

  const dmApplies = $('outsource').checked;
  const dmPctRaw = parseFloat($('designer_pct').value);
  const dmPct = dmApplies ? dmPctRaw : 0;
  $('designer_val').textContent = dmPctRaw.toFixed(1) + '%' + (dmApplies ? '' : ' (off)');
  const dmAmt = dmApplies ? Math.round(runningTotal * dmPct / 100) : 0;
  runningTotal += dmAmt;

  const rmApplies = $('direct').checked;
  const rmPctRaw = parseFloat($('retail_pct').value);
  const rmPct = rmApplies ? rmPctRaw : 0;
  $('retail_val').textContent = rmPctRaw.toFixed(0) + '%' + (rmApplies ? '' : ' (off)');
  const rmAmt = rmApplies ? Math.round(runningTotal * rmPct / 100) : 0;
  runningTotal += rmAmt;

  const level = $('cust_level').value;
  const cband = bands.customization_premium_by_level[level];
  const cpPct = (cband[0] + cband[1]) / 2;
  $('cust_val').textContent = cpPct.toFixed(1) + '%';
  const cpAmt = Math.round(runningTotal * cpPct / 100);
  runningTotal += cpAmt;

  $('mfg_inr').textContent = fmt(mfg);
  $('mm_amt').textContent  = fmt(mmAmt) + '  (' + mmPct.toFixed(1) + '%)';
  $('dm_amt').textContent  = dmApplies ? fmt(dmAmt) + '  (' + dmPct.toFixed(1) + '%)' : '— (in-house)';
  $('rm_amt').textContent  = rmApplies ? fmt(rmAmt) + '  (' + rmPct.toFixed(0) + '%)' : '— (trade channel)';
  $('cp_amt').textContent  = level === 'none' ? '— (catalogue)' : fmt(cpAmt) + '  (' + cpPct.toFixed(1) + '%)';
  $('final_inr').textContent = fmt(runningTotal);
}}
['volume_tier','outsource','designer_pct','direct','retail_pct','cust_level'].forEach(id => {{
  $(id).addEventListener('input', recalc);
  $(id).addEventListener('change', recalc);
}});
recalc();

// Model viewer — try the canonical GLTF filename next to this page.
$('viewer').setAttribute('src', '{_e(project)}-scene.gltf');

// Shareable link.
$('link').value = window.location.href;
</script>
</body>
</html>"""
    return {
        "content_type": "text/html; charset=utf-8",
        "filename": f"{project}-viewer.html",
        "bytes": body.encode("utf-8"),
    }
