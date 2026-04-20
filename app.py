"""
SimLife Empire Manager v2.2
Upgrades: Configurable Building ROI (sidebar), Market Analyzer tab,
           strict floor(cash / cost) calculation throughout.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# SECTION 1: PAGE CONFIGURATION & BASE CONSTANTS
# ============================================================

st.set_page_config(
    page_title="SimLife Empire Manager",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Immutable defaults — only used to seed session state once ---
_BUILDING_DEFAULTS: dict[str, dict] = {
    "🏢 Office Building (OB)": {
        "cost":     161_596,
        "revenue":  221_935.71,
        "time_h":   10,
        "workers":  5,
        "metal":    1_200,
        "wood":     1_000,
        "concrete": 50,
    },
    "🌉 Suspension Bridge": {
        "cost":     1_500_000,
        "revenue":  2_100_000.00,
        "time_h":   12,
        "workers":  20,
        "metal":    15_000,
        "wood":     2_000,
        "concrete": 5_000,
    },
    "🏨 Luxury Hotel": {
        "cost":     5_000_000,
        "revenue":  7_500_000.00,
        "time_h":   24,
        "workers":  50,
        "metal":    5_000,
        "wood":     15_000,
        "concrete": 10_000,
    },
}

BUILDING_KEYS = list(_BUILDING_DEFAULTS.keys())

RESOURCE_KEYS   = ["workers", "metal", "wood", "concrete"]
RESOURCE_LABELS = ["👷 Workers", "⚙️ Metal (t)", "🪵 Wood (m³)", "🧱 Concrete (m³)"]

# --- Market Analyzer reference data ---
# Format: (label, qty_in_pack, pack_price, unit_price)
MARKET_REFERENCE: dict[str, tuple[int, float, float]] = {
    "👷 Workers":     (5,    111_603.00,  22_320.60),
    "⚙️ Metal (t)":  (5023, 22_423.28,       4.46),
    "🪵 Wood (m³)":  (2009, 22_421.04,      11.16),
    "🧱 Concrete (m³)": (33, 22_097.39,    669.61),
}

ACHIEVEMENT_DEFINITIONS = [
    (
        "🥇 First Million",
        lambda s: s["cash"] >= 1_000_000,
        "Reach $1,000,000 balance",
    ),
    (
        "🏢 Office Tycoon (100+ OB)",
        lambda s: any(
            h["building"].startswith("🏢") and h["units"] >= 100
            for h in s["history"]
        ),
        "Build 100+ Office Buildings in one session",
    ),
    (
        "💰 Half-Billionaire",
        lambda s: s["cash"] >= 500_000_000,
        "Reach $500,000,000 balance",
    ),
    (
        "🤑 Billionaire",
        lambda s: s["cash"] >= 1_000_000_000,
        "Reach $1,000,000,000 balance",
    ),
    (
        "🌉 Bridge Builder",
        lambda s: any(
            h["building"].startswith("🌉") for h in s["history"]
        ),
        "Complete at least one Suspension Bridge build",
    ),
    (
        "🏨 Hotel Mogul",
        lambda s: any(
            h["building"].startswith("🏨") for h in s["history"]
        ),
        "Complete at least one Luxury Hotel build",
    ),
    (
        "📦 Warehouse Pro",
        lambda s: any(
            h.get("had_warehouse_stock") for h in s["history"]
        ),
        "Save a build while warehouse had stock > 0",
    ),
    (
        "🔁 Serial Builder",
        lambda s: len(s["history"]) >= 5,
        "Save 5 or more builds in one session",
    ),
    (
        "⚖️ Market Analyst",
        lambda s: s.get("market_calcs_done", 0) >= 3,
        "Perform 3 or more Market Analyzer calculations",
    ),
    (
        "✏️ ROI Configurator",
        lambda s: s.get("roi_edits_done", 0) >= 1,
        "Customise at least one building's cost or revenue",
    ),
]

# ============================================================
# SECTION 2: PANDAS VERSION COMPATIBILITY
# ============================================================

def _pandas_version_tuple() -> tuple[int, ...]:
    return tuple(int(x) for x in pd.__version__.split(".")[:3])


def safe_style_map(styler, func, subset=None):
    """
    Routes .map() on pandas >= 2.1.0, .applymap() on older versions.
    Prevents AttributeError from the renamed Styler API.
    """
    if _pandas_version_tuple() >= (2, 1, 0):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)  # type: ignore[attr-defined]


# ============================================================
# SECTION 3: SESSION STATE INITIALISATION
# ============================================================

def init_session_state() -> None:
    """
    Bootstrap all session keys exactly once per browser session.

    Building ROI values are stored under:
        st.session_state["buildings"][name]["cost"]
        st.session_state["buildings"][name]["revenue"]
    This lets the sidebar edit them without mutating the base constants.
    """
    if "buildings" not in st.session_state:
        # Deep-copy defaults into session state so edits never touch _BUILDING_DEFAULTS
        st.session_state["buildings"] = {
            name: dict(data)
            for name, data in _BUILDING_DEFAULTS.items()
        }

    scalar_defaults: dict = {
        "history":           [],
        "cash":              1_000_000,
        "market_calcs_done": 0,
        "roi_edits_done":    0,
    }
    for key, value in scalar_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()

# Convenience accessor — always reflects live sidebar edits
def get_buildings() -> dict[str, dict]:
    """Return the live (possibly user-edited) building config."""
    return st.session_state["buildings"]


# ============================================================
# SECTION 4: CALCULATION ENGINE (Pure Functions)
# ============================================================

def clamp_to_zero(value: float) -> float:
    """
    Warehouse safety clamp — guarantees non-negative quantities.

    clamp_to_zero(500)   →  500.0   (need to buy 500)
    clamp_to_zero(0)     →    0.0   (exactly covered)
    clamp_to_zero(-200)  →    0.0   (surplus of 200 — buy nothing)
    """
    return max(0.0, value)


def calculate_max_units(cash: float, cost_per_unit: float) -> int:
    """
    Strict formula: floor(cash / cost_per_unit).

    No income projections. No hidden adjustments.
    Returns the exact number of units affordable right now.
    """
    if cost_per_unit <= 0:
        return 0
    return int(cash // cost_per_unit)


def net_resource_needed(units: int, per_unit: int, in_stock: int) -> int:
    """
    Resources still to purchase after accounting for warehouse stock.

    to_buy = max(0, units × per_unit − in_stock)
    Always returns int >= 0.
    """
    return int(clamp_to_zero(units * per_unit - in_stock))


def build_shopping_list(
    units: int,
    building: dict,
    warehouse: dict[str, int],
) -> pd.DataFrame:
    """
    Net shopping list: total required minus warehouse stock.

    Columns: Resource | Total Needed | In Warehouse | Surplus | To Buy | Status
    'To Buy' is ALWAYS >= 0 (enforced by net_resource_needed → clamp_to_zero).
    """
    rows = []
    for key, label in zip(RESOURCE_KEYS, RESOURCE_LABELS):
        total_needed = units * building[key]
        in_stock     = warehouse[key]
        to_buy       = net_resource_needed(units, building[key], in_stock)
        surplus      = int(clamp_to_zero(in_stock - total_needed))

        rows.append({
            "Resource":     label,
            "Total Needed": total_needed,
            "In Warehouse": in_stock,
            "Surplus":      surplus,
            "To Buy":       to_buy,
            "Status":       "✅ OK" if to_buy == 0 else "🛒 Buy",
        })

    return pd.DataFrame(rows)


def identify_bottleneck(df: pd.DataFrame) -> str | None:
    """Resource with the largest outstanding 'To Buy' quantity, or None."""
    needs = df[df["To Buy"] > 0]
    if needs.empty:
        return None
    return str(needs.sort_values("To Buy", ascending=False).iloc[0]["Resource"])


def calculate_roi(cost: float, revenue: float) -> float:
    """ROI % = (revenue − cost) / cost × 100."""
    if cost <= 0:
        return 0.0
    return ((revenue - cost) / cost) * 100


def calculate_unit_price(package_qty: float, package_price: float) -> float | None:
    """
    Price per single resource unit.

    Returns None when inputs are invalid (prevents division by zero).
    Formula: package_price / package_qty
    """
    if package_qty <= 0 or package_price < 0:
        return None
    return package_price / package_qty


def warehouse_has_stock(warehouse: dict[str, int]) -> bool:
    return any(v > 0 for v in warehouse.values())


# ============================================================
# SECTION 5: STYLING HELPERS
# ============================================================

def style_to_buy_cell(val: int) -> str:
    """Colour-code a single 'To Buy' cell by urgency."""
    if val == 0:
        return "color: #4caf50; font-weight: bold;"     # green  — covered
    if val > 10_000:
        return "color: #ff6b35; font-weight: bold;"     # orange — large buy
    return "color: #ffcc00; font-weight: bold;"         # yellow — moderate buy


def style_price_vs_ref(val: float, ref: float) -> str:
    """
    Colour-code a calculated unit price relative to the reference price.

    Green  = at or below reference (good deal)
    Yellow = up to 20% above reference (acceptable)
    Red    = more than 20% above reference (expensive)
    """
    if val <= ref:
        return "color: #4caf50; font-weight: bold;"
    if val <= ref * 1.20:
        return "color: #ffcc00; font-weight: bold;"
    return "color: #ff4444; font-weight: bold;"


def format_shopping_df(df: pd.DataFrame):
    """Styled DataFrame for the shopping list (pandas 2.1+ compatible)."""
    display_df = df.copy()
    display_df["Total Needed"] = display_df["Total Needed"].apply(lambda x: f"{x:,}")
    display_df["In Warehouse"] = display_df["In Warehouse"].apply(lambda x: f"{x:,}")
    display_df["Surplus"]      = display_df["Surplus"].apply(
        lambda x: f"+{x:,}" if x > 0 else "—"
    )
    styler = display_df.style.format({"To Buy": "{:,}"})
    styler = safe_style_map(styler, style_to_buy_cell, subset=["To Buy"])
    return styler


# ============================================================
# SECTION 6: CUSTOM CSS
# ============================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }

        /* ── Metric cards ── */
        [data-testid="stMetric"] {
            background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
            border: 1px solid #4a4a6a;
            border-radius: 12px;
            padding: 16px 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.85rem !important;
            color: #a0a0c0 !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
            color: #e0e0ff !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricDelta"] { font-size: 0.9rem !important; }

        /* ── Achievement tiles ── */
        .achievement-gained {
            background: linear-gradient(135deg, #1a472a, #2d6a3f);
            border: 2px solid #4caf50;
            border-radius: 10px;
            padding: 14px 18px;
            margin: 6px 0;
            color: #e8f5e9;
            font-weight: 600;
        }
        .achievement-locked {
            background: linear-gradient(135deg, #2a1a1a, #3d2a2a);
            border: 2px solid #5a3a3a;
            border-radius: 10px;
            padding: 14px 18px;
            margin: 6px 0;
            color: #a09090;
        }
        .achievement-hint {
            font-size: 0.78rem;
            color: #707090;
            margin-top: 4px;
        }

        /* ── Alerts ── */
        .bottleneck-box {
            background: linear-gradient(135deg, #3d1a00, #5a2a00);
            border-left: 5px solid #ff6b35;
            border-radius: 8px;
            padding: 14px 18px;
            color: #ffccaa;
            font-size: 1rem;
            font-weight: 600;
        }
        .good-deal-box {
            background: linear-gradient(135deg, #1a3d1a, #2a5a2a);
            border-left: 5px solid #4caf50;
            border-radius: 8px;
            padding: 14px 18px;
            color: #ccffcc;
            font-size: 1rem;
        }
        .bad-deal-box {
            background: linear-gradient(135deg, #3d1a1a, #5a2a2a);
            border-left: 5px solid #ff4444;
            border-radius: 8px;
            padding: 14px 18px;
            color: #ffcccc;
            font-size: 1rem;
        }
        .roi-edit-box {
            background: linear-gradient(135deg, #1a1a3d, #2a2a5a);
            border: 1px solid #5a5aaa;
            border-radius: 8px;
            padding: 10px 14px;
            color: #ccccff;
            font-size: 0.85rem;
            margin-bottom: 6px;
        }

        /* ── Timer ── */
        .timer-box {
            background: linear-gradient(135deg, #003366, #004488);
            border: 2px solid #0088ff;
            border-radius: 10px;
            padding: 16px 20px;
            text-align: center;
            color: #aaddff;
            font-size: 1.1rem;
        }

        /* ── Market price display ── */
        .price-hero {
            background: linear-gradient(135deg, #1a2a1a, #2a3d2a);
            border: 2px solid #4caf50;
            border-radius: 14px;
            padding: 24px;
            text-align: center;
            color: #e8f5e9;
        }
        .price-hero .label {
            font-size: 0.9rem;
            color: #a0c0a0;
            margin-bottom: 6px;
        }
        .price-hero .value {
            font-size: 2.8rem;
            font-weight: 800;
            color: #88ff88;
        }
        .price-hero .sub {
            font-size: 0.85rem;
            color: #80a080;
            margin-top: 6px;
        }

        button[data-baseweb="tab"] { font-size: 1rem !important; }

        @media (max-width: 768px) {
            [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
            .price-hero .value { font-size: 2rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()

# ============================================================
# SECTION 7: SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## 🏦 Empire Settings")
    st.markdown("---")

    # ── Income Rates ─────────────────────────────────────────
    with st.expander("💸 Hourly Income Rates", expanded=False):
        st.caption("Used in Night Strategy & Roadmap only.")
        passive_h = st.number_input(
            "Passive Income ($/h)", value=8_480_000, min_value=0, step=10_000,
        )
        active_h = st.number_input(
            "Clicking Income ($/h)", value=46_138_788, min_value=0, step=10_000,
        )

    # ── Warehouse ─────────────────────────────────────────────
    with st.expander("📦 Warehouse Inventory", expanded=True):
        st.caption("Subtracted automatically from Shopping List.")
        warehouse: dict[str, int] = {
            "workers":  int(st.number_input("👷 Workers",        value=0, min_value=0, step=1)),
            "metal":    int(st.number_input("⚙️ Metal (t)",      value=0, min_value=0, step=100)),
            "wood":     int(st.number_input("🪵 Wood (m³)",      value=0, min_value=0, step=100)),
            "concrete": int(st.number_input("🧱 Concrete (m³)", value=0, min_value=0, step=10)),
        }

    # ── Editable Building ROI ─────────────────────────────────
    # Each building's cost and revenue is stored in session_state["buildings"]
    # so any edit here immediately flows into all calculator logic below.
    with st.expander("✏️ Edit Building ROI", expanded=False):
        st.caption(
            "Override in-game cost & revenue values. "
            "Changes apply instantly to all tabs."
        )

        buildings_state = st.session_state["buildings"]
        _edit_changed   = False

        for bname in BUILDING_KEYS:
            st.markdown(f"**{bname}**")
            orig_cost = _BUILDING_DEFAULTS[bname]["cost"]
            orig_rev  = _BUILDING_DEFAULTS[bname]["revenue"]

            new_cost = st.number_input(
                f"Cost ($) — {bname}",
                value=float(buildings_state[bname]["cost"]),
                min_value=1.0,
                step=1_000.0,
                key=f"edit_cost_{bname}",
                label_visibility="collapsed",
            )
            new_rev = st.number_input(
                f"Revenue ($) — {bname}",
                value=float(buildings_state[bname]["revenue"]),
                min_value=1.0,
                step=1_000.0,
                key=f"edit_rev_{bname}",
                label_visibility="collapsed",
            )

            # Detect changes and persist to session state
            if new_cost != buildings_state[bname]["cost"]:
                buildings_state[bname]["cost"] = new_cost
                _edit_changed = True
            if new_rev != buildings_state[bname]["revenue"]:
                buildings_state[bname]["revenue"] = new_rev
                _edit_changed = True

            # Show diff vs default
            cost_diff = new_cost - orig_cost
            rev_diff  = new_rev  - orig_rev
            diff_sign = lambda d: f"+${d:,.0f}" if d >= 0 else f"-${abs(d):,.0f}"
            st.markdown(
                f'<div class="roi-edit-box">'
                f"💵 Cost: <strong>${new_cost:,.0f}</strong> "
                f"({diff_sign(cost_diff)} vs default)&nbsp;&nbsp;"
                f"📈 Rev: <strong>${new_rev:,.0f}</strong> "
                f"({diff_sign(rev_diff)} vs default)"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown("---")

        if _edit_changed:
            st.session_state["roi_edits_done"] = (
                st.session_state.get("roi_edits_done", 0) + 1
            )

        if st.button("↩️ Reset All to Defaults", type="secondary",
                     use_container_width=True):
            for bname in BUILDING_KEYS:
                st.session_state["buildings"][bname]["cost"]    = \
                    _BUILDING_DEFAULTS[bname]["cost"]
                st.session_state["buildings"][bname]["revenue"] = \
                    _BUILDING_DEFAULTS[bname]["revenue"]
            st.rerun()

    # ── Financial Goal ────────────────────────────────────────
    st.markdown("---")
    target_goal = st.number_input(
        "🎯 Financial Goal ($)",
        value=1_000_000_000,
        min_value=0,
        step=100_000_000,
    )

    st.markdown("---")
    st.caption("SimLife Empire Manager v2.2")
    st.caption(f"pandas {pd.__version__}")
    st.caption(datetime.now().strftime("%Y-%m-%d %H:%M"))

# ============================================================
# SECTION 8: PAGE HEADER
# ============================================================

st.markdown("# 🏦 SimLife Empire Manager")
st.markdown(
    "*Enter your current cash balance — "
    "the calculator shows exactly what you can build right now.*"
)
st.markdown("---")

# ============================================================
# SECTION 9: TABS
# ============================================================

tab_calc, tab_market, tab_night, tab_roadmap, tab_achieve = st.tabs([
    "🧮 Calculator",
    "⚖️ Market Analyzer",
    "🌙 Night Strategy",
    "📊 Roadmap & History",
    "🏆 Achievements",
])

# ──────────────────────────────────────────────────────────────
# TAB 1 — CALCULATOR
# ──────────────────────────────────────────────────────────────
with tab_calc:
    st.subheader("🧮 Build Planner")
    st.caption(
        "Formula: **floor(Current Balance ÷ Building Cost)** — "
        "uses your live ROI values from the sidebar."
    )

    live_buildings = get_buildings()

    inp_col1, inp_col2 = st.columns([2, 1])

    with inp_col1:
        selected_b = st.selectbox("🏗️ Select Building Type", BUILDING_KEYS)
        cash = st.number_input(
            "💵 Current Balance ($)",
            value=1_000_000,
            min_value=0,
            step=100_000,
            help="Your actual in-game cash right now.",
        )
        st.session_state["cash"] = cash

    building = live_buildings[selected_b]

    with inp_col2:
        st.markdown("&nbsp;")
        roi_now = calculate_roi(building["cost"], building["revenue"])

        # Flag if values were edited from defaults
        is_custom = (
            building["cost"]    != _BUILDING_DEFAULTS[selected_b]["cost"] or
            building["revenue"] != _BUILDING_DEFAULTS[selected_b]["revenue"]
        )
        custom_tag = " ✏️ *custom*" if is_custom else ""

        st.info(
            f"**{selected_b}**{custom_tag}\n\n"
            f"💵 Cost: **${building['cost']:,.0f}**\n\n"
            f"📈 Revenue: **${building['revenue']:,.0f}**\n\n"
            f"📊 ROI: **{roi_now:.1f}%**\n\n"
            f"⏰ Build time: **{building['time_h']}h**"
        )

    # ── Core Calculation ───────────────────────────────────────
    # max_units  = floor(cash / building_cost)   ← strict, no projections
    # total_cost = max_units × building_cost     ← exact spend
    # cash_left  = cash − total_cost             ← always >= 0 (floor guarantees it)
    max_units    = calculate_max_units(cash, building["cost"])
    total_cost   = max_units * building["cost"]
    cash_left    = cash - total_cost
    total_rev    = max_units * building["revenue"]
    total_profit = total_rev - total_cost
    roi_pct      = calculate_roi(building["cost"], building["revenue"])

    # ── Metrics ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📈 Build Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏗️ Units to Build",  f"{max_units:,}")
    m2.metric(
        "💰 Total Cost",
        f"${total_cost:,.0f}",
        delta=f"${cash_left:,.0f} left in wallet",
    )
    m3.metric(
        "📈 ROI per Unit",
        f"{roi_pct:.1f}%",
        delta=f"${building['revenue'] - building['cost']:,.2f} profit/unit",
    )
    m4.metric(
        "🎯 Total Profit",
        f"${total_profit:,.0f}",
        delta=f"Revenue ${total_rev:,.0f}",
    )

    # ── Calculation Breakdown ──────────────────────────────────
    with st.expander("🔍 Calculation Breakdown", expanded=False):
        st.markdown(
            f"| Step | Formula | Value |\n"
            f"|---|---|---|\n"
            f"| Current Balance | — | **${cash:,.0f}** |\n"
            f"| Cost per Unit | — | **${building['cost']:,.0f}** |\n"
            f"| Max Units | floor({cash:,.0f} ÷ {building['cost']:,.0f}) "
            f"| **{max_units:,}** |\n"
            f"| Total Cost | {max_units:,} × ${building['cost']:,.0f} "
            f"| **${total_cost:,.0f}** |\n"
            f"| Cash Remaining | ${cash:,.0f} − ${total_cost:,.0f} "
            f"| **${cash_left:,.0f}** |\n"
            f"| ROI | ({building['revenue']:,.0f} − {building['cost']:,.0f}) "
            f"÷ {building['cost']:,.0f} × 100 | **{roi_pct:.2f}%** |\n"
        )

    # ── Shopping List ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🛒 Net Shopping List")
    st.caption(
        "Warehouse stock subtracted first. "
        "**'To Buy' is always ≥ 0.** Surplus = you already have extra."
    )

    if max_units == 0:
        shortfall = building["cost"] - cash
        st.warning(
            f"⚠️ Balance **${cash:,.0f}** < Building cost **${building['cost']:,.0f}**. "
            f"You need **${shortfall:,.0f}** more."
        )
    else:
        shopping_df = build_shopping_list(max_units, building, warehouse)
        st.dataframe(
            format_shopping_df(shopping_df),
            use_container_width=True,
            hide_index=True,
        )

        bottleneck = identify_bottleneck(shopping_df)
        if bottleneck:
            st.markdown(
                f'<div class="bottleneck-box">'
                f"⚠️ <strong>Bottleneck:</strong> "
                f"<strong>{bottleneck}</strong> has the largest shortage. "
                f"Prioritise this in the Autoclicker."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.success("✅ Warehouse fully covers all resources — no shopping needed!")

    # ── Save Build ─────────────────────────────────────────────
    st.markdown("---")
    save_col, _ = st.columns([1, 2])
    with save_col:
        if st.button(
            "✅ Start Build & Save to History",
            type="primary",
            use_container_width=True,
        ):
            if max_units > 0:
                finish_dt = datetime.now() + timedelta(hours=building["time_h"])
                st.session_state.history.append({
                    "timestamp":           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "building":            selected_b,
                    "units":               max_units,
                    "cost":                total_cost,
                    "profit":              total_profit,
                    "cash_left":           cash_left,
                    "finish_at":           finish_dt.strftime("%H:%M:%S"),
                    "had_warehouse_stock": warehouse_has_stock(warehouse),
                    "roi_pct":             roi_pct,
                })
                st.markdown(
                    f'<div class="timer-box">'
                    f"⏰ <strong>Build Started!</strong><br>"
                    f"{selected_b} × <strong>{max_units:,} units</strong><br>"
                    f"Completion: <strong>{finish_dt.strftime('%Y-%m-%d %H:%M:%S')}</strong>"
                    f" ({building['time_h']}h)<br>"
                    f"Cash remaining: <strong>${cash_left:,.0f}</strong>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.balloons()
            else:
                st.error("Cannot save a 0-unit build. Increase your balance.")

# ──────────────────────────────────────────────────────────────
# TAB 2 — MARKET ANALYZER
# ──────────────────────────────────────────────────────────────
with tab_market:
    st.subheader("⚖️ Market Analyzer")
    st.caption(
        "Calculate the true unit price of any resource package. "
        "Compare against the reference baseline to spot good or bad deals."
    )

    ma_col1, ma_col2 = st.columns([1, 1])

    with ma_col1:
        st.markdown("#### 🔢 Package Price Calculator")

        resource_choice = st.selectbox(
            "📦 Resource Type",
            list(MARKET_REFERENCE.keys()),
            key="market_resource",
        )
        pkg_qty = st.number_input(
            "📊 Package Amount (units in pack)",
            value=float(MARKET_REFERENCE[resource_choice][0]),
            min_value=0.01,
            step=1.0,
            key="market_qty",
            help="How many resource units are in the package you're considering.",
        )
        pkg_price = st.number_input(
            "💵 Total Package Price ($)",
            value=float(MARKET_REFERENCE[resource_choice][1]),
            min_value=0.0,
            step=100.0,
            key="market_price",
            help="The total cost of the package.",
        )

        calculate_btn = st.button(
            "⚖️ Calculate Unit Price",
            type="primary",
            use_container_width=True,
        )

    # ── Reference data for chosen resource ───────────────────
    ref_qty, ref_pack_price, ref_unit_price = MARKET_REFERENCE[resource_choice]

    with ma_col2:
        st.markdown("#### 📌 Reference Baseline")
        st.markdown(
            f"For **{resource_choice}**, the established reference is:\n\n"
            f"- Pack size: **{ref_qty:,} units**\n"
            f"- Pack price: **${ref_pack_price:,.2f}**\n"
            f"- **Unit price: ${ref_unit_price:,.2f} / unit**"
        )

        # Visual reference metric
        st.metric(
            label=f"📎 Reference: {resource_choice}",
            value=f"${ref_unit_price:,.2f} / unit",
            delta=f"Based on {ref_qty:,} units for ${ref_pack_price:,.2f}",
        )

    # ── Result ────────────────────────────────────────────────
    st.markdown("---")

    # Auto-calculate on every input change (and on button press)
    calc_unit_price = calculate_unit_price(pkg_qty, pkg_price)

    if calculate_btn and calc_unit_price is not None:
        st.session_state["market_calcs_done"] = (
            st.session_state.get("market_calcs_done", 0) + 1
        )

    if calc_unit_price is not None:
        price_diff     = calc_unit_price - ref_unit_price
        price_diff_pct = (price_diff / ref_unit_price * 100) if ref_unit_price > 0 else 0

        # ── Hero price display ────────────────────────────────
        hero_col, verdict_col = st.columns([1, 1])

        with hero_col:
            st.markdown(
                f'<div class="price-hero">'
                f'<div class="label">💰 Calculated Unit Price</div>'
                f'<div class="value">${calc_unit_price:,.2f}</div>'
                f'<div class="sub">per 1 {resource_choice} unit</div>'
                f'<div class="sub">{pkg_qty:,.0f} units × ${calc_unit_price:,.4f} '
                f'= ${pkg_qty * calc_unit_price:,.2f}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )

        with verdict_col:
            st.markdown("#### 🏷️ Deal Verdict")

            diff_label = (
                f"+${price_diff:,.2f} (+{price_diff_pct:.1f}%)"
                if price_diff >= 0
                else f"-${abs(price_diff):,.2f} ({price_diff_pct:.1f}%)"
            )

            if calc_unit_price <= ref_unit_price:
                box_class = "good-deal-box"
                verdict   = "✅ GOOD DEAL — at or below reference price!"
            elif calc_unit_price <= ref_unit_price * 1.20:
                box_class = "good-deal-box"
                verdict   = "🟡 ACCEPTABLE — within 20% of reference."
            else:
                box_class = "bad-deal-box"
                verdict   = "❌ EXPENSIVE — more than 20% above reference!"

            st.markdown(
                f'<div class="{box_class}">'
                f"<strong>{verdict}</strong><br><br>"
                f"Your price: <strong>${calc_unit_price:,.2f}</strong> / unit<br>"
                f"Reference:  <strong>${ref_unit_price:,.2f}</strong> / unit<br>"
                f"Difference: <strong>{diff_label}</strong>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # How many units of this resource does this price buy
            # for the cost of one building (selected in Calculator tab)
            selected_building_cost = live_buildings[selected_b]["cost"]
            affordable_units_of_resource = (
                selected_building_cost / calc_unit_price
                if calc_unit_price > 0 else 0
            )
            st.markdown(
                f"💡 At this price, **one {selected_b.split()[1]} "
                f"(${selected_building_cost:,.0f})** buys "
                f"**{affordable_units_of_resource:,.0f}** {resource_choice} units."
            )

    else:
        st.info("Enter a package amount and price above, then click **Calculate**.")

    # ── Full Reference Table ───────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📋 Full Reference Price Table")
    st.caption("Baseline prices derived from observed in-game market packages.")

    ref_rows = []
    for res_label, (qty, pack_p, unit_p) in MARKET_REFERENCE.items():
        ref_rows.append({
            "Resource":        res_label,
            "Pack Size":       f"{qty:,} units",
            "Pack Price":      f"${pack_p:,.2f}",
            "Unit Price":      unit_p,           # keep numeric for styling
            "Ref ($/unit)":    f"${unit_p:,.2f}",
        })

    ref_df = pd.DataFrame(ref_rows)

    # Highlight the currently selected resource row
    def highlight_selected_row(row) -> list[str]:
        if row["Resource"] == resource_choice:
            return ["background-color: #1a2a3a; border: 1px solid #4a8aff;"] * len(row)
        return [""] * len(row)

    display_ref_df = ref_df[["Resource", "Pack Size", "Pack Price", "Ref ($/unit)"]].copy()
    st.dataframe(
        display_ref_df.style.apply(highlight_selected_row, axis=1),
        use_container_width=True,
        hide_index=True,
    )

# ──────────────────────────────────────────────────────────────
# TAB 3 — NIGHT STRATEGY
# ──────────────────────────────────────────────────────────────
with tab_night:
    st.subheader("🌙 Night Strategy Planner")
    st.caption(
        "Simulation — projects passive income over sleep duration. "
        "Uses live ROI values from sidebar. Does not affect Calculator."
    )

    n1, n2 = st.columns([1, 1])
    with n1:
        sleep_h = st.slider("😴 Sleep Duration (h)", 4, 12, 8)
        night_building = st.selectbox(
            "🏗️ Overnight Building Type",
            BUILDING_KEYS,
            key="night_building",
        )
        include_clicking = st.checkbox(
            "Include clicking income?",
            value=False,
            help="Enable if you plan to click before sleeping.",
        )

    nb           = get_buildings()[night_building]
    night_income = passive_h * sleep_h + (active_h * sleep_h if include_clicking else 0)
    night_funds  = cash + night_income
    night_units  = int(night_funds // nb["cost"])
    night_cost   = night_units * nb["cost"]
    night_profit = night_units * (nb["revenue"] - nb["cost"])
    night_left   = night_funds - night_cost

    with n2:
        sn1, sn2, sn3 = st.columns(3)
        sn1.metric("😴 Sleep",           f"{sleep_h}h")
        sn2.metric("💰 Income Earned",   f"${night_income:,.0f}")
        sn3.metric("🏦 Total Funds",     f"${night_funds:,.0f}")

        sn4, sn5, sn6 = st.columns(3)
        sn4.metric("🏗️ Units Possible", f"{night_units:,}")
        sn5.metric("🧾 Build Cost",      f"${night_cost:,.0f}")
        sn6.metric("📈 Expected Profit", f"${night_profit:,.0f}")

    st.markdown("---")
    wake_time = datetime.now() + timedelta(hours=sleep_h)
    build_end = datetime.now() + timedelta(hours=nb["time_h"])

    for label, value in [
        ("🏗️ Building",        night_building),
        ("📦 Units",            f"{night_units:,}"),
        ("💵 Build Cost",       f"${night_cost:,.0f}"),
        ("💰 Cash After Build", f"${night_left:,.0f}"),
        ("⏰ Build Duration",   f"{nb['time_h']}h"),
        ("🌅 Wakeup Time",      wake_time.strftime("%H:%M")),
        ("🏁 Build Finishes",   build_end.strftime("%H:%M")),
        ("📈 ROI",              f"{calculate_roi(nb['cost'], nb['revenue']):.1f}%"),
    ]:
        lc, vc = st.columns([1, 2])
        lc.markdown(f"**{label}**")
        vc.markdown(value)

    st.markdown("---")
    if nb["time_h"] <= sleep_h:
        st.success(
            f"✅ Build completes before wakeup "
            f"({nb['time_h']}h build < {sleep_h}h sleep)."
        )
    else:
        st.info(
            f"ℹ️ Build finishes {nb['time_h'] - sleep_h}h after wakeup. "
            f"Consider a faster building or earlier start."
        )

# ──────────────────────────────────────────────────────────────
# TAB 4 — ROADMAP & HISTORY
# ──────────────────────────────────────────────────────────────
with tab_roadmap:
    st.subheader("📊 Roadmap & Session History")
    st.markdown("#### 🎯 Path to Financial Goal")

    total_income_rate = passive_h + active_h
    missing_cash      = max(0.0, target_goal - cash)
    hours_to_goal     = (
        missing_cash / total_income_rate
        if total_income_rate > 0 else float("inf")
    )
    progress_pct = min(cash / target_goal, 1.0) if target_goal > 0 else 0.0

    gc1, gc2 = st.columns(2)
    with gc1:
        st.metric("🎯 Target Goal",  f"${target_goal:,.0f}")
        st.metric("💵 Balance",      f"${cash:,.0f}")
        st.metric("📉 Still Needed", f"${missing_cash:,.0f}")
    with gc2:
        st.metric("⚡ Max Income",   f"${total_income_rate:,.0f}/h")
        st.metric(
            "⏱️ Hours to Goal",
            f"{hours_to_goal:.1f}h" if hours_to_goal != float("inf") else "∞",
        )
        eta = (
            datetime.now() + timedelta(hours=hours_to_goal)
            if hours_to_goal != float("inf") else None
        )
        st.metric("📅 ETA", eta.strftime("%Y-%m-%d %H:%M") if eta else "—")

    st.progress(progress_pct, text=f"Progress: {progress_pct * 100:.1f}%")

    st.markdown("---")
    st.markdown("#### 📜 Build History")

    if st.session_state.history:
        hist_df    = pd.DataFrame(st.session_state.history)
        disp_cols  = ["timestamp", "building", "units", "cost",
                      "profit", "cash_left", "roi_pct", "finish_at"]
        display_df = hist_df[disp_cols].copy()
        display_df["cost"]      = display_df["cost"].apply(lambda x: f"${x:,.0f}")
        display_df["profit"]    = display_df["profit"].apply(lambda x: f"${x:,.0f}")
        display_df["cash_left"] = display_df["cash_left"].apply(lambda x: f"${x:,.0f}")
        display_df["roi_pct"]   = display_df["roi_pct"].apply(lambda x: f"{x:.1f}%")
        display_df.columns      = [
            "Timestamp", "Building", "Units", "Cost",
            "Profit", "Cash Left", "ROI", "Finishes At"
        ]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        total_p = sum(h["profit"] for h in st.session_state.history)
        total_u = sum(h["units"]  for h in st.session_state.history)
        total_c = sum(h["cost"]   for h in st.session_state.history)
        st.markdown(
            f"**Totals →** Saves: `{len(st.session_state.history)}` | "
            f"Units: `{total_u:,}` | Spent: `${total_c:,.0f}` | "
            f"Profit: `${total_p:,.0f}`"
        )
        if st.button("🗑️ Clear History", type="secondary"):
            st.session_state.history = []
            st.rerun()
    else:
        st.info("No builds saved yet. Use the Calculator tab to start.")

# ──────────────────────────────────────────────────────────────
# TAB 5 — ACHIEVEMENTS
# ──────────────────────────────────────────────────────────────
with tab_achieve:
    st.subheader("🏆 Empire Achievements")
    st.caption("Milestones unlock automatically based on balance, builds, and usage.")

    achieve_state = {
        "cash":              cash,
        "history":           st.session_state.history,
        "market_calcs_done": st.session_state.get("market_calcs_done", 0),
        "roi_edits_done":    st.session_state.get("roi_edits_done", 0),
    }

    gained_count = 0
    ach_col1, ach_col2 = st.columns(2)

    for idx, (title, condition, hint) in enumerate(ACHIEVEMENT_DEFINITIONS):
        gained        = condition(achieve_state)
        gained_count += int(gained)
        css_class     = "achievement-gained" if gained else "achievement-locked"
        icon          = "🌟" if gained else "🔒"
        html = (
            f'<div class="{css_class}">{icon} <strong>{title}</strong>'
            f'<div class="achievement-hint">{hint}</div></div>'
        )
        (ach_col1 if idx % 2 == 0 else ach_col2).markdown(html, unsafe_allow_html=True)

    st.markdown("---")
    total_count = len(ACHIEVEMENT_DEFINITIONS)
    st.progress(
        gained_count / total_count if total_count > 0 else 0,
        text=f"Unlocked: {gained_count} / {total_count} "
             f"({gained_count / total_count * 100:.0f}%)",
    )

# ============================================================
# SECTION 10: GLOBAL FOOTER
# ============================================================

st.markdown("---")
f1, f2 = st.columns([2, 1])

with f1:
    if st.session_state.history:
        last = st.session_state.history[-1]
        st.markdown(
            f'<div class="timer-box">'
            f'⏰ <strong>Last Build:</strong> '
            f'{last["building"]} × {last["units"]:,} units<br>'
            f'🏁 <strong>Estimated Completion:</strong> {last["finish_at"]}'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No active builds. Start one in the Calculator tab.")

with f2:
    st.caption("SimLife Empire Manager v2.2")
    st.caption(f"pandas {pd.__version__} | streamlit {st.__version__}")
    st.caption(f"© {datetime.now().year}")
