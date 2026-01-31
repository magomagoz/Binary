import streamlit as st
import pandas as pd
import pandas_ta as ta
import requests # Assicurati che sia tra gli import in alto
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

def send_telegram_msg(message):
    try:
        # Usa direttamente le variabili caricate dai secrets all'inizio
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELE_CHAT_ID, 
            "text": message, 
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=5)
        if not response.ok:
            st.sidebar.error(f"Errore Telegram: {response.text}")
        else:
            st.write(f"📲 Invio messaggio Telegram: {message}")       
    
    except Exception as e:
        st.sidebar.error(f"Errore connessione Telegram: {e}")

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
if 'sim_pnl' not in st.session_state: st.session_state['sim_pnl'] = 0.0
if 'confirm_real' not in st.session_state: st.session_state['confirm_real'] = False
if 'last_market_alert' not in st.session_state: 
    st.session_state['last_market_alert'] = ""
if 'last_daily_report_date' not in st.session_state: 
    st.session_state['last_daily_report_date'] = None

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

def get_session_status():
    dt_roma = datetime.now(pytz.timezone('Europe/Rome'))
    ora_roma = dt_roma.hour
    giorno_settimana = dt_roma.weekday() # 0=Lun, 4=Ven, 5=Sab, 6=Dom

    # Se è Sabato o Domenica (fino alle 22:00), i mercati reali sono chiusi
    if giorno_settimana == 5 or (giorno_settimana == 6 and ora_roma < 22):
        return {
            "Sidney 🇦🇺": False,
            "Tokyo 🇯🇵": False,
            "Londra 🇬🇧": False,
            "New York 🇺🇸": False,
            "Mercati": "CHIUSI 🔴"
        }
    
    status = {
        "Sidney 🇦🇺": 22 <= ora_roma or ora_roma < 7,
        "Tokyo 🇯🇵": 1 <= ora_roma < 10,
        "Londra 🇬🇧": 9 <= ora_roma < 18,
        "New York 🇺🇸": 15 <= ora_roma < 22,
    }
    
    # Aggiunta info Overlap per l'utente
    if status["Londra 🇬🇧"] and status["New York 🇺🇸"]:
        status["MERCATO"] = "OVERLAP 🔥"
    else:
        status["MERCATO"] = "OPERATIVO 🟢"
        
    return status

def check_market_alerts():
    now = datetime.now(pytz.timezone('Europe/Rome'))
    current_time = now.strftime("%H:%M")
    
    # Definiamo gli orari di apertura e chiusura
    alerts = {
        "01:00": "🇯🇵 Apertura Borsa di TOKYO",
        "03:30": "🇯🇵 Chiusura Borsa di TOKYO",
        "04:30": "🇯🇵 Chiusura Borsa di TOKYO",
        "07:30": "🇯🇵 Chiusura Borsa di TOKYO",
        "09:00": "🇬🇧 Apertura Borsa di LONDRA",
        "15:30": "🇺🇸 Apertura Borsa di NEW YORK",
        "17:30": "🇬🇧 Chiusura Borsa di LONDRA",
        "22:00": "🇺🇸 Chiusura Borsa di NEW YORK"
    }
    
    if current_time in alerts:
        # Usiamo il session_state per non inviare il messaggio 60 volte nello stesso minuto
        if st.session_state.get("last_market_alert") != current_time:
            msg = f"🔔 *MARKET UPDATE*\n{alerts[current_time]}"
            send_telegram_msg(msg)
            st.session_state["last_market_alert"] = current_time

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
        pairs = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP"]
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

def detect_divergence(df):
    try:
        if len(df) < 10: return "N/A"
        
        # Prezzi e RSI ultimi 2 picchi
        recent_close = df['close'].tail(10)
        recent_rsi = df['rsi'].tail(10)
        
        # Logica semplificata:
        # Divergenza Rialzista: Prezzo scende, RSI sale
        if recent_close.iloc[-1] < recent_close.iloc[0] and recent_rsi.iloc[-1] > recent_rsi.iloc[0]:
            return "BULLISH 🐂"
        # Divergenza Ribassista: Prezzo sale, RSI scende
        if recent_close.iloc[-1] > recent_close.iloc[0] and recent_rsi.iloc[-1] < recent_rsi.iloc[0]:
            return "BEARISH 🐻"
            
        return "NESSUNA"
    except:
        return "N/A"

def check_binary_signal(df):
    if df.empty or len(df) < 200:
        return None, {}

    # --- CALCOLO INDICATORI (TUTTO DENTRO LA FUNZIONE) ---
    bb = ta.bbands(df['close'], length=20, std=2.2)
    rsi_series = ta.rsi(df['close'], length=7)
    rsi = rsi_series.iloc[-1]
    
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    adx = adx_df['ADX_14'].iloc[-1]
    atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
    
    ema200 = ta.ema(df['close'], length=200).iloc[-1]
    
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)
    curr_stoch_k = stoch['STOCHk_14_3_3'].iloc[-1]
    
    bbl = bb.iloc[-1, 0]
    bbu = bb.iloc[-1, 2]
    curr_close = df['close'].iloc[-1]
    
    stats = {
        "Price": curr_close,
        "RSI": round(rsi, 2),
        "ADX": round(adx, 2),
        "ATR": round(atr, 5),
        "EMA200": round(ema200, 5),
        "Stoch_K": round(curr_stoch_k, 2),
        "Trend": "UP" if curr_close > ema200 else "DOWN"
    }

    # --- LOGICA DI FILTRO ---
    if 15 < adx < 35:
        if curr_close <= bbl and rsi < 25 and curr_stoch_k < 20:
            return "CALL", stats
        elif curr_close >= bbu and rsi > 75 and curr_stoch_k > 80:
            return "PUT", stats
            
    return None, stats
    
def send_daily_report():
    now = datetime.now(pytz.timezone('Europe/Rome'))
    # Invio alle 22:05
    if now.strftime("%H:%M") == "22:05":
        if st.session_state.get("last_daily_report_date") != now.date():
            trades = st.session_state.get('trades', [])
            if not trades:
                msg = "📊 *REPORT GIORNALIERO SENTINEL*\nNessuna operazione effettuata oggi."
            else:
                df_rep = pd.DataFrame(trades)
                wins = len(df_rep[df_rep['Esito'] == 'WIN'])
                losses = len(df_rep[df_rep['Esito'] == 'LOSS'])
                win_rate = (wins / len(df_rep)) * 100
                pnl_tot = df_rep['Profitto'].sum()
                msg = (f"📊 *REPORT GIORNALIERO SENTINEL*\n"
                       f"✅ Vinte: {wins} | ❌ Perse: {losses}\n"
                       f"📈 Win Rate: {win_rate:.1f}%\n"
                       f"💰 *Profitto Totale: € {pnl_tot:.2f}*")
            send_telegram_msg(msg)
            st.session_state["last_daily_report_date"] = now.date()

def is_strength_valid(asset, strength_series, threshold=0.15):
    try:
        base_val = [val for curr, val in strength_series.items() if asset[:3] in curr]
        quote_val = [val for curr, val in strength_series.items() if asset[3:] in curr]
        if base_val and quote_val:
            return abs(base_val[0] - quote_val[0]) >= threshold
        return True
    except: return True

# --- SIDEBAR: ACCESSO E CONFIGURAZIONE ---
st.sidebar.title("🔐 IQ Option Access")

if st.session_state['iq_api'] is None:
    st.sidebar.error("🔴 STATO: DISCONNESSO")
    user_mail = st.sidebar.text_input("Email IQ", value=IQ_EMAIL)
    user_pass = st.sidebar.text_input("Password IQ", type="password", value=IQ_PASS)
    if st.sidebar.button("🔌 Connetti", use_container_width=True):
        api = IQ_Option(user_mail, user_pass)
        check, reason = api.connect()
        if check:
            api.change_balance("PRACTICE")
            st.session_state['iq_api'] = api
            st.session_state['trading_attivo'] = True
            st.rerun()
                    
else:
    st.sidebar.success("🟢 STATO: IN LINEA")
    API = st.session_state['iq_api']
    
    # --- LOGICA SWITCH CONTO CON SICUREZZA ---
    col_p, col_r = st.sidebar.columns(2)
    
    # Pulsante Practice (Sempre diretto)
    if col_p.button("🎮 Conto PRACTICE", use_container_width=True):
        API.change_balance("PRACTICE")
        st.session_state['confirm_real'] = False # Reset sicurezza
        st.rerun()
        
    # Pulsante Reale (Attiva la richiesta di conferma)
    if col_r.button("💰 Conto REALE", use_container_width=True, type="primary"):
        st.session_state['confirm_real'] = True

    # --- POP-UP DI CONFERMA (Inline nella Sidebar) ---
    if st.session_state.get('confirm_real', False):
        st.sidebar.warning("⚠️ **SICURO DI PASSARE AL CONTO REALE?**")
        c1, c2 = st.sidebar.columns(2)
        
        if c1.button("✅ SÌ, PROCEDI", use_container_width=True):
            API.change_balance("REAL")
            st.session_state['confirm_real'] = False
            st.toast("OPERATIVITÀ REALE ATTIVATA!", icon="🔥")
            st.rerun()
            
        if c2.button("❌ ANNULLA", use_container_width=True):
            st.session_state['confirm_real'] = False
            st.rerun()

    # --- LETTURA SALDO ---
    # L'API di IQ Option restituisce il saldo del conto attualmente attivo
    current_balance = API.get_balance()
    account_type = API.get_balance_mode() # Ritorna 'PRACTICE' o 'REAL'
    
    st.sidebar.metric(
        label=f"Saldo attuale ({account_type})", 
        value=f"€ {current_balance:,.2f}"
    )

    if st.sidebar.button("🚪 Esci", use_container_width=True):
        st.session_state['iq_api'] = None
        st.session_state['trading_attivo'] = False
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🌍 Sessioni di mercato")
for s_name, is_open in get_session_status().items():
    color = "🟢" if is_open else "🔴"
    st.sidebar.markdown(f"**{s_name}**: {'Aperto' if is_open else 'Chiuso'} {color}")

st.sidebar.divider()
st.sidebar.subheader("💰 Money Management")
stake = st.sidebar.number_input("Stake Singolo (€)", value=20.0)
target_profit = st.sidebar.number_input("Target Profit (€)", value=40.0)
stop_loss_limit = st.sidebar.number_input("Stop Loss (€)", value=10.0)

st.sidebar.divider()
st.sidebar.subheader("🧪 Modalità Test")
paper_trading = st.sidebar.toggle("Simulazione (Paper Trading)", value=True, help="Se attivo, il bot analizza i segnali ma non apre trade reali su IQ Option.")

# Forza la simulazione se il saldo è REAL ma l'utente ha dimenticato il toggle su ON
if not paper_trading and account_type == "REAL":
    st.sidebar.warning("⚡ OPERATIVITÀ REALE ATTIVA")

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

# Da inserire in st.sidebar per un test rapido
st.sidebar.markdown("---")
if st.sidebar.button("🧪 Test Telegram"):
    send_telegram_msg("🔔 *Sentinel AI Test*\nConnessione riuscita con successo!")
    
    st.sidebar.success("Messaggio inviato!")

# Reset Sidebar
st.sidebar.markdown("---")
with st.sidebar.popover("🗑️ **Reset Cronologia**"):
    st.warning("Sei sicuro? Questa azione cancellerà tutti i segnali salvati.")

    if st.button("SÌ, CANCELLA ORA"):
        st.session_state['trades'] = []
        st.session_state['daily_pnl'] = 0.0
        st.session_state['sim_pnl'] = 0.0
        st.rerun()

# --- MAIN INTERFACE ---
st.image("banner.png", use_container_width=True)
#st.title("🛰️ Sentinel AI - Binary Execution")

if st.session_state['iq_api']:
    acc_type = st.session_state['iq_api'].get_balance_mode()
    color = "light blue" if acc_type == "PRACTICE" else "red"
    st.markdown(f"""
        <div style="background-color: {color}; padding: 5px; border-radius: 5px; text-align: center; color: white; font-weight: bold;">
            MODALITÀ ATTUALE: {acc_type}
        </div>
    """, unsafe_allow_html=True)

# Logica Autorun
if st.session_state['iq_api'] and st.session_state['trading_attivo']:
    
    # 1. Controlla Alert Mercati (Apertura/Chiusura)
    check_market_alerts()
    
    # 2. Controlla invio Report Giornaliero
    send_daily_report()
    
    if st.session_state['daily_pnl'] >= target_profit:
        st.balloons()
        st.success("🎯 Target raggiunto! Bot fermo.")
        st.session_state['trading_attivo'] = False
    elif st.session_state['daily_pnl'] <= -stop_loss_limit:
        st.error("🛑 Stop Loss raggiunto. Bot fermo.")
        st.session_state['trading_attivo'] = False
    else:
        API = st.session_state['iq_api']

        # --- CONTROLLO STATO MERCATI ---
        is_weekend = datetime.now(pytz.timezone('Europe/Rome')).weekday() >= 5
        
        if is_weekend:
            st.error("📉 MERCATI CHIUSI (WEEKEND). Il bot non scansionerà asset reali per evitare rischi OTC")
            st.session_state['trading_attivo'] = False
        
        assets_to_scan = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP"]

        currency_strength = get_iq_currency_strength(API) # Calcolo forza valute globale
        
        with st.status("🔍 Scansione Sentinel in corso...", expanded=False) as status:
            for asset in assets_to_scan:
                df = get_data_from_iq(API, asset)
                if not df.empty:
                    df['rsi'] = ta.rsi(df['close'], length=14) 
                    
                    # 1. Analisi Divergenza
                    div_status = detect_divergence(df)
                    if div_status != "NESSUNA" and div_status != "N/A":
                        last_div_key = f"last_div_{asset}"
                        if st.session_state.get(last_div_key) != div_status:
                            send_telegram_msg(f"⚠️ *DIVERGENZA su {asset}*\nTipo: {div_status}")
                            st.session_state[last_div_key] = div_status
    
                    # 2. Segnale Tecnico (BB + RSI + Stoch)
                    signal, stats = check_binary_signal(df)
                    
                    if signal:
                        # 3. FILTRO FORZA VALUTA (Check finale prima di operare)
                        if is_strength_valid(asset, currency_strength, threshold=0.15):
                            msg_sent = f"🚀 *SEGNALE VALIDATO: {signal}* su {asset}"
                            send_telegram_msg(msg_sent)
                            
                            if paper_trading:
                                st.info(f"🧪 [SIM] Analisi {signal} su {asset}")
                                time_lib.sleep(60) # Aspetta scadenza candela
                                df_post = get_data_from_iq(API, asset)
                                if not df_post.empty:
                                    price_end = df_post['close'].iloc[-1]
                                    win = price_end > stats["Price"] if signal == "CALL" else price_end < stats["Price"]
                                    res = (stake * 0.85) if win else -stake
                                    st.session_state['trades'].append({
                                        "Ora": get_now_rome().strftime("%H:%M:%S"), "Asset": asset, "Tipo": f"SIM-{signal}",
                                        "Esito": "WIN" if win else "LOSS", "Profitto": res, 
                                        "RSI": stats["RSI"], "ADX": stats["ADX"], "Stoch": stats["Stoch_K"],
                                        "ATR": stats["ATR"], "Trend": stats["Trend"]
                                    })
                                    st.session_state['sim_pnl'] += res
                                    st.rerun()
                            else:
                                # TRADING REALE
                                check, id = API.buy(stake, asset, signal.lower(), 1)
                                if check:
                                    time_lib.sleep(62)
                                    res = API.check_win_v2(id)
                                    st.session_state['trades'].append({
                                        "Ora": get_now_rome().strftime("%H:%M:%S"), "Asset": asset, "Tipo": signal,
                                        "Esito": "WIN" if res > 0 else "LOSS", "Profitto": res, 
                                        "RSI": stats["RSI"], "ADX": stats["ADX"], "Stoch": stats["Stoch_K"],
                                        "ATR": stats["ATR"], "Trend": stats["Trend"]
                                    })
                                    st.session_state['daily_pnl'] += res
                                    st.rerun()
                        else:
                            st.write(f"⏭️ {asset}: Segnale presente ma Forza Valuta non valida.")
else:
    if not st.session_state['iq_api']:
        st.info("Effettua il login per attivare il sistema.")

# --- GRAFICO IN TEMPO REALE ---
st.markdown("---")
# 1. Recuperiamo la selezione dell'utente
selected_label = st.selectbox("Seleziona Asset per Grafico", list(asset_map.keys()))
pair = asset_map[selected_label] # <--- QUESTA RIGA RISOLVE L'ERRORE

st.subheader(f"📈 Sentinel View: {selected_label} (1m)")

if st.session_state['iq_api']:
    try:
        # Recupero candele reali da IQ Option
        candles_data = st.session_state['iq_api'].get_candles(pair, 60, 200, time_lib.time())
        df_rt = pd.DataFrame(candles_data)
        
        if not df_rt.empty:
            df_rt.rename(columns={'max': 'high', 'min': 'low', 'open': 'open', 'close': 'close', 'from': 'time'}, inplace=True)
            df_rt['time'] = pd.to_datetime(df_rt['time'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Europe/Rome')
            df_rt.set_index('time', inplace=True)
            
            # Calcolo Indicatori
            bb = ta.bbands(df_rt['close'], length=20, std=2)
            df_rt = pd.concat([df_rt, bb], axis=1)
            df_rt['rsi'] = ta.rsi(df_rt['close'], length=14)
            
            # Identificazione colonne BB
            c_up = [c for c in df_rt.columns if "BBU" in c.upper()][0]
            c_mid = [c for c in df_rt.columns if "BBM" in c.upper()][0]
            c_low = [c for c in df_rt.columns if "BBL" in c.upper()][0]

            # Visualizziamo solo gli ultimi 60 minuti
            p_df = df_rt.tail(60)

            # --- COSTRUZIONE FIGURA ---
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.05, row_heights=[0.75, 0.25])
            
            # Candele
            fig.add_trace(go.Candlestick(
                x=p_df.index, open=p_df['open'], high=p_df['high'], 
                low=p_df['low'], close=p_df['close'], name='Prezzo'
            ), row=1, col=1)
            
            # Bande di Bollinger con riempimento (BBM inclusa)
            fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_up], line=dict(color='rgba(0, 191, 255, 0.3)', width=1), name='Upper BB'), row=1, col=1)
            fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_mid], line=dict(color='rgba(255, 255, 255, 0.2)', width=1, dash='dot'), name='BBM'), row=1, col=1)
            fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_low], line=dict(color='rgba(0, 191, 255, 0.3)', width=1), fill='tonexty', fillcolor='rgba(0, 191, 255, 0.05)', name='Lower BB'), row=1, col=1)

            # RSI con soglie colorate
            fig.add_trace(go.Scatter(x=p_df.index, y=p_df['rsi'], line=dict(color='#ffcc00', width=2), name='RSI'), row=2, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", opacity=0.5, row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="#00ff00", opacity=0.5, row=2, col=1)

            # Griglia verticale ogni 5 minuti
            for t in p_df.index:
                if t.minute % 5 == 0:
                    fig.add_vline(x=t, line_width=0.8, line_dash="solid", line_color="rgba(255, 255, 255, 0.1)", layer="below")

            fig.update_layout(
                height=650, 
                template="plotly_dark", 
                xaxis_rangeslider_visible=False, 
                margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", y=1.02, xanchor="right", x=1)
            )
            
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Errore caricamento grafico: {e}")

else:
    st.info("Connetti l'account per visualizzare il grafico real-time.")

st.markdown("---")
# --- METRICHE DINAMICHE AGGIORNATE ---
st.subheader(f"🔍 Indicatori in tempo reale")

# Usiamo p_df (gli ultimi 60 min) o df_rt per le metriche
if 'df_rt' in locals() and not df_rt.empty:
    # Calcolo ADX al volo se non presente nel DataFrame del grafico
    if 'adx' not in df_rt.columns:
        adx_df = ta.adx(df_rt['high'], df_rt['low'], df_rt['close'], length=14)
        df_rt['adx'] = adx_df['ADX_14']

    c1, c2, c3, c4 = st.columns(4)

    # Estrazione valori (usiamo .get per evitare errori se le colonne mancano)
    curr_p = df_rt['close'].iloc[-1]
    curr_rsi = df_rt['rsi'].iloc[-1]
    curr_adx = df_rt['adx'].iloc[-1]
    
    # Recupero nomi colonne BB corretti
    c_up = [c for c in df_rt.columns if "BBU" in c.upper()][0]
    c_low = [c for c in df_rt.columns if "BBL" in c.upper()][0]
    bb_upper = df_rt[c_up].iloc[-1]
    bb_lower = df_rt[c_low].iloc[-1]

    # 1. Prezzo
    c1.metric("Prezzo Attuale", f"{curr_p:.5f}")

    # 2. RSI (aggiornato a 14 periodi per coerenza col grafico)
    c2.metric("RSI (14)", f"{curr_rsi:.2f}", 
              delta="IPER-COMPRATO" if curr_rsi > 70 else "IPER-VENDUTO" if curr_rsi < 30 else "NEUTRO",
              delta_color="inverse" if curr_rsi > 70 or curr_rsi < 30 else "normal")

    # 3. ADX
    c3.metric("ADX (14)", f"{curr_adx:.2f}", 
              delta="VOLATILITÀ OK" if 15 < curr_adx < 35 else "SCONSIGLIATO",
              delta_color="normal" if 15 < curr_adx < 35 else "inverse")

    # 4. Divergenza & Distanza BB
    div_status = detect_divergence(df_rt)
    c4.metric("Divergenza RSI", div_status, 
              delta="TOCCATA BB" if curr_p >= bb_upper or curr_p <= bb_lower else "IN RANGE")
    
    # Caption per info extra
    st.caption(f"📢 Analisi Sentiment: {div_status} | Trend EMA200: {'UP' if curr_p > df_rt['close'].mean() else 'DOWN'}")
else:
    st.info("In attesa di dati dal grafico...")

# --- CURRENCY STRENGTH ---
st.markdown("---")
st.subheader("⚡ Forza delle valute (Dati IQ Option)")
if st.session_state['iq_api']:
    s_data = get_iq_currency_strength(st.session_state['iq_api'])
    if not s_data.empty:
        cols = st.columns(len(s_data))
        for i, (curr, val) in enumerate(s_data.items()):
            bg = "rgba(0,255,0,0.2)" if val > 0 else "rgba(255,0,0,0.2)"
            cols[i].markdown(f"<div style='text-align:center; background:{bg}; padding:10px; border-radius:5px;'><b>{curr}</b><br>{val:.2f}%</div>", unsafe_allow_html=True)
else:
    st.info("In attesa della connessione...")

# --- REPORTING ---
st.divider()
#st.subheader(f"📊 Analisi Operativa")

col_res1, col_res2 = st.columns(2)
with col_res1:
    st.subheader(f"💰 Profitto Reale: € {st.session_state['daily_pnl']:.2f}")
with col_res2:
    sim_pnl = st.session_state.get('sim_pnl', 0.0)
    st.subheader(f"🧪 Profitto Simulato: € {sim_pnl:.2f}")

if st.session_state['trades']:
    st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)

# Auto-refresh ogni 60s
st.sidebar.markdown("""<div style="background:#222; height:5px; width:100%; border-radius:10px; overflow:hidden;"><div style="background:red; height:100%; width:100%; animation: fill 60s linear infinite;"></div></div><style>@keyframes fill {0% {width: 0%;} 100% {width: 100%;}}</style>""", unsafe_allow_html=True)
time_lib.sleep(60)
st.rerun()

# --- SEZIONE ANALISI TECNICA POST-SESSIONE ---
st.markdown("---")
st.subheader("🔬 Analisi prestazioni")

if st.session_state['trades']:
    df_analysis = pd.DataFrame(st.session_state['trades'])
    
    # Metriche
    win_rate = (len(df_analysis[df_analysis['Esito'] == 'WIN']) / len(df_analysis)) * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("Win Rate", f"{win_rate:.1f}%")
    c2.metric("RSI Medio", f"{df_analysis['RSI'].mean():.2f}")
    c3.metric("Segnali Totali", len(df_analysis))

    # Grafico Distribuzione
    fig_an = go.Figure()
    fig_an.add_trace(go.Scatter(
        x=df_analysis['RSI'], y=df_analysis['ADX'],
        mode='markers',
        marker=dict(
            color=['#00ffcc' if e == 'WIN' else '#ff4b4b' for e in df_analysis['Esito']], 
            size=12, line=dict(width=1, color='white')
        ),
        text=df_analysis['Asset']
    ))
    fig_an.update_layout(title="Analisi RSI vs ADX", template="plotly_dark", height=400)
    st.plotly_chart(fig_an, use_container_width=True)

    # Tasto Export
    csv = df_analysis.to_csv(index=False).encode('utf-8')
    st.download_button("📥 SCARICA REPORT (.csv)", data=csv, file_name="Sentinel_Report.csv", mime="text/csv")
else:
    st.info("⏳ In attesa di dati per l'analisi")
