import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests

app = Flask(__name__)

# --- CONFIG ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///local.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- API KEYS ---
# Masukkan BLOCKCHAIR_API_KEY di Railway Variables
KEYS = {
    'blockchair': os.getenv("BLOCKCHAIR_API_KEY"), 
    'solscan': os.getenv("SOLSCAN_API_KEY") 
}

# --- MODEL DATABASE (Sama seperti sebelumnya) ---
class Suspect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(100), nullable=False)
    chain = db.Column(db.String(20), nullable=False)
    risk_score = db.Column(db.Integer, default=1)
    impact_usd = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default="Under Review")
    evidence_link = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "address": self.address,
            "chain": self.chain,
            "tier": self.risk_score,
            "status": self.status,
            "impact": self.impact_usd,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M")
        }

with app.app_context():
    db.create_all()

# --- FUNGSI PELACAK (DATA FETCHER) ---

def get_wallet_data(chain, address):
    """
    Fungsi pintar untuk mengambil data wallet dari berbagai chain
    """
    data = {"balance": 0, "tx_count": 0, "provider": "unknown"}
    
    try:
        # --- JALUR 1: BLOCKCHAIR (Ethereum & BSC) ---
        if chain in ['ethereum', 'bsc']:
            # Mapping nama chain supaya sesuai dengan URL Blockchair
            bc_chain_name = 'ethereum' if chain == 'ethereum' else 'binance-smart-chain'
            
            url = f"https://api.blockchair.com/{bc_chain_name}/dashboards/address/{address}?key={KEYS['blockchair']}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('data') and res['data'].get(address):
                wallet_info = res['data'][address]['address']
                # Blockchair mengembalikan satoshi/wei, kita bagi 10^18 (kira-kira)
                data['balance'] = wallet_info['balance'] / 10**18 
                data['tx_count'] = wallet_info['transaction_count']
                data['provider'] = "Blockchair (Student Pack)"

        # --- JALUR 2: BLOCKSCOUT (Base) ---
        elif chain == 'base':
            # Base tetap pakai Blockscout (Gratis & Stabil untuk Base)
            url = f"https://base.blockscout.com/api?module=account&action=balance&address={address}"
            res = requests.get(url, timeout=10).json()
            if res['status'] == '1':
                data['balance'] = float(res['result']) / 10**18
                data['provider'] = "Blockscout Base"

        # --- JALUR 3: SOLSCAN (Solana) ---
        elif chain == 'solana':
            url = f"https://public-api.solscan.io/account/{address}"
            headers = {"token": KEYS['solscan']}
            res = requests.get(url, headers=headers, timeout=10).json()
            if 'lamports' in res:
                data['balance'] = res['lamports'] / 10**9 # Solana desimalnya 9
                data['provider'] = "Solscan Public"

    except Exception as e:
        print(f"Error fetching data: {e}")

    return data

# --- ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit_report():
    input_data = request.json
    addr = input_data.get('address')
    chain = input_data.get('chain').lower() # pastikan lowercase (ethereum, bsc, dll)
    
    # 1. Validasi on-chain otomatis sebelum disimpan
    # Kita cek dulu, walletnya beneran ada isinya gak?
    onchain_data = get_wallet_data(chain, addr)
    
    # Logika sederhana: Kalau balance > 0, kita anggap valid untuk dilaporkan
    # Kamu bisa ubah logika ini nanti
    risk_score = 3
    if onchain_data['balance'] > 10: # Kalau balance besar, risk tier naik
        risk_score = 4
    
    new_suspect = Suspect(
        address=addr,
        chain=chain,
        impact_usd=input_data.get('impact', 0),
        evidence_link=input_data.get('evidence'),
        risk_score=risk_score,
        status="Under Review"
    )
    
    db.session.add(new_suspect)
    db.session.commit()
    
    # Kembalikan data gabungan (Input User + Data On-Chain)
    return jsonify({
        "message": "Report received & verified", 
        "onchain_verification": onchain_data,
        "id": new_suspect.id
    }), 201

@app.route('/api/recent', methods=['GET'])
def get_recent():
    suspects = Suspect.query.order_by(Suspect.timestamp.desc()).limit(10).all()
    return jsonify([s.to_dict() for s in suspects])

if __name__ == '__main__':
    app.run(debug=True)
