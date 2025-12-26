import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd

# --- SEITEN-KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide")

st.title("🚀 Meine KI-Aktien-Watchlist")

# --- MANUELLE VERBINDUNG (FIX FÜR DNS & KEY) ---
def get_connection():
    # Wir ziehen die Daten einzeln und reparieren den Key lokal im Speicher
    creds = dict(st.secrets["connections"]["gsheets"])
    if "private_key" in creds:
        creds["private_key"] = creds["private_key"].replace("\\n", "\n")
    
    # Verbindung mit den reparierten Credentials aufbauen
    return st.connection("gsheets", type=GSheetsConnection, **creds)

try:
    conn = get_connection()
    # Versuche das Blatt zu lesen (Wir nehmen das erste Blatt, falls "Watchlist" fehlt)
    df_watchlist = conn.read()
    
    if df_watchlist is not None and not df_watchlist.empty:
        st.success("Verbindung zum Google Sheet hergestellt!")
        
        # Spaltennamen säubern
        df_watchlist.columns = [c.strip() for c in df_watchlist.columns]
        ticker_col = next((c for c in df_watchlist.columns if c.lower() == 'ticker'), None)

        if ticker_col:
            # Hier folgt deine Logik für yfinance (wie im vorherigen Skript)
            ticker_liste = df_watchlist[ticker_col].dropna().tolist()
            st.write(f"Analysiere folgende Ticker: {', '.join(ticker_liste)}")
            
            # (Analyse-Logik hier einfügen...)
        else:
            st.error("Bitte erstelle eine Spalte namens 'Ticker' in deinem Google Sheet.")
    else:
        st.info("Das Google Sheet scheint leer zu sein.")

except Exception as e:
    st.error(f"Verbindungsfehler: {e}")
    st.info("Hinweis: Prüfe in den Secrets, ob 'spreadsheet' die komplette URL ist.")
