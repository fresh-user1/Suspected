import os
import time
import requests
import json
from flask import Flask, render_template, request, jsonify, make_response

app = Flask(__name__)

# --- CONFIG WALLET PENERIMA (RESOURCE OWNER) ---
# Ganti dengan wallet EVM/Solana asli Anda untuk menerima pembayaran
RECEIVER_WALLET = "ARuLoMZ3DUUA4QyKwwtziFrHnS7sRxZoKvobvHH6bfGD" 

# --- API KEYS ---
BLOCKSCOUT_API_KEY = os.getenv("BLOCKSCOUT_API_KEY") # Base Primary
SOLSCAN_API_KEY = os.getenv("SOLSCAN_API_KEY")       # Solana Primary
BLOCKCHAIR_API_KEY = os.getenv("BLOCKCHAIR_API_KEY") # BACKUP (WAJIB ADA)

# --- HELPER: DATA FETCHING (DENGAN FAILOVER) ---
def get_chain_data(chain, address):
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # --- 1. COBA PRIMARY PROVIDER ---
    try:
        if chain == 'base':
            url = f"https://base.blockscout.com/api?module=account&action=txlist&address={address}&startblock=0&endblock=99999999&page=1&offset=20&sort=asc&apikey={BLOCKSCOUT_API_KEY}"
            res = requests.get(url, headers=headers, timeout=5).json()
            # Validasi response Blockscout
            if res.get('status') == '1' or (res.get('result') and isinstance(res['result'], list)):
                 return {'type': 'evm_standard', 'data': res.get('result', [])}
            else:
                raise Exception("Blockscout empty/error")

        elif chain == 'solana':
            url = f"https://public-api.solscan.io/account/transactions?account={address}&limit=20"
            headers['token'] = SOLSCAN_API_KEY 
            res = requests.get(url, headers=headers, timeout=5).json()
            if isinstance(res, list):
                return {'type': 'solana', 'data': res}
            else:
                raise Exception("Solscan error")
                
    except Exception as e:
        print(f"⚠️ Primary API Error ({chain}): {e}. Switching to Blockchair...")
        # Lanjut ke logika backup di bawah...

    # --- 2. FAILOVER: BLOCKCHAIR (BACKUP) ---
    # Jika Primary error, kode akan lari ke sini
    try:
        # Mapping nama chain untuk Blockchair
        bc_chain = 'ethereum' if chain == 'base' else 'solana' 
        # Note: Blockchair support Base sbg L2 tapi endpoint kadang beda, 
        # jika Base spesifik tidak ada di plan gratis, kita pakai Ethereum logic atau 
        # endpoint spesifik jika tersedia. Untuk Solana dia support.
        
        # URL Dashboard Blockchair (Mengembalikan list transaksi)
        url = f"https://api.blockchair.com/{bc_chain}/dashboards/address/{address}?transaction_details=true&limit=10&key={BLOCKCHAIR_API_KEY}"
        
        res = requests.get(url, headers=headers, timeout=10).json()
        data_core = res.get('data', {}).get(address, {})
        
        if 'transactions' in data_core:
            return {'type': 'blockchair_backup', 'data': data_core['transactions']}
    except Exception as e:
        print(f"❌ Backup Blockchair Error: {e}")
        return None

    return None

# --- CORE TRACING LOGIC ---
def perform_deep_trace(start_address, chain, max_depth=10):
    trail = []
    current_wallet = start_address
    
    # Thresholds
    if chain == 'solana':
        decimals = 10**9; whale_threshold = 1000 
    else:
        decimals = 10**18; whale_threshold = 50 

    for i in range(max_depth):
        print(f"Tracing Layer {i+1}: {current_wallet}")
        api_result = get_chain_data(chain, current_wallet)
        time.sleep(1) # Rate limit safety
        
        if not api_result or not api_result['data']: break
        
        found_funder = False
        tx_list = api_result['data']
        
        # A. PARSING SOLSCAN (SOLANA PRIMARY)
        if api_result['type'] == 'solana':
            for tx in tx_list:
                if tx.get('lamport') and tx.get('signer'):
                    funders = tx['signer']
                    if len(funders) > 0:
                        funder = funders[0]
                        if funder != current_wallet:
                            trail.append({"step": i + 1, "wallet": current_wallet, "funded_by": funder, "amount": "Unknown (SOL)", "tx_hash": tx.get('txHash', 'unknown')})
                            current_wallet = funder; found_funder = True; break

        # B. PARSING BLOCKSCOUT (BASE PRIMARY)
        elif api_result['type'] == 'evm_standard':
            for tx in tx_list:
                if tx['to'].lower() == current_wallet.lower() and float(tx['value']) > 0:
                    funder = tx['from']; amount = float(tx['value']) / decimals
                    trail.append({"step": i + 1, "wallet": current_wallet, "funded_by": funder, "amount": amount, "tx_hash": tx['hash']})
                    current_wallet = funder; found_funder = True
                    if amount > whale_threshold: trail.append({"info": "WHALE/EXCHANGE DETECTED", "wallet": funder}); return trail
                    break
        
        # C. PARSING BLOCKCHAIR (BACKUP UNTUK SEMUA)
        elif api_result['type'] == 'blockchair_backup':
            # Blockchair structure: list of tx hashes or details.
            # Simplified logic: cari incoming transaction dari list
            for tx in tx_list:
                # Blockchair 'balance_change' positif = uang masuk
                if tx.get('balance_change', 0) > 0:
                    amount = float(tx['balance_change']) / decimals
                    # Blockchair dashboard endpoint free-tier kadang tidak kasih 'sender' address langsung
                    # Kita tandai sebagai "Check Explorer" jika sender tidak ada di payload ringkas
                    # Atau kita asumsikan 'block_id' dsb valid.
                    
                    # *Di Production: Anda harus call endpoint /transaction/hash untuk dapat sender pasti*
                    # *Di sini: Kita simpan hash-nya saja agar tidak error*
                    trail.append({
                        "step": i + 1,
                        "wallet": current_wallet,
                        "funded_by": "Blockchair_Backup_Trace", # Placeholder karena limitasi free tier dashboard
                        "amount": amount,
                        "tx_hash": tx.get('hash', 'unknown')
                    })
                    # Kita stop trace deep disini jika pakai backup, karena butuh extra call untuk dapat sender
                    trail.append({"info": "BACKUP ENDPOINT REACHED", "wallet": "See Explorer"})
                    return trail
        
        if not found_funder: break
            
    return trail

# --- ROUTES (X402 PROTOCOL) ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/trace/execute', methods=['POST'])
def execute_trace():
    # 1. Cek Header Pembayaran
    payment_payload = request.headers.get('X-Payment')
    
    data = request.json
    address = data.get('address')
    chain = data.get('chain')
    depth = int(data.get('depth', 10))

    # SKENARIO 1: BELUM BAYAR (402)
    if not payment_payload:
        price_amount = "0.03" if depth == 10 else "0.055"
        if chain == 'solana': price_amount = str(float(price_amount) + 0.02)
        
        requirements = {
            "type": "payment_request",
            "currencies": ["USD"],
            "amount": price_amount,
            "recipient": RECEIVER_WALLET, # <-- GANTI INI DENGAN WALLET ASLI ANDA
            "network": chain,
            "description": f"Trace {chain.upper()} Wallet ({depth} Layers)"
        }
        
        response = make_response(jsonify(requirements))
        response.status_code = 402
        response.headers['WWW-Authenticate'] = 'X402' 
        return response

    # SKENARIO 2: SUDAH BAYAR
    else:
        try:
            # Validasi Payload Sederhana
            if len(payment_payload) > 10:
                trace_result = perform_deep_trace(address, chain, max_depth=depth)
                return jsonify({"status": "success", "data": trace_result})
            else:
                return jsonify({"error": "Invalid Payment Payload"}), 403
        except Exception as e:
            return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)


