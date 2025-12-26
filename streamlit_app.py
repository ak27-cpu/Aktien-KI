import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd

# --- SEITEN-KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Watchlist", layout="wide", initial_sidebar_state="collapsed")

st.title("🚀 Meine KI-Aktien-Watchlist")
st.markdown("Analysiere Verschuldung (< 60%), Trends und Korrektur-Größen live.")

# --- DATENBANK-VERBINDUNG ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Verbindungsfehler zur GSheets-Schnittstelle: {e}")

@st.cache_data(ttl=3600)  # Daten für 1 Stunde cachen
def get_stock_data(ticker):
    """Holt alle relevanten Kennzahlen von yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        
        if hist.empty:
            return None

        # Aktueller Kurs und 52-Wochen-Hoch
        current_price = info.get('currentPrice') or hist['Close'].iloc[-1]
        ath_52w = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        
        # Fundamentaldaten
        # yfinance gibt debtToEquity oft als Prozent (z.B. 40.5) oder Faktor (0.405) aus
        de_raw = info.get('debtToEquity', 0)
        debt_equity = de_raw / 100 if de_raw > 2 else de_raw
        
        pe_ratio = info.get('trailingPE')
        
        # Berechnungen
        correction = ((current_price / ath_52w) - 1) * 100
        
        # Trend-Check (SMA 200)
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        trend = "Aufwärts ✅" if current_price > sma200 else "Abwärts ⚠️"
        
        # Historische Dips (vereinfacht: Max Drawdown der letzten 2 Jahre)
        roll_max = hist['Close'].cummax()
        daily_drawdown = hist['Close'] / roll_max - 1.0
        avg_drawdown = daily_drawdown.min() * 100 # Tiefster Punkt als Referenz

        return {
            "Kurs": round(current_price, 2),
            "KGV": round(pe_ratio, 2) if pe_ratio else "N/A",
            "Schulden_Quote": round(debt_equity, 3),
            "Korrektur_%": round(correction, 2),
            "Max_Dip_2J_%": round(avg_drawdown, 2),
            "Trend": trend
        }
    except Exception as e:
        return None

# --- HAUPTTEIL ---
try:
    # Wir lesen das erste verfügbare Blatt, falls "Watchlist" nicht gefunden wird
    df_watchlist = conn.read()
    
    if df_watchlist is not None and not df_watchlist.empty:
        # Ticker-Spalte finden (ignoriert Groß/Kleinschreibung)
        df_watchlist.columns = [c.strip() for c in df_watchlist.columns]
        ticker_col = next((c for c in df_watchlist.columns if c.lower() == 'ticker'), None)

        if ticker_col:
            all_results = []
            
            for index, row in df_watchlist.iterrows():
                symbol = str(row[ticker_col]).strip()
                if symbol and symbol != "nan":
                    with st.status(f"Analysiere {symbol}...", expanded=False):
                        metrics = get_stock_data(symbol)
                        if metrics:
                            # Kombiniere Daten aus Google Sheet mit Live-Daten
                            combined = {**row.to_dict(), **metrics}
                            all_results.append(combined)
            
            if all_results:
                df_final = pd.DataFrame(all_results)
                
                # --- STYLING ---
                def style_rows(row):
                    # Kriterium: Verschuldung unter 60% (0.6)
                    color = 'background-color: rgba(0, 255, 0, 0.1)' if row['Schulden_Quote'] < 0.6 else ''
                    return [color] * len(row)

                st.subheader("Analyse-Ergebnisse")
                st.dataframe(
                    df_final.style.apply(style_rows, axis=1),
                    use_container_width=True
                )
                
                # --- INFO BOXEN ---
                st.sidebar.header("Kriterien-Check")
                st.sidebar.info("🟢 Grün: Verschuldung < 60%\n\n✅ Trend: Kurs > SMA200")
                
            else:
                st.warning("Keine gültigen Daten für die Ticker gefunden.")
        else:
            st.error("Spalte 'Ticker' nicht im Google Sheet gefunden!")
    else:
        st.info("Das Google Sheet ist leer oder konnte nicht geladen werden.")

except Exception as e:
    st.error(f"Kritischer Fehler beim Laden der App: {e}")
    st.info("Tipp: Überprüfe, ob deine GSheet-URL in den Secrets korrekt ist.")

