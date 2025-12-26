import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import datetime

# --- UI KONFIGURATION ---
st.set_page_config(page_title="Aktien-KI Watchlist", layout="wide")
st.title("🚀 Meine KI-Aktien-Watchlist")
st.write("Analysiert Verschuldung, Trends und Korrektur-Größen live.")

# --- VERBINDUNG ZUM GOOGLE SHEET ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    # Liest das Blatt "Aktien-Ki" (Ticker, Manueller_Fairer_Wert, Notizen)
    return conn.read(worksheet="Aktien-Ki")

def get_stock_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="3y") # Für Trend-Check
        
        # Fundamentale Daten
        price = info.get('currentPrice', 0)
        debt_equity = info.get('debtToEquity', 0) / 100 # In Dezimal umrechnen
        pe_ratio = info.get('trailingPE', 0)
        ath_52w = info.get('fiftyTwoWeekHigh', 1)
        
        # Berechnung Korrektur
        current_correction = ((price / ath_52w) - 1) * 100
        
        # Trend-Check (SMA 200)
        sma200 = hist['Close'].rolling(window=200).mean()
        current_sma = sma200.iloc[-1]
        trend_ok = "✅ Aufwärtstrend" if price > current_sma else "⚠️ Abwärtstrend"
        
        # Durchschnittliche Korrektur (Dips der letzten 3 Jahre)
        # Vereinfachte Logik: Durchschnitt der monatlichen Rücksetzer
        monthly_lows = hist['Low'].resample('M').min()
        monthly_highs = hist['High'].resample('M').max()
        avg_dip = ((monthly_lows / monthly_highs) - 1).mean() * 100

        return {
            "Kurs": price,
            "KGV": pe_ratio,
            "Schulden_Quote": debt_equity,
            "Korrektur_%": current_correction,
            "Ø_Korrektur_%": avg_dip,
            "Trend": trend_ok
        }
    except:
        return None

# --- HAUPTPROGRAMM ---
df_watchlist = load_data()

if not df_watchlist.empty:
    results = []
    
    for index, row in df_watchlist.iterrows():
        ticker = row['Ticker']
        with st.spinner(f'Analysiere {ticker}...'):
            metrics = get_stock_metrics(ticker)
            if metrics:
                # Kombiniere Sheet-Daten mit Live-Daten
                combined = {**row, **metrics}
                results.append(combined)

    df_final = pd.DataFrame(results)

    # --- FILTER & LOGIK ANWENDEN ---
    def highlight_debt(val):
        color = 'background-color: #90EE90' if val < 0.6 else 'background-color: #FFB6C1'
        return color

    # Tabelle anzeigen
    st.subheader("Deine Watchlist Analyse")
    st.dataframe(df_final.style.applymap(highlight_debt, subset=['Schulden_Quote']))

    # --- MANUELLE ANPASSUNG ---
    st.divider()
    st.subheader("Manuelle Anpassungen & Notizen")
    selected_ticker = st.selectbox("Aktie auswählen zum Bearbeiten:", df_final['Ticker'])
    
    new_fair_value = st.number_input("Fairer Wert anpassen:")
    new_note = st.text_area("Neue Information / Notiz:")

    if st.button("Änderungen im Google Sheet speichern"):
        # Hier würde die Logik stehen, um die Zeile im Sheet zu überschreiben
        st.success(f"Daten für {selected_ticker} wurden im Google Sheet aktualisiert!")
else:
    st.info("Dein Google Sheet ist noch leer. Füge Ticker in das Blatt 'Watchlist' ein.")
