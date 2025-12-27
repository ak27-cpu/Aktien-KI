import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Terminal 2025", layout="wide")

# API Keys aus st.secrets laden
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash') # Aktuelles Gemini Modell
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN FUNKTION ---
def get_market_indicators():
    try:
        # VIX Index
        vix = yf.Ticker("^VIX")
        vix_val = vix.history(period="1d")['Close'].iloc[-1]
        
        # S&P 500 für Fear & Greed Proxy (Abstand zur 125-Tage-Linie)
        spy = yf.Ticker("^GSPC")
        spy_hist = spy.history(period="150d")
        cp = spy_hist['Close'].iloc[-1]
        sma125 = spy_hist['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        if fg_score > 100: fg_score = 100
        
        return round(vix_val, 2), fg_score
    except:
        return 20.0, 50

@st.cache_data(ttl=1800)
def get_stock_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y")
        if h.empty: return None
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # RSI 14 Tage
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(window=14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        return {"Preis": round(cp, 2), "ATH": round(ath, 2), "RSI": round(rsi, 1)}
    except:
        return None

# --- 3. HEADER: DYNAMISCHE BANNER ---
vix, fg = get_market_indicators()

st.title("🏛️ Professional Investment Cockpit")
col_vix, col_fg = st.columns(2)

with col_vix:
    if vix < 20:
        st.success(f"📉 VIX: {vix} (Niedrige Volatilität / Ruhe)")
    elif 20 <= vix < 30:
        st.warning(f"⚠️ VIX: {vix} (Erhöhte Nervosität)")
    else:
        st.error(f"🚨 VIX: {vix} (PANIK-MODUS)")

with col_fg:
    if fg < 35:
        st.success(f"😱 Fear & Greed: {fg}/100 (Angst = KAUFCHANCE)")
    elif 35 <= fg < 70:
        st.info(f"⚖️ Fear & Greed: {fg}/100 (Neutral)")
    else:
        st.error(f"🔥 Fear & Greed: {fg}/100 (Gier = VORSICHT)")

st.divider()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Strategie-Parameter")
    t1_drop = st.slider("Tranche 1 bei ATH-Korrektur %", 5, 50, 15)
    t2_drop = st.slider("Tranche 2 bei ATH-Korrektur %", 10, 70, 30)
    rsi_limit = st.slider("Max. RSI für Kauffreigabe", 20, 70, 45)
    
    st.divider()
    if st.button("🔄 Marktdaten aktualisieren"):
        st.cache_data.clear()
        st.rerun()

# --- 5. HAUPT-LOGIK (WATCHLIST) ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    rows = []
    with st.spinner("Lade Live-Daten..."):
        for _, r in df_db.iterrows():
            m = get_stock_metrics(r['ticker'])
            if m:
                fv = r.get('fair_value', 0) or 0
                t1_p = m['ATH'] * (1 - t1_drop/100)
                t2_p = m['ATH'] * (1 - t2_drop/100)
                
                # Signal Logik
                status = "⏳ Warten"
                if m['Preis'] <= t1_p:
                    status = "🎯 TR1 BEREIT" if m['RSI'] <= rsi_limit else "⚠️ RSI HOCH"
                if m['Preis'] <= t2_p:
                    status = "🔥 TR2 LIMIT" if m['RSI'] <= rsi_limit else "⚠️ RSI HOCH"

                rows.append({
                    "Ticker": r['ticker'],
                    "Kurs": m['Preis'],
                    "Fair Value": fv,
                    "RSI": m['RSI'],
                    "ATH": m['ATH'],
                    "Korr/ATH %": round(((m['Preis']/m['ATH'])-1)*100, 1),
                    "Status": status,
                    "Notiz": r.get('notiz', "")
                })

    df_final = pd.DataFrame(rows)

    # Tabelle Styling
    def style_status(val):
        if "🎯" in val: return 'background-color: #004d00; color: white'
        if "🔥" in val: return 'background-color: #800000; color: white'
        if "⚠️" in val: return 'background-color: #4d4d00; color: white'
        return ''

    st.subheader("📊 Deine Watchlist (Live)")
    st.dataframe(df_final.style.applymap(style_status, subset=['Status']), use_container_width=True, hide_index=True)

    # --- 6. ERWEITERTE KI ANALYSE ---
    st.divider()
    st.subheader("🤖 Experten-Analyse-Terminal")
    
    sel_ticker = st.selectbox("Aktie für Tiefenprüfung wählen:", df_final['Ticker'])
    analyse_typ = st.selectbox("Analyse-Prozess starten:", [
        "1. Komplett-Analyse (Equity Report)",
        "2. Bewertungs-Profi (Fair Value Kalkulation)",
        "3. Dividenden-Sicherheits-Check",
        "4. Konkurrenz-Ranking (Market Share)",
        "5. Crash-Resistenz-Test",
        "6. Szenario-Analyse (Best/Worst Case)"
    ])

    if st.button("Prozess ausführen"):
        ctx = df_final[df_final['Ticker'] == sel_ticker].iloc[0].to_dict()
        
        prompts = {
            "1. Komplett-Analyse (Equity Report)": f"Analysiere {sel_ticker} wie ein Profi: Geschäftsmodell, Fundamentaldaten, Moat, Risiko. Marktstimmung: VIX {vix}, F&G {fg}. Kontext: {ctx}",
            "2. Bewertungs-Profi (Fair Value Kalkulation)": f"Berechne für {sel_ticker} einen fairen Wert aus DCF & KGV. Nutze RSI {ctx['RSI']} für Timing-Einschätzung. Kontext: {ctx}",
            "3. Dividenden-Sicherheits-Check": f"Untersuche Dividende von {sel_ticker}: Payout, Historie & Sicherheit. Kontext: {ctx}",
            "4. Konkurrenz-Ranking (Market Share)": f"Vergleiche {sel_ticker} mit Top-Wettbewerbern. Wer hat die besten Margen?",
            "5. Crash-Resistenz-Test": f"Wie hat sich {sel_ticker} historisch in Bärenmärkten verhalten? Daten: {ctx}",
            "6. Szenario-Analyse (Best/Worst Case)": f"Erstelle 3 Kurs-Szenarien für {sel_ticker} auf Sicht von 24 Monaten."
        }
        
        with st.chat_message("assistant"):
            st.markdown(ki_model.generate_content(prompts[analyse_typ]).text)

else:
    st.info("Watchlist leer. Nutze den Supabase Table Editor zum Hinzufügen von Tickersymbolen.")
