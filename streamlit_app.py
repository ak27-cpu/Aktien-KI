import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Terminal 2025", layout="wide")

if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("API Key fehlt!")
    st.stop()

supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

# --- 2. FUNKTIONEN ---

def ask_ki(prompt):
    try:
        return ki_model.generate_content(prompt).text
    except: return "KI Fehler"

@st.cache_data(ttl=3600)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y") # 2 Jahre für sauberes ATH
        if h.empty: return None
        
        info = s.info
        cp = info.get('currentPrice') or h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # RSI
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        d2e = info.get('debtToEquity', 0) or 0
        debt = d2e if d2e > 5 else d2e * 100
        
        return {
            "Preis": round(cp, 2), 
            "ATH": round(ath, 2),
            "RSI": round(rsi, 1), 
            "Schulden": round(debt, 1),
            "Abstand_ATH": round(((cp / ath) - 1) * 100, 1)
        }
    except: return None

# --- 3. UI & SIDEBAR ---
st.title("🏛️ Professional Investment Terminal (ATH-Tranchen)")

with st.sidebar:
    st.header("⚙️ Tranchen-Setup (vom ATH)")
    t1_drop = st.slider("Tranche 1 bei Korrektur (%)", 5, 50, 15)
    t2_drop = st.slider("Tranche 2 bei Korrektur (%)", 10, 70, 30)
    
    st.divider()
    st.header("➕ Neue Aktie")
    t_in = st.text_input("Ticker").upper()
    fv_in = st.number_input("Dein Fair Value (optional)", value=0.0)
    if st.button("Hinzufügen"):
        if t_in:
            supabase.table("watchlist").insert({"ticker": t_in, "fair_value": fv_in}).execute()
            st.rerun()

# --- 4. DASHBOARD ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    rows = []
    for _, r in df_db.iterrows():
        m = get_metrics(r['ticker'])
        if m:
            # Tranchen Berechnung vom ATH
            t1_preis = m['ATH'] * (1 - t1_drop/100)
            t2_preis = m['ATH'] * (1 - t2_drop/100)
            
            # Kaufzone Signal
            status = "🎯 TR1 ERREICHT" if m['Preis'] <= t1_preis else "⏳ Warten"
            if m['Preis'] <= t2_preis: status = "🔥 TR2 ERREICHT"

            rows.append({
                "id": r['id'],
                "Ticker": r['ticker'],
                "Kurs": m['Preis'],
                "ATH": m['ATH'],
                "Korr %": m['Abstand_ATH'],
                "RSI": m['RSI'],
                "Tranche 1": round(t1_preis, 2),
                "Tranche 2": round(t2_preis, 2),
                "Status": status
            })

    df_display = pd.DataFrame(rows)
    st.subheader("📊 Markt-Monitor (ATH-Analyse)")
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # --- 5. ERWEITERTE ANALYSE-PROZESSE ---
    st.divider()
    st.subheader("🤖 Experten-Analyse-Terminal")
    sel_ticker = st.selectbox("Wähle Aktie für Analyse:", df_display['Ticker'])
    
    # Deine erweiterten Analyse-Anweisungen
    analyse_typ = st.selectbox("Analyse-Prozess wählen:", [
        "1. Komplett-Analyse (Equity Report)",
        "2. Bewertungs-Profi (Fair Value Kalkulation)",
        "3. Dividenden-Sicherheits-Check",
        "4. Konkurrenz-Ranking (Market Share)",
        "5. Crash-Resistenz-Test",
        "6. Szenario-Analyse (Best/Worst Case)"
    ])

    if st.button("Analyse-Prozess starten"):
        stock_context = df_display[df_display['Ticker'] == sel_ticker].iloc[0].to_dict()
        
        prompts = {
            "1. Komplett-Analyse (Equity Report)": f"Analysiere {sel_ticker} wie ein Profi-Equity-Analyst: 1. Geschäftsmodell, 2. Fundamentaldaten, 3. Bewertung, 4. Bilanz, 5. Dividende, 6. Chancen/Risiken, 7. Szenarien, 8. Fazit. Daten: {stock_context}",
            "2. Bewertungs-Profi (Fair Value Kalkulation)": f"Berechne für {sel_ticker} einen gemittelten fairen Wert aus DCF, KGV-Historie und Branchen-Multiples. Nenne 3 Tranchen-Einstiegskurse basierend auf Sicherheitsmargen. Daten: {stock_context}",
            "3. Dividenden-Sicherheits-Check": f"Untersuche die Dividende von {sel_ticker}: Payout-Ratio auf FCF-Basis, Historie und Sicherheit in einer Rezession. Urteil: Sicher, Gefährdet oder Riskant?",
            "4. Konkurrenz-Ranking (Market Share)": f"Vergleiche {sel_ticker} mit den 3 stärksten Wettbewerbern. Wer hat den größten Burggraben (Moat) und die besten Margen?",
            "5. Crash-Resistenz-Test": f"Wie hat sich {sel_ticker} historisch in Bärenmärkten verhalten? Analysiere den maximalen Drawdown und die Erholungsgeschwindigkeit.",
            "6. Szenario-Analyse (Best/Worst Case)": f"Erstelle 3 Kurs-Szenarien für {sel_ticker} auf Sicht von 24 Monaten: Bull-Case, Base-Case und Bear-Case mit entsprechenden Kurspfaden."
        }
        
        with st.chat_message("assistant"):
            st.markdown(ask_ki(prompts[analyse_typ]))
