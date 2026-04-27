# EdgeIQ Report PDF Generator — Flask Backend
# Deployed on Render.com (Free tier)
# Takes scan_data JSON → returns PDF using FPDF2 (pure Python, no system deps)
# Webhook: POST /webhook/stripe
# Generate: POST /generate

import os, io, json
from flask import Flask, request, jsonify, send_file
from fpdf import FPDF

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_ISJhDu0bptRJe4nQMVflh01EF8uJeEY8")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
ALLOWED_ORIGIN = "https://edgeiqlabs.com"

SEV_COLORS = {
    "Critical": (239, 68, 68),
    "High": (249, 115, 22),
    "Medium": (234, 179, 8),
    "Low": (34, 197, 94),
    "Info": (100, 116, 139),
}
SEV_LABEL_COLOR = (220, 38, 38)  # red-600 for "Critical" label in PDF


@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, stripe-signature"
    return response


@app.route("/health")
def health():
    return jsonify({"service": "edgeiq-pdf", "status": "ok"})


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json or {}
    scan_data = data.get("scan_data") or data
    target = scan_data.get("target", "scan")
    session_id = data.get("session_id", "demo")

    if not scan_data:
        return jsonify({"error": "No scan_data provided"}), 400

    try:
        pdf_bytes = build_report_pdf(scan_data, session_id)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"edgeiq-report-{target}.pdf"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "PDF generation failed", "detail": str(e)}), 500


def build_report_pdf(scan_data, session_id):
    findings = scan_data.get("findings", [])
    target = scan_data.get("target", "N/A")
    client_name = scan_data.get("client_name", "N/A")
    consultant = scan_data.get("consultant", "EdgeIQ Labs")
    date = scan_data.get("date", "2026-04-27")
    sev_map = scan_data.get("severity_map", SEV_COLORS)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ── Cover ────────────────────────────────────────────────────────
    pdf.set_fill_color(10, 14, 23)
    pdf.rect(0, 0, 210, 50, "F")

    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, "Penetration Test Report", ln=True, align="C")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 7, f"{target}  |  {date}  |  Prepared by {consultant}", ln=True, align="C")

    pdf.ln(12)

    # Meta row
    meta = [("Target", target), ("Client", client_name), ("Consultant", consultant)]
    col_w = 63
    for label, val in meta:
        pdf.set_fill_color(17, 24, 39)
        pdf.rect(pdf.l_margin, pdf.get_y(), col_w, 16, "F")
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(col_w, 6, f"  {label.upper()}", ln=False)
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(226, 232, 240)
        pdf.cell(col_w, 6, f"  {val}", ln=True)
        pdf.set_x(pdf.l_margin + col_w)

    pdf.ln(8)

    # ── Executive Summary ─────────────────────────────────────────────
    pdf.set_fill_color(17, 24, 39)
    pdf.rect(0, pdf.get_y(), 210, 8, "F")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 8, "  EXECUTIVE SUMMARY", ln=True)

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(148, 163, 184)
    summary = f"{len(findings)} finding(s) identified during this assessment."
    pdf.multi_cell(0, 5, summary)

    pdf.ln(4)
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = f.get("severity", "Info")
        if sev in counts:
            counts[sev] += 1

    # Severity badges
    badge_w = 36
    x_start = pdf.l_margin
    for sev, count in counts.items():
        r, g, b = sev_map.get(sev, SEV_COLORS.get(sev, (100, 116, 139)))
        pdf.set_fill_color(r, g, b)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 13)
        badge_text = f"  {count} {sev}"
        pdf.cell(badge_w, 14, badge_text, fill=True, ln=True)
        pdf.set_x(x_start + badge_w)
        if (list(counts.keys()).index(sev) + 1) % 5 == 0:
            pdf.ln(18)
            pdf.set_x(x_start)
    pdf.ln(4)

    # ── Vulnerability Findings ────────────────────────────────────────
    pdf.set_fill_color(17, 24, 39)
    pdf.rect(0, pdf.get_y(), 210, 8, "F")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 8, "  VULNERABILITY FINDINGS", ln=True)
    pdf.ln(2)

    if not findings:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(0, 8, "  No findings recorded.", ln=True)
    else:
        # Table header
        col_widths = [50, 15, 70, 65]
        headers = ["Finding", "CVSS", "Description", "Remediation"]
        pdf.set_fill_color(30, 41, 59)
        pdf.set_text_color(100, 116, 139)
        pdf.set_font("Helvetica", "B", 7)
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 7, f"  {h}", fill=True, border=0)
        pdf.ln(7)

        # Rows
        pdf.set_font("Helvetica", "", 8)
        for f in findings:
            sev = f.get("severity", "Info")
            r, g, b = sev_map.get(sev, SEV_COLORS.get(sev, (100, 116, 139)))

            # Severity badge cell
            pdf.set_fill_color(r, g, b)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 7)
            name = f.get("name", f.get("title", "Finding"))
            name = name[:40] + "…" if len(name) > 42 else name
            pdf.cell(col_widths[0], 6, f"  {name}", fill=True, border=0)

            # CVSS
            cvss = str(f.get("cvss", "N/A"))
            pdf.set_fill_color(17, 24, 39)
            pdf.set_text_color(148, 163, 184)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(col_widths[1], 6, cvss, fill=True, border=0)

            # Description
            desc = f.get("description", "—")
            desc = desc[:100] + "…" if len(desc) > 102 else desc
            pdf.set_font("Helvetica", "", 7)
            pdf.cell(col_widths[2], 6, desc[:70], fill=True, border=0)

            # Remediation
            rem = f.get("remediation", f.get("fix", "—"))[:60] + "…"
            pdf.set_font("Helvetica", "", 7)
            pdf.cell(col_widths[3], 6, rem[:50], fill=True, border=0)
            pdf.ln(6)

            # Separator
            pdf.set_draw_color(30, 41, 59)
            pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
            pdf.ln(1)

    # ── Methodology ────────────────────────────────────────────────────
    if pdf.get_y() > 240:
        pdf.add_page()
    pdf.ln(4)
    pdf.set_fill_color(17, 24, 39)
    pdf.rect(0, pdf.get_y(), 210, 8, "F")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 8, "  METHODOLOGY", ln=True)
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(148, 163, 184)
    pdf.multi_cell(0, 5,
        "Assessment conducted per OWASP Testing Guide v4.2, NIST SP 800-115, and PTES. "
        "Scanning performed using EdgeIQ Labs automated scanners supplemented by manual verification.")

    # ── Footer ───────────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_draw_color(30, 41, 59)
    pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5,
        f"Generated by EdgeIQ Labs  |  {date}  |  Confidential — intended solely for the named client.  |  support@edgeiqlabs.com",
        ln=True, align="C")

    return pdf.output()


@app.route("/webhook/stripe", methods=["POST"])
def webhook():
    payload = request.get_data()
    sig = request.headers.get("stripe-signature", "")
    stripe_wh_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)

    # Verify webhook signature (best effort — non-blocking)
    if sig and stripe_wh_secret and stripe_wh_secret != "whsec_placeholder":
        try:
            import stripe as stripe_lib
            stripe_lib.api_key = STRIPE_SECRET_KEY
            stripe_lib.Webhook.construct_event(payload, sig, stripe_wh_secret)
        except Exception:
            return jsonify({"error": "Invalid signature"}), 400

    event = request.json or {}
    event_type = event.get("type", "")
    if event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        session_id = session.get("id")
        # In production: generate PDF, upload, email link
        print(f"[Stripe] Payment confirmed: {session_id}")
    return jsonify({"received": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
