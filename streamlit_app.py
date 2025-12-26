import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import pandas as pd

# --- UI ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide")
st.title("🚀 Meine KI-Aktien-Watchlist")

# --- VERBINDUNG VIA GSPREAD ---
@st.cache_resource
def get_gspread_client():
    # Wir laden die Secrets direkt aus dem [connections.gsheets] Block
    creds_dict = dict(st.secrets["connections"]["gsheets"])
    
    # Key reparieren
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    # Scopes festlegen
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Credentials Objekt erstellen
    # Wir entfernen Felder, die gspread nicht mag, falls sie existieren
    valid_keys = ["type", "project_id", "private_key_id", "private_key", 
                  "client_email", "client_id", "auth_uri", "token_uri", 
                  "auth_provider_x509_cert_url", "client_x509_cert_url"]
    
    clean_creds = {k: v for k, v in creds_dict.items() if k in valid_keys}
    
    creds = Credentials.from_service_account_info(clean_creds, scopes=scopes)
    return gspread.authorize(creds)

# --- ANALYSE-LOGIK ---
@st.cache_data(ttl=3600)
def get_stock_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        if hist.empty: return None

        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        de_raw = info.get('debtToEquity')
        debt_equity = (de_raw / 100) if (de_raw and de_raw > 1) else (de_raw or 0)
        
        ath_52w = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        correction = ((price / ath_52w) - 1) * 100
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        return {
            "Kurs": round(price, 2),
            "KGV": info.get('trailingPE', "N/A"),
            "Schulden_Quote": round(debt_equity, 3),
            "Korrektur_%": round(correction, 2),
            "Trend": "Aufwärts ✅" if price > sma200 else "Abwärts ⚠️"
        }
    except: return None

# --- HAUPTPROGRAMM ---
try:
    client = get_gspread_client()
    # URL aus den Secrets holen
    sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
    
    # Sheet öffnen
    sh = client.open_by_url(sheet_url)
    worksheet = sh.get_worksheet(0) # Nimmt das erste Tabellenblatt
    
    # Daten laden
    data = worksheet.get_all_records()
    df_watchlist = pd.DataFrame(data)

    if not df_watchlist.empty:
        # Spalte "Ticker" suchen
        ticker_col = next((c for c in df_watchlist.columns if c.lower() == 'ticker'), None)

        if ticker_col:
            results = []
            ticker_liste = df_watchlist[ticker_col].dropna().unique().tolist()
            
            for symbol in ticker_liste:
                if not symbol: continue
                with st.spinner(f"Analysiere {symbol}..."):
                    m = get_stock_metrics(str(symbol))
                    if m:
                        row_data = df_watchlist[df_watchlist[ticker_col] == symbol].iloc[0].to_dict()
                        results.append({**row_data, **m})
            
            if results:
                df_final = pd.DataFrame(results)
                
                def highlight_debt(row):
                    val = row.get('Schulden_Quote', 1.0)
                    color = 'background-color: rgba(144, 238, 144, 0.3)' if isinstance(val, (int, float)) and val < 0.6 else ''
                    return [color] * len(row)

                st.subheader("Deine Analyse")
                st.dataframe(df_final.style.apply(highlight_debt, axis=1), use_container_width=True)
            else:
                st.warning("Keine Live-Daten gefunden.")
        else:
            st.error("Bitte nenne die erste Spalte in deinem Sheet 'Ticker'.")
    else:
        st.info("Das Sheet ist noch leer.")

except Exception as e:
    st.error(f"Fehler: {e}")
