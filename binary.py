import streamlit as st
from iqoptionapi.stable_api import IQ_Option
import time
import threading

# --- CONFIGURAZIONE MINIMA ---
st.set_page_config(page_title="Micro Test IQ", layout="centered")

# Inizializzazione Sessione
if 'iq_api' not in st.session_state:
    st.session_state['iq_api'] = None

# --- FUNZIONI DI ESECUZIONE (FONDAMENTALI) ---
def smart_buy_test(API, asset):
    """Prova a comprare CALL (Su) su Digital o Binary."""
    try:
        # Tentativo 1: Digital (Spesso più stabile)
        check, id = API.buy_digital_spot(asset, 1, "call", 1)
        if check and isinstance(id, int):
            return True, id, "Digital"
        
        # Tentativo 2: Binary
        check, id = API.buy(1, asset, "call", 1)
        if check:
            return True, id, "Binary"
            
    except Exception as e:
        print(f"Errore: {e}")
    
    return False, None, "Errore"

def buy_with_timeout(API, asset):
    """Wrapper con timeout per evitare che l'app si blocchi."""
    result = [False, None, "Timeout"]
    
    def target():
        result[0], result[1], result[2] = smart_buy_test(API, asset)
    
    # Thread separato per l'acquisto
    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=20) # Timeout lungo (20s) per sicurezza
    
    if t.is_alive():
        return False, None, "API_LOCKED"
    
    return result[0], result[1], result[2]

# --- INTERFACCIA ---
st.title("🔌 IQ Option: Connectivity Test")

# 1. LOGIN
if st.session_state['iq_api'] is None:
    st.subheader("Login")
    try:
        email = st.text_input("Email", value=st.secrets["IQ_EMAIL"])
        pwd = st.text_input("Password", type="password", value=st.secrets["IQ_PASS"])
    except:
        email = st.text_input("Email")
        pwd = st.text_input("Password", type="password")
        
    if st.button("Connetti"):
        with st.spinner("Connessione in corso..."):
            api = IQ_Option(email, pwd)
            check, reason = api.connect()
            if check:
                api.change_balance("PRACTICE") 
                st.session_state['iq_api'] = api
                st.success("✅ Connesso!")
                st.rerun()
            else:
                st.error(f"Errore Login: {reason}")

else:
    # 2. PANNELLO DI CONTROLLO
    API = st.session_state['iq_api']
    
    if not API.check_connect():
        st.warning("Riconnessione...")
        API.connect()
    
    balance = API.get_balance()
    mode = API.get_balance_mode()
    
    st.info(f"🟢 Connesso come: **{mode}** | Saldo: **€ {balance:,.2f}**")
    
    st.divider()
    
    st.write("Premi il pulsante per lanciare un ordine di prova (CALL) su EURUSD.")
    
    if st.button("🚀 LANCIA TEST TRADE (1€)", type="primary"):
        asset = "EURUSD"
        
        # A. Ping Server (CORRETTO: Usiamo get_balance che esiste sicuramente)
        with st.spinner("Ping al server..."):
            API.get_balance() # Questo comando sveglia la connessione senza dare errori
            time.sleep(0.5)
            
        # B. Invio Ordine
        with st.spinner(f"Invio ordine su {asset}..."):
            success, trade_id, type_name = buy_with_timeout(API, asset)
            
        # C. Gestione Risultato Immediato
        if type_name == "API_LOCKED":
            st.error("❌ ERRORE CRITICO: Il server IQ non ha risposto in 20 secondi (API LOCKED).")
        
        elif success:
            st.success(f"✅ Ordine {type_name} ACCETTATO! ID: {trade_id}")
            
            # D. Attesa Scadenza
            prog_bar = st.progress(0)
            status_text = st.empty()
            
            for i in range(63): 
                time.sleep(1)
                prog_bar.progress((i+1)/63)
                status_text.text(f"⏳ Attesa esito... {63-(i+1)}s")
            
            # E. Controllo Vincita
            profit = 0
            if type_name == "Binary":
                profit = API.check_win_v2(trade_id)
            else:
                profit = API.get_digital_prox_result(trade_id)
                
            if profit > 0:
                st.balloons()
                st.success(f"💰 WIN! Profitto: € {profit}")
            elif profit < 0:
                st.error(f"📉 LOSS. Perso: € {profit}")
            else:
                st.warning("⚪ PAREGGIO / Nessun dato")
                
        else:
            st.warning("⚠️ Ordine non eseguito (Mercato chiuso o errore generico).")

    st.divider()
    if st.button("Disconnetti"):
        st.session_state['iq_api'] = None
        st.rerun()
