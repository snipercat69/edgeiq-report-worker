# EdgeIQ Report PDF Generator — Flask Backend
# Deployed on Render.com (Free tier)
# Takes HTML → returns PDF using WeasyPrint
# Webhook: POST /webhook/stripe
# Generate: POST /generate

import os, json, base64
from flask import Flask, request, jsonify, send_file
import weasyprint

app = Flask(__name__)
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_ISJhDu0bptRJe4nQMVflh01EF8uJeEY8")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
ALLOWED_ORIGIN = "https://edgeiqlabs.com"

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, stripe-signature"
    return response

@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    html = data.get("html") or data.get("scan_data")
    target = data.get("target", "scan")
    session_id = data.get("session_id", "demo")
    
    if not html:
        return jsonify({"error": "No HTML provided"}), 400
    
    # If scan_data dict is passed, build HTML from it
    if isinstance(html, dict):
        html = build_report_html(html, session_id)
    
    try:
        pdf = weasyprint.HTML(string=html).write_pdf()
        return send_file(
            io.BytesIO(pdf),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"edgeiq-report-{target}.pdf"
        )
    except Exception as e:
        return jsonify({"error": "PDF generation failed", "detail": str(e)}), 500

def build_report_html(scan_data, session_id):
    """Convert scan_data dict to professional PDF HTML"""
    findings = scan_data.get("findings", [])
    target = scan_data.get("target", "N/A")
    client_name = scan_data.get("client_name", "N/A")
    consultant = scan_data.get("consultant", "EdgeIQ Labs")
    date = scan_data.get("date", "2026-04-27")
    sev_map = {"Critical": "#ef4444", "High": "#f97316", "Medium": "#eab308", "Low": "#22c55e", "Info": "#64748b"}
    
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = f.get("severity", "Info")
        counts[sev] = counts.get(sev, 0) + 1
    
    rows = ""
    for f in findings:
        sev = f.get("severity", "Info")
        rows += f"""
        <tr>
          <td><strong>{f.get('name', f.get('title', 'Finding'))}</strong>
              <span class="badge {sev.lower()}">{sev}</span></td>
          <td>{f.get('cvss', 'N/A')}</td>
          <td>{f.get('description', 'No description.')}</td>
          <td>{f.get('remediation', f.get('fix', 'No remediation steps provided.'))}</td>
        </tr>"""
    
    sev_blocks = ""
    for sev, count in counts.items():
        if count > 0:
            sev_blocks += f"""
        <div class="sev-card">
          <div class="sev-num" style="color:{sev_map[sev]}">{count}</div>
          <div class="sev-name">{sev}</div>
        </div>"""
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: Inter, -apple-system, sans-serif; background:#0a0e17; color:#e2e8f0; font-size:13px; }}
.cover {{ background:linear-gradient(135deg,#0f172a,#1e1b4b,#0f172a); padding:48px; border-bottom:3px solid #7c3aed; }}
.cover h1 {{ font-size:1.8rem; font-weight:800; color:#fff; margin-bottom:8px; }}
.cover p {{ color:#94a3b8; font-size:0.9rem; }}
.meta {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin:24px 0; }}
.meta-item label {{ display:block; font-size:0.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#64748b; margin-bottom:4px; }}
.meta-item span {{ font-size:0.88rem; }}
.badge {{ display:inline-block; font-size:.65rem; font-weight:700; text-transform:uppercase; padding:2px 8px; border-radius:4px; margin-left:8px; }}
.badge.critical {{ background:rgba(239,68,68,.2); color:#f87171; }}
.badge.high {{ background:rgba(249,115,22,.2); color:#fb923c; }}
.badge.medium {{ background:rgba(234,179,8,.2); color:#facc15; }}
.badge.low {{ background:rgba(34,197,94,.2); color:#4ade80; }}
.badge.info {{ background:rgba(100,116,139,.2); color:#94a3b8; }}
.section {{ padding:32px 48px; border-bottom:1px solid #1e293b; }}
.section h2 {{ font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#64748b; margin-bottom:16px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; padding:10px 12px; border-bottom:2px solid #7c3aed; font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#64748b; }}
td {{ padding:12px; border-bottom:1px solid #1e293b; vertical-align:top; font-size:.85rem; color:#94a3b8; }}
tr:hover {{ background:rgba(255,255,255,.02); }}
.sev-grid {{ display:flex; gap:12px; }}
.sev-card {{ flex:1; background:#111827; border:1px solid #1e293b; border-radius:8px; padding:16px; text-align:center; }}
.sev-num {{ font-size:2rem; font-weight:800; }}
.sev-name {{ font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; margin-top:4px; }}
.footer {{ padding:24px 48px; font-size:.75rem; color:#64748b; border-top:1px solid #1e293b; }}
</style></head>
<body>
<div class="cover">
  <h1>Penetration Test Report</h1>
  <p>{target} &nbsp;·&nbsp; {date} &nbsp;·&nbsp; Prepared by {consultant}</p>
  <div class="meta">
    <div class="meta-item"><label>Target</label><span>{target}</span></div>
    <div class="meta-item"><label>Client</label><span>{client_name}</span></div>
    <div class="meta-item"><label>Consultant</label><span>{consultant}</span></div>
  </div>
</div>
<div class="section">
  <h2>Executive Summary</h2>
  <p style="color:#94a3b8;margin-bottom:16px;"><strong style="color:#e2e8f0">{len(findings)}</strong> finding(s) identified during this assessment.</p>
  <div class="sev-grid">{sev_blocks}</div>
</div>
<div class="section">
  <h2>Vulnerability Findings</h2>
  <table><thead><tr><th>Finding</th><th>CVSS</th><th>Description</th><th>Remediation</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>
<div class="section">
  <h2>Methodology</h2>
  <p style="color:#94a3b8;">Assessment conducted per OWASP Testing Guide v4.2, NIST SP 800-115, and PTES. Scanning performed using EdgeIQ Labs automated scanners supplemented by manual verification.</p>
</div>
<div class="footer">
  <p>Generated by <strong>EdgeIQ Labs</strong> · {date} · Confidential — intended solely for the named client.</p>
  <p style="margin-top:4px;">Questions? support@edgeiqlabs.com</p>
</div>
</body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
