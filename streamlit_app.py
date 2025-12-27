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
        
        return {
            "Preis": round(cp, 2), 
            "ATH": round(ath, 2),
            "RSI": round(rsi, 1), 
            "Abstand_ATH": round(((cp / ath) - 1) * 100, 1)
        }
    except: return None

# --- 3. UI & SIDEBAR ---
st.title("🏛️ Professional Investment Terminal (ATH, FV & RSI)")

with st.sidebar:
    st.header("⚙️ Tranchen-Parameter")
    t1_drop = st.slider("Tranche 1 bei ATH-Korrektur (%)", 5, 50, 15)
    t2_drop = st.slider("Tranche 2 bei ATH-Korrektur (%)", 10, 70, 30)
    
    st.divider()
    st.header("🛡️ RSI-Filter")
    max_rsi_kauf = st.slider("Max. RSI für Kauffreigabe", 20, 70, 45, help="Nur wenn der RSI unter diesem Wert liegt, wird ein Kaufsignal (🎯) angezeigt.")
    
    st.divider()
    st.header("➕ Neue Aktie")
    t_in = st.text_input("Ticker Symbol").upper()
    fv_in = st.number_input("Fairer Wert (€)", value=0.0)
    if st.button("Speichern"):
        if t_in:
            supabase.table("watchlist").insert({"ticker": t_in, "fair_value": fv_in}).execute()
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
                t1_preis = m['ATH'] * (1 - t1_drop/100)
                t2_preis = m['ATH'] * (1 - t2_drop/100)
                diff_fv = ((m['Preis'] / fv) - 1) * 100 if fv > 0 else 0
                
                # KOMPLEXE SIGNAL-LOGIK (Preis + RSI)
                status = "⏳ Warten"
                if m['Preis'] <= t1_preis:
                    if m['RSI'] <= max_rsi_kauf:
                        status = "🎯 TR1 BEREIT"
                    else:
                        status = "⚠️ Preis OK, RSI zu hoch"
                
                if m['Preis'] <= t2_preis:
                    if m['RSI'] <= max_rsi_kauf:
                        status = "🔥 TR2 LIMIT"
                    else:
                        status = "⚠️ TR2 Preis erreicht, RSI hoch"

                rows.append({
                    "id": r['id'],
                    "Ticker": r['ticker'],
                    "Kurs": m['Preis'],
                    "Fair Value": fv,
                    "Diff_FV %": round(diff_fv, 1),
                    "Korr_ATH %": m['Abstand_ATH'],
                    "RSI": m['RSI'],
                    "Tranche 1": round(t1_preis, 2),
                    "Tranche 2": round(t2_preis, 2),
                    "Status": status
                })

    df_display = pd.DataFrame(rows)

    # --- TABELLEN STYLING (HEATMAP) ---
    def style_rows(row):
        styles = [''] * len(row)
        if "🎯" in str(row['Status']) or "🔥" in str(row['Status']):
            styles = ['background-color: #004d00'] * len(row) # Dunkelgrün für Kaufzone
        elif "⚠️" in str(row['Status']):
            styles = ['background-color: #4d4d00'] * len(row) # Dunkelgelb für RSI-Warnung
        return styles

    st.subheader("📊 Multi-Faktor Watchlist & Heatmap")
    
    st.data_editor(
        df_display.style.apply(style_rows, axis=1),
        column_config={
            "id": None,
            "RSI": st.column_config.NumberColumn("RSI", help="Grün < 35, Rot > 65"),
            "Diff_FV %": st.column_config.NumberColumn("Abstand FV %", format="%.1f%%"),
            "Status": st.column_config.TextColumn("Handlungsempfehlung")
        },
        disabled=list(df_display.columns), # Deaktiviert Bearbeitung in der Ansicht für Stabilität
        hide_index=True,
        use_container_width=True
    )

    # Lösch-Funktion & FV-Update in separaten Bereich für besseres UI
    col_up, col_del = st.columns(2)
    with col_up:
        with st.expander("📝 Fair Value manuell anpassen"):
            up_ticker = st.selectbox("Ticker wählen", df_display['Ticker'])
            new_fv = st.number_input("Neuer Wert", value=0.0)
            if st.button("Update"):
                supabase.table("watchlist").update({"fair_value": new_fv}).eq("ticker", up_ticker).execute()
                st.rerun()
    
    with col_del:
        with st.expander("🗑️ Ticker entfernen"):
            del_t = st.selectbox("Ticker löschen", df_display['Ticker'])
            if st.button("Löschen"):
                supabase.table("watchlist").delete().eq("ticker", del_t).execute()
                st.rerun()

    # --- 5. EXPERTEN ANALYSE ---
    st.divider()
    st.subheader("🤖 KI Analyse-Terminal")
    sel_ticker = st.selectbox("Aktie für Tiefenprüfung:", df_display['Ticker'], key="deepdive")
    
    analyse_typ = st.selectbox("Analyse-Prozess wählen:", [
        "1. Komplett-Analyse (Equity Report)",
        "2. Bewertungs-Profi (Fair Value Kalkulation)",
        "3. Dividenden-Sicherheits-Check",
        "4. Konkurrenz-Ranking (Market Share)",
        "5. Crash-Resistenz-Test",
        "6. Szenario-Analyse (Best/Worst Case)"
    ])

    if st.button("KI Prozess starten"):
        stock_context = df_display[df_display['Ticker'] == sel_ticker].iloc[0].to_dict()
        
        # Hier habe ich deine spezifischen Analyse-Anweisungen eingebaut
        prompts = {
            "1. Komplett-Analyse (Equity Report)": f"Analysiere {sel_ticker} wie ein Profi: 1. Geschäftsmodell, 2. Fundamentaldaten, 3. Bewertung, 4. Bilanz, 5. Dividende, 6. Chancen/Risiken, 7. Szenarien, 8. Fazit. Kontext: {stock_context}",
            "2. Bewertungs-Profi (Fair Value Kalkulation)": f"Berechne für {sel_ticker} einen fairen Wert aus DCF & KGV. Nutze den aktuellen RSI von {stock_context['RSI']} für das Timing. Kontext: {stock_context}",
            "3. Dividenden-Sicherheits-Check": f"Untersuche die Dividende von {sel_ticker}: Payout-Ratio, Historie & Sicherheit. Kontext: {stock_context}",
            "4. Konkurrenz-Ranking (Market Share)": f"Vergleiche {sel_ticker} mit den Top-Wettbewerbern. Margen- & Burggraben-Check.",
            "5. Crash-Resistenz-Test": f"Wie hat sich {sel_ticker} historisch in Bärenmärkten verhalten? Drawdowns & Recovery.",
            "6. Szenario-Analyse (Best/Worst Case)": f"Erstelle 3 Kurs-Szenarien auf 24 Monate für {sel_ticker}."
        }
        
        with st.chat_message("assistant"):
            st.markdown(ask_ki(prompts[analyse_typ]))

else:
    st.info("Watchlist ist leer.")
