# EdgeIQ Report Worker

Stripe checkout + PDF report generation backend for EdgeIQ Labs.

## Services

### checkout_server/ (Flask)
- `POST /create-checkout-session` → returns Stripe checkout URL
- `GET /verify-payment?session_id=xxx` → verify payment
- `POST /webhook` → Stripe webhook handler

### pdf_backend/ (Flask + WeasyPrint)
- `POST /generate-pdf` → body: `{ html, target }` → PDF file

### src/ (Cloudflare Worker)
- `POST /webhook/stripe` → Stripe webhook
- `POST /generate` → PDF generation (calls pdf_backend)

## Deploy

### Render.com
1. Connect `snipercat69/edgeiq-report-worker` GitHub repo
2. Deploy checkout_server and pdf_backend as separate services
3. Env vars: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, APP_URL
