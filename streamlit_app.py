import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import pandas as pd

# --- SEITEN-KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide")

st.title("🚀 Meine KI-Aktien-Watchlist")
st.markdown("Analysiert Verschuldung, Trends und Korrektur-Größen live.")

# --- GOOGLE SHEETS VERBINDUNG ---
@st.cache_resource
def get_gspread_client():
    try:
        # Credentials aus den Secrets laden
        creds_dict = dict(st.secrets["connections"]["gsheets"])
        
        # DNS & URL Fix: Wir erzwingen die stabilere API-Adresse
        creds_dict["token_uri"] = "https://oauth2.googleapis.com/token"
        
        # Key-Reparatur für Zeilenumbrüche
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        # Scopes für Google Sheets & Drive
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Fehler bei der Credential-Prüfung: {e}")
        return None

# --- AKTIEN-ANALYSE LOGIK ---
@st.cache_data(ttl=3600)
def get_stock_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        
        if hist.empty:
            return None

        # Kennzahlen abrufen
        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        
        # Schulden-Quote (Debt to Equity)
        de_raw = info.get('debtToEquity')
        # Korrektur für Prozentwerte (manche Ticker geben 40.5 statt 0.405 aus)
        debt_equity = (de_raw / 100) if (de_raw and de_raw > 2) else (de_raw or 0)
        
        # 52-Wochen-Hoch & Korrektur
        ath_52w = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        correction = ((price / ath_52w) - 1) * 100
        
        # Trend (SMA 200)
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        trend = "Aufwärts ✅" if price > sma200 else "Abwärts ⚠️"
        
        return {
            "Kurs": round(price, 2),
            "KGV": info.get('trailingPE', "N/A"),
            "Schulden_Quote": round(debt_equity, 3),
            "Korrektur_%": round(correction, 2),
            "Trend": trend
        }
    except Exception:
        return None

# --- HAUPTPROGRAMM ---
client = get_gspread_client()

if client:
    try:
        # Datei über den Namen öffnen
        sh = client.open("Aktien-KI")
        worksheet = sh.get_worksheet(0)
        
        # Daten in DataFrame laden
        data = worksheet.get_all_records()
        
        if not data:
            st.info("Das Google Sheet ist leer. Bitte trage Ticker in die erste Spalte ein.")
        else:
            df_watchlist = pd.DataFrame(data)
            
            # Suche die Ticker-Spalte
            ticker_col = next((c for c in df_watchlist.columns if c.lower() == 'ticker'), None)

            if ticker_col:
                results = []
                # Bereinige Ticker-Liste
                ticker_liste = df_watchlist[ticker_col].dropna().unique().tolist()
                
                # Fortschrittsanzeige
                progress_bar = st.progress(0)
                for i, symbol in enumerate(ticker_liste):
                    if not symbol: continue
                    metrics = get_stock_metrics(str(symbol))
                    if metrics:
                        # Daten aus Sheet mit Live-Daten mischen
                        original_row = df_watchlist[df_watchlist[ticker_col] == symbol].iloc[0].to_dict()
                        results.append({**original_row, **metrics})
                    progress_bar.progress((i + 1) / len(ticker_liste))
                
                if results:
                    df_final = pd.DataFrame(results)
                    
                    # Styling: Grün markieren wenn Schulden < 60% (0.6)
                    def highlight_debt(row):
                        val = row.get('Schulden_Quote', 1.0)
                        color = 'background-color: rgba(0, 255, 0, 0.15)' if isinstance(val, (int, float)) and val < 0.6 else ''
                        return [color] * len(row)

                    st.subheader("Aktuelle Analyse")
                    st.dataframe(
                        df_final.style.apply(highlight_debt, axis=1),
                        use_container_width=True
                    )
                    
                    st.caption("🟢 Markierung: Verschuldung unter 60% (Debt/Equity < 0.6)")
                else:
                    st.warning("Keine Live-Daten von Yahoo Finance empfangen.")
            else:
                st.error("Konnte keine Spalte mit dem Namen 'Ticker' finden.")

    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Die Datei 'Aktien-KI' wurde nicht gefunden. Bitte prüfe den Namen in Google Sheets.")
    except Exception as e:
        st.error(f"Verbindungsfehler: {e}")
else:
    st.error("Konnte keine Verbindung zu Google herstellen.")
