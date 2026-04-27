#!/usr/bin/env python3
"""
EdgeIQ Report - Stripe Checkout Session Creator
Flask app that creates Stripe Checkout sessions with scan metadata,
then redirects to Stripe. After payment, Stripe redirects back to /report
with session_id. The report page verifies payment and generates the PDF.

Deploy to: Render.com (Free) — or any Python host
"""
import os, json, base64
from flask import Flask, request, jsonify, redirect
import stripe

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
ENDPOINT_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
APP_URL = os.environ.get('APP_URL', 'https://edgeiqlabs.com')

# Price map — match Stripe Payment Link prices
PRICE_MAP = {
    'single': os.environ.get('STRIPE_PRICE_SINGLE', 'price_19_single'),
    'bundle5': os.environ.get('STRIPE_PRICE_BUNDLE5', 'price_79_bundle5'),
    'bundle10': os.environ.get('STRIPE_PRICE_BUNDLE10', 'price_129_bundle10'),
}

@app.after_request
def cors(response):
    response.headers['Access-Control-Allow-Origin'] = 'https://edgeiqlabs.com'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create a Stripe Checkout Session with scan metadata."""
    data = request.json
    email = data.get('email', '').strip()
    scan_data = data.get('scan_data', {})
    package = data.get('package', 'single')  # single | bundle5 | bundle10
    
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    # Encode scan data to pass through Stripe metadata (limit 500 chars per field)
    # For large scan data, we store in KV and just pass a reference key
    scan_key = f"scan_{request.remote_addr}_{int(os.time.time())}"
    
    # Build metadata
    metadata = {
        'package': package,
        'target': scan_data.get('target', '')[:200],
        'client_name': scan_data.get('client_name', '')[:200],
        'consultant': scan_data.get('consultant', '')[:200],
        'scan_type': scan_data.get('scan_type', '')[:50],
        'findings_count': str(len(scan_data.get('findings', []))),
        'email': email,
        'scan_key': scan_key,
    }
    
    try:
        # Build Stripe Checkout Session
        checkout_params = {
            'mode': 'payment',
            'success_url': f'{APP_URL}/report.html?session_id={{CHECKOUT_SESSION_ID}}&key={scan_key}',
            'cancel_url': f'{APP_URL}/report.html?cancelled=1',
            'customer_email': email,
            'metadata': metadata,
            'payment_intent_data': {
                'metadata': metadata
            }
        }
        
        if package == 'bundle5':
            checkout_params['line_items'] = [{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': 7900,
                    'product_data': {
                        'name': 'EdgeIQ Report Bundle — 5 Reports',
                        'description': 'Pay once, use anytime. Reports never expire.',
                    }
                },
                'quantity': 1
            }]
        elif package == 'bundle10':
            checkout_params['line_items'] = [{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': 12900,
                    'product_data': {
                        'name': 'EdgeIQ Report Bundle — 10 Reports',
                        'description': 'Pay once, use anytime. Reports never expire.',
                    }
                },
                'quantity': 1
            }]
        elif package == 'single':
            checkout_params['line_items'] = [{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': 1900,
                    'product_data': {
                        'name': 'EdgeIQ Security Report — Single',
                        'description': 'One branded pentest PDF with CVSS scoring, executive summary, and remediation steps.',
                    }
                },
                'quantity': 1
            }]
        
        session = stripe.checkout.Session.create(**checkout_params)
        
        # Store scan data (for later PDF generation)
        # In production: store in Redis/KV. For now: return scan_key + session in response
        return jsonify({
            'url': session.url,
            'session_id': session.id,
            'scan_key': scan_key
        })
        
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/verify-payment', methods=['GET'])
def verify_payment():
    """Called after Stripe redirects back with session_id. Verify and return status."""
    session_id = request.args.get('session_id', '')
    scan_key = request.args.get('key', '')
    
    if not session_id:
        return jsonify({'error': 'Missing session_id'}), 400
    
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == 'paid':
            # Deduct credit if bundle
            package = session.metadata.get('package', 'single')
            # In production: decrement credit in KV here
            return jsonify({
                'paid': True,
                'package': package,
                'customer_email': session.customer_details.email if session.customer_details else '',
                'amount': session.amount_total,
                'scan_key': scan_key
            })
        else:
            return jsonify({'paid': False, 'status': session.payment_status})
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events."""
    payload = request.data
    sig = request.headers.get('Stripe-Signature', '')
    
    try:
        event = stripe.Webhook.construct_event(payload, sig, ENDPOINT_SECRET)
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        # Store in KV for later verification
        # In production: store payment record in KV with scan_key reference
        print(f"Payment completed: {session.id} — {session.metadata.get('package')}")
    
    return jsonify({'received': True})

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    """Generate and stream the PDF after payment verification."""
    # This endpoint should verify payment first
    session_id = request.args.get('session_id', '')
    
    # In production: verify session is paid before generating
    # For now: accept scan_key + session_id combo
    
    data = request.json or {}
    scan_key = data.get('scan_key', '')
    
    # Retrieve scan data from KV by scan_key
    # For now: build from passed data
    from weasyprint import HTML
    html_content = data.get('html', '')
    
    if not html_content:
        return jsonify({'error': 'No HTML provided'}), 400
    
    try:
        pdf = HTML(string=html_content).write_pdf()
        from io import BytesIO
        return send_file(
            BytesIO(pdf),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"edgeiq-report.pdf"
        )
    except Exception as e:
        return jsonify({'error': 'PDF generation failed', 'detail': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'edgeiq-report-checkout'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)