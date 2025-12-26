import streamlit as st
import gspread
import json
from google.oauth2.service_account import Credentials
import yfinance as yf
import pandas as pd

# --- VERBINDUNG VIA JSON-BLOCK ---
@st.cache_resource
def get_gspread_client():
    try:
        # 1. Den JSON-Text aus den Secrets laden
        json_info = json.loads(st.secrets["gsheets"]["json_data"])
        
        # 2. Scopes definieren
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 3. Credentials direkt aus dem JSON-Objekt erstellen
        creds = Credentials.from_service_account_info(json_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Verbindungsfehler: {e}")
        return None

# --- HAUPTPROGRAMM ---
st.title("🚀 Meine KI-Aktien-Watchlist")

client = get_gspread_client()

if client:
    try:
        # Name aus Secrets holen
        sheet_name = st.secrets["gsheets"]["spreadsheet_name"]
        sh = client.open(sheet_name)
        worksheet = sh.get_worksheet(0)
        
        # Daten laden
        data = worksheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            st.write("Daten erfolgreich geladen!", df.head())
            # Hier kannst du nun deine yfinance-Logik dranhängen...
        else:
            st.warning("Das Sheet ist leer.")
            
    except Exception as e:
        st.error(f"Konnte das Sheet nicht öffnen: {e}")
