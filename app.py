"""
SimLife Empire Manager v2.1
Simplified: cash-only calculation, warehouse subtraction, no income projections
in the main calculator. Night Strategy tab retains passive income simulation.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# SECTION 1: PAGE CONFIGURATION & CONSTANTS
# ============================================================

st.set_page_config(
    page_title="SimLife Empire Manager",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Building Data Constants ---
BUILDINGS: dict[str, dict] = {
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

RESOURCE_KEYS   = ["workers", "metal", "wood", "concrete"]
RESOURCE_LABELS = ["👷 Workers", "⚙️ Metal (t)", "🪵 Wood (m³)", "🧱 Concrete (m³)"]

# Achievements updated: removed click_h and zero_out references
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
]

# ============================================================
# SECTION 2: PANDAS VERSION COMPATIBILITY
# ============================================================

def _pandas_version_tuple() -> tuple[int, ...]:
    """Return pandas version as a comparable integer tuple."""
    return tuple(int(x) for x in pd.__version__.split(".")[:3])


def safe_style_map(styler, func, subset=None):
    """
    Shim: routes to .map() on pandas >= 2.1.0, .applymap() on older versions.
    Prevents AttributeError crash caused by the renamed API.
    """
    if _pandas_version_tuple() >= (2, 1, 0):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)  # type: ignore[attr-defined]


# ============================================================
# SECTION 3: SESSION STATE
# ============================================================

def init_session_state() -> None:
    """Initialise all session keys with safe defaults on first run."""
    defaults: dict = {
        "history": [],
        "cash":    1_000_000,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()

# ============================================================
# SECTION 4: CALCULATION ENGINE
# ============================================================

def clamp_to_zero(value: float) -> float:
    """
    Warehouse safety clamp — guarantees non-negative purchase quantities.

    Called whenever we subtract warehouse stock from total required.
    A negative result means the warehouse already covers that resource
    in full; the correct purchase amount is 0, never a negative number.

    Examples
    --------
    clamp_to_zero(500)   →  500.0   stock is insufficient, buy 500
    clamp_to_zero(0)     →    0.0   stock exactly meets requirement
    clamp_to_zero(-200)  →    0.0   surplus of 200, buy nothing
    """
    return max(0.0, value)


def calculate_max_units(cash: float, cost_per_unit: float) -> int:
    """
    Core formula: floor(cash / cost_per_unit).

    Uses only the current cash balance — no income projections.
    This gives the player an honest "right now" answer.

    Parameters
    ----------
    cash         : current spendable balance in dollars
    cost_per_unit: cost of one building

    Returns
    -------
    int >= 0
    """
    if cost_per_unit <= 0:
        return 0
    return int(cash // cost_per_unit)


def net_resource_needed(units: int, per_unit: int, in_stock: int) -> int:
    """
    How many units of a resource must be purchased after warehouse deduction?

    total_required = units × per_unit
    to_buy         = max(0, total_required − in_stock)

    Always returns a non-negative integer.
    """
    total_required = units * per_unit
    return int(clamp_to_zero(total_required - in_stock))


def build_shopping_list(
    units: int,
    building: dict,
    warehouse: dict[str, int],
) -> pd.DataFrame:
    """
    Generate the net shopping list for a planned build.

    For each resource:
    - Total Needed  = units × per_unit
    - In Warehouse  = current stock (user input)
    - To Buy        = max(0, Total Needed − In Warehouse)   ← never negative
    - Surplus       = max(0, In Warehouse − Total Needed)   ← leftover stock
    - Status        = ✅ OK if To Buy == 0 else 🛒 Buy

    Returns
    -------
    pd.DataFrame with columns:
        Resource | Total Needed | In Warehouse | Surplus | To Buy | Status
    """
    rows = []
    for key, label in zip(RESOURCE_KEYS, RESOURCE_LABELS):
        total_needed = units * building[key]
        in_stock     = warehouse[key]
        to_buy       = net_resource_needed(units, building[key], in_stock)
        surplus      = int(clamp_to_zero(in_stock - total_needed))
        status       = "✅ OK" if to_buy == 0 else "🛒 Buy"

        rows.append({
            "Resource":     label,
            "Total Needed": total_needed,
            "In Warehouse": in_stock,
            "Surplus":      surplus,
            "To Buy":       to_buy,
            "Status":       status,
        })

    return pd.DataFrame(rows)


def identify_bottleneck(df: pd.DataFrame) -> str | None:
    """
    Find the resource with the highest outstanding purchase requirement.
    Returns None when warehouse covers everything.
    """
    needs_buying = df[df["To Buy"] > 0]
    if needs_buying.empty:
        return None
    return str(
        needs_buying.sort_values("To Buy", ascending=False).iloc[0]["Resource"]
    )


def calculate_roi(cost: float, revenue: float) -> float:
    """Return-on-Investment as a percentage: (revenue - cost) / cost × 100."""
    if cost <= 0:
        return 0.0
    return ((revenue - cost) / cost) * 100


def warehouse_has_stock(warehouse: dict[str, int]) -> bool:
    """True if any warehouse resource has stock > 0."""
    return any(v > 0 for v in warehouse.values())


# ============================================================
# SECTION 5: STYLING HELPERS
# ============================================================

def style_to_buy_cell(val: int) -> str:
    """
    Per-cell CSS for the 'To Buy' column in the shopping list table.

    Colour scale:
      0          → green  (warehouse covers it, no purchase needed)
      1–10,000   → yellow (moderate buy)
      > 10,000   → orange (large / expensive buy — likely the bottleneck)
    """
    if val == 0:
        return "color: #4caf50; font-weight: bold;"
    if val > 10_000:
        return "color: #ff6b35; font-weight: bold;"
    return "color: #ffcc00; font-weight: bold;"


def format_shopping_df(df: pd.DataFrame):
    """
    Apply formatting and colour styling to the shopping list DataFrame.

    - Numeric columns receive thousand-separator formatting.
    - Surplus is displayed as '+N' or '—' to clearly signal leftover stock.
    - 'To Buy' cells are colour-coded via safe_style_map()
      (compatible with pandas 2.0 and 2.2+).
    """
    display_df = df.copy()

    display_df["Total Needed"] = display_df["Total Needed"].apply(
        lambda x: f"{x:,}"
    )
    display_df["In Warehouse"] = display_df["In Warehouse"].apply(
        lambda x: f"{x:,}"
    )
    display_df["Surplus"] = display_df["Surplus"].apply(
        lambda x: f"+{x:,}" if x > 0 else "—"
    )

    # 'To Buy' stays numeric so the styler function receives an int
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

        /* ── Bottleneck alert ── */
        .bottleneck-box {
            background: linear-gradient(135deg, #3d1a00, #5a2a00);
            border-left: 5px solid #ff6b35;
            border-radius: 8px;
            padding: 14px 18px;
            color: #ffccaa;
            font-size: 1rem;
            font-weight: 600;
        }

        /* ── Timer / info box ── */
        .timer-box {
            background: linear-gradient(135deg, #003366, #004488);
            border: 2px solid #0088ff;
            border-radius: 10px;
            padding: 16px 20px;
            text-align: center;
            color: #aaddff;
            font-size: 1.1rem;
        }

        /* ── Summary box (night strategy) ── */
        .summary-box {
            background: linear-gradient(135deg, #1a1a3e, #2a2a5a);
            border: 1px solid #5a5a9a;
            border-radius: 10px;
            padding: 16px 20px;
            color: #d0d0ff;
        }

        button[data-baseweb="tab"] { font-size: 1rem !important; }

        /* ── Mobile ── */
        @media (max-width: 768px) {
            [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
            .stSlider > div { padding: 0 8px; }
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

    # Income rates are still needed for Night Strategy and Roadmap tabs
    with st.expander("💸 Hourly Income Rates", expanded=True):
        st.caption("Used in Night Strategy & Roadmap tabs only.")
        passive_h = st.number_input(
            "Passive Income ($/h)",
            value=8_480_000,
            min_value=0,
            step=10_000,
            help="Auto-generated income every hour (not used in Calculator).",
        )
        active_h = st.number_input(
            "Clicking Income ($/h)",
            value=46_138_788,
            min_value=0,
            step=10_000,
            help="Income per hour of active clicking (Night Strategy only).",
        )

    with st.expander("📦 Warehouse Inventory", expanded=True):
        st.caption("Stock is subtracted from your Shopping List automatically.")
        warehouse: dict[str, int] = {
            "workers":  int(st.number_input(
                "👷 Workers", value=0, min_value=0, step=1
            )),
            "metal":    int(st.number_input(
                "⚙️ Metal (t)", value=0, min_value=0, step=100
            )),
            "wood":     int(st.number_input(
                "🪵 Wood (m³)", value=0, min_value=0, step=100
            )),
            "concrete": int(st.number_input(
                "🧱 Concrete (m³)", value=0, min_value=0, step=10
            )),
        }

    st.markdown("---")
    target_goal = st.number_input(
        "🎯 Financial Goal ($)",
        value=1_000_000_000,
        min_value=0,
        step=100_000_000,
        help="Target balance for the Roadmap tab.",
    )

    st.markdown("---")
    st.caption("SimLife Empire Manager v2.1")
    st.caption(f"pandas {pd.__version__}")
    st.caption(datetime.now().strftime("%Y-%m-%d %H:%M"))

# ============================================================
# SECTION 8: PAGE HEADER
# ============================================================

st.markdown("# 🏦 SimLife Empire Manager")
st.markdown(
    "*Enter your current cash balance below — "
    "the calculator shows exactly what you can build right now.*"
)
st.markdown("---")

# ============================================================
# SECTION 9: TABS
# ============================================================

tab_calc, tab_night, tab_roadmap, tab_achieve = st.tabs([
    "🧮 Calculator",
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
        "Calculation: **floor(Current Balance ÷ Building Cost)** — "
        "no income projections, no hidden assumptions."
    )

    # ── Inputs ────────────────────────────────────────────────
    inp_col1, inp_col2 = st.columns([2, 1])

    with inp_col1:
        selected_b = st.selectbox(
            "🏗️ Select Building Type",
            list(BUILDINGS.keys()),
        )
        cash = st.number_input(
            "💵 Current Balance ($)",
            value=1_000_000,
            min_value=0,
            step=100_000,
            help="Your real current in-game cash balance right now.",
        )
        # Sync to session state for Achievements and Roadmap
        st.session_state["cash"] = cash

    with inp_col2:
        building = BUILDINGS[selected_b]
        st.markdown("&nbsp;")
        st.info(
            f"**{selected_b}**\n\n"
            f"💵 Cost: **${building['cost']:,}**\n\n"
            f"📈 Revenue: **${building['revenue']:,.0f}**\n\n"
            f"⏰ Build time: **{building['time_h']}h**",
        )

    # ── Core Calculation ───────────────────────────────────────
    #
    #   max_units  = floor(cash / building_cost)
    #   total_cost = max_units × building_cost        ← exactly what you spend
    #   cash_left  = cash - total_cost                ← honest remainder
    #
    max_units   = calculate_max_units(cash, building["cost"])
    total_cost  = max_units * building["cost"]        # true spend, not a projection
    cash_left   = cash - total_cost                   # always >= 0 by floor division
    total_rev   = max_units * building["revenue"]
    total_profit= total_rev - total_cost
    roi_pct     = calculate_roi(building["cost"], building["revenue"])

    # ── Key Metrics ────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📈 Build Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "🏗️ Units to Build",
        f"{max_units:,}",
    )
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

    # ── Quick Sanity Check ─────────────────────────────────────
    # Confirms to the user that our arithmetic is correct.
    with st.expander("🔍 Calculation Breakdown", expanded=False):
        st.markdown(
            f"| Step | Value |\n"
            f"|---|---|\n"
            f"| Current Balance | **${cash:,.0f}** |\n"
            f"| Cost per Unit | **${building['cost']:,}** |\n"
            f"| Units = floor({cash:,.0f} ÷ {building['cost']:,}) | "
            f"**{max_units:,}** |\n"
            f"| Total Cost = {max_units:,} × ${building['cost']:,} | "
            f"**${total_cost:,.0f}** |\n"
            f"| Cash Remaining = ${cash:,.0f} − ${total_cost:,.0f} | "
            f"**${cash_left:,.0f}** |\n"
        )

    # ── Shopping List ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🛒 Net Shopping List")
    st.caption(
        "Warehouse stock is subtracted first. "
        "**'To Buy' is always ≥ 0.** "
        "A '+' Surplus means you already have more than needed."
    )

    if max_units == 0:
        st.warning(
            f"⚠️ Your balance of **${cash:,.0f}** is below the building cost "
            f"of **${building['cost']:,}**. "
            f"You need **${building['cost'] - cash:,.0f}** more."
        )
    else:
        shopping_df = build_shopping_list(max_units, building, warehouse)
        styled_df   = format_shopping_df(shopping_df)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # ── Bottleneck Alert ───────────────────────────────────
        bottleneck = identify_bottleneck(shopping_df)
        if bottleneck:
            st.markdown(
                f'<div class="bottleneck-box">'
                f"⚠️ <strong>Bottleneck:</strong> "
                f"<strong>{bottleneck}</strong> has the largest shortage. "
                f"Prioritise purchasing this in the Autoclicker."
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.success(
                "✅ Your warehouse fully covers all resources for this build! "
                "No shopping needed."
            )

    # ── Save Build ─────────────────────────────────────────────
    st.markdown("---")
    save_col, _ = st.columns([1, 2])
    with save_col:
        if st.button("✅ Start Build & Save to History", type="primary",
                     use_container_width=True):
            if max_units > 0:
                finish_dt = datetime.now() + timedelta(hours=building["time_h"])
                record = {
                    "timestamp":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "building":           selected_b,
                    "units":              max_units,
                    "cost":               total_cost,
                    "profit":             total_profit,
                    "cash_left":          cash_left,
                    "finish_at":          finish_dt.strftime("%H:%M:%S"),
                    "had_warehouse_stock": warehouse_has_stock(warehouse),
                }
                st.session_state.history.append(record)

                st.markdown(
                    f'<div class="timer-box">'
                    f"⏰ <strong>Build Started!</strong><br>"
                    f"Building: <strong>{selected_b}</strong> "
                    f"× <strong>{max_units:,} units</strong><br>"
                    f"Estimated completion: "
                    f"<strong>{finish_dt.strftime('%Y-%m-%d %H:%M:%S')}</strong>"
                    f" ({building['time_h']}h)<br>"
                    f"Cash remaining after build: "
                    f"<strong>${cash_left:,.0f}</strong>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.balloons()
            else:
                st.error(
                    "Cannot save a 0-unit build. "
                    "Increase your balance in the input above."
                )

# ──────────────────────────────────────────────────────────────
# TAB 2 — NIGHT STRATEGY
# ──────────────────────────────────────────────────────────────
with tab_night:
    st.subheader("🌙 Night Strategy Planner")
    st.caption(
        "Simulation only — uses passive income rate to project what "
        "you can build after sleeping. Does not affect the Calculator tab."
    )

    n1, n2 = st.columns([1, 1])

    with n1:
        sleep_h = st.slider("😴 Sleep Duration (h)", 4, 12, 8)
        night_building = st.selectbox(
            "🏗️ Overnight Building Type",
            list(BUILDINGS.keys()),
            key="night_building",
        )
        include_clicking = st.checkbox(
            "Include clicking income in projection?",
            value=False,
            help="Enable if you plan to actively click before sleeping.",
        )

    nb = BUILDINGS[night_building]

    # Night income: passive always + optional clicking
    night_income = passive_h * sleep_h
    if include_clicking:
        night_income += active_h * sleep_h

    # Use current cash as starting point for night projection
    night_total_funds = cash + night_income
    night_units       = int(night_total_funds // nb["cost"])
    night_cost        = night_units * nb["cost"]
    night_profit      = night_units * (nb["revenue"] - nb["cost"])
    night_cash_left   = night_total_funds - night_cost

    with n2:
        sn1, sn2, sn3 = st.columns(3)
        sn1.metric("😴 Sleep",           f"{sleep_h}h")
        sn2.metric("💰 Income Earned",   f"${night_income:,.0f}")
        sn3.metric("🏦 Total Funds",     f"${night_total_funds:,.0f}")

        sn4, sn5, sn6 = st.columns(3)
        sn4.metric("🏗️ Units Possible", f"{night_units:,}")
        sn5.metric("🧾 Build Cost",      f"${night_cost:,.0f}")
        sn6.metric("📈 Expected Profit", f"${night_profit:,.0f}")

    st.markdown("---")
    st.markdown("#### 📋 Overnight Plan")

    wake_time = datetime.now() + timedelta(hours=sleep_h)
    build_end = datetime.now() + timedelta(hours=nb["time_h"])

    plan_rows = [
        ("🏗️ Building",       night_building),
        ("📦 Units",           f"{night_units:,}"),
        ("💵 Total Cost",      f"${night_cost:,.0f}"),
        ("💰 Cash After Build",f"${night_cash_left:,.0f}"),
        ("⏰ Build Duration",  f"{nb['time_h']}h"),
        ("⏰ Wakeup Time",     wake_time.strftime("%H:%M")),
        ("🏁 Build Finishes",  build_end.strftime("%H:%M")),
        ("📈 ROI",             f"{calculate_roi(nb['cost'], nb['revenue']):.1f}%"),
    ]

    for label, value in plan_rows:
        lc, vc = st.columns([1, 2])
        lc.markdown(f"**{label}**")
        vc.markdown(value)

    st.markdown("---")
    if nb["time_h"] <= sleep_h:
        st.success(
            f"✅ Build completes **before** you wake up! "
            f"({nb['time_h']}h build < {sleep_h}h sleep)"
        )
    else:
        overtime = nb["time_h"] - sleep_h
        st.info(
            f"ℹ️ Build will finish **{overtime}h after** you wake up. "
            f"Consider starting the build earlier or choosing a faster building."
        )

# ──────────────────────────────────────────────────────────────
# TAB 3 — ROADMAP & HISTORY
# ──────────────────────────────────────────────────────────────
with tab_roadmap:
    st.subheader("📊 Roadmap & Session History")

    # ── Goal Progress ──────────────────────────────────────────
    st.markdown("#### 🎯 Path to Financial Goal")

    total_income_rate = passive_h + active_h          # max hourly rate
    missing_cash      = max(0.0, target_goal - cash)
    hours_to_goal     = (
        missing_cash / total_income_rate
        if total_income_rate > 0 else float("inf")
    )
    progress_pct = (
        min(cash / target_goal, 1.0) if target_goal > 0 else 0.0
    )

    gc1, gc2 = st.columns(2)
    with gc1:
        st.metric("🎯 Target Goal",   f"${target_goal:,.0f}")
        st.metric("💵 Balance",       f"${cash:,.0f}")
        st.metric("📉 Still Needed",  f"${missing_cash:,.0f}")
    with gc2:
        st.metric("⚡ Max Income",    f"${total_income_rate:,.0f}/h")
        st.metric(
            "⏱️ Hours to Goal",
            f"{hours_to_goal:.1f}h"
            if hours_to_goal != float("inf") else "∞",
        )
        eta = (
            datetime.now() + timedelta(hours=hours_to_goal)
            if hours_to_goal != float("inf") else None
        )
        st.metric(
            "📅 ETA",
            eta.strftime("%Y-%m-%d %H:%M") if eta else "—",
        )

    st.progress(
        progress_pct,
        text=f"Progress to goal: {progress_pct * 100:.1f}%",
    )

    # ── Build History ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📜 Build History")

    if st.session_state.history:
        hist_df = pd.DataFrame(st.session_state.history)

        display_df = hist_df[[
            "timestamp", "building", "units", "cost", "profit", "cash_left", "finish_at"
        ]].copy()
        display_df["cost"]      = display_df["cost"].apply(lambda x: f"${x:,.0f}")
        display_df["profit"]    = display_df["profit"].apply(lambda x: f"${x:,.0f}")
        display_df["cash_left"] = display_df["cash_left"].apply(lambda x: f"${x:,.0f}")
        display_df.columns = [
            "Timestamp", "Building", "Units", "Cost",
            "Profit", "Cash Left After", "Build Finishes At"
        ]

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        total_profit_all = sum(h["profit"] for h in st.session_state.history)
        total_units_all  = sum(h["units"]  for h in st.session_state.history)
        total_cost_all   = sum(h["cost"]   for h in st.session_state.history)

        st.markdown(
            f"**Session Totals →** "
            f"Saves: `{len(st.session_state.history)}` | "
            f"Units: `{total_units_all:,}` | "
            f"Spent: `${total_cost_all:,.0f}` | "
            f"Profit: `${total_profit_all:,.0f}`"
        )

        if st.button("🗑️ Clear History", type="secondary"):
            st.session_state.history = []
            st.rerun()
    else:
        st.info(
            "No builds saved yet. "
            "Go to the Calculator tab, plan a build, and click 'Start Build'."
        )

# ──────────────────────────────────────────────────────────────
# TAB 4 — ACHIEVEMENTS
# ──────────────────────────────────────────────────────────────
with tab_achieve:
    st.subheader("🏆 Empire Achievements")
    st.caption("Milestones unlock automatically based on your balance and build history.")

    achieve_state = {
        "cash":    cash,
        "history": st.session_state.history,
    }

    gained_count = 0
    ach_col1, ach_col2 = st.columns(2)

    for idx, (title, condition, hint) in enumerate(ACHIEVEMENT_DEFINITIONS):
        gained        = condition(achieve_state)
        gained_count += int(gained)
        css_class     = "achievement-gained" if gained else "achievement-locked"
        icon          = "🌟" if gained else "🔒"

        html = (
            f'<div class="{css_class}">'
            f"{icon} <strong>{title}</strong>"
            f'<div class="achievement-hint">{hint}</div>'
            f"</div>"
        )
        (ach_col1 if idx % 2 == 0 else ach_col2).markdown(
            html, unsafe_allow_html=True
        )

    st.markdown("---")
    total_count = len(ACHIEVEMENT_DEFINITIONS)
    st.progress(
        gained_count / total_count if total_count > 0 else 0,
        text=(
            f"Unlocked: {gained_count} / {total_count} "
            f"({gained_count / total_count * 100:.0f}%)"
            if total_count > 0 else "No achievements defined."
        ),
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
    st.caption("SimLife Empire Manager v2.1")
    st.caption(f"pandas {pd.__version__} | streamlit {st.__version__}")
    st.caption(f"© {datetime.now().year}")
