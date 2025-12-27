import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import pandas as pd

# --- VERBINDUNG ZU SUPABASE ---
@st.cache_resource
def get_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

# --- DATEN LADEN ---
def load_data():
    # Holt alle Ticker aus der Supabase-Tabelle 'watchlist'
    response = supabase.table("watchlist").select("*").execute()
    return pd.DataFrame(response.data)

# --- ANALYSE LOGIK ---
@st.cache_data(ttl=3600)
def get_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get('currentPrice')
        de = info.get('debtToEquity', 0)
        debt_ratio = de / 100 if de > 2 else de
        
        return {
            "Kurs": round(price, 2),
            "KGV": info.get('trailingPE', "N/A"),
            "Schulden_Quote": round(debt_ratio, 3),
            "Trend": "Aufwärts ✅" if price > (stock.history(period="200d")['Close'].mean()) else "Abwärts ⚠️"
        }
    except:
        return None

# --- UI ---
st.title("🚀 Watchlist via Supabase")

data = load_data()

if not data.empty:
    all_results = []
    for _, row in data.iterrows():
        ticker = row['ticker']
        with st.spinner(f"Lade {ticker}..."):
            metrics = get_metrics(ticker)
            if metrics:
                all_results.append({**row, **metrics})
    
    df_final = pd.DataFrame(all_results)
    
    # Styling
    st.dataframe(df_final.style.format(subset=["Schulden_Quote"], formatter="{:.2f}"), use_container_width=True)

# --- NEUEN TICKER HINZUFÜGEN ---
with st.sidebar:
    st.header("Verwaltung")
    new_t = st.text_input("Neuer Ticker").upper()
    if st.button("Speichern"):
        supabase.table("watchlist").insert({"ticker": new_t}).execute()
        st.success(f"{new_t} gespeichert!")
        st.rerun()
