"""
SimLife Empire Manager v2.0
Senior-grade Streamlit BI Dashboard for resource management and ROI optimization.
Author: Senior Python Developer
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

ACHIEVEMENT_DEFINITIONS = [
    ("🥇 First Million",          lambda s: s["cash"] >= 1_000_000),
    ("🏢 Office Tycoon (100+ OB)",lambda s: any(
        h["building"].startswith("🏢") and h["units"] >= 100
        for h in s["history"]
    )),
    ("💰 Half-Billionaire",       lambda s: s["cash"] >= 500_000_000),
    ("🤑 Billionaire",            lambda s: s["cash"] >= 1_000_000_000),
    ("⏰ Workaholic (12h click)", lambda s: s["click_h"] == 12),
    ("📦 Zero-Waste Manager",     lambda s: any(h.get("zero_out") for h in s["history"])),
    ("🌉 Bridge Builder",         lambda s: any(
        h["building"].startswith("🌉") for h in s["history"]
    )),
    ("🏨 Hotel Mogul",            lambda s: any(
        h["building"].startswith("🏨") for h in s["history"]
    )),
]

# ============================================================
# SECTION 2: SESSION STATE INITIALISATION
# ============================================================

def init_session_state() -> None:
    """Bootstrap all session-state keys with safe defaults."""
    defaults = {
        "history":   [],
        "click_h":   1,
        "cash":      1_000_000,
        "zero_out":  False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================
# SECTION 3: CALCULATION ENGINE (Pure Functions)
# ============================================================

def clamp_to_zero(value: float) -> float:
    """
    Warehouse safety clamp.

    Ensures we NEVER suggest buying a negative quantity.
    Negative values arise when in-stock inventory EXCEEDS the total
    required amount – meaning the warehouse already covers that resource
    in full. The correct answer in that case is 0 (nothing to buy).

    Examples
    --------
    >>> clamp_to_zero(500)   # need 500 more  → buy 500
    500
    >>> clamp_to_zero(0)     # exactly covered → buy nothing
    0
    >>> clamp_to_zero(-200)  # surplus of 200  → buy nothing (NOT -200)
    0
    """
    return max(0.0, value)


def net_resource_needed(units: int, per_unit: int, in_stock: int) -> int:
    """
    Calculate how much of a single resource must be purchased.

    Parameters
    ----------
    units    : number of buildings to construct
    per_unit : resource units required per building
    in_stock : current warehouse inventory for this resource

    Returns
    -------
    int – quantity to purchase; always >= 0
    """
    total_required = units * per_unit
    return int(clamp_to_zero(total_required - in_stock))


def calculate_available_funds(
    cash: float,
    passive_h: float,
    active_h: float,
    click_h: int,
) -> float:
    """Total spendable funds including projected income."""
    clicking_income = active_h * click_h
    return cash + passive_h * click_h + clicking_income


def calculate_max_units_by_cash(funds: float, cost_per_unit: float) -> int:
    """How many units can we afford purely based on cash?"""
    if cost_per_unit <= 0:
        return 0
    return int(funds // cost_per_unit)


def calculate_max_units_zero_out(
    funds: float,
    building: dict,
    warehouse: dict[str, int],
) -> int:
    """
    Zero-Out Mode: find the unit count that maximises warehouse consumption
    without exceeding available funds.

    Strategy
    --------
    1. For each resource, determine how many units the warehouse alone covers
       (floor division). If stock is 0 for a resource, that resource imposes
       no additional constraint from the warehouse side.
    2. The binding warehouse constraint is the MINIMUM across all resources
       that have stock > 0 (we want to exhaust the smallest pile first).
    3. Final answer is the lesser of (cash limit, warehouse limit).
    """
    cash_limit = calculate_max_units_by_cash(funds, building["cost"])

    # Warehouse-driven upper bounds per resource
    warehouse_limits = []
    for key in RESOURCE_KEYS:
        stock     = warehouse[key]
        per_unit  = building[key]
        if stock > 0 and per_unit > 0:
            warehouse_limits.append(stock // per_unit)

    if not warehouse_limits:
        return cash_limit  # no stock at all → pure cash limit

    warehouse_limit = min(warehouse_limits)

    # We want to BUILD as many as we can afford, but at least as many
    # as the warehouse demands we clear (otherwise "zero-out" is pointless).
    # We cap at cash_limit to stay solvent.
    return int(min(cash_limit, max(warehouse_limit, cash_limit)))


def build_shopping_list(
    units: int,
    building: dict,
    warehouse: dict[str, int],
) -> pd.DataFrame:
    """
    Produce the net shopping list after deducting warehouse inventory.

    Every 'To Buy' value is guaranteed >= 0 via net_resource_needed().
    """
    rows = []
    for key, label in zip(RESOURCE_KEYS, RESOURCE_LABELS):
        total_needed = units * building[key]
        in_stock     = warehouse[key]
        to_buy       = net_resource_needed(units, building[key], in_stock)
        surplus      = int(clamp_to_zero(in_stock - total_needed))
        status       = "✅ OK" if to_buy == 0 else "🛒 Buy"

        rows.append({
            "Resource":      label,
            "Total Needed":  f"{total_needed:,}",
            "In Warehouse":  f"{in_stock:,}",
            "Surplus":       f"+{surplus:,}" if surplus > 0 else "—",
            "To Buy":        to_buy,
            "Status":        status,
        })

    return pd.DataFrame(rows)


def identify_bottleneck(shopping_df: pd.DataFrame) -> str | None:
    """Return the resource with the highest 'To Buy' demand, or None."""
    needs_buying = shopping_df[shopping_df["To Buy"] > 0]
    if needs_buying.empty:
        return None
    return needs_buying.sort_values("To Buy", ascending=False).iloc[0]["Resource"]


def calculate_roi(cost: float, revenue: float) -> float:
    """Return-on-Investment as a percentage."""
    if cost <= 0:
        return 0.0
    return ((revenue - cost) / cost) * 100


# ============================================================
# SECTION 4: CUSTOM CSS (Mobile-First, High-Contrast)
# ============================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* ── Global ── */
        html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }

        /* ── Metric cards ── */
        [data-testid="stMetric"] {
            background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
            border: 1px solid #4a4a6a;
            border-radius: 12px;
            padding: 16px 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        [data-testid="stMetricLabel"]  { font-size: 0.85rem !important; color: #a0a0c0 !important; }
        [data-testid="stMetricValue"]  { font-size: 1.8rem !important; color: #e0e0ff !important; font-weight: 700 !important; }
        [data-testid="stMetricDelta"]  { font-size: 0.9rem !important; }

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
            font-weight: 400;
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

        /* ── Timer box ── */
        .timer-box {
            background: linear-gradient(135deg, #003366, #004488);
            border: 2px solid #0088ff;
            border-radius: 10px;
            padding: 16px 20px;
            text-align: center;
            color: #aaddff;
            font-size: 1.1rem;
        }

        /* ── Tab font size ── */
        button[data-baseweb="tab"] { font-size: 1rem !important; }

        /* ── Mobile: bump up input sizes ── */
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
# SECTION 5: SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## 🏦 Empire Settings")
    st.markdown("---")

    # ── Income Section ──────────────────────────────────────
    with st.expander("💸 Hourly Income", expanded=True):
        passive_h = st.number_input(
            "Passive Income ($/h)",
            value=8_480_000,
            min_value=0,
            step=10_000,
            help="Income generated automatically every hour.",
        )
        active_h = st.number_input(
            "Clicking Income ($/h)",
            value=46_138_788,
            min_value=0,
            step=10_000,
            help="Additional income generated per hour of active clicking.",
        )

    # ── Warehouse Section ────────────────────────────────────
    with st.expander("📦 Warehouse Inventory", expanded=True):
        warehouse = {
            "workers":  int(st.number_input("👷 Workers",      value=0, min_value=0, step=1)),
            "metal":    int(st.number_input("⚙️ Metal (t)",    value=0, min_value=0, step=100)),
            "wood":     int(st.number_input("🪵 Wood (m³)",    value=0, min_value=0, step=100)),
            "concrete": int(st.number_input("🧱 Concrete (m³)",value=0, min_value=0, step=10)),
        }

    st.markdown("---")

    # ── Financial Goal ───────────────────────────────────────
    target_goal = st.number_input(
        "🎯 Financial Goal ($)",
        value=1_000_000_000,
        min_value=0,
        step=100_000_000,
        help="Target cash balance for Roadmap tab.",
    )

    # ── App Info ─────────────────────────────────────────────
    st.markdown("---")
    st.caption("SimLife Empire Manager v2.0")
    st.caption(f"Session started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================================
# SECTION 6: PAGE HEADER
# ============================================================

st.markdown("# 🏦 SimLife Empire Manager")
st.markdown("*Real-time resource planning & ROI optimization for your business empire.*")
st.markdown("---")

# ============================================================
# SECTION 7: TABS
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

    # ── Input Row ────────────────────────────────────────────
    inp_col1, inp_col2, inp_col3 = st.columns([2, 1, 1])

    with inp_col1:
        selected_b = st.selectbox("🏗️ Select Building Type", list(BUILDINGS.keys()))
        cash = st.number_input(
            "💵 Current Balance ($)",
            value=1_000_000,
            min_value=0,
            step=100_000,
        )
        # Sync to session state for achievements
        st.session_state["cash"] = cash

    with inp_col2:
        click_h = st.slider("⏱️ Active Clicking Hours", 0, 12, 1)
        st.session_state["click_h"] = click_h

    with inp_col3:
        zero_out = st.checkbox(
            "♻️ Zero-Out Warehouse Mode",
            value=False,
            help=(
                "Prioritise consuming existing warehouse inventory. "
                "The calculator will find the unit count that best "
                "exhausts current stock without exceeding your budget."
            ),
        )
        st.session_state["zero_out"] = zero_out

        st.markdown("&nbsp;")  # vertical spacer

        st.info(
            f"**Building time:** {BUILDINGS[selected_b]['time_h']}h per batch",
            icon="⏰",
        )

    building = BUILDINGS[selected_b]

    # ── Core Calculations ─────────────────────────────────────
    available_funds = calculate_available_funds(cash, passive_h, active_h, click_h)

    if zero_out:
        max_units = calculate_max_units_zero_out(available_funds, building, warehouse)
    else:
        max_units = calculate_max_units_by_cash(available_funds, building["cost"])

    total_cost    = max_units * building["cost"]
    total_revenue = max_units * building["revenue"]
    total_profit  = total_revenue - total_cost
    roi_pct       = calculate_roi(building["cost"], building["revenue"])

    # ── Key Metrics ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📈 Build Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "🏗️ Units to Build",
        f"{max_units:,}",
        delta=f"+{max_units} vs. 0",
    )
    m2.metric(
        "💰 Total Cost",
        f"${total_cost:,.0f}",
        delta=f"${available_funds - total_cost:,.0f} remaining",
    )
    m3.metric(
        "📈 ROI per Unit",
        f"{roi_pct:.1f}%",
        delta=f"${building['revenue'] - building['cost']:,.0f} profit/unit",
    )
    m4.metric(
        "🎯 Total Profit",
        f"${total_profit:,.0f}",
        delta=f"Revenue: ${total_revenue:,.0f}",
    )

    # ── Available Funds Breakdown ─────────────────────────────
    with st.expander("💡 Available Funds Breakdown", expanded=False):
        fd1, fd2, fd3 = st.columns(3)
        fd1.metric("Cash on Hand",      f"${cash:,.0f}")
        fd2.metric("Passive Income",    f"${passive_h * click_h:,.0f}",
                   delta=f"${passive_h:,.0f}/h × {click_h}h")
        fd3.metric("Clicking Income",   f"${active_h * click_h:,.0f}",
                   delta=f"${active_h:,.0f}/h × {click_h}h")
        st.markdown(f"**🏦 Total Available Funds: ${available_funds:,.0f}**")

    # ── Shopping List ─────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🛒 Net Shopping List")
    st.caption(
        "Quantities already in your warehouse are subtracted. "
        "**'To Buy' is always ≥ 0** — a surplus means you're already covered."
    )

    if max_units == 0:
        st.warning("⚠️ No units can be built with current funds. Increase balance or reduce building cost.")
    else:
        shopping_df = build_shopping_list(max_units, building, warehouse)

        # Colour-code the To Buy column via styling
        def style_to_buy(val: int) -> str:
            if val == 0:
                return "color: #4caf50; font-weight: bold;"
            if val > 10_000:
                return "color: #ff6b35; font-weight: bold;"
            return "color: #ffcc00; font-weight: bold;"

        styled = (
            shopping_df.style
            .applymap(style_to_buy, subset=["To Buy"])
            .format({"To Buy": "{:,}"})
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # ── Bottleneck Alert ──────────────────────────────────
        bottleneck = identify_bottleneck(shopping_df)
        if bottleneck:
            st.markdown(
                f"""<div class="bottleneck-box">
                ⚠️ <strong>Bottleneck Detected:</strong>
                <strong>{bottleneck}</strong> is your most deficient resource.
                Prioritise purchasing this in the Autoclicker.
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            st.success("✅ Warehouse fully covers all resources for this build!")

    # ── Save Build Button ─────────────────────────────────────
    st.markdown("---")
    if st.button("✅ Start Build & Save to History", type="primary"):
        if max_units > 0:
            finish_dt = datetime.now() + timedelta(hours=building["time_h"])
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "building":  selected_b,
                "units":     max_units,
                "cost":      total_cost,
                "profit":    total_profit,
                "zero_out":  zero_out,
                "finish_at": finish_dt.strftime("%H:%M:%S"),
            }
            st.session_state.history.append(record)

            # ── Countdown Timer display ────────────────────────
            st.markdown(
                f"""<div class="timer-box">
                ⏰ <strong>Build Started!</strong><br>
                Estimated completion: <strong>{finish_dt.strftime("%Y-%m-%d %H:%M:%S")}</strong><br>
                ({building['time_h']}h from now)
                </div>""",
                unsafe_allow_html=True,
            )
            st.balloons()
        else:
            st.error("Cannot save a build with 0 units. Increase available funds.")

# ──────────────────────────────────────────────────────────────
# TAB 2 — NIGHT STRATEGY
# ──────────────────────────────────────────────────────────────
with tab_night:
    st.subheader("🌙 Night Strategy Planner")
    st.markdown(
        "Configure your pre-sleep build so your passive income is fully "
        "invested while you rest."
    )

    n1, n2 = st.columns([1, 2])
    with n1:
        sleep_h = st.slider("😴 Sleep Duration (hours)", 4, 12, 8)
        night_building = st.selectbox(
            "Building for overnight queue",
            list(BUILDINGS.keys()),
            key="night_building",
        )

    nb = BUILDINGS[night_building]
    night_passive_income = passive_h * sleep_h
    night_total_funds    = cash + night_passive_income  # no clicking while asleep
    night_units          = int(night_total_funds // nb["cost"])
    night_cost           = night_units * nb["cost"]
    night_profit         = night_units * (nb["revenue"] - nb["cost"])

    with n2:
        sn1, sn2, sn3 = st.columns(3)
        sn1.metric("💤 Sleep Duration",      f"{sleep_h}h")
        sn2.metric("💰 Passive Earned",      f"${night_passive_income:,.0f}")
        sn3.metric("🏗️ Suggested Units",    f"{night_units:,}")

        sn4, sn5, _ = st.columns(3)
        sn4.metric("🧾 Build Cost",          f"${night_cost:,.0f}")
        sn5.metric("📈 Expected Profit",     f"${night_profit:,.0f}")

    st.markdown("---")
    st.markdown("#### 📋 Night Build Plan")

    wake_time = datetime.now() + timedelta(hours=sleep_h)
    build_end  = datetime.now() + timedelta(hours=nb["time_h"])

    night_info = {
        "Action":        "Start overnight build NOW",
        "Building":      night_building,
        "Units":         f"{night_units:,}",
        "Cost":          f"${night_cost:,.0f}",
        "Wakeup Time":   wake_time.strftime("%H:%M"),
        "Build Finish":  build_end.strftime("%H:%M"),
        "Overnight ROI": f"{calculate_roi(nb['cost'], nb['revenue']):.1f}%",
    }

    for k, v in night_info.items():
        col_k, col_v = st.columns([1, 2])
        col_k.markdown(f"**{k}**")
        col_v.markdown(v)

    if nb["time_h"] <= sleep_h:
        st.success(
            f"✅ Build completes **before** you wake up! "
            f"({nb['time_h']}h build < {sleep_h}h sleep)"
        )
    else:
        overtime = nb["time_h"] - sleep_h
        st.info(
            f"ℹ️ Build finishes **{overtime}h after** you wake up. "
            f"Consider starting it slightly earlier."
        )

# ──────────────────────────────────────────────────────────────
# TAB 3 — ROADMAP & HISTORY
# ──────────────────────────────────────────────────────────────
with tab_roadmap:
    st.subheader("📊 Roadmap & Session History")

    # ── Goal Progress ─────────────────────────────────────────
    st.markdown("#### 🎯 Path to Financial Goal")

    total_income_rate = passive_h + active_h  # per hour (max rate)
    missing_cash      = max(0.0, target_goal - cash)
    hours_to_goal     = missing_cash / total_income_rate if total_income_rate > 0 else float("inf")
    progress_pct      = min(cash / target_goal, 1.0) if target_goal > 0 else 0.0

    goal_col1, goal_col2 = st.columns(2)
    with goal_col1:
        st.metric("🎯 Target Goal",          f"${target_goal:,.0f}")
        st.metric("💵 Current Balance",      f"${cash:,.0f}")
        st.metric("📉 Remaining",            f"${missing_cash:,.0f}")
    with goal_col2:
        st.metric("⚡ Max Income Rate",      f"${total_income_rate:,.0f}/h")
        st.metric("⏱️ Hours to Goal",        f"{hours_to_goal:.1f}h"
                  if hours_to_goal != float("inf") else "∞")
        eta = datetime.now() + timedelta(hours=hours_to_goal) \
              if hours_to_goal != float("inf") else None
        st.metric("📅 ETA",
                  eta.strftime("%Y-%m-%d %H:%M") if eta else "—")

    st.progress(progress_pct, text=f"Progress: {progress_pct * 100:.1f}%")

    # ── Session History ───────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📜 Build History")

    if st.session_state.history:
        hist_df = pd.DataFrame(st.session_state.history)

        # Format for display
        display_df = hist_df.copy()
        display_df["cost"]   = display_df["cost"].apply(lambda x: f"${x:,.0f}")
        display_df["profit"] = display_df["profit"].apply(lambda x: f"${x:,.0f}")
        display_df.columns   = [c.replace("_", " ").title() for c in display_df.columns]

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Summary stats
        total_profit_all = sum(h["profit"] for h in st.session_state.history)
        total_units_all  = sum(h["units"]  for h in st.session_state.history)
        st.markdown(
            f"**Session Totals →** "
            f"Builds: `{len(st.session_state.history)}` | "
            f"Units: `{total_units_all:,}` | "
            f"Cumulative Profit: `${total_profit_all:,.0f}`"
        )

        if st.button("🗑️ Clear History", type="secondary"):
            st.session_state.history = []
            st.rerun()
    else:
        st.info("No builds saved yet. Use the Calculator tab to plan and save your first build.")

# ──────────────────────────────────────────────────────────────
# TAB 4 — ACHIEVEMENTS
# ──────────────────────────────────────────────────────────────
with tab_achieve:
    st.subheader("🏆 Empire Achievements")
    st.markdown("Track your milestones and unlock badges as your empire grows.")

    # Build the state snapshot the achievement lambdas read from
    achieve_state = {
        "cash":    cash,
        "history": st.session_state.history,
        "click_h": click_h,
    }

    gained_count = 0
    total_count  = len(ACHIEVEMENT_DEFINITIONS)

    ach_col1, ach_col2 = st.columns(2)
    for idx, (title, condition) in enumerate(ACHIEVEMENT_DEFINITIONS):
        gained = condition(achieve_state)
        if gained:
            gained_count += 1
        html = (
            f'<div class="achievement-gained">🌟 {title}</div>'
            if gained
            else f'<div class="achievement-locked">🔒 {title}</div>'
        )
        target_col = ach_col1 if idx % 2 == 0 else ach_col2
        target_col.markdown(html, unsafe_allow_html=True)

    st.markdown("---")
    achievement_pct = (gained_count / total_count) * 100 if total_count > 0 else 0
    st.progress(
        gained_count / total_count,
        text=f"Achievements Unlocked: {gained_count} / {total_count} ({achievement_pct:.0f}%)",
    )

# ============================================================
# SECTION 8: GLOBAL FOOTER WITH LAST BUILD TIMER
# ============================================================

st.markdown("---")
footer_col1, footer_col2 = st.columns([2, 1])

with footer_col1:
    if st.session_state.history:
        last = st.session_state.history[-1]
        st.markdown(
            f"""<div class="timer-box">
            ⏰ <strong>Last Build:</strong> {last['building']} × {last['units']:,} units<br>
            🏁 <strong>Estimated completion:</strong> {last['finish_at']}
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No active builds. Start one in the Calculator tab.")

with footer_col2:
    st.caption("SimLife Empire Manager v2.0")
    st.caption(f"© {datetime.now().year} – Built with Streamlit")
