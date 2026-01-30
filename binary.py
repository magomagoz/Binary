import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import pytz
import logging
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sentinel AI - Binary Bot", layout="wide")

# --- CONFIGURAZIONE CREDENZIALI ---
try:
    IQ_EMAIL = st.secrets["IQ_EMAIL"]
    IQ_PASS = st.secrets["IQ_PASS"]
    TELE_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELE_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
except:
    st.error("Configura correttamente st.secrets!")

# --- CONFIGURAZIONE LOGGING & STATO INIZIALE ---
logging.disable(logging.CRITICAL)

# Inizializzazione rigorosa di TUTTE le variabili di stato per evitare KeyError
if 'iq_api' not in st.session_state: st.session_state['iq_api'] = None
if 'trades' not in st.session_state: st.session_state['trades'] = []
if 'daily_pnl' not in st.session_state: st.session_state['daily_pnl'] = 0.0
if 'trading_attivo' not in st.session_state: st.session_state['trading_attivo'] = False
if 'signal_history' not in st.session_state: st.session_state['signal_history'] = pd.DataFrame()
if 'sentinel_logs' not in st.session_state: st.session_state['sentinel_logs'] = []
if 'last_scan_status' not in st.session_state: st.session_state['last_scan_status'] = "In attesa di connessione..."

# --- MAPPA ASSET ---
asset_map = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "EUR/JPY": "EURJPY",
    "USD/JPY": "USDJPY",
    "AUD/USD": "AUDUSD",
    "USD/CHF": "USDCHF",
    "NZD/USD": "NZDUSD",
    "EUR/GBP": "EURGBP",
    "USD/CAD": "USDCAD"
}

# --- FUNZIONI UTILI ---
def get_now_rome():
    return datetime.now(pytz.timezone('Europe/Rome'))

def send_telegram_msg(message):
    # Inserire qui logica requests.post per Telegram
    st.write(f"📲 Telegram Log: {message}")

def get_session_status():
    h = datetime.now(pytz.utc).hour
    return {
        "Tokyo": 0 <= h < 9,
        "Londra": 8 <= h < 17,
        "New York": 13 <= h < 22
    }

# --- FUNZIONI TECNICHE IQ OPTION ---
def get_data_from_iq(API, asset):
    try:
        candles = API.get_candles(asset, 60, 100, time_lib.time())
        df = pd.DataFrame(candles)
        if df.empty: return pd.DataFrame()
        df.rename(columns={'max': 'high', 'min': 'low', 'from': 'time'}, inplace=True)
        return df
    except: 
        return pd.DataFrame()

def get_iq_currency_strength(API):
    try:
        pairs = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"]
        weights = {}
        for pair in pairs:
            candles = API.get_candles(pair, 60, 60, time_lib.time())
            if candles:
                df = pd.DataFrame(candles)
                change = ((df['close'].iloc[-1] - df['open'].iloc[0]) / df['open'].iloc[0]) * 100
                weights[pair] = change
        
        strength = {
            "USD 🇺🇸": (-weights.get("EURUSD",0) - weights.get("GBPUSD",0) + weights.get("USDJPY",0) + weights.get("USDCHF",0) + weights.get("USDCAD",0) - weights.get("AUDUSD",0) - weights.get("NZDUSD",0)) / 7,
            "EUR 🇪🇺": (weights.get("EURUSD",0)) * 1.2,
            "GBP 🇬🇧": (weights.get("GBPUSD",0)) * 1.2,
            "JPY 🇯🇵": (-weights.get("USDJPY",0)),
            "CHF 🇨🇭": (-weights.get("USDCHF",0)),
            "AUD 🇦🇺": (weights.get("AUDUSD",0)),
            "CAD 🇨🇦": (-weights.get("USDCAD",0)),
            "NZD 🇳🇿": (weights.get("NZDUSD",0))
        }
        return pd.Series(strength).sort_values(ascending=False)
    except:
        return pd.Series(dtype=float)

def check_binary_signal(df):
    if df.empty or len(df) < 20: return None, {}
    
    # Calcolo Indicatori
    bb = ta.bbands(df['close'], length=20, std=2.2)
    rsi = ta.rsi(df['close'], length=7).iloc[-1]
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    adx = adx_df['ADX_14'].iloc[-1]
    
    bbl = bb.iloc[-1, 0] # Lower Band
    bbu = bb.iloc[-1, 2] # Upper Band
    curr_close = df['close'].iloc[-1]
    
    # Snapshot dei valori per analisi
    stats = {"RSI": round(rsi, 2), "ADX": round(adx, 2), "Price": curr_close, "BB_Low": round(bbl, 5), "BB_Up": round(bbu, 5)}

    # Logica Segnale
    if 15 < adx < 35:
        if curr_close <= bbl and rsi < 25:
            return "CALL", stats
        elif curr_close >= bbu and rsi > 75:
            return "PUT", stats
            
    return None, stats

# --- SIDEBAR: ACCESSO E CONFIGURAZIONE ---
st.sidebar.title("🔐 Sentinel AI Access")

if st.session_state['iq_api'] is None:
    st.sidebar.error("🔴 STATO: DISCONNESSO")
    user_mail = st.sidebar.text_input("Email IQ", value=IQ_EMAIL)
    user_pass = st.sidebar.text_input("Password IQ", type="password", value=IQ_PASS)
    if st.sidebar.button("🔌 Connetti Practice", use_container_width=True):
        api = IQ_Option(user_mail, user_pass)
        check, reason = api.connect()
        if check:
            api.change_balance("PRACTICE")
            st.session_state['iq_api'] = api
            st.session_state['trading_attivo'] = True
            st.rerun()
        else:
            st.sidebar.error(f"Errore: {reason}")
else:
    st.sidebar.success("🟢 STATO: IN LINEA")
    if st.sidebar.button("🚪 Esci e Ferma Bot", use_container_width=True):
        st.session_state['iq_api'] = None
        st.session_state['trading_attivo'] = False
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💰 Money Management")
stake = st.sidebar.number_input("Stake Singolo (€)", value=20.0)
target_profit = st.sidebar.number_input("Target Profit (€)", value=40.0)
stop_loss_limit = st.sidebar.number_input("Stop Loss (€)", value=10.0)

st.sidebar.divider()
st.sidebar.subheader("🛡️ Kill-Switch")
if st.session_state['trading_attivo']:
    if st.sidebar.button("🛑 STOP TOTALE", type="primary", use_container_width=True):
        st.session_state['trading_attivo'] = False
        st.rerun()
else:
    if st.sidebar.button("🚀 RIATTIVA SISTEMA", use_container_width=True):
        st.session_state['trading_attivo'] = True
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🌍 Sessioni")
for s_name, is_open in get_session_status().items():
    color = "🟢" if is_open else "🔴"
    st.sidebar.markdown(f"**{s_name}**: {'Open' if is_open else 'Closed'} {color}")

with st.sidebar.popover("🗑️ Reset Cronologia"):
    if st.button("CANCELLA ORA"):
        st.session_state['trades'] = []
        st.rerun()

# --- MAIN INTERFACE ---
st.image("banner.png", use_container_width=True)
#st.title("🛰️ Sentinel AI - Binary Execution")

# Logica Autorun
if st.session_state['iq_api'] and st.session_state['trading_attivo']:
    if st.session_state['daily_pnl'] >= target_profit:
        st.balloons()
        st.success("🎯 Target raggiunto! Bot fermo.")
        st.session_state['trading_attivo'] = False
    elif st.session_state['daily_pnl'] <= -stop_loss_limit:
        st.error("🛑 Stop Loss raggiunto. Bot fermo.")
        st.session_state['trading_attivo'] = False
    else:
        API = st.session_state['iq_api']
        assets_to_scan = ["EURUSD", "GBPUSD", "EURJPY", "AUDUSD"]
        
        with st.status("🔍 Scansione Sentinel in corso...", expanded=False) as status:
            for asset in assets_to_scan:
                st.write(f"Verifica {asset}...")
                df = get_data_from_iq(API, asset)
                signal = check_binary_signal(df)
                
                if signal:
                    # SOUND ALERT
                    st.markdown("""<audio autoplay><source src="https://codeskulptor-demos.commondatastorage.googleapis.com/pang/arrow.mp3" type="audio/mp3"></audio>""", unsafe_allow_html=True)
                    st.warning(f"🔥 SEGNALE {signal} SU {asset}!")
                    
                    check, id = API.buy(stake, asset, signal.lower(), 1)
    
                    if check:
                        st.info(f"✅ Ordine inviato. ID: {id}")
                        time_lib.sleep(62)
                        res = API.check_win_v2(id)
                        st.session_state['daily_pnl'] += res
                        st.session_state['trades'].append({
                            "Ora": get_now_rome().strftime("%H:%M:%S"),
                            "Asset": asset,
                            "Tipo": signal,
                            "Prezzo Entrata": stats["Price"],
                            "RSI": stats["RSI"],
                            "ADX": stats["ADX"],
                            "BB_Limit": stats["BB_Low"] if signal == "CALL" else stats["BB_Up"],
                            "Esito": "WIN" if res > 0 else "LOSS",
                            "Profitto": res
                        })
                        st.rerun()
            status.update(label="✅ Scansione completata. In attesa...", state="complete")
else:
    if not st.session_state['iq_api']:
        st.info("👋 Effettua il login per attivare il sistema.")
    else:
        st.warning("⚠️ Bot in pausa.")

# --- GRAFICO IN TEMPO REALE ---
st.divider()
st.subheader(f"📈 Grafico con BB e RSI (1m)")
selected_label = st.selectbox("Seleziona Asset per Grafico", list(asset_map.keys()))
pair = asset_map[selected_label]

if st.session_state['iq_api']:
    try:
        candles_data = st.session_state['iq_api'].get_candles(pair, 60, 100, time_lib.time())
        df_rt = pd.DataFrame(candles_data)
        if not df_rt.empty:
            df_rt.rename(columns={'max': 'high', 'min': 'low', 'open': 'open', 'close': 'close', 'from': 'time'}, inplace=True)
            df_rt['time'] = pd.to_datetime(df_rt['time'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Europe/Rome')
            df_rt.set_index('time', inplace=True)
            
            # Indicatori
            bb = ta.bbands(df_rt['close'], length=20, std=2)
            df_rt = pd.concat([df_rt, bb], axis=1)
            df_rt['rsi'] = ta.rsi(df_rt['close'], length=14)
            c_up = [c for c in df_rt.columns if "BBU" in c.upper()][0]
            c_low = [c for c in df_rt.columns if "BBL" in c.upper()][0]

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            fig.add_trace(go.Candlestick(x=df_rt.index, open=df_rt['open'], high=df_rt['high'], low=df_rt['low'], close=df_rt['close'], name='Prezzo'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_rt.index, y=df_rt[c_up], line=dict(color='gray', width=1), name='BB Upper'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_rt.index, y=df_rt[c_low], line=dict(color='gray', width=1), fill='tonexty', name='BB Lower'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_rt.index, y=df_rt['rsi'], line=dict(color='yellow'), name='RSI'), row=2, col=1)
            fig.update_layout(height=500, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
    except:
        st.error("Errore caricamento grafico.")

# --- METRICHE DINAMICHE SOTTO IL GRAFICO ---
st.markdown("### 🔍 Sentinel Real-Time Oscillators")
c1, c2, c3, c4 = st.columns(4)

# Calcolo valori attuali
curr_p = df_rt['close'].iloc[-1]
curr_rsi = df_rt['rsi'].iloc[-1]
curr_adx = df_rt['adx'].iloc[-1] # Assicurati di aver calcolato ADX nel df
bb_upper = df_rt[c_up].iloc[-1]
bb_lower = df_rt[c_low].iloc[-1]

# Visualizzazione
c1.metric("Prezzo", f"{curr_p:.5f}")

c2.metric("RSI (7)", f"{curr_rsi:.2f}", 
          delta="IPER-COMPRATO" if curr_rsi > 75 else "IPER-VENDUTO" if curr_rsi < 25 else "NEUTRO",
          delta_color="inverse" if curr_rsi > 75 or curr_rsi < 25 else "normal")

c3.metric("ADX (14)", f"{curr_adx:.2f}", 
          delta="FILTRO OK" if 15 < curr_adx < 35 else "NO TRADE",
          delta_color="normal" if 15 < curr_adx < 35 else "inverse")

# Distanza dalle Bande
dist_up = bb_upper - curr_p
dist_low = curr_p - bb_lower
c4.metric("Distanza BB", f"{min(dist_up, dist_low):.5f}", 
          delta="TOCCATA" if dist_up <= 0 or dist_low <= 0 else "DISTANTE")

# --- CURRENCY STRENGTH ---
st.divider()
st.subheader("⚡ Currency Strength (IQ Option Data)")
if st.session_state['iq_api']:
    s_data = get_iq_currency_strength(st.session_state['iq_api'])
    if not s_data.empty:
        cols = st.columns(len(s_data))
        for i, (curr, val) in enumerate(s_data.items()):
            bg = "rgba(0,255,0,0.2)" if val > 0 else "rgba(255,0,0,0.2)"
            cols[i].markdown(f"<div style='text-align:center; background:{bg}; padding:10px; border-radius:5px;'><b>{curr}</b><br>{val:.2f}%</div>", unsafe_allow_html=True)

# --- REPORTING ---
st.divider()
st.subheader(f"📊 Risultato Sessione: € {st.session_state['daily_pnl']:.2f}")
if st.session_state['trades']:
    st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)

# Auto-refresh ogni 60s
st.sidebar.markdown("""<div style="background:#222; height:5px; width:100%; border-radius:10px; overflow:hidden;"><div style="background:red; height:100%; width:100%; animation: fill 60s linear infinite;"></div></div><style>@keyframes fill {0% {width: 0%;} 100% {width: 100%;}}</style>""", unsafe_allow_html=True)
time_lib.sleep(60)
st.rerun()

st.markdown("---")
st.subheader("🔬 Analisi Tecnica Post-Sessione")

if st.session_state['trades']:
    df_analysis = pd.DataFrame(st.session_state['trades'])
    
    # Analisi efficacia indicatori
    avg_rsi_win = df_analysis[df_analysis['Esito'] == 'WIN']['RSI'].mean()
    avg_adx_win = df_analysis[df_analysis['Esito'] == 'WIN']['ADX'].mean()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("RSI Medio (WIN)", f"{avg_rsi_win:.2f}")
    c2.metric("ADX Medio (WIN)", f"{avg_adx_win:.2f}")
    c3.metric("Segnali Totali", len(df_analysis))

    # Grafico a dispersione per vedere dove si concentrano i successi
    fig_an = go.Figure()
    fig_an.add_trace(go.Scatter(
        x=df_analysis['RSI'], y=df_analysis['ADX'],
        mode='markers',
        marker=dict(color=['green' if e == 'WIN' else 'red' for e in df_analysis['Esito']], size=12),
        text=df_analysis['Asset']
    ))
    fig_an.update_layout(title="Distribuzione Segnali (RSI vs ADX)", xaxis_title="RSI", yaxis_title="ADX", template="plotly_dark")
    st.plotly_chart(fig_an, use_container_width=True)
else:
    st.info("In attesa di dati per l'analisi statistica...")
