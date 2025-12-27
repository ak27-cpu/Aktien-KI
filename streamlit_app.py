import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import pandas as pd

# --- KONFIGURATION ---
st.set_page_config(page_title="Aktien-KI | Supabase", layout="wide")

# --- SUPABASE VERBINDUNG ---
@st.cache_resource
def get_supabase():
    # Diese Werte müssen in den Streamlit Secrets stehen
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

# --- DATEN-FUNKTIONEN ---
def load_watchlist():
    response = supabase.table("watchlist").select("*").execute()
    return pd.DataFrame(response.data)

def add_ticker(ticker, fair_value):
    try:
        supabase.table("watchlist").insert({
            "ticker": ticker.upper(),
            "fair_value": fair_value
        }).execute()
        return True
    except:
        return False

def delete_ticker(ticker_id):
    supabase.table("watchlist").delete().eq("id", ticker_id).execute()

# --- ANALYSE-LOGIK ---
@st.cache_data(ttl=3600)
def get_live_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        if hist.empty: return None

        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        de = info.get('debtToEquity', 0)
        debt_ratio = de / 100 if de > 2 else de
        
        ath = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        correction = ((price / ath) - 1) * 100
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]

        return {
            "Live_Kurs": round(price, 2),
            "Schulden_Quote": round(debt_ratio, 3),
            "Korrektur_%": round(correction, 1),
            "Trend": "Aufwärts ✅" if price > sma200 else "Abwärts ⚠️"
        }
    except:
        return None

# --- UI DESIGN ---
st.title("🚀 Meine KI-Watchlist")
st.caption("Datenquelle: Supabase SQL & Yahoo Finance")

# Sidebar für Verwaltung
with st.sidebar:
    st.header("➕ Neue Aktie")
    with st.form("add_form", clear_on_submit=True):
        new_t = st.text_input("Ticker (z.B. AAPL, SAP.DE)")
        new_fv = st.number_input("Mein Fairer Wert", value=0.0)
        submit = st.form_submit_button("Hinzufügen")
        
        if submit and new_t:
            if add_ticker(new_t, new_fv):
                st.success("Gespeichert!")
                st.rerun()
            else:
                st.error("Fehler (Ticker schon vorhanden?)")

# Hauptinhalt
df_db = load_watchlist()

if not df_db.empty:
    results = []
    for _, row in df_db.iterrows():
        with st.spinner(f"Analysiere {row['ticker']}..."):
            live = get_live_metrics(row['ticker'])
            if live:
                # Kombiniere DB-Daten mit Live-Daten
                results.append({**row, **live})

    if results:
        df_final = pd.DataFrame(results)
        
        # Spalten sortieren für bessere Ansicht
        cols = ["ticker", "Live_Kurs", "fair_value", "Schulden_Quote", "Korrektur_%", "Trend"]
        df_display = df_final[cols]

        # Styling
        def style_rows(row):
            # Grün markieren wenn Schulden < 60% UND Kurs unter Fairem Wert
            color = ''
            if row['Schulden_Quote'] < 0.6:
                color = 'background-color: rgba(0, 255, 0, 0.1)'
            return [color] * len(row)

        st.dataframe(
            df_display.style.apply(style_rows, axis=1).format({"Schulden_Quote": "{:.2f}", "Live_Kurs": "{:.2f} €"}),
            use_container_width=True,
            hide_index=True
        )

        # Lösch-Bereich
        with st.expander("🗑️ Aktie entfernen"):
            to_delete = st.selectbox("Ticker wählen", df_final['ticker'])
            id_to_del = df_final[df_final['ticker'] == to_delete]['id'].values[0]
            if st.button("Endgültig löschen"):
                delete_ticker(id_to_del)
                st.rerun()
else:
    st.info("Deine Datenbank ist noch leer. Füge links einen Ticker hinzu.")
