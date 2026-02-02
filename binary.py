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
if 'confirm_real' not in st.session_state: st.session_state['confirm_real'] = False
if 'last_market_alert' not in st.session_state: 
    st.session_state['last_market_alert'] = ""
if 'last_daily_report_date' not in st.session_state: 
    st.session_state['last_daily_report_date'] = None
if 'scarti_adx' not in st.session_state: st.session_state['scarti_adx'] = 0
if 'scarti_rsi_stoch' not in st.session_state: st.session_state['scarti_rsi_stoch'] = 0
if 'scarti_forza' not in st.session_state: st.session_state['scarti_forza'] = 0
if 'pnl_power_hour' not in st.session_state: st.session_state['pnl_power_hour'] = 0.0
if 'pnl_normal' not in st.session_state: st.session_state['pnl_normal'] = 0.0


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
    now_gmt = datetime.now(pytz.utc)
    ora_gmt = now_gmt.hour + now_gmt.minute / 60
    giorno = now_gmt.weekday() 

    # Controllo Weekend
    if giorno == 5 or (giorno == 4 and ora_gmt >= 22) or (giorno == 6 and ora_gmt < 21):
        return {"STATO": "CLOSED 🔴", "sessions": {}}

    # Definizione Borse
    sessions = {
        "Sidney 🇦🇺": 21 <= ora_gmt or ora_gmt < 6,
        "Tokyo 🇯🇵": 0 <= ora_gmt < 9,
        "Londra 🇬🇧": 8 <= ora_gmt < 17,
        "New York 🇺🇸": 13 <= ora_gmt < 22,
    }
    
    # Calcolo Stato Globale
    if sessions["Londra 🇬🇧"] and sessions["New York 🇺🇸"]:
        stato = "OVERLAP 🔥"
    else:
        stato = "OPERATIVO 🟢"
        
    return {"STATO": stato, "sessions": sessions}

def check_and_reconnect():
    """Controlla la connessione e riconnette se necessario."""
    if st.session_state['iq_api'] is not None:
        if not st.session_state['iq_api'].check_connect():
            st.sidebar.warning("🔄 Connessione persa! Tentativo di riconnessione automatica...")
            check, reason = st.session_state['iq_api'].connect()
            if check:
                st.sidebar.success("✅ Riconnessione riuscita!")
                return True
            else:
                st.sidebar.error("❌ Riconnessione fallita. Controlla le credenziali.")
                return False
        return True
    return False

def check_market_alerts():
    # Usiamo il fuso orario UTC (GMT)
    now_gmt = datetime.now(pytz.utc)
    current_time = now_gmt.strftime("%H:%M")
    
    # Orari ufficiali in GMT
    alerts = {
        "00:00": "🇯🇵 Apertura Sessione TOKYO",
        "06:00": "🇦🇺 Chiusura Sessione SIDNEY",
        "08:00": "🇬🇧 Apertura Sessione LONDRA",
        "09:00": "🇯🇵 Chiusura Sessione TOKYO",
        "13:00": "🇺🇸 Apertura Sessione NEW YORK", # 13:00 GMT = 14:00/15:00 Roma
        "17:00": "🇬🇧 Chiusura Sessione LONDRA",
        "21:00": "🇦🇺 Apertura Sessione SIDNEY",
        "22:00": "🇺🇸 Chiusura Sessione NEW YORK"
    }
    
    if current_time in alerts:
        # Controllo per evitare invii multipli nello stesso minuto
        if st.session_state.get("last_market_alert") != current_time:
            # 1. Calcoliamo l'ora locale per il messaggio
            ora_roma = datetime.now(pytz.timezone('Europe/Rome')).strftime("%H:%M")
            
            # 2. Componiamo il messaggio unico
            msg = (f"🔔 *MARKET UPDATE (GMT: {current_time})*\n"
                   f"{alerts[current_time]}\n"
                   f"🇮🇹 Ora locale Roma: {ora_roma}")
            
            # 3. Invio e salvataggio stato
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
    if df.empty or len(df) < 60:
        return None, {}, "Dati insufficienti"

    # --- INDICATORI ---
    # Bollinger più strette (std 2.0) e RSI più reattivo (30/70)
    bb = ta.bbands(df['close'], length=20, std=2.0)
    rsi = ta.rsi(df['close'], length=7).iloc[-1]
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    adx = adx_df['ADX_14'].iloc[-1]
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)
    curr_k = stoch['STOCHk_14_3_3'].iloc[-1]
    
    bbl = bb.iloc[-1, 0]
    bbu = bb.iloc[-1, 2]
    curr_close = df['close'].iloc[-1]
    
    stats = {"Price": curr_close, "RSI": round(rsi, 2), "ADX": round(adx, 2), "Stoch": round(curr_k, 2)}

    # --- LOGICA FILTRI ALLENTATA ---
    # Accettiamo volatilità tra 12 e 45 (prima era 15-35)
    if not (12 < adx < 45):
        return None, stats, f"ADX non ideale ({stats['ADX']})"
    
    # Ingressi a 30/70 invece di 25/75
    if curr_close <= bbl and rsi < 30 and curr_k < 25:
        return "CALL", stats, "Segnale Validato"
    elif curr_close >= bbu and rsi > 70 and curr_k > 75:
        return "PUT", stats, "Segnale Validato"
            
    return None, stats, "Condizioni tecniche non soddisfatte"
    
def smart_buy(API, stake, asset, action, duration):
    # Prova Digital prima, poi Binary, con gestione errori
    try:
        # Digital
        check, id = API.buy_digital_spot(asset, stake, action, duration)
        if check and isinstance(id, int): return True, id, "Digital"
        
        # Binary
        check, id = API.buy(stake, asset, action, duration)
        if check: return True, id, "Binary"
        
    except Exception:
        pass
    return False, None, "Error/Closed"

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
st.sidebar.subheader("🌍 Sessioni di Mercato")

status_data = get_session_status()

# --- BLOCCO STATO GENERALE ---
st.sidebar.markdown(f"""
    <div style="background-color: rgba(255, 255, 255, 0.1); 
                padding: 8px; 
                border-radius: 10px; 
                border: 1px solid #444; 
                text-align: center; 
                margin-bottom: 10px;">
        <small style="color: #888; text-transform: uppercase; font-size: 0.7em;">Stato Mercato</small><br>
        <b style="font-size: 1em;">{status_data['STATO']}</b>
    </div>
""", unsafe_allow_html=True)

# --- LISTA BORSE IN LINEA (ANTI-A CAPO) ---
if status_data['sessions']:
    for s_name, is_open in status_data['sessions'].items():
        icon = "🟢" if is_open else "🔴"
        # Usiamo un unico markdown per riga, senza colonne
        # Il simbolo &nbsp; aggiunge uno spazio fisso tra nome e pallino
        st.sidebar.markdown(f"**{s_name}**&nbsp;&nbsp;{icon}")
else:
    st.sidebar.warning("Mercato chiuso (Weekend)")

st.sidebar.divider()
st.sidebar.subheader("💰 Money Management")
stake = st.sidebar.number_input("Stake Singolo (€)", value=50.0)
target_profit = st.sidebar.number_input("Target Profit (€)", value=250.0)
stop_loss_limit = st.sidebar.number_input("Stop Loss (€)", value=200.0)

st.sidebar.divider()
st.sidebar.subheader("🛡️ Protezione Strategia")

# Calcolo trade mancanti per l'attivazione del Kill-Switch
trade_effettuati = len(st.session_state['trades'])
trade_minimi = 10

if trade_effettuati < trade_minimi:
    mancanti = trade_minimi - trade_effettuati
    st.sidebar.info(f"⏳ Analisi WR attiva tra: **{mancanti} trade**")
    st.sidebar.progress(trade_effettuati / trade_minimi)
else:
    st.sidebar.success("✅ Monitoraggio WR Attivo")
    # Mostra il WR attuale anche qui per comodità
    wins = len([t for t in st.session_state['trades'] if t['Esito'] == 'WIN'])
    wr_real = (wins / trade_effettuati) * 100
    st.sidebar.metric("Win Rate Sessione", f"{wr_real:.1f}%")

st.sidebar.divider()
st.sidebar.subheader("📊 Report Filtri (Scarti)")
#c1, c2 = st.sidebar.columns(2)
#c1.metric("ADX ", st.session_state['scarti_adx'])
#c2.metric("Tecnico No", st.session_state['scarti_rsi_stoch'])à
#st.sidebar.divider()

with st.sidebar.expander("Dettaglio Scarti", expanded=True):
    st.write(f"📉 **ADX non idoneo:** {st.session_state['scarti_adx']}")
    st.write(f"🖇️ **RSI/Stoch flat:** {st.session_state['scarti_rsi_stoch']}")
    st.write(f"💪 **Forza debole:** {st.session_state['scarti_forza']}")

    if st.button("Reset Statistiche Scarto"):
        st.session_state['scarti_adx'] = 0
        st.session_state['scarti_rsi_stoch'] = 0
        st.session_state['scarti_forza'] = 0
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("📡 Stato Sistema")

if st.session_state.get('iq_api'):
    # Semaforo sicuro: controlla se l'oggetto esiste prima di chiamarlo
    if st.session_state['iq_api'].check_connect():
        st.sidebar.markdown("### 🟢 API OPERATIVA")
        st.sidebar.caption(f"✅ Modalità: {st.session_state['iq_api'].get_balance_mode()}")
    else:
        st.sidebar.markdown("### 🔴 API DISCONNESSA")
else:
    st.sidebar.markdown("### ⚪ ATTESA LOGIN")

st.sidebar.caption(f"🕒 Ultimo Scan: {get_now_rome().strftime('%H:%M:%S')}")

# Da inserire in st.sidebar per un test rapido
st.sidebar.markdown("---")
if st.sidebar.button("🧪 Test Telegram"):
    send_telegram_msg("🔔 *Sentinel AI Test*\nConnessione riuscita con successo!")
    
    st.sidebar.success("Messaggio inviato!")

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

# Reset Sidebar
st.sidebar.markdown("---")
with st.sidebar.popover("🗑️ **Reset Cronologia**"):
    st.warning("Sei sicuro? Questa azione cancellerà tutti i segnali salvati.")

    if st.button("SÌ, CANCELLA ORA"):
        st.session_state['trades'] = []
        st.session_state['daily_pnl'] = 0.0
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

# --- LOGICA DI SCANSIONE CON TIMEOUT 15s ---
if st.session_state['iq_api'] and st.session_state['trading_attivo']:
    # Controllo riconnessione automatica
    if not check_and_reconnect():
        st.error("Il sistema non riesce a stabilire una connessione stabile.")
        time_lib.sleep(5)
        st.rerun()
    
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
           
        # --- PUNTO 1: CONTROLLO INTEGRITÀ CONNESSIONE ---
        if not API.check_connect():
            st.sidebar.warning("⚠️ Connessione persa! Riconnessione...")
            connected, reason = API.connect() 
            if not connected:
                st.error("❌ Errore critico IQ Option. Bot fermato.")
                st.session_state['trading_attivo'] = False
                st.rerun()

        # --- CONTROLLO WEEKEND ---
        is_weekend = datetime.now(pytz.timezone('Europe/Rome')).weekday() >= 5
        if is_weekend:
            st.error("📉 MERCATI CHIUSI. Il bot non scansiona asset reali nel weekend.")
            st.session_state['trading_attivo'] = False
            st.stop()
        
        assets_to_scan = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP"]
                
        with st.status("🔍 Scansione Sentinel in corso...", expanded=True) as status:
            for asset in assets_to_scan:
                time_lib.sleep(0.5) 
                df = get_data_from_iq(API, asset)
    
                if df.empty: continue 
    
                signal, stats, reason = check_binary_signal(df)
            
                if signal:
                    st.markdown(f"🚀 **{asset}**: Segnale {signal} trovato!")

                    # --- LOGICA TIMEOUT 15 SECONDI ---
                    start_op = time_lib.time()
                    success = False
                    trade_id = None
                    mode = ""
    
                    try:
                        # Esecuzione con protezione timeout
                        success, trade_id, mode = smart_buy(API, stake, asset, signal.lower(), 1)
                        
                        # Controllo se l'API ha impiegato più di 15s
                        if time_lib.time() - start_op > 15:
                            st.warning(f"⚠️ Timeout 15s superato su {asset}. Operazione annullata.")
                            break

                        if success:
                            st.success(f"✅ Ordine {mode} inviato! ID: {trade_id}")
                            with st.spinner(f"⏳ Trade in corso su {asset}... Esito in 62s"):
                                time_lib.sleep(62) 

                            # --- Registrazione Esito ---
                            res = API.check_win_v2(trade_id) if mode == "Binary" else API.get_digital_prox_result(trade_id)
                            
                            # Determina se è Power Hour (13:00-17:00 GMT)
                            now_gmt = datetime.now(pytz.utc)
                            is_ph = 13 <= now_gmt.hour < 17
                            
                            # Salvataggio dati estesi
                            st.session_state['trades'].append({
                                "Ora": get_now_rome().strftime("%H:%M"),
                                "Asset": asset, 
                                "Tipo": signal,
                                "Esito": "WIN" if res > 0 else "LOSS", 
                                "Profitto": res,
                                "Sessione": "🔥 Power Hour" if is_ph else "☕ Normal",
                                "RSI": stats.get('RSI', 0), 
                                "ADX": stats.get('ADX', 0)
                            })
                            
                            # Aggiornamento PnL specifico
                            if is_ph:
                                st.session_state['pnl_power_hour'] += res
                            else:
                                st.session_state['pnl_normal'] += res
                            
                            st.session_state['daily_pnl'] += res
                            send_telegram_msg(f"📊 *TRADE CONCLUSO*\nAsset: {asset}\nEsito: {'✅ WIN' if res > 0 else '❌ LOSS'}\nProfitto: €{res:.2f}")

                            # Controllo Kill-Switch WR
                            df_temp = pd.DataFrame(st.session_state['trades'])
                            if len(df_temp) >= 10:
                                wins_count = len(df_temp[df_temp['Esito'] == 'WIN'])
                                current_wr = (wins_count / len(df_temp)) * 100
                                if current_wr < 50:
                                    send_telegram_msg(f"🛑 *KILL-SWITCH*: WR al {current_wr:.1f}%. Bot fermato.")
                                    st.session_state['trading_attivo'] = False
                                    st.rerun()
                            break 
                        
                        else:
                            st.warning(f"⚠️ {asset}: Ordine rifiutato (Mercato chiuso o Payout basso).")
                            
                    except Exception as e:
                        st.error(f"❌ Errore esecuzione: {e}")
                else:
                    # Aggiornamento contatori scarti
                    if "ADX" in reason: st.session_state['scarti_adx'] += 1
                    elif "Condizioni tecniche" in reason: st.session_state['scarti_rsi_stoch'] += 1
                    st.write(f"❌ {asset}: {reason}")
else:
    if not st.session_state['iq_api']:
        st.info("Effettua il login per attivare il sistema.")

# --- GRAFICO IN TEMPO REALE ---
st.markdown("---")
# 1. Recuperiamo la selezione dell'utente
selected_label = st.selectbox("Seleziona Asset per Grafico", list(asset_map.keys()))
pair = asset_map[selected_label] # <--- QUESTA RIGA RISOLVE L'ERRORE

st.subheader(f"📈 Grafico in tempo reale: {selected_label} (1m)")

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
            fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_mid], line=dict(color='rgba(100, 100, 100, 0.2)', width=1, dash='dot'), name='BBM'), row=1, col=1)
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
                legend=dict(orientation="h", yanchor="top", y=1.10, xanchor="left", x=0.01, bgcolor="rgba(220,220,220,0.1)")
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
st.subheader("⚡ Forza delle valute")
if st.session_state['iq_api']:
    s_data = get_iq_currency_strength(st.session_state['iq_api'])
    if not s_data.empty:
        cols = st.columns(len(s_data))
        for i, (curr, val) in enumerate(s_data.items()):
            bg = "rgba(0,255,0,0.2)" if val > 0 else "rgba(255,0,0,0.2)"
            cols[i].markdown(f"<div style='text-align:center; background:{bg}; padding:10px; border-radius:5px;'><b>{curr}</b><br>{val:.2f}%</div>", unsafe_allow_html=True)
else:
    st.info("In attesa della connessione...")

# --- SEZIONE ANALISI TECNICA POST-SESSIONE ---
st.markdown("---")
st.subheader("🔬 Analisi prestazioni")

if st.session_state['trades']:
    df_analysis = pd.DataFrame(st.session_state['trades'])
    wins = len(df_analysis[df_analysis['Esito'] == 'WIN'])
    total = len(df_analysis)
    wr = (wins / total) * 100

    # Visualizzazione chiara del target
    color = "green" if wr > 58 else "red"
    st.markdown(f"### Win Rate Attuale: <span style='color:{color}'>{wr:.1f}%</span>", unsafe_allow_html=True)
    
    if wr > 58:
        st.success("✅ La strategia è statisticamente vincente!")
    else:
        st.warning("⚠️ WR sotto il 58%: la strategia necessita di filtri più severi.")

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

st.subheader("⚔️ Power Hour Challenge")
col_ph, col_norm = st.columns(2)

with col_ph:
    st.status("### 🔥 Sessione Power")
    st.metric("PnL Power Hour", f"€ {st.session_state['pnl_power_hour']:.2f}")
    df_ph = pd.DataFrame([t for t in st.session_state['trades'] if t['Sessione'] == "🔥 Power Hour"])
    if not df_ph.empty:
        wr_ph = (len(df_ph[df_ph['Esito'] == 'WIN']) / len(df_ph)) * 100
        st.caption(f"Win Rate: {wr_ph:.1f}%")

with col_norm:
    st.markdown("### ☕ Ore Normali")
    st.metric("PnL Normal Hours", f"€ {st.session_state['pnl_normal']:.2f}")
    df_norm = pd.DataFrame([t for t in st.session_state['trades'] if t['Sessione'] == "☕ Normal"])
    if not df_norm.empty:
        wr_norm = (len(df_norm[df_norm['Esito'] == 'WIN']) / len(df_norm)) * 100
        st.caption(f"Win Rate: {wr_norm:.1f}%")

# --- SEZIONE REPORTING FINALE ---
st.divider()
st.subheader("📊 Riepilogo Operazioni")

if st.session_state['trades']:
    col_res1, col_res2 = st.columns([1, 2])
    
    with col_res1:
        st.metric("Profitto Totale", f"€ {st.session_state['daily_pnl']:.2f}")
    
    with col_res2:
        # Mostriamo solo le ultime 10 operazioni per non allungare troppo la pagina
        df_history = pd.DataFrame(st.session_state['trades']).tail(10)
        st.table(df_history) # 'st.table' è ottima per visualizzazioni statiche veloci
else:
    st.info("🟡 Nessun trade eseguito in questa sessione. Scansione attiva...")

# --- LOGICA DI REFRESH ---
if st.session_state['trading_attivo']:
    # Mostra un piccolo timer visivo o avviso
    st.caption(f"🔄 Prossimo aggiornamento tra 10 secondi... (Ora: {get_now_rome().strftime('%H:%M:%S')})")
    time_lib.sleep(10)
    st.rerun()
else:
    st.info("🛑 Bot in pausa. Riattiva dalla sidebar per riprendere la scansione.")
