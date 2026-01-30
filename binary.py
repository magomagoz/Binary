import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import pytz
from iqoptionapi.stable_api import IQ_Option
import logging

# --- CONFIGURAZIONE LOGGING & STATO ---
logging.disable(logging.CRITICAL)
if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0

# --- FUNZIONE DI CONNESSIONE ---
def connect_to_iq(email, password):
    # Rimuovi i log eccessivi per pulizia
    logging.disable(logging.CRITICAL)
    
    API = IQ_Option(email, password)
    API.change_balance("PRACTICE") # Forza l'uso del conto DEMO
    
    check, reason = API.connect()
    if check:
        st.sidebar.success("✅ Connesso a IQ Option (PRACTICE)")
        return API
    else:
        st.sidebar.error(f"❌ Errore: {reason}")
        return None

# --- LOGICA DI ESECUZIONE TRADE ---
def execute_binary_trade(API, asset, direction, amount, duration=1):
    """
    Esegue il trade su IQ Option.
    duration = minuti (1, 5, etc.)
    """
    if API:
        # Converte la direzione per l'API
        action = "buy" if direction == "CALL" else "sell"
        
        # Esegue l'ordine
        check, id = API.buy(amount, asset, action, duration)
        if check:
            return True, id
        else:
            return False, "Errore apertura"
    return False, "API non connessa"

# --- FUNZIONE ORARI MERCATI ---
def is_market_open():
    """Monitoraggio Sessioni: Tokyo, Londra, New York"""
    now_utc = datetime.now(pytz.utc)
    if now_utc.weekday() >= 5: 
        return False, "Mercati Chiusi (Weekend)"
    
    hour = now_utc.hour
    # Sessioni (UTC): Tokyo (00-09), Londra (08-17), New York (13-22)
    if (0 <= hour <= 9) or (8 <= hour <= 17) or (13 <= hour <= 22):
        return True, "Mercati Aperti (Sessione Attiva)"
    return False, "Pausa Mercato (Volatilità Insufficiente)"

# --- FUNZIONI TECNICHE ---
def get_data_from_iq(API, asset):
    try:
        candles = API.get_candles(asset, 60, 100, time_lib.time())
        df = pd.DataFrame(candles)
        if df.empty: return pd.DataFrame()
        df.rename(columns={'max': 'high', 'min': 'low', 'from': 'time'}, inplace=True)
        return df
    except: 
        return pd.DataFrame()

# --- LOGICA SEGNALE ---
def check_binary_signal(df):
    if df.empty or len(df) < 20: return None
    bb = ta.bbands(df['close'], length=20, std=2.2)
    if bb is None: return None
    
    bbl_col = [c for c in bb.columns if 'BBL' in c][0]
    bbu_col = [c for c in bb.columns if 'BBU' in c][0]
    rsi = ta.rsi(df['close'], length=7)
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    
    curr_close = df['close'].iloc[-1]
    curr_rsi = rsi.iloc[-1]
    curr_adx = adx_df.iloc[-1, 0]

    # Filtro Operativo
    if 15 < curr_adx < 35:
        if curr_close <= bb[bbl_col].iloc[-1] and curr_rsi < 25:
            return "CALL"
        elif curr_close >= bb[bbu_col].iloc[-1] and curr_rsi > 75:
            return "PUT"
    return None

# --- CONFIGURAZIONE ---
logging.disable(logging.CRITICAL)

if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0

# --- SIDEBAR ACCESS ---
st.sidebar.title("🔐 Accesso IQ Option")
if st.session_state['iq_api'] is None:
    st.sidebar.error("🔴 STATO: DISCONNESSO")
    user_mail = st.sidebar.text_input("Email IQ")
    user_pass = st.sidebar.text_input("Password IQ", type="password")
    if st.sidebar.button("🔌 Connetti Practice"):
        api = IQ_Option(user_mail, user_pass)
        check, reason = api.connect()
        if check:
            time_lib.sleep(3)
            api.change_balance("PRACTICE")
            st.session_state['iq_api'] = api
            st.rerun()
        else:
            st.sidebar.error(f"Errore: {reason}")
else:
    st.sidebar.success("🟢 STATO: IN LINEA")
    if st.sidebar.button("🚪 Esci"):
        st.session_state['iq_api'] = None
        st.rerun()

    # --- BARRA DEI 60 SECONDI (PROGRESSIVA) ---
    st.write("⏳ Prossimo check tra:")
    progress_bar = st.progress(0)
    for percent_complete in range(100):
        time_lib.sleep(0.6) # 0.6s * 100 = 60 secondi
        progress_bar.progress(percent_complete + 1)
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💰 Money Management")
target_profit = st.sidebar.number_input("Target Profit Giornaliero ($)", value=50.0)
stop_loss_limit = st.sidebar.number_input("Stop Loss Giornaliero ($)", value=30.0)
stake = st.sidebar.number_input("Investimento singolo ($)", value=10.0)

# --- CONFIGURAZIONE PAGINA E BANNER ---
# Banner logic
banner_path = "banner1.png"
st.image(banner_path, use_container_width=True)
st.header("🛰️ Sentinel AI - Binary Bot 🛰️")

# Controllo limiti di gestione capitale
if st.session_state['daily_pnl'] >= target_profit:
    st.balloons()
    st.success("🎯 Target raggiunto! Bot in pausa per oggi.")
elif st.session_state['daily_pnl'] <= -stop_loss_limit:
    st.error("🛑 Stop Loss raggiunto. Bot fermato per sicurezza.")
else:
    if st.button("🚀 AVVIA SCANSIONE CICLICA (1m)"):
        API = st.session_state['iq_api']
        if API:
            assets = ["EURUSD", "GBPUSD", "EURJPY", "AUDUSD"] # Lista asset da monitorare
            
            with st.spinner("Scansione attiva..."):
                for asset in assets:
                    st.write(f"Analizzando {asset}...")
                    df = get_data_from_iq(API, asset)
                    signal = check_binary_signal(df)
                    
                    if signal:
                        st.warning(f"🔥 Segnale {signal} trovato su {asset}!")
                        # ESECUZIONE REALE
                        check, id = API.buy(stake, asset, signal.lower(), 1)
                        if check:
                            st.info(f"✅ Trade aperto! ID: {id}")
                            # Aspettiamo il risultato (60s + piccolo buffer)
                            time_lib.sleep(62)
                            result = API.check_win_v2(id)
                            st.session_state['daily_pnl'] += result
                            st.session_state['trades'].append({
                                "Ora": datetime.now().strftime("%H:%M"),
                                "Asset": asset,
                                "Tipo": signal,
                                "Esito": "WIN" if result > 0 else "LOSS",
                                "Profitto": result
                            })
        else:
            st.warning("Connetti l'API prima di iniziare.")

# --- REPORTING ---
st.divider()
st.subheader(f"Risultato Sessione: ${st.session_state['daily_pnl']:.2f}")
if st.session_state['trades']:
    st.table(pd.DataFrame(st.session_state['trades']))
                
if st.session_state['trades']:
    st.subheader("📜 Cronologia Sessione")
    st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)



