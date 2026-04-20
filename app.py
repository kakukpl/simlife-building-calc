import streamlit as st
import pandas as pd
import math

# ─────────────────────────────────────────────
#  KONFIGURACJA BUDYNKÓW
#  Aby dodać nowy typ budynku, wystarczy dodać
#  kolejny słownik do tej listy.
# ─────────────────────────────────────────────
BUILDINGS = [
    {
        "id": "ob",
        "name": "OB (Ordinary Building)",
        "emoji": "🏗️",
        "cost": 161_596,          # PLN za sztukę
        "revenue_10h": 221_935.71, # PLN przychód po 10h
        "needs": {
            "Budowniczowie": (5, "os."),
            "Metal":         (1_200, "t"),
            "Drewno":        (1_000, "m³"),
            "Beton":         (50,    "m³"),
        },
    },
    # Przykład – odkomentuj i uzupełnij dane gdy będziesz gotowy:
    # {
    #     "id": "suspension_bridge",
    #     "name": "Suspension Bridge",
    #     "emoji": "🌉",
    #     "cost": 0,
    #     "revenue_10h": 0,
    #     "needs": {
    #         "Budowniczowie": (0, "os."),
    #         "Metal":         (0, "t"),
    #         "Drewno":        (0, "m³"),
    #         "Beton":         (0, "m³"),
    #         "Kable":         (0, "szt."),
    #     },
    # },
]

# ─────────────────────────────────────────────
#  PRZYCHODY GRACZA (edytuj tutaj)
# ─────────────────────────────────────────────
PASSIVE_INCOME_PER_H  = 8_480_000      # PLN/h  – Pasywka
CLICKING_INCOME_PER_H = 46_138_788     # PLN/h  – Klikanie

# ─────────────────────────────────────────────
#  FUNKCJE POMOCNICZE
# ─────────────────────────────────────────────
def fmt(n: float, decimals: int = 0) -> str:
    """Formatuje liczbę z separatorem tysięcy i jednostką PLN."""
    return f"{n:,.{decimals}f}".replace(",", " ")

def fmt_pln(n: float) -> str:
    return f"{fmt(n, 2)} PLN"

def calculate(balance: float, click_hours: float, building: dict) -> dict:
    passive   = PASSIVE_INCOME_PER_H * click_hours
    clicking  = CLICKING_INCOME_PER_H * click_hours
    earned    = passive + clicking
    total     = balance + earned
    max_units = math.floor(total / building["cost"])
    spent     = max_units * building["cost"]
    remaining = total - spent
    profit_10h = max_units * building["revenue_10h"]

    return {
        "passive":   passive,
        "clicking":  clicking,
        "earned":    earned,
        "total":     total,
        "max_units": max_units,
        "spent":     spent,
        "remaining": remaining,
        "profit_10h": profit_10h,
    }

# ─────────────────────────────────────────────
#  LAYOUT
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="OB Empire Manager",
    page_icon="🏗️",
    layout="centered",
)

# ── CSS – mobile-first, czytelny kontrast ────
st.markdown("""
<style>
    /* Ogólne tło */
    .stApp { background: #0f1117; }

    /* Karta metryki */
    [data-testid="metric-container"] {
        background: #1e2130;
        border: 1px solid #2d3250;
        border-radius: 12px;
        padding: 12px 16px;
    }

    /* Tabela zakupów */
    .buy-table { width: 100%; border-collapse: collapse; }
    .buy-table th {
        background: #2d3250;
        color: #a0aec0;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: .05em;
        padding: 8px 10px;
        text-align: left;
    }
    .buy-table td {
        padding: 10px 10px;
        border-bottom: 1px solid #2d3250;
        color: #e2e8f0;
        font-size: 0.92rem;
    }
    .buy-table tr:last-child td { border-bottom: none; }
    .buy-table tr:hover td { background: #1e2130; }

    /* Badge zielony */
    .badge-green {
        background: #22543d; color: #9ae6b4;
        padding: 2px 8px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600;
    }
    /* Badge niebieski */
    .badge-blue {
        background: #1a365d; color: #90cdf4;
        padding: 2px 8px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600;
    }

    /* Nagłówek sekcji */
    .section-title {
        font-size: 1rem; font-weight: 700;
        color: #90cdf4; margin: 1.2rem 0 .5rem;
        border-left: 3px solid #4299e1;
        padding-left: 10px;
    }
    div[data-testid="stNumberInput"] input { font-size: 1.1rem; }
</style>
""", unsafe_allow_html=True)

# ── Tytuł ────────────────────────────────────
st.markdown("## 🏗️ OB Empire Manager")
st.caption("Optymalizator budowy · Mobile First")
st.divider()

# ── Wybór budynku (jeśli jest więcej niż jeden) ─
if len(BUILDINGS) > 1:
    building_names = [f"{b['emoji']} {b['name']}" for b in BUILDINGS]
    chosen_idx = st.selectbox("Typ budynku", range(len(BUILDINGS)),
                               format_func=lambda i: building_names[i])
    building = BUILDINGS[chosen_idx]
else:
    building = BUILDINGS[0]

# ── Inputy ───────────────────────────────────
col1, col2 = st.columns([3, 2], gap="medium")

with col1:
    balance_raw = st.number_input(
        "💰 Aktualne Saldo (PLN)",
        min_value=0,
        max_value=10_000_000_000,
        value=0,
        step=100_000,
        help="Wpisz swoje bieżące saldo w PLN",
        format="%d",
    )

with col2:
    click_hours = st.slider(
        "⏱️ Czas klikania (h)",
        min_value=0.0,
        max_value=12.0,
        value=0.0,
        step=0.5,
        help="Ile godzin planujesz klikać?",
    )

balance = float(balance_raw)

# ── Obliczenia ───────────────────────────────
r = calculate(balance, click_hours, building)

# ── Sekcja: Prognoza zarobku ─────────────────
st.markdown('<p class="section-title">📈 Prognoza zarobku</p>', unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
c1.metric("Pasywka",   f"{fmt(r['passive'])} PLN",  help=f"{fmt(PASSIVE_INCOME_PER_H)} PLN/h")
c2.metric("Klikanie",  f"{fmt(r['clicking'])} PLN", help=f"{fmt(CLICKING_INCOME_PER_H)} PLN/h × {click_hours}h")
c3.metric("Łącznie",   f"{fmt(r['earned'])} PLN",   delta=f"Saldo po: {fmt(r['total'])} PLN")

# ── Sekcja: Wynik zakupu ─────────────────────
st.markdown('<p class="section-title">🏆 Wynik zakupu</p>', unsafe_allow_html=True)

ca, cb = st.columns(2)
ca.metric(f"Maks. {building['emoji']} do kupienia",
          f"{fmt(r['max_units'])} szt.",
          help="Maksymalna liczba całkowita budynków")
cb.metric("Reszta na koncie",
          f"{fmt_pln(r['remaining'])}",
          help="Środki po zakupie wszystkich budynków")

st.metric("💸 Przewidywany zysk po 10h",
          f"{fmt_pln(r['profit_10h'])}",
          help=f"{r['max_units']} szt. × {fmt_pln(building['revenue_10h'])} / budynek")

# ── Sekcja: Tabela zakupów dla autoklikera ───
st.markdown('<p class="section-title">🤖 Tabela zakupów (dla autoklikera)</p>',
            unsafe_allow_html=True)

if r["max_units"] == 0:
    st.info("Uzupełnij saldo lub zwiększ czas klikania, aby obliczyć zakupy.")
else:
    rows = []
    for resource, (amount_per_unit, unit) in building["needs"].items():
        total_needed = amount_per_unit * r["max_units"]
        rows.append({
            "Zasób": resource,
            "Na 1 budynek": f"{fmt(amount_per_unit)} {unit}",
            "Łącznie": f"{fmt(total_needed)} {unit}",
        })

    df = pd.DataFrame(rows)

    # Renderuj jako HTML table z niestandardowym stylem
    header_html = "".join(f"<th>{col}</th>" for col in df.columns)
    rows_html   = ""
    for _, row in df.iterrows():
        rows_html += "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"

    table_html = f"""
    <table class="buy-table">
      <thead><tr>{header_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    st.markdown(f"""
    <br>
    <span class="badge-blue">📦 Łączny koszt zakupu: {fmt_pln(r['spent'])}</span>
    &nbsp;
    <span class="badge-green">✅ Budynki do kupna: {fmt(r['max_units'])} szt.</span>
    """, unsafe_allow_html=True)

# ── Sekcja: Dane bazowe budynku ──────────────
with st.expander(f"ℹ️ Dane bazowe – {building['name']}"):
    st.markdown(f"""
| Parametr | Wartość |
|---|---|
| Koszt budynku | {fmt_pln(building['cost'])} |
| Przychód po 10h | {fmt_pln(building['revenue_10h'])} |
| Pasywka (konfiguracja) | {fmt(PASSIVE_INCOME_PER_H)} PLN/h |
| Klikanie (konfiguracja) | {fmt(CLICKING_INCOME_PER_H)} PLN/h |
    """)

st.divider()
st.caption("OB Empire Manager · v1.0 · Dane konfiguracyjne w `app.py` → sekcja BUILDINGS i PRZYCHODY GRACZA")
