import streamlit as st
import yfinance as yf
import pandas as pd

# --- SEITEN-KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide")

st.title("🚀 KI-Aktien-Watchlist (Demo-Modus)")
st.info("Diese Version läuft ohne Google Sheet. Ticker können direkt unten hinzugefügt werden.")

# --- DATEN-LOGIK (SIMULIERTES SHEET) ---
# Hier definieren wir die Ticker, die normalerweise in deinem Sheet stehen würden
if 'ticker_liste' not in st.session_state:
    st.session_state.ticker_liste = ["AAPL", "MSFT", "TSLA", "NVDA", "ASML"]

# --- ANALYSE-FUNKTION ---
@st.cache_data(ttl=3600)
def get_stock_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        
        if hist.empty: return None

        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        
        # Schulden-Quote (Debt/Equity)
        de_raw = info.get('debtToEquity')
        # Korrektur: Viele Broker geben 40.5 aus, wir wollen 0.405
        debt_equity = (de_raw / 100) if (de_raw and de_raw > 2) else (de_raw or 0)
        
        # 52-Wochen-Hoch & Korrektur
        ath_52w = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        correction = ((price / ath_52w) - 1) * 100
        
        # Trend (SMA 200)
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        return {
            "Ticker": ticker,
            "Kurs": round(price, 2),
            "KGV": info.get('trailingPE', "N/A"),
            "Schulden_Quote": round(debt_equity, 3),
            "Korrektur_%": round(correction, 2),
            "Trend": "Aufwärts ✅" if price > sma200 else "Abwärts ⚠️"
        }
    except:
        return None

# --- UI: NEUEN TICKER HINZUFÜGEN ---
with st.expander("➕ Neuen Ticker hinzufügen"):
    new_ticker = st.text_input("Ticker Symbol (z.B. SAP.DE, AMZN):").upper()
    if st.button("Hinzufügen"):
        if new_ticker and new_ticker not in st.session_state.ticker_liste:
            st.session_state.ticker_liste.append(new_ticker)
            st.rerun()

# --- HAUPTPROGRAMM ---
if st.session_state.ticker_liste:
    results = []
    
    # Analyse der Ticker
    for symbol in st.session_state.ticker_liste:
        with st.spinner(f"Lade {symbol}..."):
            m = get_stock_metrics(symbol)
            if m:
                results.append(m)
    
    if results:
        df_final = pd.DataFrame(results)
        
        # --- STYLING ---
        def highlight_debt(row):
            # Grün markieren, wenn Schulden < 60%
            color = 'background-color: rgba(0, 255, 0, 0.1)' if row['Schulden_Quote'] < 0.6 else ''
            return [color] * len(row)

        st.subheader("Aktuelle Analyse")
        st.dataframe(
            df_final.style.apply(highlight_debt, axis=1),
            use_container_width=True,
            hide_index=True
        )
        
        # Mobile-Optimierte Ansicht (Karten-Layout)
        st.write("---")
        st.subheader("Mobile Schnellansicht")
        for res in results:
            col1, col2 = st.columns([1, 1])
            with col1:
                st.metric(res['Ticker'], f"{res['Kurs']} €", f"{res['Korrektur_%']}%")
            with col2:
                status = "✅ STARK" if res['Schulden_Quote'] < 0.6 else "⚠️ HOCH"
                st.write(f"Schulden: {res['Schulden_Quote']} ({status})")
                st.write(f"Trend: {res['Trend']}")
            st.divider()
    else:
        st.warning("Konnte keine Daten abrufen.")
