import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests

app = Flask(__name__)

# --- KONFIGURASI RAILWAY & DATABASE ---
# Railway otomatis menyediakan DATABASE_URL saat plugin Postgres dipasang
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///local.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- API KEYS (Diatur di Railway Variables) ---
API_KEYS = {
    'ethereum': os.getenv("ETHERSCAN_API_KEY"),
    'base': os.getenv("BASESCAN_API_KEY"),
    'bsc': os.getenv("BSCSCAN_API_KEY"),
    'solana': os.getenv("SOLSCAN_API_KEY") # Solana kadang butuh header beda, ini placeholder
}

# --- MODEL DATABASE (TABEL SUSPECT) ---
class Suspect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(100), nullable=False)
    chain = db.Column(db.String(20), nullable=False)
    risk_score = db.Column(db.Integer, default=1) # 1-5 (Tier)
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

# --- SETUP DATABASE OTOMATIS ---
with app.app_context():
    db.create_all()

# --- ROUTES (JALUR WEB) ---

@app.route('/')
def home():
    # Render file HTML yang ada di folder templates
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit_report():
    data = request.json
    
    # Simpan data dari form HTML ke Postgres
    new_suspect = Suspect(
        address=data.get('address'),
        chain=data.get('chain'),
        impact_usd=data.get('impact', 0),
        evidence_link=data.get('evidence'),
        risk_score=3, # Default tier awal sebelum audit
        status="Under Review"
    )
    
    db.session.add(new_suspect)
    db.session.commit()
    
    return jsonify({"message": "Report received", "id": new_suspect.id}), 201

@app.route('/api/recent', methods=['GET'])
def get_recent():
    # Ambil 10 data terbaru dari Database untuk ditampilkan di Frontend
    suspects = Suspect.query.order_by(Suspect.timestamp.desc()).limit(10).all()
    return jsonify([s.to_dict() for s in suspects])

if __name__ == '__main__':
    app.run(debug=True)


