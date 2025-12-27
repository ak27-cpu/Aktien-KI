import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import pandas as pd
import google.generativeai as genai

# --- 1. KONFIGURATION & SETUP ---
st.set_page_config(page_title="KI Aktien-Terminal", layout="wide")

# KI Setup
# --- KI SETUP (AKTUALISIERT) ---
if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    # Wir nutzen das neueste Modell aus deiner Liste
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("Gemini API Key fehlt in den Secrets!")

def ask_ki(prompt):
    try:
        # Sicherheits-Check: Falls das Modell eine Antwort verweigert
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"KI-Fehler: {str(e)}. Versuche es in einem Moment erneut."

# Supabase Setup
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

supabase = get_supabase()
# --- DEBUG: WELCHE MODELLE SIND VERFÜGBAR? ---
with st.expander("🛠️ KI-System-Check (Nur bei Fehlern nutzen)"):
    if st.button("Verfügbare Modelle auflisten"):
        try:
            available_models = genai.list_models()
            models_list = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
            st.write("Dein Key unterstützt folgende Modelle:")
            st.json(models_list)
        except Exception as e:
            st.error(f"Fehler beim Abrufen der Modelle: {e}")

# --- 2. FUNKTIONEN ---
def load_watchlist():
    res = supabase.table("watchlist").select("*").execute()
    return pd.DataFrame(res.data)

import numpy as np

@st.cache_data(ttl=3600)
def get_extended_metrics(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y") # 2 Jahre für stabilere Durchschnitte
        info = stock.info
        
        if hist.empty: return None

        # 1. Kurs & Allzeithoch (52W)
        current_price = info.get('currentPrice') or hist['Close'].iloc[-1]
        high_52w = info.get('fiftyTwoWeekHigh') or hist['High'].max()
        aktuelle_korrektur = ((current_price / high_52w) - 1) * 100
        
        # 2. Historische Korrektur (Durchschnittliche Drawdowns)
        # Wir berechnen den Schnitt der Abstände vom rollierenden Hoch
        rolling_max = hist['Close'].cummax()
        drawdowns = (hist['Close'] / rolling_max - 1) * 100
        hist_korrektur_schnitt = drawdowns.mean()

        # 3. RSI (Relative Strength Index) - 14 Tage
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1+rs)).iloc[-1]

        # 4. Verschuldungsgrad (Total Debt / Equity)
        debt_to_equity = info.get('debtToEquity', 0) 
        # yfinance liefert oft Werte wie 80.0 für 80%
        verschuldungsgrad = debt_to_equity if debt_to_equity < 5 else debt_to_equity / 100

        return {
            "Kurs": round(current_price, 2),
            "Korrektur_%": round(aktuelle_korrektur, 1),
            "Hist_Korrektur_%": round(hist_korrektur_schnitt, 1),
            "Schulden_%": round(verschuldungsgrad * 100, 1),
            "RSI": round(rsi, 1),
            "Trend": "Aufwärts ✅" if current_price > hist['Close'].rolling(200).mean().iloc[-1] else "Abwärts ⚠️"
        }
    except Exception as e:
        return None

# --- UI DARSTELLUNG ---
df_db = load_watchlist()
if not df_db.empty:
    all_results = []
    for _, row in df_db.iterrows():
        m = get_extended_metrics(row['ticker'])
        if m:
            # KI-Quick-Check (Kurze Einschätzung für die Tabelle)
            # Wir geben der KI nur die nackten Zahlen für ein schnelles Urteil
            abstand_fv = ((m['Kurs'] / row['fair_value']) - 1) * 100 if row['fair_value'] > 0 else 0
            
            # Kurzes KI Urteil generieren (Optional für jede Zeile)
            status_prompt = f"Aktie {row['ticker']}: Kurs {m['Kurs']}, FairValue {row['fair_value']}, RSI {m['RSI']}, Schulden {m['Schulden_%']}%. Urteil in 2 Worten (z.B. 'Günstig, Kaufen' oder 'Teuer, Warten')."
            ki_kurzurteil = ask_ki(status_prompt)
            
            all_results.append({
                "Ticker": row['ticker'],
                "Preis": f"{m['Kurs']} €",
                "Fair Value": f"{row['fair_value']} €",
                "Abstand FV": f"{round(abstand_fv, 1)}%",
                "Korrektur": f"{m['Korrektur_%']}%",
                "Ø Korr.": f"{m['Hist_Korrektur_%']}%",
                "Schulden": f"{m['Schulden_%']}%",
                "RSI": m['RSI'],
                "KI-Check": ki_kurzurteil
            })

    df_power = pd.DataFrame(all_results)
    
    # Styling für die Tabelle
    def style_rsi(v):
        if v < 30: return 'background-color: #00ff00; color: black' # Überverkauft
        if v > 70: return 'background-color: #ff4b4b; color: white' # Überkauft
        return ''

    st.subheader("🚀 Power-Watchlist")
    st.dataframe(df_power.style.applymap(style_rsi, subset=['RSI']), use_container_width=True, hide_index=True)
        }
    except: return None

def ask_ki(prompt):
    try:
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e: return f"Fehler: {e}"

# --- 3. HAUPT-UI ---
st.title("🚀 Mein KI-Aktien-Terminal")

# Sidebar: Verwaltung
with st.sidebar:
    st.header("➕ Watchlist")
    t_input = st.text_input("Ticker").upper()
    fv_input = st.number_input("Fair Value", value=0.0)
    if st.button("Hinzufügen"):
        supabase.table("watchlist").insert({"ticker": t_input, "fair_value": fv_input}).execute()
        st.rerun()

# Daten laden
df_db = load_watchlist()

if not df_db.empty:
    # Live-Daten mischen
    with st.spinner("Lade Marktdaten..."):
        all_data = []
        for _, row in df_db.iterrows():
            live = get_live_data(row['ticker'])
            if live: all_data.append({**row, **live})
    
    df_final = pd.DataFrame(all_data)
    st.dataframe(df_final, use_container_width=True, hide_index=True)

    st.divider()

    # --- KI ANALYSE BEREICH ---
    st.subheader("🤖 KI Analysten-Terminal")
    
    sel_ticker = st.selectbox("Aktie wählen:", df_final['ticker'])
    modus = st.radio("Analyse-Typ:", [
        "Komplett-Analyse", "Bewertungs-Profi", "Dividenden-Check", 
        "Konkurrenz-Vergleich", "Crash-Analyse", "Portfolio-Check"
    ], horizontal=True)

    # Hier greift dein Experten-Regelwerk
    if st.button(f"Analyse für {sel_ticker} starten"):
        stock_info = df_final[df_final['ticker'] == sel_ticker].iloc[0].to_dict()
        
        prompts = {
            "Komplett-Analyse": f"Analysiere {sel_ticker} wie ein Profi-Equity-Analyst: 1. Geschäftsmodell, 2. Fundamentaldaten, 3. Bewertung, 4. Bilanz, 5. Dividende, 6. Chancen/Risiken, 7. Szenarien, 8. Fazit. Daten: {stock_info}",
            "Bewertungs-Profi": f"Berechne fairen Wert für {sel_ticker} via DCF, Multiples & Branchenvergleich. Daten: {stock_info}",
            "Dividenden-Check": f"Prüfe Dividendenqualität von {sel_ticker}: Quote, Historie, Sicherheit. Urteil: sicher, fraglich, riskant.",
            "Konkurrenz-Vergleich": f"Vergleiche {sel_ticker} mit 3 Konkurrenten (Wachstum, Margen, Burggraben). Erstelle Ranking.",
            "Crash-Analyse": f"Historisches Verhalten von {sel_ticker} in Krisen. Stabilität 1-10.",
            "Portfolio-Check": f"Bewerte mein Portfolio: {df_final['ticker'].tolist()}. Fokus auf Klumpenrisiken & Optimierung."
        }
        
        with st.chat_message("assistant"):
            bericht = ask_ki(prompts[modus])
            st.markdown(bericht)
else:
    st.info("Noch keine Ticker in der Datenbank.")
