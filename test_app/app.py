from flask import Flask
app = Flask(__name__)
@app.route('/')
def hello(): return 'Hello'
@app.route('/health')
def health(): return 'OK'
