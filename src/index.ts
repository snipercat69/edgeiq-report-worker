/**
 * EdgeIQ Report Generator — Cloudflare Worker
 *
 * Flow:
 * POST /webhook/stripe  → receives Stripe webhook → stores in KV
 * POST /create-checkout → creates Stripe Checkout session → returns URL
 * POST /generate        → proxies to PDF service (verified payment required)
 */

const CHECKOUT_SERVICE = "https://edgeiq-checkout4.onrender.com";
const PDF_SERVICE = "https://edgeiq-pdf3.onrender.com";
const ALLOWED_ORIGIN = "https://edgeiqlabs.com";

interface Env {
  EDGEIQ_KV: KVNamespace;
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
}

export async function handleCreateCheckout(request: Request, env: Env): Promise<Response> {
  const origin = request.headers.get("Origin") || "";
  if (!origin.startsWith(ALLOWED_ORIGIN)) {
    return new Response("Forbidden", { status: 403 });
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }

  const { scan_data, package_type = "single", email, target = "scan" } = body;
  if (!scan_data || !email) {
    return json({ error: "scan_data and email are required" }, 400);
  }

  try {
    const resp = await fetch(`${CHECKOUT_SERVICE}/create-checkout-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scan_data, package: package_type, email, target }),
    });

    if (!resp.ok) {
      const err = await resp.text();
      return json({ error: "Checkout service error", detail: err }, 502);
    }

    const session = await resp.json();
    return json(session);

  } catch (err: any) {
    return json({ error: "Failed to create checkout session", detail: err.message }, 500);
  }
}

export async function handleWebhook(request: Request, env: Env): Promise<Response> {
  const body = await request.text();

  // Simplified webhook handling
  const event = JSON.parse(body);
  if (event.type === "checkout.session.completed") {
    const sessionId = event.data?.object?.id;
    const email = event.data?.object?.customer_details?.email;
    const metadata = event.data?.object?.metadata;
    if (sessionId) {
      await env.EDGEIQ_KV.put(`payment:${sessionId}`, JSON.stringify({
        paid: true,
        email,
        metadata,
        created: Date.now(),
      }), { expirationTtl: 86400 * 30 });
    }
    return json({ received: true });
  }

  return json({ received: true });
}

export async function handleGenerate(request: Request, env: Env): Promise<Response> {
  const origin = request.headers.get("Origin") || "";
  if (!origin.startsWith(ALLOWED_ORIGIN)) {
    return new Response("Forbidden", { status: 403 });
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }

  const { session_id, scan_data, target = "scan" } = body;
  if (!scan_data) {
    return json({ error: "scan_data is required" }, 400);
  }

  // Verify payment via KV or Stripe
  let paid = false;
  if (session_id) {
    const kvData = await env.EDGEIQ_KV.get(`payment:${session_id}`);
    if (kvData) {
      const info = JSON.parse(kvData);
      paid = info.paid === true;
    }

    if (!paid) {
      const stripeKey = env.STRIPE_SECRET_KEY || "sk_live_placeholder";
      try {
        const resp = await fetch(`https://api.stripe.com/v1/checkout/sessions/${session_id}`, {
          headers: { "Authorization": `Bearer ${stripeKey}` }
        });
        const session = await resp.json();
        paid = session?.payment_status === "paid";
      } catch {
        return json({ error: "Payment verification failed" }, 500);
      }
    }
  }

  if (!paid) {
    return json({ error: "Payment not confirmed" }, 402);
  }

  // Call PDF service with scan_data
  try {
    const pdfResp = await fetch(`${PDF_SERVICE}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scan_data, target, session_id }),
    });

    if (!pdfResp.ok) {
      const err = await pdfResp.text();
      return json({ error: "PDF generation failed", detail: err }, 502);
    }

    const pdfBuffer = await pdfResp.arrayBuffer();
    const filename = `edgeiq-report-${target}.pdf`;

    return new Response(pdfBuffer, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
      }
    });
  } catch (err: any) {
    return json({ error: "PDF service unreachable", detail: err.message }, 500);
  }
}

function json(obj: any, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN }
  });
}

export default {
  async fetch(request: Request, env: Env) {
    const url = new URL(request.url);
    const path = url.pathname;

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
      return handleWebhook(request, env);
    }

    if (path === "/create-checkout" && request.method === "POST") {
      return handleCreateCheckout(request, env);
    }

    if (path === "/generate" && request.method === "POST") {
      return handleGenerate(request, env);
    }

    if (path === "/health") {
      return json({ status: "ok", service: "edgeiq-worker" });
    }

    return new Response("EdgeIQ Report Worker — alive", { status: 200 });
  }
};
