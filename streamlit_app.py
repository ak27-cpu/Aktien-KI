import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd

# --- SEITEN-KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide")
st.title("🚀 Meine KI-Aktien-Watchlist")

# --- MANUELLE VERBINDUNG ---
def get_connection():
    # Wir ziehen alle Daten aus den Secrets
    s_creds = dict(st.secrets["connections"]["gsheets"])
    
    # 1. Die Spreadsheet-URL separat speichern
    spreadsheet_url = s_creds.pop("spreadsheet", None)
    
    # 2. Den Private Key reparieren
    if "private_key" in s_creds:
        s_creds["private_key"] = s_creds["private_key"].replace("\\n", "\n")
    
    # 3. WICHTIG: Alles außer 'type' in ein Unter-Dictionary 'service_account' packen
    # Das ist das Format, das die Bibliothek st-gsheets-connection intern erwartet
    conn = st.connection("gsheets", type=GSheetsConnection, service_account=s_creds)
    
    return conn, spreadsheet_url

# --- ANALYSE-LOGIK ---
@st.cache_data(ttl=3600)
def get_stock_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        if hist.empty: return None

        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        
        # Schulden-Logik
        de_raw = info.get('debtToEquity')
        debt_equity = (de_raw / 100) if (de_raw and de_raw > 2) else (de_raw or 0)
        
        # Korrektur & Trend
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
    conn, sheet_url = get_connection()
    
    if sheet_url:
        # Hier wird die URL beim Lesen verwendet
        df_watchlist = conn.read(spreadsheet=sheet_url)
        
        if df_watchlist is not None and not df_watchlist.empty:
            df_watchlist.columns = [c.strip() for c in df_watchlist.columns]
            ticker_col = next((c for c in df_watchlist.columns if c.lower() == 'ticker'), None)

            if ticker_col:
                results = []
                # Bereinige Ticker (entferne NaN und leere Felder)
                ticker_liste = df_watchlist[ticker_col].dropna().unique().tolist()
                
                for symbol in ticker_liste:
                    with st.spinner(f"Analysiere {symbol}..."):
                        m = get_stock_metrics(str(symbol))
                        if m:
                            # Suche ursprüngliche Zeile im Sheet
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
                    st.warning("Keine Daten gefunden. Prüfe die Ticker-Symbole (z.B. 'AAPL', 'MSFT').")
            else:
                st.error("Keine Spalte 'Ticker' gefunden!")
        else:
            st.info("Das Google Sheet ist leer oder hat keine Überschriften.")
    else:
        st.error("Spreadsheet URL fehlt in den Secrets!")

except Exception as e:
    st.error(f"Kritischer Fehler: {e}")
