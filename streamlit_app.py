import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="KI Aktien-Terminal Pro", layout="wide", initial_sidebar_state="collapsed")

# KI Setup mit dem neuen Modellpfad
if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    # Dein verifizierter Modellpfad aus dem Test
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("Gemini API Key fehlt in den Secrets!")
    st.stop()

# Supabase Verbindung
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

supabase = get_supabase()

# --- 2. HILFSFUNKTIONEN ---

def ask_ki(prompt):
    try:
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"KI-Fehler: {e}"

@st.cache_data(ttl=3600)
def get_pro_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        if hist.empty: return None
        
        info = stock.info
        curr = info.get('currentPrice') or hist['Close'].iloc[-1]
        
        # Korrekturanalyse
        high_52w = hist['High'].tail(252).max()
        aktuelle_korr = ((curr / high_52w) - 1) * 100
        
        # Historische Korrektur (Durchschnittlicher Drawdown)
        roll_max = hist['Close'].cummax()
        drawdowns = (hist['Close'] / roll_max - 1) * 100
        avg_drawdown = drawdowns.mean()
        
        # RSI (14 Tage)
        delta = hist['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        # Schulden (Normalisierung auf Prozent)
        d2e = info.get('debtToEquity')
        debt_val = 0
        if d2e:
            debt_val = d2e if d2e > 5 else d2e * 100

        return {
            "Preis": round(curr, 2),
            "Korr_%": round(aktuelle_korr, 1),
            "Hist_Korr_%": round(avg_drawdown, 1),
            "Schulden_%": round(debt_val, 1),
            "RSI": round(rsi, 1),
            "Trend": "Aufwärts ✅" if curr > hist['Close'].rolling(200).mean().iloc[-1] else "Abwärts ⚠️"
        }
    except: return None

# --- 3. DATEN LADEN & VERARBEITEN ---

res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

st.title("🚀 KI Aktien-Terminal Pro")

if not df_db.empty:
    all_data = []
    with st.spinner("Analysiere Marktdaten & Technik..."):
        for _, row in df_db.iterrows():
            m = get_pro_metrics(row['ticker'])
            if m:
                # Schnell-Check Logik
                abstand_fv = ((m['Preis'] / row['fair_value']) - 1) * 100 if row['fair_value'] > 0 else 0
                
                # KI-Kurzurteil für die Tabelle
                kurz_prompt = f"Aktie {row['ticker']}: Kurs {m['Preis']}, RSI {m['RSI']}, Schulden {m['Schulden_%']}%. Urteil (2 Wörter)."
                ki_status = ask_ki(kurz_prompt)
                
                all_data.append({
                    "Ticker": row['ticker'],
                    "Kurs": m['Preis'],
                    "FairV": row['fair_value'],
                    "Diff_%": round(abstand_fv, 1),
                    "Korr_%": m['Korr_%'],
                    "Ø_Korr": m['Hist_Korr_%'],
                    "Schulden_%": m['Schulden_%'],
                    "RSI": m['RSI'],
                    "KI_Check": ki_status
                })

    df_final = pd.DataFrame(all_data)

    # --- TABELLEN ANZEIGE ---
    st.subheader("📊 Deine Power-Watchlist")
    
    def color_values(val):
        if isinstance(val, (int, float)):
            if val < 35: return 'color: #00ff00; font-weight: bold' # RSI Kaufsignal
            if val > 65: return 'color: #ff4b4b' # RSI Warnung
        return ''

    st.dataframe(
        df_final.style.map(color_values, subset=['RSI']),
        use_container_width=True, hide_index=True
    )

    st.divider()

    # --- 4. EXPERTEN KI-TERMINAL ---
    st.subheader("🤖 Deep-Dive KI Analyse")
    
    col1, col2 = st.columns(2)
    with col1:
        sel_ticker = st.selectbox("Aktie wählen", df_final['Ticker'])
    with col2:
        modus = st.selectbox("Analyse-Modus", [
            "Komplett-Analyse (Equity Report)",
            "Bewertungs-Profi (DCF + Multiples)",
            "Dividenden-Sicherheitscheck",
            "Konkurrenz- & Marktvergleich",
            "Crash- & Rezessionsanalyse",
            "Portfolio-Optimierungs-Check"
        ])

    if st.button(f"Starte {modus}"):
        stock_info = df_final[df_final['Ticker'] == sel_ticker].iloc[0].to_dict()
        
        # Deine spezifischen Anweisungen
        prompts = {
            "Komplett-Analyse (Equity Report)": f"Erstelle eine vollständige Analyse für {sel_ticker}. Struktur: 1. Geschäftsmodell, 2. Fundamentaldaten, 3. Bewertung, 4. Bilanzqualität, 5. Dividenden, 6. Chancen/Risiken, 7. Szenarien, 8. Fazit. Daten: {stock_info}",
            "Bewertungs-Profi (DCF + Multiples)": f"Berechne fairen Wert für {sel_ticker} (DCF + Multiples). Price Range und Annahmen angeben. Daten: {stock_info}",
            "Dividenden-Sicherheitscheck": f"Prüfe Dividendenqualität von {sel_ticker}: Ausschüttung (EPS/FCF), Historie, Sicherheit. Urteil: sicher/fraglich/riskant.",
            "Konkurrenz- & Marktvergleich": f"Vergleiche {sel_ticker} mit 3 Top-Konkurrenten (Margen, Wachstum, Burggraben). Erstelle Ranking.",
            "Crash- & Rezessionsanalyse": f"Wie reagiert {sel_ticker} auf Krisen? Stabilität (1-10), Cashflow-Resistenz.",
            "Portfolio-Optimierungs-Check": f"Bewerte mein Portfolio: {df_final['Ticker'].tolist()}. Diversifikation und Klumpenrisiken prüfen."
        }

        with st.chat_message("assistant"):
            st.markdown(ask_ki(prompts[modus]))

else:
    st.info("Füge Ticker in deine Supabase-Datenbank ein.")

# --- SIDEBAR: VERWALTUNG ---
with st.sidebar:
    st.header("⚙️ Verwaltung")
    new_ticker = st.text_input("Neuer Ticker (z.B. AAPL)").upper()
    new_fv = st.number_input("Fairer Wert (€)", value=100.0)
    if st.button("Hinzufügen"):
        supabase.table("watchlist").insert({"ticker": new_ticker, "fair_value": new_fv}).execute()
        st.rerun()
