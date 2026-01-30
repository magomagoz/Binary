import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import logging

# --- CONFIGURAZIONE LOGGING & STATO ---
logging.disable(logging.CRITICAL)
if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0

# --- LOGICA DI TRADING ---

def get_data_from_iq(API, asset, count=60, period=60):
    """Recupera candele reali da IQ invece di YFinance"""
    candles = API.get_candles(asset, period, count, time_lib.time())
    df = pd.DataFrame(candles)
    df.rename(columns={'max': 'high', 'min': 'low', 'from': 'time'}, inplace=True)
    return df

def check_binary_signal(df):
    """Strategia Mean Reversion ottimizzata per 60s"""
    if df.empty: return None
    
    # Calcolo indicatori su dati reali IQ
    bb = ta.bbands(df['close'], length=20, std=2.2)
    rsi = ta.rsi(df['close'], length=7)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    
    curr = df.iloc[-1]
    curr_rsi = rsi.iloc[-1]
    curr_adx = adx['ADX_14'].iloc[-1]
    
    # FILTRO VOLATILITÀ: Evitiamo mercati piatti (ADX < 15) o trend esplosivi (ADX > 35)
    if 15 < curr_adx < 35:
        if curr['close'] <= bb['BBL_20_2.2'].iloc[-1] and curr_rsi < 25:
            return "CALL"
        elif curr['close'] >= bb['BBU_20_2.2'].iloc[-1] and curr_rsi > 75:
            return "PUT"
    return None

# --- UI SIDEBAR ---
st.sidebar.title("🔐 Accesso IQ Option")
email = st.sidebar.text_input("Email")
password = st.sidebar.text_input("Password", type="password")

if st.sidebar.button("Connetti Practice"):
    st.session_state['iq_api'] = IQ_Option(email, password)
    st.session_state['iq_api'].change_balance("PRACTICE")
    check, reason = st.session_state['iq_api'].connect()
    if check: st.sidebar.success("Connesso!")
    else: st.sidebar.error(reason)

st.sidebar.divider()
st.sidebar.subheader("💰 Money Management")
target_profit = st.sidebar.number_input("Target Profit Giornaliero ($)", value=50.0)
stop_loss_limit = st.sidebar.number_input("Stop Loss Giornaliero ($)", value=30.0)
stake = st.sidebar.number_input("Investimento singolo ($)", value=10.0)

# --- BODY PRINCIPALE ---
st.title("🤖 Sentinel Binary Bot v2")

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
