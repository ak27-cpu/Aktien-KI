import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta
import time

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v24", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. KI FUNKTION MIT RATE-LIMIT SCHUTZ ---
def safe_ai_call(prompt):
    """Führt KI-Calls aus und fängt Quota-Fehler ab."""
    try:
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e:
        if "429" in str(e) or "ResourceExhausted" in str(e):
            return "QUOTA_LIMIT"
        return f"Fehler: {str(e)}"

def get_ai_fair_value(ticker, info, cp):
    prompt = f"Gib NUR den fairen Wert für {ticker} als Zahl zurück. Aktueller Preis: {cp}."
    res = safe_ai_call(prompt)
    if res == "QUOTA_LIMIT":
        return cp * 0.95 # Fallback wenn API voll
    try:
        val = "".join(c for c in res if c.isdigit() or c == '.')
        return float(val)
    except:
        return cp * 0.95

# --- 3. DATEN-ENGINE ---
@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        roll_max = h['High'].cummax()
        avg_dd = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)

        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        avg_vol = h['Volume'].tail(20).mean()
        curr_vol = h['Volume'].iloc[-1]
        vol_info = "Normal"
        if curr_vol > avg_vol * 1.5:
            vol_info = "⚠️ LONG-Druck" if (cp - h['Close'].iloc[-2]) > 0 else "⚠️ SHORT-Druck"

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "Korr_Akt": round(((cp / ath) - 1) * 100, 1),
            "Korr_Avg": avg_dd,
            "RSI": round(rsi, 1),
            "Trend": "Aufwärts 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Abwärts 📉",
            "Vol_Info": vol_info,
            "raw_info": info
        }
    except: return None

# --- 4. MARKT-HEADER ---
try:
    vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
    spy = yf.Ticker("^GSPC").history(period="300d")
    sma125 = spy['Close'].rolling(125).mean().iloc[-1]
    fg = min(100, int((spy['Close'].iloc[-1] / sma125) * 50))
except:
    vix, fg = 20.0, 50

st.title("🏛️ Professional Investment Cockpit")
c1, c2 = st.columns(2)
c1.metric("VIX (Angst)", round(vix, 2))
c2.metric("Fear & Greed Index", f"{fg}/100")
st.divider()

# --- 5. DATEN LADEN & TABS ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    m_data = []
    with st.spinner("Analysiere Daten (API-schonend)..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                db_fv = r.get('fair_value')
                # Nur KI rufen, wenn FV in DB 0 oder None ist
                if db_fv and db_fv > 0:
                    fv = float(db_fv)
                else:
                    fv = get_ai_fair_value(r['ticker'], m['raw_info'], m['Preis'])
                
                t1, t2 = m['ATH'] * 0.90, m['ATH'] * 0.80
                score = (1 if m['RSI'] < 35 else 0) + (1 if m['Korr_Akt'] < m['Korr_Avg'] else 0) + (1 if m['Preis'] <= fv else 0)
                rating = "KAUFEN 🟢" if score >= 2 else "BEOBACHTEN 🟡" if score == 1 else "WARTEN ⚪"

                m_data.append({**m, "Ticker": r['ticker'], "FV": fv, "T1": round(t1, 2), "T2": round(t2, 2), "Empfehlung": rating})

    if m_data:
        df = pd.DataFrame(m_data)
        t1, t2, t3 = st.tabs(["📊 Markt", "🎯 Technik", "🚀 Strategie"])
        with t1: st.dataframe(df[["Ticker", "Name", "Sektor", "Preis", "FV"]], use_container_width=True, hide_index=True)
        with t2: st.dataframe(df[["Ticker", "Korr_Akt", "Korr_Avg", "RSI", "Trend", "Vol_Info"]], use_container_width=True, hide_index=True)
        with t3: st.dataframe(df[["Ticker", "Preis", "FV", "T1", "T2", "Empfehlung"]].style.apply(lambda x: ['background-color: #004d00' if "🟢" in str(x.Empfehlung) else '' for i in x], axis=1), use_container_width=True, hide_index=True)

        # DEEP DIVE BUTTON
        st.divider()
        sel = st.selectbox("Aktie für KI-Deep-Dive:", df['Ticker'].tolist())
        if st.button("Deep-Dive Analyse starten"):
            d = next(item for item in m_data if item["Ticker"] == sel)
            prompt = f"Bewerte {sel}. News 10 Tage, Markt, RSI {d['RSI']}, Prognose, Einstieg? Kurs {d['Preis']}, FV {d['FV']}."
            result = safe_ai_call(prompt)
            if result == "QUOTA_LIMIT":
                st.warning("⚠️ KI-Limit erreicht. Bitte in 1 Minute erneut versuchen (Free Tier Limit).")
            else:
                st.markdown(result)
