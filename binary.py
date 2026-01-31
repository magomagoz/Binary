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
        token = st.secrets["TELEGRAM_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id, 
            "text": message, 
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=5)
        if not response.ok:
            st.error(f"Errore API Telegram: {response.text}")
    except Exception as e:
        st.error(f"Errore invio: {e}")

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
    dt_roma = datetime.now(pytz.timezone('Europe/Rome'))
    ora_roma = dt_roma.hour
    giorno_settimana = dt_roma.weekday() # 5 = Sabato, 6 = Domenica

    # Se è Sabato o Domenica, i mercati reali sono chiusi
    if giorno_settimana >= 5:
        return {
            "Tokyo 🇯🇵": False,
            "Londra 🇬🇧": False,
            "New York 🇺🇸": False,
            "Weekend": False # Segnale extra per il sistema
        }
    
    return {
        "Tokyo 🇯🇵": 1 <= ora_roma < 8,
        "Londra 🇬🇧": 9 <= ora_roma < 18,
        "New York 🇺🇸": 15 <= ora_roma < 22,
        "Weekend": True
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

def check_binary_signal(df):
    if df.empty or len(df) < 200: # Servono 200 candele per l'EMA
        return None, {}
    
    # --- CALCOLO INDICATORI ---
    # Bollinger & RSI
    bb = ta.bbands(df['close'], length=20, std=2.2)
    rsi = ta.rsi(df['close'], length=7).iloc[-1]
    
    # ADX & ATR
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    adx = adx_df['ADX_14'].iloc[-1]
    atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
    
    # EMA 200 (Trend Primario)
    ema200 = ta.ema(df['close'], length=200).iloc[-1]
    
    # Stocastico (K=14, D=3)
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)
    curr_stoch_k = stoch['STOCHk_14_3_3'].iloc[-1]
    
    # Limiti Bande
    bbl = bb.iloc[-1, 0]
    bbu = bb.iloc[-1, 2]
    curr_close = df['close'].iloc[-1]
    
    # Snapshot completo per Cronologia
    stats = {
        "Price": curr_close,
        "RSI": round(rsi, 2),
        "ADX": round(adx, 2),
        "ATR": round(atr, 5),
        "EMA200": round(ema200, 5),
        "Stoch_K": round(curr_stoch_k, 2),
        "Trend": "UP" if curr_close > ema200 else "DOWN"
    }

    # --- LOGICA DI FILTRO AVANZATA ---
    # 1. Filtro Volatilità (ADX)
    if 15 < adx < 35:
        # 2. Condizione CALL (Ipervenduto + Stocastico basso + Sopra EMA200 per sicurezza)
        if curr_close <= bbl and rsi < 25 and curr_stoch_k < 20:
            return "CALL", stats
            
        # 3. Condizione PUT (Ipercomprato + Stocastico alto + Sotto EMA200 per sicurezza)
        elif curr_close >= bbu and rsi > 75 and curr_stoch_k > 80:
            return "PUT", stats
            
    return None, stats

# --- SIDEBAR: ACCESSO E CONFIGURAZIONE ---
st.sidebar.title("🔐 IQ Option Access")

if st.session_state['iq_api'] is None:
    st.sidebar.error("🔴 STATO: DISCONNESSO")
    user_mail = st.sidebar.text_input("Email IQ", value=IQ_EMAIL)
    user_pass = st.sidebar.text_input("Password IQ", type="password", value=IQ_PASS)
    if st.sidebar.button("🔌 Connetti CONTO PRACTICE 🟢", use_container_width=True):
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
    
    # --- LOGICA SWITCH CONTO ---
    col_p, col_r = st.sidebar.columns(2)
    
    if col_p.button("🎮 PRACTICE", use_container_width=True):
        API.change_balance("PRACTICE")
        st.toast("Passato a Conto Practice", icon="🎮")
        
    if col_r.button("💰 REALE", use_container_width=True, type="primary"):
        API.change_balance("REAL")
        st.toast("ATTENZIONE: Passato a Conto REALE", icon="⚠️")

    # --- LETTURA SALDO ---
    # L'API di IQ Option restituisce il saldo del conto attualmente attivo
    current_balance = API.get_balance()
    account_type = API.get_balance_mode() # Ritorna 'PRACTICE' o 'REAL'
    
    st.sidebar.metric(
        label=f"Saldo attuale ({account_type})", 
        value=f"€ {current_balance:,.2f}"
    )

    if st.sidebar.button("🚪 Esci e Ferma Bot", use_container_width=True):
        st.session_state['iq_api'] = None
        st.session_state['trading_attivo'] = False
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🌍 Sessioni di mercato")
for s_name, is_open in get_session_status().items():
    color = "🟢" if is_open else "🔴"
    st.sidebar.markdown(f"**{s_name}**: {'Open' if is_open else 'Closed'} {color}")

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
        st.session_state['signal_history'] = pd.DataFrame(columns=['DataOra', 'Asset', 'Direzione', 'Prezzo', 'SL', 'TP', 'Size', 'Stato'])
        save_history_permanently() # Questo sovrascrive il file CSV con uno vuoto
        st.rerun()

# --- MAIN INTERFACE ---
st.image("banner.png", use_container_width=True)
#st.title("🛰️ Sentinel AI - Binary Execution")

if st.session_state['iq_api']:
    acc_type = st.session_state['iq_api'].get_balance_mode()
    color = "blue" if acc_type == "PRACTICE" else "red"
    st.markdown(f"""
        <div style="background-color: {color}; padding: 5px; border-radius: 5px; text-align: center; color: white; font-weight: bold;">
            MODALITÀ ATTUALE: {acc_type}
        </div>
    """, unsafe_allow_html=True)


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

        # --- CONTROLLO STATO MERCATI ---
        is_weekend = datetime.now(pytz.timezone('Europe/Rome')).weekday() >= 5
        
        if is_weekend:
            st.error("📉 MERCATI CHIUSI (WEEKEND). Il bot non scansionerà asset reali per evitare rischi OTC.")
            st.session_state['trading_attivo'] = False
        
        # --- PROTEZIONE WEEKEND ---
        #giorno_settimana = datetime.now(pytz.timezone('Europe/Rome')).weekday()
        #if giorno_settimana >= 5:
            #st.error("🛑 MERCATI CHIUSI. Il trading automatico è disabilitato nel weekend per evitare i mercati OTC.")
            #st.session_state['trading_attivo'] = False
            #st.stop() 

        assets_to_scan = ["EURUSD", "GBPUSD", "EURJPY", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP"]

        with st.status("🔍 Scansione Sentinel in corso...", expanded=False) as status:
            for asset in assets_to_scan:
                st.write(f"Verifica {asset}...")
                df = get_data_from_iq(API, asset)
                
                # CORREZIONE QUI: spacchettiamo i due valori restituiti
                signal, stats = check_binary_signal(df)
                
                if signal:
                    # Costruzione del messaggio con i tuoi dati reali
                    telegram_text = (
                        f"🚀 *NUOVO SEGNALE: {signal}*\n"
                        f"📈 Asset: {asset}\n"
                        f"💰 Entrata: {stats['Price']}\n"
                        f"🎯 RSI: {stats['RSI']}\n"
                        f"🛡️ ADX: {stats['ADX']}\n"
                        f"______________________"
                        f"💳 Investimento: {stake}€"
                    )
                    send_telegram_msg(telegram_text)
                    
                    if paper_trading:
                        # Suono leggero (Ping) per la Simulazione
                        st.markdown("""<audio autoplay><source src="https://codeskulptor-demos.commondatastorage.googleapis.com/despot/ping.mp3" type="audio/mp3"></audio>""", unsafe_allow_html=True)
                        st.info(f"🧪 SEGNALE TEST: {signal} su {asset}")
                    else:
                        # Suono deciso (Siren/Arrow) per Trading Reale
                        st.markdown("""<audio autoplay><source src="https://codeskulptor-demos.commondatastorage.googleapis.com/pang/arrow.mp3" type="audio/mp3"></audio>""", unsafe_allow_html=True)
                        st.warning(f"🔥 SEGNALE REALE: {signal} su {asset}!")

                    if paper_trading:
                        # --- LOGICA SIMULAZIONE (già corretta prima) ---
                        st.info(f"🧪 [SIMULAZIONE] Analisi esito per {asset}...")
                        time_lib.sleep(60) 
                        
                        df_post = get_data_from_iq(API, asset)
                        if not df_post.empty:
                            price_end = df_post['close'].iloc[-1]
                            price_start = stats["Price"]
                            sim_win = price_end > price_start if signal == "CALL" else price_end < price_start
                            
                            res = (stake * 0.85) if sim_win else -stake 
                            
                            st.session_state['trades'].append({
                                "Ora": get_now_rome().strftime("%H:%M:%S"),
                                "Asset": asset,
                                "Tipo": f"SIM-{signal}",
                                "Esito": "WIN" if sim_win else "LOSS",
                                "Profitto": res,
                                "RSI": stats["RSI"], "ADX": stats["ADX"], "Stoch": stats["Stoch_K"],
                                "ATR": stats["ATR"], "Trend": stats["Trend"]
                            })
                            # Usiamo una variabile di stato dedicata per il profitto simulato
                            if 'sim_pnl' not in st.session_state: st.session_state['sim_pnl'] = 0.0
                            st.session_state['sim_pnl'] += res
                            st.rerun()
                    else:
                        # --- LOGICA REALE ---
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
                            
            status.update(label="✅ Scansione completata. In attesa...", state="complete")
else:
    if not st.session_state['iq_api']:
        st.info("👋 Effettua il login per attivare il sistema.")
    else:
        st.warning("⚠️ Bot in pausa.")

# --- GRAFICO IN TEMPO REALE ---
st.markdown("---")
st.subheader(f"📈 Grafico con Indicatori (1m)")
selected_label = st.selectbox("Seleziona Asset per Grafico", list(asset_map.keys()))
pair = asset_map[selected_label]

# Inizializziamo df_rt come vuoto per evitare errori di definizione
df_rt = pd.DataFrame()

if st.session_state['iq_api']:
    try:
        candles_data = st.session_state['iq_api'].get_candles(pair, 60, 200, time_lib.time())
        df_rt = pd.DataFrame(candles_data)
        if not df_rt.empty:
            df_rt.rename(columns={'max': 'high', 'min': 'low', 'open': 'open', 'close': 'close', 'from': 'time'}, inplace=True)
            df_rt['time'] = pd.to_datetime(df_rt['time'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Europe/Rome')
            df_rt.set_index('time', inplace=True)
            
            # Assicurati di calcolare l'ADX anche qui per le metriche visive
            adx_vis = ta.adx(df_rt['high'], df_rt['low'], df_rt['close'], length=14)
            df_rt['adx'] = adx_vis['ADX_14']
            
            # --- CALCOLO INDICATORI PER IL GRAFICO ---
            # Bollinger
            bb = ta.bbands(df_rt['close'], length=20, std=2.2)
            df_rt = pd.concat([df_rt, bb], axis=1)
            c_up = [c for c in df_rt.columns if "BBU" in c.upper()][0]
            c_low = [c for c in df_rt.columns if "BBL" in c.upper()][0]
            
            # RSI (usiamo 7 come nella logica del segnale)
            df_rt['rsi'] = ta.rsi(df_rt['close'], length=7)
            
            # ADX (Necessario per le metriche sotto)
            adx_df = ta.adx(df_rt['high'], df_rt['low'], df_rt['close'], length=14)
            df_rt['adx'] = adx_df['ADX_14']

            # Plotly
            # --- CREAZIONE FIGURA ---
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            
            # Candele
            fig.add_trace(go.Candlestick(x=df_rt.index, open=df_rt['open'], high=df_rt['high'], low=df_rt['low'], close=df_rt['close'], name='Prezzo'), row=1, col=1)
            
            # Bande di Bollinger
            fig.add_trace(go.Scatter(x=df_rt.index, y=df_rt[c_up], line=dict(color='rgba(173, 216, 230, 0.3)', width=1), name='BB Upper'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_rt.index, y=df_rt[c_low], line=dict(color='rgba(173, 216, 230, 0.3)', width=1), fill='tonexty', name='BB Lower'), row=1, col=1)
            
            # RSI
            fig.add_trace(go.Scatter(x=df_rt.index, y=df_rt['rsi'], line=dict(color='yellow'), name='RSI'), row=2, col=1)

            # --- AGGIUNTA FRECCE SEGNALI (Dallo storico trade) ---
            for trade in st.session_state['trades']:
                # Mostriamo solo i segnali dell'asset attualmente visualizzato
                if trade['Asset'] == pair:
                    try:
                        trade_time = pd.to_datetime(trade['Ora'], format='%H:%M:%S').replace(
                            year=df_rt.index[-1].year, month=df_rt.index[-1].month, day=df_rt.index[-1].day
                        ).tz_localize('Europe/Rome')

                        color = "lime" if "CALL" in trade['Tipo'] else "red"
                        symbol = "triangle-up" if "CALL" in trade['Tipo'] else "triangle-down"
                        y_pos = df_rt.loc[trade_time, 'low'] * 0.9999 if "CALL" in trade['Tipo'] else df_rt.loc[trade_time, 'high'] * 1.0001
                        
                        fig.add_trace(go.Scatter(
                            x=[trade_time], y=[y_pos],
                            mode="markers",
                            marker=dict(symbol=symbol, size=15, color=color, line=dict(width=2, color="white")),
                            name=trade['Tipo']
                        ), row=1, col=1)
                    except: continue

            # --- FORZATURA ZOOM 1 ORA E GRIGLIA ---
            ora_fine = df_rt.index[-1]
            ora_inizio = ora_fine - pd.Timedelta(minutes=60)

            fig.update_xaxes(
                range=[ora_inizio, ora_fine],
                type="date", # Forza il tipo data per lo zoom
                dtick=60000, # Linea ogni minuto
                gridcolor='rgba(255, 255, 255, 0.05)',
                row=1, col=1
            )

            # Linee verticali per ogni minuto
            for t in df_rt.index:
                if t >= ora_inizio:
                    fig.add_vline(x=t, line_width=0.4, line_color="rgba(255,255,255,0.1)", row="all")

            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
            
    except Exception as e:
        st.error(f"Errore caricamento grafico: {e}")

else:
    st.info("In attesa della connessione...")

st.markdown("---")
# --- METRICHE DINAMICHE (Protezione contro DataFrame vuoto) ---
st.subheader(f"🔍 Sentinel Real-Time Oscillators")

if not df_rt.empty:
    c1, c2, c3, c4 = st.columns(4)

    # Estrazione valori sicura
    curr_p = df_rt['close'].iloc[-1]
    curr_rsi = df_rt['rsi'].iloc[-1]
    curr_adx = df_rt['adx'].iloc[-1]
    bb_upper = df_rt[c_up].iloc[-1]
    bb_lower = df_rt[c_low].iloc[-1]

    # Visualizzazione Metriche
    c1.metric("Prezzo Attuale", f"{curr_p:.5f}")

    c2.metric("RSI (7)", f"{curr_rsi:.2f}", 
              delta="IPER-COMPRATO" if curr_rsi > 75 else "IPER-VENDUTO" if curr_rsi < 25 else "NEUTRO",
              delta_color="inverse" if curr_rsi > 75 or curr_rsi < 25 else "normal")

    c3.metric("ADX (14)", f"{curr_adx:.2f}", 
              delta="VOLATILITÀ OK" if 15 < curr_adx < 35 else "SCONSIGLIATO",
              delta_color="normal" if 15 < curr_adx < 35 else "inverse")

    # Distanza dalle Bande
    dist_up = bb_upper - curr_p
    dist_low = curr_p - bb_lower
    min_dist = min(abs(dist_up), abs(dist_low))
    c4.metric("Distanza BB", f"{min_dist:.5f}", 
              delta="TOCCATA" if dist_up <= 0 or dist_low <= 0 else "IN RANGE")
else:
    st.info("In attesa della connessione...")

# --- CURRENCY STRENGTH ---
st.markdown("---")
st.subheader("⚡ Currency Strength (IQ Option Data)")
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
    stsubheader(f"🧪 Profitto Simulato: € {sim_pnl:.2f}")

if st.session_state['trades']:
    st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)

# Auto-refresh ogni 60s
st.sidebar.markdown("""<div style="background:#222; height:5px; width:100%; border-radius:10px; overflow:hidden;"><div style="background:red; height:100%; width:100%; animation: fill 60s linear infinite;"></div></div><style>@keyframes fill {0% {width: 0%;} 100% {width: 100%;}}</style>""", unsafe_allow_html=True)
time_lib.sleep(60)
st.rerun()

# --- SEZIONE ANALISI TECNICA POST-SESSIONE ---
st.markdown("---")
st.subheader("🔬 Sentinel Deep Analysis")

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
    st.download_button("📥 SCARICA REPORT (CSV)", data=csv, file_name="Sentinel_Report.csv", mime="text/csv")
else:
    st.info("⏳ In attesa di dati per l'analisi")
