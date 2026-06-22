#!/usr/bin/env python3
"""Render results/experiment/analysis.json into a self-contained HTML dashboard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COLORS = {"openai:gpt-5.5": "#10a37f",
          "anthropic:claude-opus-4-8": "#d97757",
          "google:gemini-3.5-flash": "#4285f4"}
SHORT = {"openai:gpt-5.5": "GPT-5.5",
         "anthropic:claude-opus-4-8": "Opus 4.8",
         "google:gemini-3.5-flash": "Gemini 3.5 Flash"}


def line_chart(models, grid, curve_of, title, ylabel, xcaption="fraction disclosed"):
    W, H, PAD = 560, 300, 44
    x = lambda i: PAD + i * (W - 2 * PAD) / (len(grid) - 1)
    y = lambda v: H - PAD - (v or 0) * (H - 2 * PAD)
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{title}">']
    # grid lines + y labels
    for gy in (0, 0.25, 0.5, 0.75, 1.0):
        yy = y(gy)
        parts.append(f'<line x1="{PAD}" y1="{yy:.0f}" x2="{W-PAD}" y2="{yy:.0f}" stroke="#23262d"/>')
        parts.append(f'<text x="{PAD-8}" y="{yy+4:.0f}" fill="#8b909a" font-size="11" text-anchor="end">{gy:.2f}</text>')
    # x labels
    for i, f in enumerate(grid):
        parts.append(f'<text x="{x(i):.0f}" y="{H-PAD+18:.0f}" fill="#8b909a" font-size="11" text-anchor="middle">{int(float(f)*100)}%</text>')
    parts.append(f'<text x="{W/2:.0f}" y="{H-6:.0f}" fill="#aeb4bf" font-size="12" text-anchor="middle">{xcaption}</text>')
    for m in models:
        c = curve_of(m)
        pts = " ".join(f"{x(i):.1f},{y(c[i]):.1f}" for i in range(len(grid)) if c[i] is not None)
        col = COLORS.get(m, "#999")
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5"/>')
        for i in range(len(grid)):
            if c[i] is not None:
                parts.append(f'<circle cx="{x(i):.1f}" cy="{y(c[i]):.1f}" r="3" fill="{col}"/>')
    parts.append("</svg>")
    return "".join(parts)


def bars(models, value_of, title, fmt="{:.0%}"):
    rows = []
    mx = max((value_of(m) or 0) for m in models) or 1
    for m in models:
        v = value_of(m) or 0
        col = COLORS.get(m, "#999")
        rows.append(
            f'<div class="bar-row"><span class="bar-lbl">{SHORT.get(m,m)}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{v/mx*100:.0f}%;background:{col}"></span></span>'
            f'<span class="bar-val">{fmt.format(v)}</span></div>')
    return f'<div class="bars">{"".join(rows)}</div>'


def build(a: dict) -> str:
    models = a["models"]
    grid = [str(g) for g in a["grid"]]
    agg = a["aggregate"]
    unit = a.get("disclose_unit", "turn")
    xcap = f"fraction of {unit}s disclosed"
    n_total = sum((agg[models[0]][k]["n"] or 0) for k in ("must_detect", "abstain_ok", "no_event"))

    def det_curve(m):
        c = agg[m]["must_detect"]["detection_curve"]
        return [c.get(g) for g in grid]

    def abst_curve(m):
        c = agg[m]["no_event"]["abstention_curve"]
        return [c.get(g) for g in grid]

    # must-detect (occurred) cards
    cards = []
    for m in models:
        e = agg[m]["must_detect"]
        cards.append(f"""<div class="card" style="border-top:3px solid {COLORS.get(m,'#999')}">
          <div class="card-name">{SHORT.get(m,m)}</div>
          <div class="metric"><b>{(e['final_detection_accuracy'] or 0):.0%}</b><span>occurred events detected (final)</span></div>
          <div class="metric"><b>{e['median_first_correct_k']}</b><span>median turns to first correct</span></div>
          <div class="metric"><b>{(e['median_evidence_fraction'] or 0):.0%}</b><span>of the conversation needed</span></div>
        </div>""")

    # abstain-acceptable (upcoming/weak/cancelled) disposition bars
    def dcorrect(m): return agg[m]["abstain_ok"]["detect_correct_rate"]
    def dabst(m): return agg[m]["abstain_ok"]["abstain_rate"]
    def dlen(m): return agg[m]["abstain_ok"]["lenient_accuracy"]

    # per-type matrix
    types = sorted({t for m in models for t in agg[m]["by_generation_type"]})
    th = "".join(f"<th>{SHORT.get(m,m)}</th>" for m in models)
    trows = []
    for t in types:
        cells = []
        for m in models:
            v = agg[m]["by_generation_type"].get(t, {}).get("final_accuracy")
            if v is None:
                cells.append("<td>–</td>")
            else:
                # red->green heat
                r = int(220 - v * 150); g = int(80 + v * 130)
                cells.append(f'<td style="background:rgba({r},{g},90,.30)">{v:.2f}</td>')
        trows.append(f"<tr><td class='tname'>{t}</td>{''.join(cells)}</tr>")

    # abstention table values
    def fa(m): return agg[m]["no_event"]["final_abstention_accuracy"]
    def fc(m): return agg[m]["no_event"]["false_commit_rate_any_step"]

    return f"""<title>Stage 1 — Evidence-to-Decision</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0d0f12; color:#e6e9ef; font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:32px 22px 64px; }}
  h1 {{ font-size:26px; margin:0 0 4px; letter-spacing:-.02em; }}
  .sub {{ color:#8b909a; margin:0 0 28px; }}
  h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.08em; color:#aeb4bf; margin:38px 0 14px; font-weight:600; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; }}
  .card {{ background:#15181d; border:1px solid #23262d; border-radius:12px; padding:16px 18px; }}
  .card-name {{ font-weight:600; margin-bottom:12px; }}
  .metric {{ display:flex; align-items:baseline; gap:8px; margin:8px 0; }}
  .metric b {{ font-size:24px; font-variant-numeric:tabular-nums; }}
  .metric span {{ color:#8b909a; font-size:12.5px; }}
  .panel {{ background:#15181d; border:1px solid #23262d; border-radius:12px; padding:18px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
  @media (max-width:760px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  .bars {{ display:flex; flex-direction:column; gap:10px; margin-top:6px; }}
  .bar-row {{ display:grid; grid-template-columns:120px 1fr 54px; align-items:center; gap:10px; font-size:13px; }}
  .bar-track {{ background:#23262d; border-radius:6px; height:14px; overflow:hidden; }}
  .bar-fill {{ display:block; height:100%; border-radius:6px; }}
  .bar-val {{ text-align:right; font-variant-numeric:tabular-nums; color:#cdd2da; }}
  .legend {{ display:flex; gap:18px; flex-wrap:wrap; margin:6px 0 0; font-size:13px; color:#aeb4bf; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:middle; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:7px 9px; text-align:center; border-bottom:1px solid #1d2025; }}
  td.tname {{ text-align:left; color:#cdd2da; white-space:nowrap; }}
  th {{ color:#8b909a; font-weight:600; }}
  .note {{ background:#1a1407; border:1px solid #3a2e10; border-radius:10px; padding:14px 16px; color:#d8c9a0; font-size:13.5px; margin-top:14px; }}
  .scroll {{ overflow-x:auto; }}
</style>
<div class="wrap">
  <h1>Stage 1 — Evidence-to-Decision</h1>
  <p class="sub">How many {unit}s each model needs to identify the life event, and how robustly it abstains when there is none · {n_total} multi-{unit} records · {a['n_errors']} call errors</p>

  <h2>A · Must-detect events (occurred)</h2>
  <div class="cards">{''.join(cards)}</div>

  <div class="grid2" style="margin-top:18px">
    <div class="panel">
      <h2 style="margin-top:0">Detection curve (must-detect)</h2>
      {line_chart(models, grid, det_curve, "detection", "label correct", xcap)}
      <div class="legend">{''.join(f'<span><span class="dot" style="background:{COLORS[m]}"></span>{SHORT.get(m,m)}</span>' for m in models)}</div>
    </div>
    <div class="panel">
      <h2 style="margin-top:0">Abstention curve (no-event)</h2>
      {line_chart(models, grid, abst_curve, "abstention", "abstaining", xcap)}
      <div class="legend">{''.join(f'<span><span class="dot" style="background:{COLORS[m]}"></span>{SHORT.get(m,m)}</span>' for m in models)}</div>
    </div>
  </div>

  <h2>B · Abstain-acceptable events (upcoming / weak_signal / cancelled)</h2>
  <p class="sub" style="margin:-6px 0 12px">Detecting with the correct label <i>or</i> abstaining are both prompt-compliant; lenient accuracy counts either.</p>
  <div class="grid2">
    <div class="panel"><div style="color:#8b909a;font-size:12.5px;margin-bottom:8px">Lenient accuracy — detect-correct OR abstain (higher = better)</div>{bars(models, dlen, "len")}</div>
    <div class="panel"><div style="color:#8b909a;font-size:12.5px;margin-bottom:8px">Chose to abstain (prompt-compliant on weak evidence)</div>{bars(models, dabst, "abst")}</div>
  </div>

  <h2>C · Abstention robustness (no-event records)</h2>
  <div class="grid2">
    <div class="panel"><div style="color:#8b909a;font-size:12.5px;margin-bottom:8px">Final abstention accuracy (higher = better)</div>{bars(models, fa, "abstain")}</div>
    <div class="panel"><div style="color:#8b909a;font-size:12.5px;margin-bottom:8px">False-commit rate, any step (lower = better)</div>{bars(models, fc, "fc")}</div>
  </div>

  <h2>Final accuracy by generation type</h2>
  <div class="panel scroll"><table><thead><tr><th class="tname">generation_type</th>{th}</tr></thead><tbody>{''.join(trows)}</tbody></table></div>

  <div class="note"><b>Reading the numbers.</b> Records are split by gold <code>event_status</code>: <b>must-detect</b> (occurred — the model should identify) vs <b>abstain-acceptable</b> (upcoming/weak_signal/cancelled — the prompt allows or requires abstention, and the schema can't even emit "cancelled"). Two findings stand out: (1) must-detect accuracy is depressed by <b>ambiguous/under-evidenced gold</b> — on the missed records all three vendors agree against the gold label (e.g. a "결혼" record that reads as "이사"), which signals bad data, not model failure; (2) the detection curve is <b>flat</b> — clean occurred events are identified at the first user turn, so there is little progressive gradient.</div>
</div>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", type=Path, default=REPO / "results/experiment/analysis.json")
    ap.add_argument("--out", type=Path, default=REPO / "results/experiment/report.html")
    args = ap.parse_args()
    a = json.loads(args.analysis.read_text(encoding="utf-8"))
    args.out.write_text(build(a), encoding="utf-8")
    print(f"[artifact] wrote {args.out}")


if __name__ == "__main__":
    main()
