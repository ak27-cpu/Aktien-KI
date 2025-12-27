import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Terminal 2025", layout="wide")

if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("API Key fehlt!")
    st.stop()

supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

# --- 2. HILFSFUNKTIONEN ---

def ask_ki(prompt):
    try:
        return ki_model.generate_content(prompt).text
    except: return "KI Fehler"

@st.cache_data(ttl=3600)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y")
        if h.empty: return None
        
        info = s.info
        cp = info.get('currentPrice') or h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # RSI Berechnung
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(window=14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
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
st.title("🏛️ Professional Investment Terminal (ATH & Fair Value)")

with st.sidebar:
    st.header("⚙️ Tranchen-Parameter")
    t1_drop = st.slider("Tranche 1 bei ATH-Korrektur (%)", 5, 50, 15)
    t2_drop = st.slider("Tranche 2 bei ATH-Korrektur (%)", 10, 70, 30)
    
    st.divider()
    st.header("➕ Neue Aktie")
    t_in = st.text_input("Ticker Symbol").upper()
    fv_in = st.number_input("Fairer Wert (€)", value=0.0)
    if st.button("Speichern"):
        if t_in:
            supabase.table("watchlist").insert({"ticker": t_in, "fair_value": fv_in}).execute()
            st.success(f"{t_in} wurde hinzugefügt!")
            st.rerun()

# --- 4. DATENVERARBEITUNG ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    rows = []
    with st.spinner("Lade Marktdaten..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                fv = r.get('fair_value', 0) or 0
                
                # Tranchen-Berechnung vom ATH
                t1_preis = m['ATH'] * (1 - t1_drop/100)
                t2_preis = m['ATH'] * (1 - t2_drop/100)
                
                # Abstände berechnen
                diff_fv = ((m['Preis'] / fv) - 1) * 100 if fv > 0 else 0
                
                # Signal-Logik
                # Kaufzone wenn unter FV UND Tranche 1 vom ATH erreicht
                status = "🎯 KAUFBEREIT" if fv > 0 and m['Preis'] <= fv and m['Preis'] <= t1_preis else "⏳ Warten"
                if m['Preis'] <= t2_preis: status = "🔥 TR2 LIMIT"

                rows.append({
                    "id": r['id'],
                    "Ticker": r['ticker'],
                    "Kurs": m['Preis'],
                    "Fair Value": fv,
                    "Diff_FV %": round(diff_fv, 1),
                    "ATH": m['ATH'],
                    "Korr_ATH %": m['Abstand_ATH'],
                    "RSI": m['RSI'],
                    "Tranche 1": round(t1_preis, 2),
                    "Tranche 2": round(t2_preis, 2),
                    "Status": status
                })

    df_display = pd.DataFrame(rows)

    # --- TABELLE ---
    st.subheader("📊 Multi-Faktor Watchlist")
    
    # Editor für Fair Value Änderungen
    edited_df = st.data_editor(
        df_display,
        column_config={
            "id": None,
            "Fair Value": st.column_config.NumberColumn("Fair Value (€)", format="%.2f"),
            "Diff_FV %": st.column_config.NumberColumn("Diff/FV", format="%.1f%%"),
            "Korr_ATH %": st.column_config.NumberColumn("Korr/ATH", format="%.1f%%"),
        },
        disabled=["Ticker", "Kurs", "Diff_FV %", "ATH", "Korr_ATH %", "RSI", "Tranche 1", "Tranche 2", "Status"],
        hide_index=True,
        use_container_width=True
    )

    if st.button("💾 Alle Fair Value Änderungen speichern"):
        for _, row in edited_df.iterrows():
            supabase.table("watchlist").update({"fair_value": row["Fair Value"]}).eq("id", row["id"]).execute()
        st.success("Datenbank aktualisiert!")
        st.rerun()

    # Lösch-Funktion
    with st.expander("🗑️ Ticker entfernen"):
        del_ticker = st.selectbox("Wähle Ticker", df_display['Ticker'])
        if st.button("Löschen"):
            supabase.table("watchlist").delete().eq("ticker", del_ticker).execute()
            st.rerun()

    # --- 5. EXPERTEN ANALYSE ---
    st.divider()
    st.subheader("🤖 KI Analyse-Terminal")
    sel_ticker = st.selectbox("Aktie für Tiefenprüfung:", df_display['Ticker'])
    
    # Deine erweiterten Analyse-Prozesse
    analyse_typ = st.selectbox("Analyse-Prozess wählen:", [
        "1. Komplett-Analyse (Equity Report)",
        "2. Bewertungs-Profi (Fair Value Kalkulation)",
        "3. Dividenden-Sicherheits-Check",
        "4. Konkurrenz-Ranking (Market Share)",
        "5. Crash-Resistenz-Test",
        "6. Szenario-Analyse (Best/Worst Case)"
    ])

    if st.button("Prozess starten"):
        stock_context = df_display[df_display['Ticker'] == sel_ticker].iloc[0].to_dict()
        
        prompts = {
            "1. Komplett-Analyse (Equity Report)": f"Analysiere {sel_ticker} wie ein Profi-Equity-Analyst: 1. Geschäftsmodell, 2. Fundamentaldaten, 3. Bewertung, 4. Bilanz, 5. Dividende, 6. Chancen/Risiken, 7. Szenarien, 8. Fazit. Daten: {stock_context}",
            "2. Bewertungs-Profi (Fair Value Kalkulation)": f"Berechne für {sel_ticker} einen fairen Wert aus DCF & KGV. Vergleiche mit meinem FV von {stock_context['Fair Value']}€. Daten: {stock_context}",
            "3. Dividenden-Sicherheits-Check": f"Untersuche die Dividende von {sel_ticker}: Payout-Ratio, Historie & Sicherheit. Daten: {stock_context}",
            "4. Konkurrenz-Ranking (Market Share)": f"Vergleiche {sel_ticker} mit den Top-Wettbewerbern. Margen- & Burggraben-Check. Daten: {stock_context}",
            "5. Crash-Resistenz-Test": f"Wie hat sich {sel_ticker} historisch in Bärenmärkten verhalten? Maximale Drawdowns. Daten: {stock_context}",
            "6. Szenario-Analyse (Best/Worst Case)": f"Erstelle 3 Kurs-Szenarien für {sel_ticker} auf Sicht von 24 Monaten basierend auf Wachstumsprognosen. Daten: {stock_context}"
        }
        
        with st.chat_message("assistant"):
            st.markdown(ask_ki(prompts[analyse_typ]))
else:
    st.info("Watchlist ist leer.")
