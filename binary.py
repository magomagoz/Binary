import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import logging

# Inizializzazione Session State
if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0

def get_data_from_iq(API, asset):
    try:
        candles = API.get_candles(asset, 60, 100, time_lib.time())
        df = pd.DataFrame(candles)
        if df.empty: return pd.DataFrame()
        df.rename(columns={'max': 'high', 'min': 'low', 'from': 'time'}, inplace=True)
        return df
    except: return pd.DataFrame()

def check_binary_signal(df):
    if df.empty or len(df) < 20: return None
    
    # Calcolo pulito con nomi colonne standardizzati
    bb = ta.bbands(df['close'], length=20, std=2.2)
    if bb is None or bb.empty: return None
    
    # Risoluzione dinamica nomi colonne per evitare KeyError
    bbl_col = [c for c in bb.columns if 'BBL' in c][0]
    bbu_col = [c for c in bb.columns if 'BBU' in c][0]
    
    rsi = ta.rsi(df['close'], length=7)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    
    curr = df.iloc[-1]
    curr_rsi = rsi.iloc[-1]
    curr_adx = adx.iloc[-1, 0] # ADX_14
    
    if 15 < curr_adx < 35:
        if curr['close'] <= bb[bbl_col].iloc[-1] and curr_rsi < 25:
            return "CALL"
        elif curr['close'] >= bb[bbu_col].iloc[-1] and curr_rsi > 75:
            return "PUT"
    return None

# --- SIDEBAR (Stato Connessione) ---
st.sidebar.title("🔐 Controllo Accesso")
if st.session_state['iq_api'] is None:
    st.sidebar.warning("⚠️ Stato: DISCONNESSO")
    email = st.sidebar.text_input("Email")
    password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Connetti Practice"):
        api = IQ_Option(email, password)
        check, reason = api.connect()
        if check:
            time_lib.sleep(2) # Buffer critico per caricamento profilo
            api.change_balance("PRACTICE")
            st.session_state['iq_api'] = api
            st.rerun()
        else:
            st.sidebar.error(f"Errore: {reason}")
else:
    st.sidebar.success("✅ Stato: CONNESSO (PRACTICE)")
    if st.sidebar.button("Esci / Reset"):
        st.session_state['iq_api'] = None
        st.rerun()

# --- MONEY MANAGEMENT ---
st.sidebar.divider()
st.sidebar.subheader("💰 Gestione")
target_p = st.sidebar.number_input("Target Profit ($)", value=50.0)
stop_l = st.sidebar.number_input("Stop Loss ($)", value=30.0)
stake = st.sidebar.number_input("Stake ($)", value=10.0)

# --- AREA OPERATIVA ---
st.title("🤖 Sentinel Binary Bot v2")

if st.session_state['iq_api'] is None:
    st.info("👋 Benvenuto. Per iniziare, inserisci le credenziali IQ Option nella sidebar.")
else:
    # Mostra indicatori di sistema online
    col1, col2, col3 = st.columns(3)
    col1.metric("Sistema", "ONLINE", delta="Pronto")
    col2.metric("Saldo Sessione", f"${st.session_state['daily_pnl']:.2f}")
    col3.metric("Trade Eseguiti", len(st.session_state['trades']))

    if st.button("🚀 AVVIA SCANSIONE"):
        if st.session_state['daily_pnl'] >= target_p or st.session_state['daily_pnl'] <= -stop_l:
            st.warning("Limiti giornalieri raggiunti. Operatività bloccata.")
        else:
            assets = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY"]
            for asset in assets:
                with st.status(f"Analizzando {asset}...", expanded=False):
                    df = get_data_from_iq(st.session_state['iq_api'], asset)
                    signal = check_binary_signal(df)
                    if signal:
                        st.write(f"Segnale {signal} rilevato! Invio ordine...")
                        check, id = st.session_state['iq_api'].buy(stake, asset, signal.lower(), 1)
                        if check:
                            st.write("Ordine inviato. Attendendo scadenza (62s)...")
                            time_lib.sleep(62)
                            res = st.session_state['iq_api'].check_win_v2(id)
                            st.session_state['daily_pnl'] += res
                            st.session_state['trades'].append({
                                "Asset": asset, "Tipo": signal, "Esito": "WIN" if res > 0 else "LOSS"
                            })
                            st.rerun()
                    else:
                        st.write("Nessuna opportunità valida.")

# Tabella riassuntiva
if st.session_state['trades']:
    st.table(st.session_state['trades'])
