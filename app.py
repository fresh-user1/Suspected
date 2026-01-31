import os
import time
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- CONFIG ---
X402_API_KEY = os.getenv("X402_API_KEY")
X402_SHOP_ID = os.getenv("X402_SHOP_ID")

# API KEYS
BLOCKSCOUT_API_KEY = os.getenv("BLOCKSCOUT_API_KEY") # Base
SOLSCAN_API_KEY = os.getenv("SOLSCAN_API_KEY")       # Solana
# BLOCKCHAIR_API_KEY dihapus dari logika karena ETH/BSC tidak dipakai lagi

# --- HELPER: API HANDLERS ---
def get_chain_data(chain, address):
    """
    Router pintar untuk memilih API Provider yang sesuai
    (Hanya Base dan Solana)
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 1. BASE (Blockscout)
    if chain == 'base':
        url = f"https://base.blockscout.com/api?module=account&action=txlist&address={address}&startblock=0&endblock=99999999&page=1&offset=20&sort=asc&apikey={BLOCKSCOUT_API_KEY}"
        try:
            res = requests.get(url, headers=headers, timeout=5).json()
            return {'type': 'evm_standard', 'data': res.get('result', [])}
        except:
            return None

    # 2. SOLANA (Solscan)
    elif chain == 'solana':
        url = f"https://public-api.solscan.io/account/transactions?account={address}&limit=20"
        headers['token'] = SOLSCAN_API_KEY 
        try:
            res = requests.get(url, headers=headers, timeout=5).json()
            return {'type': 'solana', 'data': res}
        except:
            return None
            
    return None

# --- CORE TRACING LOGIC ---
def perform_deep_trace(start_address, chain, max_depth=10):
    trail = []
    current_wallet = start_address
    
    # Tentukan Decimal & Threshold berdasarkan chain
    if chain == 'solana':
        decimals = 10**9
        whale_threshold = 1000 # 1000 SOL
    else:
        decimals = 10**18
        whale_threshold = 50 # 50 ETH (Base)

    for i in range(max_depth):
        print(f"Tracing Layer {i+1}: {current_wallet} on {chain}")
        
        api_result = get_chain_data(chain, current_wallet)
        time.sleep(1) # Rate limit protection
        
        if not api_result or not api_result['data']:
            break
            
        found_funder = False
        tx_list = api_result['data']
        
        # --- PARSING LOGIC BERDASARKAN TIPE API ---
        
        # A. SOLANA (Solscan)
        if api_result['type'] == 'solana':
            for tx in tx_list:
                # Logic: Cari tx dimana signer != current_wallet (Incoming)
                if tx.get('lamport') and tx.get('signer'):
                    funders = tx['signer']
                    # Biasanya index 0 adalah fee payer/sender
                    if len(funders) > 0:
                        funder = funders[0]
                        
                        if funder != current_wallet:
                            trail.append({
                                "step": i + 1,
                                "wallet": current_wallet,
                                "funded_by": funder,
                                "amount": "Unknown (SOL)", # Solscan free API limitasi detail amount
                                "tx_hash": tx.get('txHash', 'unknown')
                            })
                            current_wallet = funder
                            found_funder = True
                            break

        # B. EVM STANDARD (Base/Blockscout)
        elif api_result['type'] == 'evm_standard':
            for tx in tx_list:
                # Cari Incoming Transaction
                if tx['to'].lower() == current_wallet.lower() and float(tx['value']) > 0:
                    funder = tx['from']
                    amount = float(tx['value']) / decimals
                    
                    trail.append({
                        "step": i + 1,
                        "wallet": current_wallet,
                        "funded_by": funder,
                        "amount": amount,
                        "tx_hash": tx['hash']
                    })
                    
                    current_wallet = funder
                    found_funder = True
                    
                    if amount > whale_threshold:
                        trail.append({"info": "WHALE/EXCHANGE DETECTED", "wallet": funder})
                        return trail
                    break
        
        if not found_funder:
            break
            
    return trail

# --- ROUTES UPDATE ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/payment/create', methods=['POST'])
def create_payment():
    data = request.json
    depth = data.get('depth', 10)
    chain = data.get('chain', 'base') # Default base
    
    # Harga dinamis
    base_price = 0.03 if depth == 10 else 0.055
    
    # Premium charge hanya untuk Solana (Ethereum dihapus)
    if chain == 'solana':
        base_price += 0.02 
        
    payload = {
        "shop_id": X402_SHOP_ID,
        "amount": base_price,
        "currency": "USD",
        "description": f"Trace {chain.upper()} Wallet - {depth} Layers"
    }
    
    # Simulate x402 Response
    return jsonify({
        "status": "pending",
        "payment_url": f"https://x402.com/pay/mock_{chain}_{int(time.time())}",
        "charge_id": f"ch_{int(time.time())}",
        "price": base_price
    })

@app.route('/api/trace/execute', methods=['POST'])
def execute_trace():
    data = request.json
    address = data.get('address')
    chain = data.get('chain')
    depth = int(data.get('depth', 10))
    
    # Mock verify payment logic here...
    
    trace_result = perform_deep_trace(address, chain, max_depth=depth)
    
    return jsonify({"status": "success", "data": trace_result})

if __name__ == '__main__':
    app.run(debug=True)
