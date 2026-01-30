import streamlit as st
import pandas as pd
import pandas_ta as ta
from iqoptionapi.stable_api import IQ_Option
import time as time_lib
from datetime import datetime
import pytz
from iqoptionapi.stable_api import IQ_Option
import logging

# --- CONFIGURAZIONE CREDENZIALI (NON HARDCODARE LA PASSWORD SE PUOI) ---
# Usa st.secrets o variabili d'ambiente per sicurezza
# Recupero dai Secrets
IQ_EMAIL = st.secrets["IQ_EMAIL"]
IQ_PASS = st.secrets["IQ_PASS"]
TELE_TOKEN = st.secrets["TELEGRAM_TOKEN"]
TELE_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]

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

def connetti(self):
    check, reason = self.api.connect()
    if check:
        # FORZA IL CONTO DEMO (PRACTICE)
        self.api.change_balance("PRACTICE") 
        saldo = self.api.get_balance()
        print(f"✅ Connesso! Saldo Demo attuale: {saldo}€")
        self.connected = True
    else:
        self.connected = False
    return self.connected

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

def invia_report_settimanale():
    """Genera e invia il riepilogo delle performance via Telegram"""
    data = get_advanced_stats()
    if not data:
        invia_telegram("📊 **Report Settimanale**: Nessuna operazione conclusa questa settimana.")
        return

    stats, asset_perf, _ = data
    
    # Costruiamo il messaggio
    msg = (
        "📊 **SENTINEL: REPORT SETTIMANALE** 📈\n"
        "----------------------------------\n"
        f"💰 **Profitto Netto:** € {stats['total_pnl']:.2f}\n"
        f"🏆 **Win Rate:** {stats['win_rate']:.1f}%\n"
        f"🚀 **Miglior Asset:** {stats['best_asset']}\n"
        f"⚠️ **Ora Critica:** {stats['worst_hour']}\n"
        "----------------------------------\n"
        "✅ Mercati in chiusura. Buon weekend!"
    )
    
    invia_telegram(msg)

def get_currency_strength():
    try:
        forex = ["EURUSD", "GBPUSD", "USDCHF", "USDCHF", "AUDUSD", "NZDUSD", "EURCHF","EURJPY", "GBPJPY","EURGBP"]
        data = yf.download(forex, period="5d", interval="1d", progress=False, timeout=15)
        
        if data is None or data.empty: 
            return pd.Series(dtype=float)

        if isinstance(data.columns, pd.MultiIndex):
            if 'Close' in data.columns.get_level_values(0): close_data = data['Close']
            else: close_data = data['Close'] if 'Close' in data else data
        else:
            close_data = data['Close'] if 'Close' in data else data

        close_data = close_data.ffill().dropna()
        if len(close_data) < 2: return pd.Series(dtype=float)

        returns = close_data.pct_change().iloc[-1] * 100
        
        strength = {
            "USD 🇺🇸": (-returns.get("EURUSD=X",0) - returns.get("GBPUSD=X",0) + returns.get("USDJPY=X",0) - returns.get("AUDUSD=X",0) + returns.get("USDCAD=X",0) + returns.get("USDCHF=X",0) - returns.get("NZDUSD=X",0) + returns.get("USDCNY=X",0) + returns.get("USDRUB=X",0) + returns.get("USDCOP=X",0) + returns.get("USDARS=X",0) + returns.get("USDBRL=X",0)) / 12,
            "EUR 🇪🇺": (returns.get("EURUSD=X",0) + returns.get("EURJPY=X",0) + returns.get("EURGBP=X",0) + returns.get("EURCHF=X", 0) + returns.get("EURGBP=X", 0) + returns.get("EURJPY=X", 0)) / 6,
            "GBP 🇬🇧": (returns.get("GBPUSD=X",0) + returns.get("GBPJPY=X",0) - returns.get("EURGBP=X",0) + returns.get("GBPCHF=X", 0) + returns.get("GBPJPY=X", 0)) / 5,
            "JPY 🇯🇵": (-returns.get("USDJPY=X",0) - returns.get("EURJPY=X",0) - returns.get("GBPJPY=X",0)) / 3,
            "CHF 🇨🇭": (-returns.get("USDCHF=X",0) - returns.get("EURCHF=X",0) - returns.get("GBPCHF=X",0)) / 3,
            "AUD 🇦🇺": returns.get("AUDUSD=X", 0),
            "NZD 🇳🇿": returns.get("NZDUSD=X", 0),
            "CAD 🇨🇦": -returns.get("USDCAD=X", 0)
            #"CNY 🇨🇳": -returns.get("CNY=X", 0),
            #"RUB 🇷🇺": -returns.get("RUB=X", 0),
            #"COP 🇨🇴": -returns.get("COP=X", 0),
            #"ARS 🇦🇷": -returns.get("ARS=X", 0),
            #"BRL 🇧🇷": -returns.get("BRL=X", 0),
            #"MXN 🇲🇽": -returns.get("MXN=X", 0)
            #"BTC ₿": returns.get("BTC-USD", 0),
            #"ETH 💎": returns.get("ETH-USD", 0)
        }
        return pd.Series(strength).sort_values(ascending=False)
    except Exception:
        return pd.Series(dtype=float)

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
target_profit = st.sidebar.number_input("Target Profit Giornaliero (€)", value=100.0)
stop_loss_limit = st.sidebar.number_input("Stop Loss Giornaliero (€)", value=30.0)
stake = st.sidebar.number_input("Investimento singolo (€)", value=20.0)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Sicurezza Sistema")

# Tasto dinamico per attivare/disattivare
if st.session_state['trading_attivo']:
    if st.sidebar.button("🛑 STOP TOTALE BOT", use_container_width=True, type="primary"):
        st.session_state['trading_attivo'] = False
        send_telegram_msg("⚠️ **SISTEMA SOSPESO**: Kill-switch attivato manualmente.")
        st.rerun()
else:
    if st.sidebar.button("🚀 RIATTIVA SISTEMA", use_container_width=True):
        st.session_state['trading_attivo'] = True
        send_telegram_msg("✅ **SISTEMA RIATTIVATO**: Il bot riprende l'analisi.")
        st.rerun()

# Stato visivo
status_color = "green" if st.session_state['trading_attivo'] else "red"
st.sidebar.markdown(f"<p style='text-align:center; color:{status_color}; font-weight:bold;'>Stato: {'OPERATIVO' if st.session_state['trading_attivo'] else 'SOSPESO'}</p>", unsafe_allow_html=True)

st.sidebar.markdown("---")
# Countdown Testuale e Barra Rossa Animata
st.sidebar.markdown("⏳ **Prossimo Scan**")

# CSS per la barra che si riempie in 60 secondi
st.sidebar.markdown("""
    <style>
        @keyframes progressFill {
            0% { width: 0%; }
            100% { width: 100%; }
        }
        .container-bar {
            width: 100%; background-color: #222; border-radius: 5px;
            height: 12px; margin-bottom: 25px; border: 1px solid #444; overflow: hidden;
        }
        .red-bar {
            height: 100%; background-color: #ff4b4b; width: 0%;
            animation: progressFill 60s linear infinite;
            box-shadow: 0 0 10px #ff4b4b;
        }
    </style>
    <div class="container-bar"><div class="red-bar"></div></div>
""", unsafe_allow_html=True)

with st.sidebar.expander("🔍 Live Sentinel Data", expanded=True):
    if 'sentinel_logs' in st.session_state and st.session_state['sentinel_logs']:
        for log in st.session_state['sentinel_logs']:
            st.caption(log)
    else:
        st.caption("In attesa del primo scan...")

st.sidebar.subheader("📡 Sentinel Status")
status = st.session_state.get('last_scan_status', 'In attesa...')

# Usiamo un contenitore con colore dinamico
if "⚠️" in status:
    st.sidebar.error(status)
elif "🔍" in status:
    st.sidebar.success(status)
else:
    st.sidebar.info(status)

# Parametri Input
selected_label = st.sidebar.selectbox("**Asset**", list(asset_map.keys()))
pair = asset_map[selected_label]

st.sidebar.markdown("---")
# ... (restante codice sidebar: sessioni, win rate, reset)
st.sidebar.subheader("🌍 Sessioni di Mercato")
for s_name, is_open in get_session_status().items():
    color = "🟢" if is_open else "🔴"
    status_text = "APERTO" if is_open else "CHIUSO"
    st.sidebar.markdown(f"**{s_name}** <small>: {status_text}</small> {color}",
unsafe_allow_html=True)
   
# --- TASTO ESPORTAZIONE DATI ---
#st.sidebar.markdown("---")
#st.sidebar.subheader("💾 Backup Report")

#if not st.session_state['signal_history'].empty:
    #csv_data = st.session_state['signal_history'].to_csv(index=False).encode('utf-8')
    #st.sidebar.download_button(
        #label="📥 SCARICA CRONOLOGIA CSV",
        #data=csv_data,
        #file_name=f"Trading_Report_{get_now_rome().strftime('%Y%m%d_%H%M')}.csv",
        #mime="text/csv",
        #use_container_width=True
    #)
#else:
    #st.sidebar.info("Nessun dato da esportare")

# --- TASTO TEST TELEGRAM ---
st.sidebar.markdown("---")
if st.sidebar.button("✈️ TEST NOTIFICA TELEGRAM"):
    test_msg = "🔔 **SENTINEL TEST**\nIl sistema di notifiche è operativo! 🚀"
    send_telegram_msg(test_msg)
    st.sidebar.success("Segnale di test inviato!")

# --- TASTO TEST DINAMICO ---
if st.sidebar.button("🔊 TEST ALERT COMPLETO"):
    # Calcolo dinamico basato sui tuoi cursori attuali
    current_bal = st.session_state.get('balance_val', 1000)
    current_r = st.session_state.get('risk_val', 2.0)
    inv_test = current_bal * (current_r / 100)
    
    test_data = {
        'DataOra': get_now_rome().strftime("%Y-%m-%d %H:%M:%S"),
        'Asset': 'TEST/EUR', 
        'Direzione': 'VENDI', 
        'Prezzo': '1.0950', 
        'TP': '1.0900', 
        'SL': '1.0980', 
        'Stato': 'In Corso',
        'Investimento €': f"{inv_test:.2f}", # Ora legge il 2% di 1000 = 20.00
        'Risultato €': "0.00",
        'Costo Spread €': f"{(inv_test):.2f}",
        'Stato_Prot': 'Iniziale',
        'Protezione': 'Trailing 3/6%'
    }
    
    st.session_state['signal_history'] = pd.concat(
        [pd.DataFrame([test_data]), st.session_state['signal_history']], 
        ignore_index=True
    )
    st.session_state['last_alert'] = test_data
    if 'alert_notified' in st.session_state: del st.session_state['alert_notified']
    st.rerun()

# Reset Sidebar
st.sidebar.markdown("---")
with st.sidebar.popover("🗑️ **Reset Cronologia**"):
    st.warning("Sei sicuro? Questa azione cancellerà tutti i segnali salvati.")

    if st.button("SÌ, CANCELLA ORA"):
        st.session_state['signal_history'] = pd.DataFrame(columns=['DataOra', 'Asset', 'Direzione', 'Prezzo', 'SL', 'TP', 'Size', 'Stato'])
        save_history_permanently() # Questo sovrascrive il file CSV con uno vuoto
        st.rerun()

st.sidebar.markdown("---")

#if st.sidebar.button("TEST ALERT"):
    #st.session_state['last_alert'] = {'Asset': 'TEST/EUR', 'Direzione': 'COMPRA', 'Prezzo': '1.0000', 'TP': '1.0100', 'SL': '0.9900', 'Protezione': 'Standard'}
    #if 'alert_start_time' in st.session_state: del st.session_state['alert_start_time']
    #st.rerun()

#st.sidebar.markdown("---")

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

st.info(f"🛰️ **Sentinel AI Attiva**: Monitoraggio in corso su {len(asset_map)} asset Forex in tempo reale (1m).")
st.caption(f"Ultimo aggiornamento globale: {get_now_rome().strftime('%Y-%m-%d %H:%M:%S')}")

st.markdown("---")
#st.subheader("📈 Grafico in tempo reale")
st.subheader(f"📈 Grafico {selected_label} (1m) con BB e RSI")

p_unit, price_fmt, p_mult, a_type = get_asset_params(pair)
df_rt = get_realtime_data(pair) 
df_d = yf.download(pair, period="1y", interval="1d", progress=False)

if df_rt is not None and not df_rt.empty and df_d is not None and not df_d.empty:
    
    # Pulizia dati
    if isinstance(df_d.columns, pd.MultiIndex): df_d.columns = df_d.columns.get_level_values(0)
    df_d.columns = [c.lower() for c in df_d.columns]
    
    # Calcolo indicatori
    bb = ta.bbands(df_rt['close'], length=20, std=2)
    df_rt = pd.concat([df_rt, bb], axis=1)
    df_rt['rsi'] = ta.rsi(df_rt['close'], length=14)
    df_d['rsi'] = ta.rsi(df_d['close'], length=14)
    df_d['atr'] = ta.atr(df_d['high'], df_d['low'], df_d['close'], length=14)
          
    c_up = [c for c in df_rt.columns if "BBU" in c.upper()][0]
    c_mid = [c for c in df_rt.columns if "BBM" in c.upper()][0]
    c_low = [c for c in df_rt.columns if "BBL" in c.upper()][0]
    
    curr_p = float(df_rt['close'].iloc[-1])
    curr_rsi = float(df_rt['rsi'].iloc[-1])
    rsi_val = float(df_d['rsi'].iloc[-1]) 
    last_atr = float(df_d['atr'].iloc[-1])
    
    score = 50 + (20 if curr_p < df_rt[c_low].iloc[-1] else -20 if curr_p > df_rt[c_up].iloc[-1] else 0)

    # --- COSTRUZIONE GRAFICO ---
    p_df = df_rt.tail(60)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    # Candele
    fig.add_trace(go.Candlestick(
        x=p_df.index, open=p_df['open'], high=p_df['high'], 
        low=p_df['low'], close=p_df['close'], name='Prezzo'
    ), row=1, col=1)
    
    # Bande Bollinger
    fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_up], line=dict(color='rgba(0, 191, 255, 0.6)', width=1), name='Upper BB'), row=1, col=1)
    fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_mid], line=dict(color='rgba(0, 0, 0, 0.3)', width=1), name='BBM'), row=1, col=1)
    fig.add_trace(go.Scatter(x=p_df.index, y=p_df[c_low], line=dict(color='rgba(0, 191, 255, 0.6)', width=1), fill='tonexty', fillcolor='rgba(0, 191, 255, 0.15)', name='Lower BB'), row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=p_df.index, y=p_df['rsi'], line=dict(color='#ffcc00', width=2), name='RSI'), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff00", row=2, col=1)

    # --- AGGIUNTA GRIGLIA VERTICALE (OGNI 10 MINUTI) ---
    for t in p_df.index:
        if t.minute % 10 == 0:
            fig.add_vline(x=t, line_width=0.5, line_dash="solid", line_color="rgba(0, 0, 0, 0.3)", layer="below")

    # Layout Grafico
    fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=30,b=0), legend=dict(orientation="h", y=1.02))
    st.plotly_chart(fig, use_container_width=True)

    # 4. Metriche Base
    c_met1, c_met2 = st.columns(2)
    c_met1.metric(label=f"Prezzo {selected_label}", value=price_fmt.format(curr_p))
    c_met2.metric(label="RSI (5m)", value=f"{curr_rsi:.1f}", delta="Ipercomprato" if curr_rsi > 70 else "Ipervenduto" if curr_rsi < 30 else "Neutro", delta_color="inverse")
    
    st.caption(f"📢 RSI Daily: {rsi_val:.1f} | Divergenza: {detect_divergence(df_d)}")

    # --- VISUALIZZAZIONE METRICHE AVANZATE (ADX & AI) ---
    adx_df_ai = ta.adx(df_rt['high'], df_rt['low'], df_rt['close'], length=14)
    curr_adx_ai = adx_df_ai['ADX_14'].iloc[-1]

# --- 8. CURRENCY STRENGTH ---
st.markdown("---")
st.subheader("⚡ Currency Strength Meter")
s_data = get_currency_strength()

if not s_data.empty:
    cols = st.columns(len(s_data))
    for i, (curr, val) in enumerate(s_data.items()):
        bg = "#006400" if val > 0.15 else "#8B0000" if val < -0.15 else "#333333"
        txt_c = "#00FFCC" if val > 0.15 else "#FF4B4B" if val < -0.15 else "#FFFFFF"
        cols[i].markdown(
            f"<div style='text-align:center; background:{bg}; padding:6px; border-radius:8px; border:1px solid {txt_c}; min-height:80px;'>"
            f"<b style='color:white; font-size:0.8em;'>{curr}</b><br>"
            f"<span style='color:{txt_c};'>{val:.2f}%</span></div>", 
            unsafe_allow_html=True
        )
else:
    st.info("⏳ Caricamento dati macro in corso...")

# --- 9. CRONOLOGIA SEGNALI (CON COLORI DINAMICI) ---
st.markdown("---")
st.subheader("📜 Cronologia Segnali")

if not st.session_state['signal_history'].empty:
    display_df = st.session_state['signal_history'].copy()
    display_df = display_df.sort_values(by='DataOra', ascending=False)

    try:
        # Applichiamo gli stili a colonne diverse
        styled_df = display_df.style.map(
            style_status, subset=['Stato']
        ).map(
            style_protection, subset=['Protezione']
        )

        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_order=[
                'DataOra', 'Asset', 'Direzione', 'Prezzo', 
                'TP', 'SL', 'Stato', 'Protezione', 
                'Investimento €', 'Risultato €'
            ]
        )
    except Exception as e:
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    # 4. Pulsante esportazione (Sempre dentro l'IF, ma fuori dal TRY/EXCEPT)
    st.write("") 
    csv_data = display_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Esporta Cronologia (CSV)",
        data=csv_data,
        file_name=f"trading_history_{datetime.now(rome_tz).strftime("%Y-%m-%d %H:%M:%S")}.csv",
        mime="text/csv",
        use_container_width=True
    )
    
# 5. Se la cronologia è vuota (allineato all'IF iniziale)
else:
    st.info("Nessun segnale registrato.")

# --- REPORTING ---
st.divider()
st.subheader(f"Risultato Sessione: ${st.session_state['daily_pnl']:.2f}")
if st.session_state['trades']:
    st.table(pd.DataFrame(st.session_state['trades']))
                
if st.session_state['trades']:
    st.subheader("📜 Cronologia Sessione")
    st.dataframe(pd.DataFrame(st.session_state['trades']), use_container_width=True)



