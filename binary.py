import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import logging

# --- CONFIGURAZIONE INIZIALE ---
logging.disable(logging.CRITICAL)

if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0
if 'last_scan' not in st.session_state: st.session_state['last_scan'] = None

# --- FUNZIONI TECNICHE ---
def get_data_from_iq(API, asset):
    try:
        # Preleviamo 100 candele da 1 minuto
        candles = API.get_candles(asset, 60, 100, time_lib.time())
        df = pd.DataFrame(candles)
        if df.empty: return pd.DataFrame()
        df.rename(columns={'max': 'high', 'min': 'low', 'from': 'time'}, inplace=True)
        return df
    except: return pd.DataFrame()

def check_binary_signal(df):
    """Logica di filtraggio per Win Rate > 60%"""
    if df.empty or len(df) < 20: return None
    
    # Calcolo indicatori con gestione dinamica dei nomi colonne
    bb = ta.bbands(df['close'], length=20, std=2.2)
    if bb is None: return None
    
    bbl_col = [c for c in bb.columns if 'BBL' in c][0]
    bbu_col = [c for c in bb.columns if 'BBU' in c][0]
    
    rsi = ta.rsi(df['close'], length=7)
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    
    curr_close = df['close'].iloc[-1]
    curr_rsi = rsi.iloc[-1]
    curr_adx = adx_df.iloc[-1, 0] # Colonna ADX_14
    
    # Logica: Mean Reversion solo in bassa/media volatilità
    if 15 < curr_adx < 35:
        if curr_close <= bb[bbl_col].iloc[-1] and curr_rsi < 25:
            return "CALL"
        elif curr_close >= bb[bbu_col].iloc[-1] and curr_rsi > 75:
            return "PUT"
    return None

# --- INTERFACCIA SIDEBAR (STATO LOGGED IN/OUT) ---
st.sidebar.title("🛂 Accesso IQ Option")

if st.session_state['iq_api'] is None:
    st.sidebar.error("🔴 STATO: DISCONNESSO")
    user_mail = st.sidebar.text_input("Email IQ", placeholder="esempio@mail.com")
    user_pass = st.sidebar.text_input("Password IQ", type="password")
    
    if st.sidebar.button("🔌 Connetti Practice"):
        with st.sidebar.status("Connessione in corso..."):
            api = IQ_Option(user_mail, user_pass)
            check, reason = api.connect()
            if check:
                time_lib.sleep(3) # Tempo di caricamento profilo lato server
                api.change_balance("PRACTICE")
                st.session_state['iq_api'] = api
                st.rerun()
            else:
                st.sidebar.error(f"Errore: {reason}")
else:
    st.sidebar.success("🟢 STATO: IN LINEA (PRACTICE)")
    if st.sidebar.button("🚪 Disconnetti Bot"):
        st.session_state['iq_api'] = None
        st.rerun()

# --- MONEY MANAGEMENT ---
st.sidebar.divider()
st.sidebar.subheader("💰 Gestione Capitale")
target_p = st.sidebar.number_input("Target Profit ($)", 5.0, 500.0, 50.0)
stop_l = st.sidebar.number_input("Stop Loss ($)", 5.0, 500.0, 30.0)
stake = st.sidebar.number_input("Investimento per Trade ($)", 1.0, 100.0, 10.0)

# --- DASHBOARD OPERATIVA ---
st.title("🛡️ Sentinel Binary Bot v2.5")

if st.session_state['iq_api'] is None:
    st.info("👋 **Benvenuto!** Il bot è in attesa delle tue credenziali per iniziare il monitoraggio.")
    st.image("https://img.icons8.com/fluency/96/bot.png")
else:
    # Header Metriche
    m1, m2, m3 = st.columns(3)
    m1.metric("Status API", "CONNECTED", "Real-time")
    m2.metric("Profitto Oggi", f"${st.session_state['daily_pnl']:.2f}")
    m3.metric("Trade Chiusi", len(st.session_state['trades']))

    st.divider()

    # Logica Timer e Scansione
    if st.session_state['daily_pnl'] >= target_p:
        st.success("🏆 Target raggiunto! Il bot ha terminato la sessione.")
    elif st.session_state['daily_pnl'] <= -stop_l:
        st.error("🛑 Stop Loss raggiunto. Operatività sospesa.")
    else:
        # Contenitore per il Timer
        timer_placeholder = st.empty()
        
        # Simulazione Scan (Si attiva ogni 60 secondi)
        assets = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY"]
        
        with st.status("🔍 Sentinel sta scansionando i mercati...", expanded=True) as status:
            for asset in assets:
                st.write(f"Analisi tecnica su **{asset}**...")
                df = get_data_from_iq(st.session_state['iq_api'], asset)
                signal = check_binary_signal(df)
                
                if signal:
                    st.toast(f"🔥 SEGNALE {signal} su {asset}!", icon="🚀")
                    # Esecuzione
                    check, id = st.session_state['iq_api'].buy(stake, asset, signal.lower(), 1)
                    if check:
                        st.write(f"✅ Trade {signal} aperto. Scadenza 60s...")
                        time_lib.sleep(62) # Attesa esito
                        res = st.session_state['iq_api'].check_win_v2(id)
                        st.session_state['daily_pnl'] += res
                        st.session_state['trades'].append({
                            "Ora": datetime.now().strftime("%H:%M"),
                            "Asset": asset, "Tipo": signal, "Esito": "WIN" if res > 0 else "LOSS"
                        })
                        st.rerun()
                else:
                    st.write(f"⚪ {asset}: Nessuna condizione ottimale.")
            
            status.update(label="Scansione completata. In attesa del prossimo ciclo.", state="complete")

    # Visualizzazione Cronologia
    if st.session_state['trades']:
        st.subheader("📜 Ultime Operazioni")
        st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)

