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
# --- BERECHNUNGEN & UI ERWEITERUNG ---
df_db = load_watchlist()

if not df_db.empty:
    results = []
    for _, row in df_db.iterrows():
        with st.spinner(f"Analysiere {row['ticker']}..."):
            live = get_live_metrics(row['ticker'])
            if live:
                # 1. Berechnung: Abstand zum Fairen Wert
                fv = row.get('fair_value', 0)
                diff_to_fv = ((live['Live_Kurs'] / fv) - 1) * 100 if fv > 0 else 0
                
                # Alles zusammenfügen
                results.append({
                    **row, 
                    **live, 
                    "Abstand_FV_%": round(diff_to_fv, 1)
                })

    if results:
        df_final = pd.DataFrame(results)
        
        # --- METRIKEN OBEN (Zusammenfassung) ---
        c1, c2, c3 = st.columns(3)
        c1.metric("Aktien in Watchlist", len(df_final))
        # Zähle wie viele im Aufwärtstrend sind
        uptrend_count = df_final[df_final['Trend'].str.contains("Aufwärts")].shape[0]
        c2.metric("Im Aufwärtstrend", f"{uptrend_count}")
        # Günstigste Aktie finden
        top_pick = df_final.loc[df_final['Abstand_FV_%'].idxmin()]
        c3.metric("Top Pick (FV)", top_pick['ticker'], f"{top_pick['Abstand_FV_%']}%")

        # --- TABELLEN-STYLING ---
        st.subheader("Detail-Analyse")
        
        def color_logic(val):
            if isinstance(val, (int, float)):
                if val < 0: return 'color: #00ff00; font-weight: bold' # Unter Fair Value = Grün
                if val > 20: return 'color: #ff4b4b' # Weit über Fair Value = Rot
            return ''

        st.dataframe(
            df_final.style.applymap(color_logic, subset=['Abstand_FV_%'])
            .format({
                "Schulden_Quote": "{:.2f}", 
                "Live_Kurs": "{:.2f} €", 
                "Abstand_FV_%": "{:+.1f}%"
            }),
            use_container_width=True,
            hide_index=True
        )

        # --- MOBILE KARTEN (Extra für das iPhone) ---
        st.write("### 📱 Mobile Check")
        for _, stock in df_final.iterrows():
            with st.container():
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.markdown(f"**{stock['ticker']}** | {stock['sector'] or 'Diverse'}")
                    st.markdown(f"Kurs: {stock['Live_Kurs']} € (Ziel: {stock['fair_value']} €)")
                with col_b:
                    # Kleiner visueller Marker für den Kaufpreis
                    if stock['Abstand_FV_%'] <= 0:
                        st.success("KAUFZONE")
                    else:
                        st.warning(f"+{stock['Abstand_FV_%']}%")
                st.divider()
