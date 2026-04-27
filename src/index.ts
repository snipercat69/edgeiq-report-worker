/**
 * EdgeIQ Report PDF Generator
 * Cloudflare Worker — handles Stripe webhook + triggers PDF generation
 * 
 * Flow:
 * POST /webhook/stripe  → receives Stripe payment webhook → stores payment in KV
 * POST /generate       → accepts {session_id, scan_data, email} → returns PDF or error
 * GET  /status/:id     → check PDF generation status
 */

const STRIPE_WEBHOOK_SECRET = "";
const STRIPE_SECRET_KEY = "";
const PDF_SERVICE_URL = "https://pdf.microlabs.io/api/generate"; // placeholder for Puppeteer service
const ALLOWED_ORIGIN = "https://edgeiqlabs.com";

export async function handleWebhook(request) {
  const signature = request.headers.get("stripe-signature");
  const body = await request.text();
  
  // Verify webhook signature
  // Note: Stripe webhooks need raw body, so we pass as-is
  const stripeRes = await fetch("https://api.stripe.com/v1/webhooks", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${STRIPE_SECRET_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      payload: body,
      signature: signature,
      secret: STRIPE_WEBHOOK_SECRET,
      tolerance: 300
    })
  });

  if (!stripeRes.ok) {
    return new Response("Webhook verification failed", { status: 400 });
  }

  const event = JSON.parse(body);
  
  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    const sessionId = session.id;
    const customerEmail = session.customer_details?.email || session.metadata?.email;
    const product = session.metadata?.product;
    
    // Store payment in KV
    const kvKey = `payment:${sessionId}`;
    await EDGEIQ_KV.put(kvKey, JSON.stringify({
      paid: true,
      email: customerEmail,
      product,
      amount: session.amount_total,
      created: session.created,
      status: "completed"
    }), { expirationTtl: 86400 * 30 }); // 30 day expiry
    
    return new Response(JSON.stringify({ received: true, sessionId }), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  }
  
  return new Response(JSON.stringify({ received: true }), { status: 200 });
}

export async function handleGenerate(request) {
  // CORS check
  const origin = request.headers.get("Origin") || "";
  if (!origin.startsWith(ALLOWED_ORIGIN)) {
    return new Response("Forbidden", { status: 403 });
  }
  
  const { session_id, scan_data, email, client_name, target, consultant } = await request.json();
  
  if (!session_id || !scan_data) {
    return new Response(JSON.stringify({ error: "Missing session_id or scan_data" }), {
      status: 400,
      headers: { "Content-Type": "application/json" }
    });
  }
  
  // Verify payment in KV
  const kvKey = `payment:${session_id}`;
  const paymentData = await EDGEIQ_KV.get(kvKey);
  
  if (!paymentData) {
    // Fallback: verify directly with Stripe
    const stripeCheck = await fetch(`https://api.stripe.com/v1/checkout/sessions/${session_id}`, {
      headers: { "Authorization": `Bearer ${STRIPE_SECRET_KEY}` }
    });
    const session = await stripeCheck.json();
    
    if (!session.payment_status || session.payment_status !== "paid") {
      return new Response(JSON.stringify({ error: "Payment not confirmed" }), {
        status: 402,
        headers: { "Content-Type": "application/json" }
      });
    }
  }
  
  // Build the report HTML
  const reportHtml = buildReportHtml({ scan_data, client_name, target, consultant, email });
  
  // Call PDF generation service
  // Note: Replace PDF_SERVICE_URL with actual Puppeteer service endpoint
  // Options: pdf.microlabs.io, pdfrocket.com, or self-hosted Puppeteer on Render/Fly.io
  try {
    const pdfRes = await fetch(PDF_SERVICE_URL, {
      method: "POST",
      headers: { "Content-Type": "text/html" },
      body: reportHtml
    });
    
    if (!pdfRes.ok) {
      throw new Error(`PDF service error: ${pdfRes.status}`);
    }
    
    const pdfBuffer = await pdfRes.arrayBuffer();
    
    return new Response(pdfBuffer, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="edgeiq-report-${target || 'scan'}.pdf"`
      }
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: "PDF generation failed", detail: err.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" }
    });
  }
}

function buildReportHtml({ scan_data, client_name, target, consultant, email }) {
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  const findings = Array.isArray(scan_data) ? scan_data : scan_data.findings || [];
  
  const severityCounts = { Critical: 0, High: 0, Medium: 0, Low: 0, Info: 0 };
  findings.forEach(f => {
    const sev = f.severity || 'Info';
    severityCounts[sev] = (severityCounts[sev] || 0) + 1;
  });
  
  const sevColors = { Critical: '#ef4444', High: '#f97316', Medium: '#eab308', Low: '#22c55e', Info: '#64748b' };
  
  const findingsHtml = findings.map(f => `
    <tr>
      <td style="padding:12px;border-bottom:1px solid #1e293b">
        <span style="font-weight:600;font-size:0.9rem;color:#e2e8f0">${f.name || f.title || 'Unknown Finding'}</span>
        <span style="margin-left:8px;font-size:0.72rem;font-weight:700;text-transform:uppercase;padding:2px 8px;border-radius:4px;background:${sevColors[f.severity]}22;color:${sevColors[f.severity]}">${f.severity || 'Info'}</span>
      </td>
      <td style="padding:12px;border-bottom:1px solid #1e293b;color:#94a3b8;font-size:0.85rem">${f.cvss || 'N/A'}</td>
      <td style="padding:12px;border-bottom:1px solid #1e293b;color:#94a3b8;font-size:0.85rem">${f.description || f.summary || 'No description provided.'}</td>
      <td style="padding:12px;border-bottom:1px solid #1e293b;color:#94a3b8;font-size:0.85rem">${f.remediation || f.fix || 'No remediation steps provided.'}</td>
    </tr>
  `).join('');
  
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0e17; color: #e2e8f0; font-size: 14px; line-height: 1.5; }
  .page { max-width: 900px; margin: 0 auto; }
  .cover { background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%); padding: 48px; border-bottom: 3px solid #7c3aed; }
  .cover-header { display: flex; align-items: center; gap: 14px; margin-bottom: 36px; }
  .cover-header h1 { font-size: 1.5rem; font-weight: 800; color: #fff; }
  .cover-header p { color: #94a3b8; font-size: 0.9rem; }
  .meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 24px 0; }
  .meta-item label { display: block; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 4px; }
  .meta-item span { font-size: 0.9rem; color: #e2e8f0; }
  .classification { display: inline-block; background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.4); color: #f87171; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; padding: 3px 10px; border-radius: 4px; }
  .section { padding: 32px 48px; border-bottom: 1px solid #1e293b; }
  .section h2 { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 12px; border-bottom: 2px solid #7c3aed; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; }
  .sev-bar { display: flex; align-items: center; gap: 10px; margin: 6px 0; }
  .sev-label { width: 56px; font-size: 0.8rem; font-weight: 600; color: #94a3b8; }
  .sev-bar-fill { flex: 1; height: 8px; background: #1e293b; border-radius: 4px; overflow: hidden; }
  .sev-fill { height: 100%; border-radius: 4px; }
  .footer { padding: 24px 48px; font-size: 0.78rem; color: #64748b; border-top: 1px solid #1e293b; }
</style>
</head>
<body>
<div class="page">
  <div class="cover">
    <div class="cover-header">
      <div>
        <h1>Penetration Test Report</h1>
        <p>${target || 'Target URL'} &nbsp;·&nbsp; ${date} &nbsp;·&nbsp; Prepared by ${consultant || 'EdgeIQ Labs'}</p>
      </div>
    </div>
    <div class="meta-grid">
      <div class="meta-item"><label>Target</label><span>${target || 'N/A'}</span></div>
      <div class="meta-item"><label>Report Date</label><span>${date}</span></div>
      <div class="meta-item"><label>Client</label><span>${client_name || 'N/A'}</span></div>
      <div class="meta-item"><label>Consultant</label><span>${consultant || 'EdgeIQ Labs'}</span></div>
      <div class="meta-item"><label>Classification</label><span class="classification">Confidential</span></div>
      <div class="meta-item"><label>Report ID</label><span>${session_id || 'DEMO'}</span></div>
    </div>
  </div>
  
  <div class="section">
    <h2>Executive Summary</h2>
    <p style="color:#94a3b8;margin-bottom:12px;">A total of <strong style="color:#e2e8f0">${findings.length}</strong> finding(s) were identified during this assessment.</p>
    <div style="display:flex;gap:8px;margin-top:16px;">
      ${Object.entries(severityCounts).filter(([k,v]) => v > 0).map(([sev, count]) => `
        <div style="flex:1;background:#111827;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:1.8rem;font-weight:800;color:${sevColors[sev]}">${count}</div>
          <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;color:${sevColors[sev]}">${sev}</div>
        </div>
      `).join('')}
    </div>
  </div>
  
  <div class="section">
    <h2>Vulnerability Findings</h2>
    <table>
      <thead><tr><th>Finding</th><th>CVSS</th><th>Description</th><th>Remediation</th></tr></thead>
      <tbody>${findingsHtml}</tbody>
    </table>
  </div>
  
  <div class="section">
    <h2>Methodology</h2>
    <p style="color:#94a3b8;">This assessment was conducted in accordance with OWASP Testing Guide v4.2, NIST SP 800-115, and PTES (Penetration Testing Execution Standard). Scanning was performed using EdgeIQ Labs automated scanners supplemented by manual verification.</p>
  </div>
  
  <div class="footer">
    <p>Generated by <strong>EdgeIQ Labs</strong> · ${date} · This report is confidential and intended solely for the use of the named client.</p>
    <p style="margin-top:6px;">For questions contact: support@edgeiqlabs.com</p>
  </div>
</div>
</body>
</html>`;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;
    
    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, stripe-signature",
        }
      });
    }
    
    if (path === "/webhook/stripe" && request.method === "POST") {
      const res = await handleWebhook(request);
      // Add CORS headers
      res.headers.set("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
      return res;
    }
    
    if (path === "/generate" && request.method === "POST") {
      const res = await handleGenerate(request);
      res.headers.set("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
      return res;
    }
    
    if (path === "/status" && request.method === "GET") {
      const sessionId = url.searchParams.get("session_id");
      if (!sessionId) return new Response(JSON.stringify({ error: "Missing session_id" }), { status: 400 });
      const data = await EDGEIQ_KV.get(`payment:${sessionId}`);
      return new Response(JSON.stringify(data || { paid: false }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN }
      });
    }
    
    return new Response("EdgeIQ Report Generator Worker — alive", { status: 200 });
  }
};
