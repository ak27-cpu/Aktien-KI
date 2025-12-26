import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd

# --- SEITEN-KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide")

st.title("🚀 Meine KI-Aktien-Watchlist")

# --- MANUELLE VERBINDUNG ---
def get_connection():
    # Wir laden nur die Zugangsdaten (Credentials)
    creds = dict(st.secrets["connections"]["gsheets"])
    
    # Wir entfernen alles, was nicht direkt mit dem Login zu tun hat
    # spreadsheet und type dürfen NICHT in die connection-Funktion als kwargs
    spreadsheet_url = creds.pop("spreadsheet", None)
    creds.pop("type", None)
    
    # Key-Fix für Zeilenumbrüche
    if "private_key" in creds:
        creds["private_key"] = creds["private_key"].replace("\\n", "\n")
    
    # Verbindung pur aufbauen
    conn = st.connection("gsheets", type=GSheetsConnection, **creds)
    return conn, spreadsheet_url

@st.cache_data(ttl=3600)
def get_stock_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        
        if hist.empty: return None

        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        
        # Schulden-Logik (Sicherheitshaltber Check auf N/A)
        de_raw = info.get('debtToEquity')
        if de_raw is None:
            debt_equity = 0
        else:
            debt_equity = de_raw / 100 if de_raw > 2 else de_raw
        
        # Korrektur-Logik
        ath_52w = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        correction = ((price / ath_52w) - 1) * 100
        
        # Trend (SMA 200)
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        return {
            "Kurs": round(price, 2),
            "KGV": info.get('trailingPE', "N/A"),
            "Schulden_Quote": round(debt_equity, 3),
            "Korrektur_%": round(correction, 2),
            "Trend": "Aufwärts ✅" if price > sma200 else "Abwärts ⚠️"
        }
    except:
        return None

# --- HAUPTPROGRAMM ---
try:
    conn, sheet_url = get_connection()
    
    # Jetzt übergeben wir die URL erst HIER beim Lesen
    if sheet_url:
        df_watchlist = conn.read(spreadsheet=sheet_url)
    else:
        # Falls URL nicht in GSheets-Sektion, versuche Standard-Suche
        df_watchlist = conn.read()
    
    if df_watchlist is not None and not df_watchlist.empty:
        df_watchlist.columns = [c.strip() for c in df_watchlist.columns]
        ticker_col = next((c for c in df_watchlist.columns if c.lower() == 'ticker'), None)

        if ticker_col:
            results = []
            ticker_liste = df_watchlist[ticker_col].dropna().unique().tolist()
            
            for symbol in ticker_liste:
                with st.spinner(f"Analysiere {symbol}..."):
                    m = get_stock_metrics(str(symbol))
                    if m:
                        # Daten zusammenführen
                        row_data = df_watchlist[df_watchlist[ticker_col] == symbol].iloc[0].to_dict()
                        results.append({**row_data, **m})
            
            if results:
                df_final = pd.DataFrame(results)
                
                # Styling: Zeile grün markieren wenn Schulden < 0.6
                def highlight_debt(row):
                    # Wir prüfen ob der Wert numerisch ist
                    val = row.get('Schulden_Quote', 1.0)
                    color = 'background-color: rgba(144, 238, 144, 0.3)' if isinstance(val, (int, float)) and val < 0.6 else ''
                    return [color] * len(row)

                st.subheader("Deine Analyse")
                st.dataframe(df_final.style.apply(highlight_debt, axis=1), use_container_width=True)
            else:
                st.warning("Keine Daten von Yahoo Finance empfangen.")
        else:
            st.error("Spalte 'Ticker' fehlt im Google Sheet.")
    else:
        st.info("Das Google Sheet ist leer.")

except Exception as e:
    st.error(f"Fehler: {e}")
