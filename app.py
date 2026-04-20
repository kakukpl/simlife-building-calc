"""
SimLife Empire Manager v2.4
New: Dynamic Market Sheet (st.data_editor), Smart Cost Engine
     (auto-calculated cost from market prices + manual override),
     Cost Breakdown expander, Market Status indicator.
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

# Immutable building defaults — never mutated after startup
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

BUILDING_KEYS   = list(_BUILDING_DEFAULTS.keys())
RESOURCE_KEYS   = ["workers", "metal", "wood", "concrete"]
RESOURCE_LABELS = ["👷 Workers", "⚙️ Metal (t)", "🪵 Wood (m³)", "🧱 Concrete (m³)"]

# Default market reference data used to seed the editable Market Sheet
# Structure: resource_key → (label, default_qty, default_pack_price, ref_unit_price)
_MARKET_DEFAULTS: dict[str, tuple[str, int, float, float]] = {
    "workers":  ("👷 Workers",      5,    111_603.00, 22_320.60),
    "metal":    ("⚙️ Metal (t)",   5023,  22_423.28,      4.46),
    "wood":     ("🪵 Wood (m³)",   2009,  22_421.04,     11.16),
    "concrete": ("🧱 Concrete (m³)", 33,  22_097.39,    669.61),
}

# ============================================================
# ACHIEVEMENT DEFINITIONS
# ============================================================

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
        lambda s: any(h.get("had_warehouse_stock") for h in s["history"]),
        "Save a build while warehouse had stock > 0",
    ),
    (
        "🔁 Serial Builder",
        lambda s: len(s["history"]) >= 5,
        "Save 5 or more builds in one session",
    ),
    (
        "⚖️ Market Analyst",
        lambda s: s.get("market_syncs_done", 0) >= 1,
        "Sync market prices to the calculator at least once",
    ),
    (
        "🧠 Smart Cost Engineer",
        lambda s: s.get("overrides_used", 0) >= 1,
        "Manually override a building cost at least once",
    ),
]
# ============================================================
# SECTION 2: PANDAS COMPATIBILITY SHIM
# ============================================================

def _pandas_version_tuple() -> tuple[int, ...]:
    return tuple(int(x) for x in pd.__version__.split(".")[:3])


def safe_style_map(styler, func, subset=None):
    """Routes to .map() (pandas ≥ 2.1) or .applymap() (older)."""
    if _pandas_version_tuple() >= (2, 1, 0):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)  # type: ignore[attr-defined]


# ============================================================
# SECTION 3: SESSION STATE INITIALISATION
# ============================================================

def _default_market_df() -> pd.DataFrame:
    """
    Build the seed DataFrame for the editable Market Sheet.
    Unit Price is intentionally stored as float so the editor
    can display it and we recalculate it on every sync.
    """
    rows = []
    for key in RESOURCE_KEYS:
        label, qty, pack_price, unit_price = _MARKET_DEFAULTS[key]
        rows.append({
            "Resource":      label,
            "Package Qty":   qty,
            "Package Price": pack_price,
            "Unit Price":    round(pack_price / qty, 4),
        })
    return pd.DataFrame(rows)


def _default_market_prices() -> dict[str, float]:
    """Seed unit prices from hard-coded reference data."""
    return {
        key: _MARKET_DEFAULTS[key][3]   # ref_unit_price
        for key in RESOURCE_KEYS
    }


def init_session_state() -> None:
    """
    Initialise every session key exactly once.

    Key design decisions
    --------------------
    market_sheet_df   : editable DataFrame shown in st.data_editor
    market_prices     : dict[resource_key, unit_price] — source of truth
                        for Smart Cost Engine; only updated on "Sync" click
    cost_overrides    : dict[building_name, float | None]
                        None  → use smart-calculated cost
                        float → use the manually entered override
    buildings         : dict with resource requirements + live revenue
                        (cost is now derived, not stored here for calc)
    """
    if "buildings" not in st.session_state:
        st.session_state["buildings"] = {
            name: dict(data) for name, data in _BUILDING_DEFAULTS.items()
        }

    if "market_sheet_df" not in st.session_state:
        st.session_state["market_sheet_df"] = _default_market_df()

    if "market_prices" not in st.session_state:
        st.session_state["market_prices"] = _default_market_prices()

    if "cost_overrides" not in st.session_state:
        st.session_state["cost_overrides"] = {k: None for k in BUILDING_KEYS}

    scalar_defaults = {
        "history":          [],
        "cash":             1_000_000,
        "market_syncs_done": 0,
        "overrides_used":   0,
    }
    for key, val in scalar_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session_state()


def get_buildings() -> dict[str, dict]:
    return st.session_state["buildings"]


def get_market_prices() -> dict[str, float]:
    return st.session_state["market_prices"]


# ============================================================
# SECTION 4: SMART COST ENGINE
# ============================================================

def calculate_smart_cost(building_name: str, market_prices: dict[str, float]) -> float:
    """
    Derive building cost purely from resource requirements × market unit prices.

    Formula
    -------
    smart_cost = Σ (resource_qty[r] × market_price[r])   for r in resources

    This reflects the real market cost of assembling the building's
    ingredients, independent of any in-game listed price.

    Parameters
    ----------
    building_name : key in st.session_state["buildings"]
    market_prices : dict mapping resource key → current unit price

    Returns
    -------
    float — always > 0 when market prices are positive
    """
    b = st.session_state["buildings"][building_name]
    return sum(b[rk] * market_prices.get(rk, 0.0) for rk in RESOURCE_KEYS)


def get_effective_cost(building_name: str, market_prices: dict[str, float]) -> float:
    """
    Return the price used in all calculations for a given building.

    Priority
    --------
    1. Manual override (if set and > 0)  →  use override
    2. Smart-calculated cost (default)   →  use market-derived cost

    This single function is the ONLY place where effective cost is decided,
    ensuring every part of the app (calculator, sidebar, history) uses
    the same value consistently.
    """
    override = st.session_state["cost_overrides"].get(building_name)
    if override is not None and override > 0:
        return float(override)
    return calculate_smart_cost(building_name, market_prices)


def get_cost_breakdown(building_name: str, market_prices: dict[str, float]) -> list[dict]:
    """
    Per-resource cost breakdown for the Cost Breakdown expander.

    Returns a list of dicts:
        resource, qty, unit_price, subtotal, pct_of_total
    """
    b     = st.session_state["buildings"][building_name]
    total = calculate_smart_cost(building_name, market_prices)
    rows  = []
    for rk, rl in zip(RESOURCE_KEYS, RESOURCE_LABELS):
        qty      = b[rk]
        u_price  = market_prices.get(rk, 0.0)
        subtotal = qty * u_price
        rows.append({
            "Resource":   rl,
            "Qty":        qty,
            "Unit Price": u_price,
            "Subtotal":   subtotal,
            "% of Cost":  (subtotal / total * 100) if total > 0 else 0.0,
        })
    return sorted(rows, key=lambda r: r["Subtotal"], reverse=True)


# ============================================================
# SECTION 5: CORE CALCULATION ENGINE
# ============================================================

def clamp_to_zero(value: float) -> float:
    """
    Warehouse safety clamp — never returns a negative purchase quantity.

    clamp_to_zero(500)   →  500.0   insufficient stock, buy 500
    clamp_to_zero(0)     →    0.0   exactly covered
    clamp_to_zero(-200)  →    0.0   surplus of 200, buy nothing
    """
    return max(0.0, value)


def calculate_max_units(cash: float, cost_per_unit: float) -> int:
    """
    Strict formula: floor(cash / cost_per_unit).
    Uses effective_cost — override if set, smart-cost otherwise.
    """
    if cost_per_unit <= 0:
        return 0
    return int(cash // cost_per_unit)


def net_resource_needed(units: int, per_unit: int, in_stock: int) -> int:
    """to_buy = max(0, units × per_unit − in_stock). Always ≥ 0."""
    return int(clamp_to_zero(units * per_unit - in_stock))


def build_shopping_list(
    units: int,
    building: dict,
    warehouse: dict[str, int],
) -> pd.DataFrame:
    """
    Net shopping list after deducting warehouse stock.
    'To Buy' is ALWAYS ≥ 0 via clamp_to_zero inside net_resource_needed.
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
    needs = df[df["To Buy"] > 0]
    if needs.empty:
        return None
    return str(needs.sort_values("To Buy", ascending=False).iloc[0]["Resource"])


def calculate_roi(cost: float, revenue: float) -> float:
    if cost <= 0:
        return 0.0
    return ((revenue - cost) / cost) * 100


def warehouse_has_stock(warehouse: dict[str, int]) -> bool:
    return any(v > 0 for v in warehouse.values())


# ============================================================
# SECTION 6: STYLING HELPERS
# ============================================================

def style_to_buy_cell(val: int) -> str:
    if val == 0:
        return "color: #4caf50; font-weight: bold;"
    if val > 10_000:
        return "color: #ff6b35; font-weight: bold;"
    return "color: #ffcc00; font-weight: bold;"


def format_shopping_df(df: pd.DataFrame):
    display_df = df.copy()
    display_df["Total Needed"] = display_df["Total Needed"].apply(lambda x: f"{x:,}")
    display_df["In Warehouse"] = display_df["In Warehouse"].apply(lambda x: f"{x:,}")
    display_df["Surplus"]      = display_df["Surplus"].apply(
        lambda x: f"+{x:,}" if x > 0 else "—"
    )
    styler = display_df.style.format({"To Buy": "{:,}"})
    styler = safe_style_map(styler, style_to_buy_cell, subset=["To Buy"])
    return styler


def style_breakdown_pct(val: float) -> str:
    """Colour-code percentage of build cost per resource."""
    if val >= 60:
        return "color: #ff6b35; font-weight: bold;"
    if val >= 30:
        return "color: #ffcc00; font-weight: bold;"
    return "color: #a0c0a0;"


# ============================================================
# SECTION 7: CUSTOM CSS
# ============================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }

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
        .status-green {
            background: linear-gradient(135deg, #0a2a0a, #1a4a1a);
            border: 2px solid #4caf50;
            border-radius: 10px;
            padding: 12px 16px;
            color: #aaffaa;
            font-size: 1rem;
            font-weight: 700;
        }
        .status-red {
            background: linear-gradient(135deg, #2a0a0a, #4a1a1a);
            border: 2px solid #ff4444;
            border-radius: 10px;
            padding: 12px 16px;
            color: #ffaaaa;
            font-size: 1rem;
            font-weight: 700;
        }
        .override-box {
            background: linear-gradient(135deg, #1a1a0a, #2a2a0a);
            border: 1px solid #8a8a2a;
            border-radius: 8px;
            padding: 10px 14px;
            color: #ddddaa;
            font-size: 0.82rem;
            margin: 4px 0 8px 0;
        }
        .timer-box {
            background: linear-gradient(135deg, #003366, #004488);
            border: 2px solid #0088ff;
            border-radius: 10px;
            padding: 16px 20px;
            text-align: center;
            color: #aaddff;
            font-size: 1.1rem;
        }
        .cost-source-tag {
            display: inline-block;
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 0.75rem;
            font-weight: 700;
            margin-left: 6px;
        }
        .tag-smart  { background: #1a4a1a; color: #88ff88; border: 1px solid #4caf50; }
        .tag-manual { background: #3a2a00; color: #ffcc44; border: 1px solid #aa8800; }

        button[data-baseweb="tab"] { font-size: 1rem !important; }

        @media (max-width: 768px) {
            [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()

# ============================================================
# SECTION 8: SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## 🏦 Empire Settings")
    st.markdown("---")

    # ── Income Rates ─────────────────────────────────────────
    with st.expander("💸 Hourly Income Rates", expanded=False):
        st.caption("Night Strategy & Roadmap tabs only.")
        passive_h = st.number_input(
            "Passive Income ($/h)", value=8_480_000, min_value=0, step=10_000,
        )
        active_h = st.number_input(
            "Clicking Income ($/h)", value=46_138_788, min_value=0, step=10_000,
        )

    # ── Warehouse ─────────────────────────────────────────────
    with st.expander("📦 Warehouse Inventory", expanded=True):
        st.caption("Subtracted automatically from the Shopping List.")
        warehouse: dict[str, int] = {
            "workers":  int(st.number_input("👷 Workers",        value=0, min_value=0, step=1)),
            "metal":    int(st.number_input("⚙️ Metal (t)",      value=0, min_value=0, step=100)),
            "wood":     int(st.number_input("🪵 Wood (m³)",      value=0, min_value=0, step=100)),
            "concrete": int(st.number_input("🧱 Concrete (m³)", value=0, min_value=0, step=10)),
        }

    # ── Smart Cost Engine — Override Panel ────────────────────
    with st.expander("🧠 Smart Cost Engine", expanded=True):
        st.caption(
            "Each building's cost is **auto-calculated** from market prices. "
            "You can override any value manually below."
        )

        live_market = get_market_prices()

        for bname in BUILDING_KEYS:
            smart_cost = calculate_smart_cost(bname, live_market)
            base_cost  = _BUILDING_DEFAULTS[bname]["cost"]
            override   = st.session_state["cost_overrides"].get(bname)

            st.markdown(f"**{bname}**")

            # Show the auto-calculated cost as reference
            diff_pct = ((smart_cost - base_cost) / base_cost * 100) if base_cost > 0 else 0
            diff_icon = "🔴" if diff_pct > 5 else "🟢"
            st.markdown(
                f'<div class="override-box">'
                f"🧮 Smart cost: <strong>${smart_cost:,.0f}</strong> "
                f"{diff_icon} ({diff_pct:+.1f}% vs default ${base_cost:,})"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Override input — default shows smart cost, editable
            override_val = st.number_input(
                f"Override cost — {bname}",
                value=float(override) if override is not None else smart_cost,
                min_value=1.0,
                step=1_000.0,
                key=f"override_{bname}",
                label_visibility="collapsed",
                help="Leave at smart cost to use market prices. Change to override.",
            )

            # Detect if user actually changed it from smart cost
            tol = 0.01
            if abs(override_val - smart_cost) > tol:
                if st.session_state["cost_overrides"][bname] != override_val:
                    st.session_state["cost_overrides"][bname] = override_val
                    st.session_state["overrides_used"] = (
                        st.session_state.get("overrides_used", 0) + 1
                    )
            else:
                # User reset back to smart cost → clear override
                st.session_state["cost_overrides"][bname] = None

            st.markdown("---")

        if st.button("↩️ Clear All Overrides", type="secondary", use_container_width=True):
            st.session_state["cost_overrides"] = {k: None for k in BUILDING_KEYS}
            st.rerun()

    # ── Revenue Editor (kept from v2.2) ───────────────────────
    with st.expander("📈 Edit Revenue Values", expanded=False):
        st.caption("Override in-game revenue per building.")
        for bname in BUILDING_KEYS:
            new_rev = st.number_input(
                f"Revenue — {bname}",
                value=float(st.session_state["buildings"][bname]["revenue"]),
                min_value=1.0,
                step=1_000.0,
                key=f"rev_{bname}",
            )
            st.session_state["buildings"][bname]["revenue"] = new_rev

        if st.button("↩️ Reset Revenue to Defaults", type="secondary",
                     use_container_width=True):
            for bname in BUILDING_KEYS:
                st.session_state["buildings"][bname]["revenue"] = (
                    _BUILDING_DEFAULTS[bname]["revenue"]
                )
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
    st.caption("SimLife Empire Manager v2.4")
    st.caption(f"pandas {pd.__version__}")
    st.caption(datetime.now().strftime("%Y-%m-%d %H:%M"))

# ============================================================
# SECTION 9: PAGE HEADER
# ============================================================

st.markdown("# 🏦 SimLife Empire Manager")
st.markdown(
    "*Smart cost engine active — building costs derived from live market prices.*"
)
st.markdown("---")

# ============================================================
# SECTION 10: TABS
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

    live_buildings = get_buildings()
    live_market    = get_market_prices()

    inp_col1, inp_col2 = st.columns([2, 1])

    with inp_col1:
        selected_b = st.selectbox("🏗️ Select Building Type", BUILDING_KEYS)
        cash = st.number_input(
            "💵 Current Balance ($)",
            value=1_000_000,
            min_value=0,
            step=100_000,
            help="Your actual in-game cash balance right now.",
        )
        st.session_state["cash"] = cash

    building       = live_buildings[selected_b]
    effective_cost = get_effective_cost(selected_b, live_market)
    smart_cost     = calculate_smart_cost(selected_b, live_market)
    base_cost      = _BUILDING_DEFAULTS[selected_b]["cost"]
    is_overridden  = st.session_state["cost_overrides"].get(selected_b) is not None

    with inp_col2:
        st.markdown("&nbsp;")
        source_tag = (
            '<span class="cost-source-tag tag-manual">✏️ Manual Override</span>'
            if is_overridden
            else '<span class="cost-source-tag tag-smart">🧮 Smart Cost</span>'
        )
        roi_now = calculate_roi(effective_cost, building["revenue"])
        st.info(
            f"**{selected_b}**\n\n"
            f"💵 Effective Cost: **${effective_cost:,.0f}**\n\n"
            f"📈 Revenue: **${building['revenue']:,.0f}**\n\n"
            f"📊 ROI: **{roi_now:.1f}%**\n\n"
            f"⏰ Build time: **{building['time_h']}h**"
        )
        st.markdown(source_tag, unsafe_allow_html=True)

    # ── Core Calculation ───────────────────────────────────────
    # max_units  = floor(cash / effective_cost)
    # effective_cost = override ?? smart_cost
    # smart_cost = Σ resource_qty × market_unit_price
    max_units    = calculate_max_units(cash, effective_cost)
    total_cost   = max_units * effective_cost
    cash_left    = cash - total_cost          # always ≥ 0 by floor division
    total_rev    = max_units * building["revenue"]
    total_profit = total_rev - total_cost
    roi_pct      = calculate_roi(effective_cost, building["revenue"])

    # ── Market Status ──────────────────────────────────────────
    # Compare effective cost vs default base cost to signal deal quality
    st.markdown("---")
    status_col, _ = st.columns([2, 1])
    with status_col:
        cost_vs_base_pct = (
            (effective_cost - base_cost) / base_cost * 100
        ) if base_cost > 0 else 0

        if cost_vs_base_pct <= 0:
            st.markdown(
                f'<div class="status-green">'
                f"🟢 Market Status: GOOD DEAL — "
                f"cost is {abs(cost_vs_base_pct):.1f}% BELOW base price "
                f"(${base_cost:,})"
                f"</div>",
                unsafe_allow_html=True,
            )
        elif cost_vs_base_pct <= 10:
            st.markdown(
                f'<div class="status-green">'
                f"🟡 Market Status: ACCEPTABLE — "
                f"cost is {cost_vs_base_pct:.1f}% above base price "
                f"(${base_cost:,})"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="status-red">'
                f"🔴 Market Status: EXPENSIVE — "
                f"cost is {cost_vs_base_pct:.1f}% ABOVE base price "
                f"(${base_cost:,})"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── Key Metrics ────────────────────────────────────────────
    st.markdown("#### 📈 Build Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏗️ Units to Build", f"{max_units:,}")
    m2.metric(
        "💰 Total Cost",
        f"${total_cost:,.0f}",
        delta=f"${cash_left:,.0f} left in wallet",
    )
    m3.metric(
        "📈 ROI per Unit",
        f"{roi_pct:.1f}%",
        delta=f"${building['revenue'] - effective_cost:,.2f} profit/unit",
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
            f"| Smart Cost (market) | Σ qty × unit price | **${smart_cost:,.0f}** |\n"
            f"| Override Active | {'Yes ✏️' if is_overridden else 'No 🧮'} "
            f"| **${effective_cost:,.0f}** |\n"
            f"| Max Units | floor({cash:,.0f} ÷ {effective_cost:,.0f}) "
            f"| **{max_units:,}** |\n"
            f"| Total Cost | {max_units:,} × ${effective_cost:,.0f} "
            f"| **${total_cost:,.0f}** |\n"
            f"| Cash Remaining | ${cash:,.0f} − ${total_cost:,.0f} "
            f"| **${cash_left:,.0f}** |\n"
            f"| ROI | (rev − cost) ÷ cost × 100 | **{roi_pct:.2f}%** |\n"
        )

    # ── Cost Breakdown by Resource ─────────────────────────────
    with st.expander("💡 Cost Breakdown by Resource", expanded=False):
        st.caption(
            "Shows how much each resource contributes to the smart-calculated cost. "
            "Helps identify which resource drives your build expense."
        )
        breakdown = get_cost_breakdown(selected_b, live_market)

        bd_df = pd.DataFrame(breakdown)
        bd_df["Unit Price"] = bd_df["Unit Price"].apply(lambda x: f"${x:,.4f}")
        bd_df["Subtotal"]   = bd_df["Subtotal"].apply(lambda x: f"${x:,.2f}")
        bd_df["% of Cost"]  = bd_df["% of Cost"].apply(lambda x: f"{x:.1f}%")
        bd_df["Qty"]        = bd_df["Qty"].apply(lambda x: f"{x:,}")

        # Colour the percentage column
        raw_pcts = [r["% of Cost"] for r in breakdown]

        def _pct_style(val: str) -> str:
            try:
                v = float(val.replace("%", ""))
            except ValueError:
                return ""
            return style_breakdown_pct(v)

        styled_bd = bd_df.style
        styled_bd = safe_style_map(styled_bd, _pct_style, subset=["% of Cost"])
        st.dataframe(styled_bd, use_container_width=True, hide_index=True)

        # Bar chart of subtotals
        chart_data = pd.DataFrame({
            "Resource": [r["Resource"] for r in breakdown],
            "Cost ($)": [r["Subtotal"] for r in breakdown],
        }).set_index("Resource")
        st.bar_chart(chart_data, use_container_width=True)

    # ── Shopping List ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🛒 Net Shopping List")
    st.caption(
        "Warehouse stock subtracted first. "
        "**'To Buy' is always ≥ 0.** Surplus = already have extra."
    )

    if max_units == 0:
        shortfall = effective_cost - cash
        st.warning(
            f"⚠️ Balance **${cash:,.0f}** < Effective cost **${effective_cost:,.0f}**. "
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
            st.success("✅ Warehouse covers all resources — no shopping needed!")

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
                    "cost_source":         "override" if is_overridden else "smart",
                })
                st.markdown(
                    f'<div class="timer-box">'
                    f"⏰ <strong>Build Started!</strong><br>"
                    f"{selected_b} × <strong>{max_units:,} units</strong><br>"
                    f"Completion: "
                    f"<strong>{finish_dt.strftime('%Y-%m-%d %H:%M:%S')}</strong>"
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
    st.subheader("⚖️ Market Analyzer — Dynamic Market Sheet")
    st.caption(
        "Edit package quantities and prices directly in the table below. "
        "Unit prices are **auto-calculated**. "
        "Click **Sync** to push prices into the Smart Cost Engine."
    )

    # ── Editable Market Sheet ─────────────────────────────────
    st.markdown("#### 📊 Live Market Sheet")

    # Recompute Unit Price column from current sheet values before display
    sheet_df = st.session_state["market_sheet_df"].copy()

    edited_df = st.data_editor(
        sheet_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Resource": st.column_config.TextColumn(
                "Resource",
                disabled=True,
                help="Resource type (read-only)",
            ),
            "Package Qty": st.column_config.NumberColumn(
                "Package Qty",
                min_value=0.01,
                step=1.0,
                format="%g",
                help="Number of resource units in the package",
            ),
            "Package Price": st.column_config.NumberColumn(
                "Package Price ($)",
                min_value=0.0,
                step=100.0,
                format="$%.2f",
                help="Total price you pay for the package",
            ),
            "Unit Price": st.column_config.NumberColumn(
                "Unit Price (auto)",
                disabled=True,
                format="$%.4f",
                help="Calculated automatically: Package Price ÷ Package Qty",
            ),
        },
        key="market_editor",
    )

    # Recalculate Unit Price live from edited rows (auto-column logic)
    edited_df["Unit Price"] = (
        edited_df["Package Price"] / edited_df["Package Qty"].replace(0, float("nan"))
    ).round(4)

    # Persist back so data_editor and session_state stay in sync
    st.session_state["market_sheet_df"] = edited_df

    # ── Sync Button ───────────────────────────────────────────
    sync_col, reset_col = st.columns([1, 1])

    with sync_col:
        if st.button(
            "💾 Sync Prices to Calculator",
            type="primary",
            use_container_width=True,
            help="Push current unit prices into the Smart Cost Engine.",
        ):
            new_prices: dict[str, float] = {}
            for rk, rl in zip(RESOURCE_KEYS, RESOURCE_LABELS):
                label_match = _MARKET_DEFAULTS[rk][0]
                row = edited_df[edited_df["Resource"] == label_match]
                if not row.empty:
                    unit_p = row.iloc[0]["Unit Price"]
                    new_prices[rk] = float(unit_p) if pd.notna(unit_p) else 0.0

            st.session_state["market_prices"] = new_prices
            # Clear overrides so smart cost recalculates with new prices
            st.session_state["cost_overrides"] = {k: None for k in BUILDING_KEYS}
            st.session_state["market_syncs_done"] = (
                st.session_state.get("market_syncs_done", 0) + 1
            )
            st.success(
                "✅ Prices synced! Smart Cost Engine updated. "
                "All overrides cleared."
            )
            st.rerun()

    with reset_col:
        if st.button(
            "↩️ Reset to Reference Prices",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state["market_sheet_df"]  = _default_market_df()
            st.session_state["market_prices"]    = _default_market_prices()
            st.session_state["cost_overrides"]   = {k: None for k in BUILDING_KEYS}
            st.rerun()

    # ── Live Preview: Impact on Building Costs ────────────────
    st.markdown("---")
    st.markdown("#### 🏗️ Live Cost Preview — All Buildings")
    st.caption(
        "Shows what each building would cost at current (un-synced) sheet prices. "
        "Click **Sync** above to apply."
    )

    # Calculate costs from the edited (not yet synced) sheet
    preview_prices: dict[str, float] = {}
    for rk in RESOURCE_KEYS:
        label_match = _MARKET_DEFAULTS[rk][0]
        row = edited_df[edited_df["Resource"] == label_match]
        if not row.empty:
            u = row.iloc[0]["Unit Price"]
            preview_prices[rk] = float(u) if pd.notna(u) else 0.0

    preview_cols = st.columns(len(BUILDING_KEYS))
    for idx, bname in enumerate(BUILDING_KEYS):
        preview_cost = sum(
            _BUILDING_DEFAULTS[bname][rk] * preview_prices.get(rk, 0.0)
            for rk in RESOURCE_KEYS
        )
        synced_cost  = calculate_smart_cost(bname, get_market_prices())
        base_c       = _BUILDING_DEFAULTS[bname]["cost"]
        diff_pct     = (preview_cost - base_c) / base_c * 100 if base_c > 0 else 0
        preview_cols[idx].metric(
            label=bname,
            value=f"${preview_cost:,.0f}",
            delta=f"{diff_pct:+.1f}% vs base ${base_c:,}",
        )

    # ── Reference Comparison Table ────────────────────────────
    st.markdown("---")
    st.markdown("#### 📋 Reference vs Current Prices")
    st.caption("Green = at/below reference. Red = above reference.")

    current_prices = get_market_prices()

    ref_compare_rows = []
    for rk in RESOURCE_KEYS:
        label     = _MARKET_DEFAULTS[rk][0]
        ref_u     = _MARKET_DEFAULTS[rk][3]
        curr_u    = current_prices.get(rk, ref_u)
        sheet_u   = preview_prices.get(rk, ref_u)
        diff_pct  = (curr_u - ref_u) / ref_u * 100 if ref_u > 0 else 0
        ref_compare_rows.append({
            "Resource":        label,
            "Reference $/unit": ref_u,
            "Synced $/unit":    curr_u,
            "Sheet $/unit":     sheet_u,
            "Diff vs Ref":      diff_pct,
        })

    ref_cmp_df = pd.DataFrame(ref_compare_rows)

    def _colour_diff(val: float) -> str:
        if val <= 0:
            return "color: #4caf50; font-weight: bold;"
        if val <= 20:
            return "color: #ffcc00; font-weight: bold;"
        return "color: #ff4444; font-weight: bold;"

    display_cmp = ref_cmp_df.copy()
    display_cmp["Reference $/unit"] = display_cmp["Reference $/unit"].apply(
        lambda x: f"${x:,.4f}"
    )
    display_cmp["Synced $/unit"] = display_cmp["Synced $/unit"].apply(
        lambda x: f"${x:,.4f}"
    )
    display_cmp["Sheet $/unit"] = display_cmp["Sheet $/unit"].apply(
        lambda x: f"${x:,.4f}"
    )
    display_cmp["Diff vs Ref"] = display_cmp["Diff vs Ref"].apply(
        lambda x: f"{x:+.1f}%"
    )

    st.dataframe(display_cmp, use_container_width=True, hide_index=True)

# ──────────────────────────────────────────────────────────────
# TAB 3 — NIGHT STRATEGY
# ──────────────────────────────────────────────────────────────
with tab_night:
    st.subheader("🌙 Night Strategy Planner")
    st.caption("Uses effective building costs (smart or overridden) from the engine.")

    n1, n2 = st.columns([1, 1])
    with n1:
        sleep_h = st.slider("😴 Sleep Duration (h)", 4, 12, 8)
        night_building = st.selectbox(
            "🏗️ Overnight Building Type", BUILDING_KEYS, key="night_building",
        )
        include_clicking = st.checkbox("Include clicking income?", value=False)

    nb_data       = get_buildings()[night_building]
    nb_eff_cost   = get_effective_cost(night_building, get_market_prices())
    night_income  = passive_h * sleep_h + (active_h * sleep_h if include_clicking else 0)
    night_funds   = cash + night_income
    night_units   = int(night_funds // nb_eff_cost)
    night_cost    = night_units * nb_eff_cost
    night_profit  = night_units * (nb_data["revenue"] - nb_eff_cost)
    night_left    = night_funds - night_cost

    with n2:
        sn1, sn2, sn3 = st.columns(3)
        sn1.metric("😴 Sleep",            f"{sleep_h}h")
        sn2.metric("💰 Income Earned",    f"${night_income:,.0f}")
        sn3.metric("🏦 Total Funds",      f"${night_funds:,.0f}")
        sn4, sn5, sn6 = st.columns(3)
        sn4.metric("🏗️ Units Possible",  f"{night_units:,}")
        sn5.metric("🧾 Build Cost",       f"${night_cost:,.0f}")
        sn6.metric("📈 Expected Profit",  f"${night_profit:,.0f}")

    st.markdown("---")
    wake_time = datetime.now() + timedelta(hours=sleep_h)
    build_end = datetime.now() + timedelta(hours=nb_data["time_h"])

    for label, value in [
        ("🏗️ Building",        night_building),
        ("📦 Units",            f"{night_units:,}"),
        ("💵 Effective Cost",   f"${nb_eff_cost:,.0f}/unit"),
        ("💵 Build Cost",       f"${night_cost:,.0f}"),
        ("💰 Cash After Build", f"${night_left:,.0f}"),
        ("⏰ Build Duration",   f"{nb_data['time_h']}h"),
        ("🌅 Wakeup Time",      wake_time.strftime("%H:%M")),
        ("🏁 Build Finishes",   build_end.strftime("%H:%M")),
        ("📈 ROI",              f"{calculate_roi(nb_eff_cost, nb_data['revenue']):.1f}%"),
    ]:
        lc, vc = st.columns([1, 2])
        lc.markdown(f"**{label}**")
        vc.markdown(value)

    st.markdown("---")
    if nb_data["time_h"] <= sleep_h:
        st.success(
            f"✅ Build completes before wakeup "
            f"({nb_data['time_h']}h < {sleep_h}h sleep)."
        )
    else:
        st.info(
            f"ℹ️ Build finishes {nb_data['time_h'] - sleep_h}h after wakeup."
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
        disp_cols  = [
            "timestamp", "building", "units", "cost",
            "profit", "cash_left", "roi_pct", "cost_source", "finish_at",
        ]
        display_df = hist_df[[c for c in disp_cols if c in hist_df.columns]].copy()
        display_df["cost"]      = display_df["cost"].apply(lambda x: f"${x:,.0f}")
        display_df["profit"]    = display_df["profit"].apply(lambda x: f"${x:,.0f}")
        display_df["cash_left"] = display_df["cash_left"].apply(lambda x: f"${x:,.0f}")
        display_df["roi_pct"]   = display_df["roi_pct"].apply(lambda x: f"{x:.1f}%")
        display_df.columns      = [c.replace("_", " ").title() for c in display_df.columns]
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
    st.caption("Milestones unlock automatically.")

    achieve_state = {
        "cash":              cash,
        "history":           st.session_state.history,
        "market_syncs_done": st.session_state.get("market_syncs_done", 0),
        "overrides_used":    st.session_state.get("overrides_used", 0),
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
# SECTION 11: GLOBAL FOOTER
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
    st.caption("SimLife Empire Manager v2.4")
    st.caption(f"pandas {pd.__version__} | streamlit {st.__version__}")
    st.caption(f"© {datetime.now().year}")
