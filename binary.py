import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import pytz
import logging


# --- CONFIGURAZIONE PAGINA E BANNER ---
st.set_page_config(page_title="Sentinel AI - Binary Bot", layout="wide")

# Inserisci qui l'URL dell'immagine del banner che abbiamo creato
st.image("https://i.imgur.com/your_banner_link.png", use_container_width=True)


# --- CONFIGURAZIONE ---
logging.disable(logging.CRITICAL)

if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0

# --- FUNZIONE ORARI MERCATI ---
def is_market_open():
    """Controlla se i mercati Forex sono aperti (Lun-Ven) e identifica le sessioni"""
    now_utc = datetime.now(pytz.utc)
    weekday = now_utc.weekday() # 0=Lun, 4=Ven, 5=Sab, 6=Dom
    
    if weekday >= 5: # Mercati chiusi nel weekend
        return False, "Mercati Chiusi (Weekend)"
    
    hour = now_utc.hour
    # Sessioni (UTC): Tokyo (00-09), Londra (08-17), New York (13-22)
    if (0 <= hour <= 9) or (8 <= hour <= 17) or (13 <= hour <= 22):
        return True, "Mercati Aperti"
    
    return False, "Pausa Mercato (Bassa Volatilità)"

# --- FUNZIONI TECNICHE ---
def get_data_from_iq(API, asset):
    try:
        candles = API.get_candles(asset, 60, 100, time_lib.time())
        df = pd.DataFrame(candles)
        if df.empty: return pd.DataFrame()
        df.rename(columns={'max': 'high', 'min': 'low', 'from': 'time'}, inplace=True)
        return df
    except: return pd.DataFrame()

def is_market_open():
    """Monitoraggio Sessioni: Tokyo, Londra, New York"""
    now_utc = datetime.now(pytz.utc)
    if now_utc.weekday() >= 5: 
        return False, "Mercati Chiusi (Weekend)"
    
    hour = now_utc.hour
    if (0 <= hour <= 9) or (8 <= hour <= 17) or (13 <= hour <= 22):
        return True, "Mercati Aperti (Sessione Attiva)"
    return False, "Pausa Mercato (Volatilità Insufficiente)"

# --- LOGICA SEGNALE ---
def check_binary_signal(df):
    if df.empty or len(df) < 20: return None
    bb = ta.bbands(df['close'], length=20, std=2.2)
    if bb is None: return None
    
    bbl_col = [c for c in bb.columns if 'BBL' in c][0]
    bbu_col = [c for c in bb.columns if 'BBU' in c][0]
    rsi = ta.rsi(df['close'], length=7)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14).iloc[-1, 0]
    
    curr_close = df['close'].iloc[-1]
    curr_rsi = rsi.iloc[-1]
    curr_adx = adx_df.iloc[-1, 0]

    curr = df.iloc[-1]

    # Filtro Operativo
    if 15 < curr_adx < 35:
        if curr_close <= bb[bbl_col].iloc[-1] and curr_rsi < 25:
            return "CALL"
        elif curr_close >= bb[bbu_col].iloc[-1] and curr_rsi > 75:
            return "PUT"
    return None

# --- SIDEBAR ACCESS ---
st.sidebar.title("🛂 Sentinel AI Bynary")
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

# --- AREA OPERATIVA ---
st.title("🛡️ Sentinel - AI Binary Bot")

open_status, status_msg = is_market_open()

if st.session_state['iq_api'] is None:
    st.info("Benvenuto in Sentinel AI. Effettua il login per attivare l'analisi dei mercati.")
else:
    # Metriche
    c1, c2, c3 = st.columns(3)
    c1.metric("Mercato", "OPEN" if open_status else "CLOSED", status_msg)
    c2.metric("Sessione PnL", f"${st.session_state['daily_pnl']:.2f}")
    c3.metric("Segnali", len(st.session_state['trades']))

    if not open_status:
        st.warning(f"⚠️ Operatività sospesa: {status_msg}")
    else:
        if st.button("🚀 AVVIA CICLO AUTOMATICO"):
            while True: # Ciclo infinito di scansione
                assets = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY"]
                
                with st.status("🔍 Scansione in corso...", expanded=False) as s:
                    for asset in assets:
                        df = st.session_state['iq_api'].get_candles(asset, 60, 100, time_lib.time())
                        df = pd.DataFrame(df).rename(columns={'max':'high','min':'low','from':'time'})
                        signal = check_binary_signal(df)
                        
                        if signal:
                            s.update(label=f"🔥 SEGNALE {signal} su {asset}!", state="running")

                    		#stake = 10 # Puoi legarlo a un input
                            check, id = st.session_state['iq_api'].buy(stake, asset, signal.lower(), 1)
                            if check:
                        				st.write(f"✅ Ordine {signal} inviato. Attesa 60s...")
                                time_lib.sleep(62)
                                res = st.session_state['iq_api'].check_win_v2(id)
                                st.session_state['daily_pnl'] += res
				                        st.session_state['trades'].append({
        			                    "Ora": datetime.now().strftime("%H:%M"),
              			              "Asset": asset, "Tipo": signal, "Esito": "WIN" if res > 0 else "LOSS"
                    				    })
                        				st.rerun()

            								status.update(label="Scansione completata. Prossimo ciclo tra 60s.", state="complete")
            								
                # --- BARRA DEI 60 SECONDI (PROGRESSIVA) ---
                st.write("⏳ Prossimo check tra:")
                progress_bar = st.progress(0)
                for percent_complete in range(100):
                    time_lib.sleep(0.6) # 0.6s * 100 = 60 secondi
                    progress_bar.progress(percent_complete + 1)
                st.rerun()

	    else:
        st.warning(f"Operatività dormiente: {status_msg}")

if st.session_state['trades']:
    st.subheader("📜 Cronologia Sessione")
    st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)
    




