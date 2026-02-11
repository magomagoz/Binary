# ✅ SCANNER COMPLETO + TRADE AUTOMATICI 1m (tutto incluso)
import streamlit as st
import pandas as pd
import pandas_ta as ta
import time_module
from datetime import datetime

ALL_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]

if st.session_state.get('connected', False):
    # ✅ INIZIALIZZAZIONE COMPLETA
    if 'scanner' not in st.session_state: st.session_state.scanner = False
    if 'scanner_data' not in st.session_state: st.session_state.scanner_data = {}
    if 'scanner_last_update' not in st.session_state: st.session_state.scanner_last_update = 0
    if 'scanner_alerts' not in st.session_state: st.session_state.scanner_alerts = []
    if 'rsi_buy' not in st.session_state: st.session_state.rsi_buy = 30
    if 'rsi_sell' not in st.session_state: st.session_state.rsi_sell = 70
    if 'amount' not in st.session_state: st.session_state.amount = 1
    if 'trades_executed' not in st.session_state: st.session_state.trades_executed = []
    if 'total_profit' not in st.session_state: st.session_state.total_profit = 0
    
    Iq = st.session_state['iq']
    
    # ✅ TOGGLE SCANNER + TRADE AUTO
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.scanner = st.toggle("🔍 **Attiva Scanner**", value=st.session_state.scanner)
    with col2:
        auto_trade = st.toggle("🤖 **Trade Automatici 1m**", value=False)
    
    # ✅ PARAMETRI
    col1, col2, col3 = st.columns(3)
    with col1: st.session_state.rsi_buy = st.number_input("RSI Buy", value=30, min_value=10, max_value=40)
    with col2: st.session_state.rsi_sell = st.number_input("RSI Sell", value=70, min_value=60, max_value=90)
    with col3: st.session_state.amount = st.number_input("Importo €", value=1, min_value=1, max_value=100)
    
    if st.session_state.scanner:
        # ✅ STATUS
        last_scan = datetime.fromtimestamp(st.session_state.scanner_last_update).strftime("%H:%M:%S")
        st.markdown(f"🕐 **Scanner ultimo update**: {last_scan}")
        
        # ✅ SCANNER OGNI 60s + TRADE AUTO
        current_time = time_module.time()
        if current_time - st.session_state.scanner_last_update > 60:
            placeholder = st.empty()
            with placeholder.container():
                st.spinner("🔍 Scanning + Trading...")
            
            st.session_state.scanner_data = {}
            st.session_state.scanner_alerts = []
            trades_this_scan = 0
            
            for pair in ALL_PAIRS:
                try:
                    # 📊 CANDLES 1m
                    candles = Iq.get_candles(pair, 60, 50, time_module.time())
                    if not candles: 
                        raise ValueError("No candles")
                    
                    df = pd.DataFrame(candles)
                    df['from'] = pd.to_datetime(df['from'], unit='s')
                    df.set_index('from', inplace=True)
                    
                    # 🔧 INDICATORI
                    df['RSI'] = ta.rsi(df['close'], length=14)
                    macd = ta.macd(df['close'])
                    df['MACD'] = macd['MACD_12_26_9']
                    df['MACD_signal'] = macd['MACDs_12_26_9']
                    
                    latest_rsi = df['RSI'].iloc[-1]
                    macd_bullish = df['MACD'].iloc[-1] > df['MACD_signal'].iloc[-1]
                    current_price = df['close'].iloc[-1]
                    
                    signal = "⚪ ATTESA"
                    
                    # 🟢 TRADE AUTOMATICO CALL 1m
                    if auto_trade and latest_rsi < st.session_state.rsi_buy and macd_bullish:
                        result = Iq.buy(
                            amount=st.session_state.amount,
                            asset=pair,
                            action="call",
                            duration=1,  # 1 MINUTO
                            price=current_price
                        )
                        
                        trade_info = {
                            'time': datetime.now().strftime("%H:%M:%S"),
                            'pair': pair,
                            'type': '🟢 CALL',
                            'amount': st.session_state.amount,
                            'price': f"{current_price:.5f}",
                            'id': result.get('id', 'N/A'),
                            'status': '⏳ PENDING'
                        }
                        st.session_state.trades_executed.append(trade_info)
                        st.session_state.scanner_alerts.append(trade_info)
                        trades_this_scan += 1
                        signal = "🟢🔼 COMPRA AUTO"
                    
                    # 🔴 TRADE AUTOMATICO PUT 1m  
                    elif auto_trade and latest_rsi > st.session_state.rsi_sell and not macd_bullish:
                        result = Iq.buy(
                            amount=st.session_state.amount,
                            asset=pair,
                            action="put",
                            duration=1,  # 1 MINUTO
                            price=current_price
                        )
                        
                        trade_info = {
                            'time': datetime.now().strftime("%H:%M:%S"),
                            'pair': pair,
                            'type': '🔴 PUT',
                            'amount': st.session_state.amount,
                            'price': f"{current_price:.5f}",
                            'id': result.get('id', 'N/A'),
                            'status': '⏳ PENDING'
                        }
                        st.session_state.trades_executed.append(trade_info)
                        st.session_state.scanner_alerts.append(trade_info)
                        trades_this_scan += 1
                        signal = "🔴🔽 VENDI AUTO"
                    
                    # 📊 SALVA DATI
                    st.session_state.scanner_data[pair] = {
                        'price': f"{current_price:.5f}",
                        'rsi': f"{latest_rsi:.1f}",
                        'signal': signal
                    }
                    
                except Exception as e:
                    st.session_state.scanner_data[pair] = {
                        'price': '❌', 'rsi': '❌', 'signal': f'ERROR'
                    }
            
            st.session_state.scanner_last_update = current_time
            placeholder.success(f"✅ Scanner aggiornato! {trades_this_scan} trade eseguiti")
            st.rerun()
        
        # ✅ TABELLA SCANNER
        st.subheader("🔍 **SCANNER FOREX**")
        if st.session_state.scanner:
            scanner_df = pd.DataFrame(st.session_state.scanner_data).T
            scanner_df.reset_index(inplace=True)
            scanner_df.rename(columns={'index': 'PAIR'}, inplace=True)
            scanner_df = scanner_df[['PAIR', 'price', 'rsi', 'signal']]
            st.dataframe(scanner_df, use_container_width=True, height=400, hide_index=True)
        
        # ✅ TRADES LIVE
        if st.session_state.trades_executed:
            st.subheader("📊 **TRADES IN CORSO**")
            trades_df = pd.DataFrame(st.session_state.trades_executed)
            st.dataframe(trades_df, use_container_width=True)
            
            # 💰 PROFITTO TOTALE
            st.metric("💵 Profitto Totale", f"€{st.session_state.total_profit:.2f}")
