"""
SimLife Empire Manager v2.0
Senior-grade Streamlit BI Dashboard for resource management and ROI optimization.
Fix: pandas .applymap() → .map() for pandas >= 2.1.0 compatibility.
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
    ("🥇 First Million",           lambda s: s["cash"] >= 1_000_000),
    ("🏢 Office Tycoon (100+ OB)", lambda s: any(
        h["building"].startswith("🏢") and h["units"] >= 100
        for h in s["history"]
    )),
    ("💰 Half-Billionaire",        lambda s: s["cash"] >= 500_000_000),
    ("🤑 Billionaire",             lambda s: s["cash"] >= 1_000_000_000),
    ("⏰ Workaholic (12h click)",  lambda s: s["click_h"] == 12),
    ("📦 Zero-Waste Manager",      lambda s: any(
        h.get("zero_out") for h in s["history"]
    )),
    ("🌉 Bridge Builder",          lambda s: any(
        h["building"].startswith("🌉") for h in s["history"]
    )),
    ("🏨 Hotel Mogul",             lambda s: any(
        h["building"].startswith("🏨") for h in s["history"]
    )),
]

# ============================================================
# SECTION 2: PANDAS VERSION COMPATIBILITY UTILITY
# ============================================================

def _pandas_version_tuple() -> tuple[int, ...]:
    """Return pandas version as a comparable integer tuple e.g. (2, 2, 1)."""
    return tuple(int(x) for x in pd.__version__.split(".")[:3])


def safe_style_map(styler, func, subset=None):
    """
    Compatibility shim for DataFrame styler cell-wise mapping.

    - pandas < 2.1.0  → uses .applymap()  (original API)
    - pandas >= 2.1.0 → uses .map()       (new API, applymap removed in 2.2)

    Parameters
    ----------
    styler : pandas.io.formats.style.Styler
    func   : callable  – receives a single cell value, returns CSS string
    subset : label or list of labels (columns to target)

    Returns
    -------
    pandas.io.formats.style.Styler
    """
    version = _pandas_version_tuple()
    if version >= (2, 1, 0):
        return styler.map(func, subset=subset)
    else:
        return styler.applymap(func, subset=subset)  # type: ignore[attr-defined]

# ============================================================
# SECTION 3: SESSION STATE INITIALISATION
# ============================================================

def init_session_state() -> None:
    """Bootstrap all session-state keys with safe defaults."""
    defaults: dict = {
        "history":  [],
        "click_h":  1,
        "cash":     1_000_000,
        "zero_out": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()

# ============================================================
# SECTION 4: CALCULATION ENGINE (Pure Functions)
# ============================================================

def clamp_to_zero(value: float) -> float:
    """
    Warehouse safety clamp — ensures we NEVER return a negative quantity.

    Negative values arise when warehouse stock EXCEEDS the total required
    amount for the planned build.  The correct purchase quantity is 0
    (nothing to buy), not a negative number.

    Examples
    --------
    clamp_to_zero(500)   →  500   (need 500 more)
    clamp_to_zero(0)     →    0   (exactly covered)
    clamp_to_zero(-200)  →    0   (surplus of 200 — buy nothing)
    """
    return max(0.0, value)


def net_resource_needed(units: int, per_unit: int, in_stock: int) -> int:
    """
    Calculate how much of one resource must be purchased.

    Always returns a non-negative integer.
    """
    total_required = units * per_unit
    return int(clamp_to_zero(total_required - in_stock))


def calculate_available_funds(
    cash: float,
    passive_h: float,
    active_h: float,
    click_h: int,
) -> float:
    """Total spendable funds including projected active + passive income."""
    return cash + (passive_h * click_h) + (active_h * click_h)


def calculate_max_units_by_cash(funds: float, cost_per_unit: float) -> int:
    """How many units can we afford purely by cash?"""
    if cost_per_unit <= 0:
        return 0
    return int(funds // cost_per_unit)


def calculate_max_units_zero_out(
    funds: float,
    building: dict,
    warehouse: dict[str, int],
) -> int:
    """
    Zero-Out Mode: maximise warehouse consumption without exceeding budget.

    Strategy
    --------
    For every resource that has stock > 0, compute how many units that
    stock alone would cover.  The binding warehouse constraint is the
    minimum of those per-resource limits (exhaust the smallest pile first).
    Final answer is capped by the cash limit so we stay solvent.
    """
    cash_limit = calculate_max_units_by_cash(funds, building["cost"])

    warehouse_limits = [
        warehouse[key] // building[key]
        for key in RESOURCE_KEYS
        if warehouse[key] > 0 and building[key] > 0
    ]

    if not warehouse_limits:
        return cash_limit

    warehouse_limit = min(warehouse_limits)
    return int(min(cash_limit, max(warehouse_limit, cash_limit)))


def build_shopping_list(
    units: int,
    building: dict,
    warehouse: dict[str, int],
) -> pd.DataFrame:
    """
    Build the net shopping list after deducting warehouse stock.

    The 'To Buy' column is ALWAYS >= 0 — enforced via net_resource_needed()
    which internally calls clamp_to_zero().
    """
    rows = []
    for key, label in zip(RESOURCE_KEYS, RESOURCE_LABELS):
        total_needed = units * building[key]
        in_stock     = warehouse[key]
        to_buy       = net_resource_needed(units, building[key], in_stock)
        surplus      = int(clamp_to_zero(in_stock - total_needed))
        status       = "✅ OK"  if to_buy == 0 else "🛒 Buy"

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
    """Return the resource with the highest 'To Buy' demand, or None."""
    needs_buying = df[df["To Buy"] > 0]
    if needs_buying.empty:
        return None
    return str(needs_buying.sort_values("To Buy", ascending=False).iloc[0]["Resource"])


def calculate_roi(cost: float, revenue: float) -> float:
    """Return-on-Investment as a percentage."""
    if cost <= 0:
        return 0.0
    return ((revenue - cost) / cost) * 100


# ============================================================
# SECTION 5: STYLING HELPERS
# ============================================================

def style_to_buy_cell(val: int) -> str:
    """
    CSS string for a single 'To Buy' cell.
    Used via safe_style_map() — compatible with both pandas 2.0 and 2.2.
    """
    if val == 0:
        return "color: #4caf50; font-weight: bold;"        # green  — no purchase needed
    if val > 10_000:
        return "color: #ff6b35; font-weight: bold;"        # orange — large purchase
    return "color: #ffcc00; font-weight: bold;"            # yellow — moderate purchase


def format_shopping_df(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """
    Return a fully styled Styler for the shopping list dataframe.
    Handles pandas 2.1+ compatibility via safe_style_map().
    """
    display_df = df.copy()

    # Human-readable formatting for display columns
    display_df["Total Needed"] = display_df["Total Needed"].apply(lambda x: f"{x:,}")
    display_df["In Warehouse"] = display_df["In Warehouse"].apply(lambda x: f"{x:,}")
    display_df["Surplus"]      = display_df["Surplus"].apply(
        lambda x: f"+{x:,}" if x > 0 else "—"
    )
    # Keep 'To Buy' as raw int for styling, then format after
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

        [data-testid="stMetric"] {
            background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
            border: 1px solid #4a4a6a;
            border-radius: 12px;
            padding: 16px 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        [data-testid="stMetricLabel"] { font-size: 0.85rem !important; color: #a0a0c0 !important; }
        [data-testid="stMetricValue"] { font-size: 1.8rem  !important; color: #e0e0ff !important; font-weight: 700 !important; }
        [data-testid="stMetricDelta"] { font-size: 0.9rem  !important; }

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
        .bottleneck-box {
            background: linear-gradient(135deg, #3d1a00, #5a2a00);
            border-left: 5px solid #ff6b35;
            border-radius: 8px;
            padding: 14px 18px;
            color: #ffccaa;
            font-size: 1rem;
            font-weight: 600;
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
# SECTION 7: SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## 🏦 Empire Settings")
    st.markdown("---")

    with st.expander("💸 Hourly Income", expanded=True):
        passive_h = st.number_input(
            "Passive Income ($/h)",
            value=8_480_000,
            min_value=0,
            step=10_000,
            help="Auto-generated income every hour.",
        )
        active_h = st.number_input(
            "Clicking Income ($/h)",
            value=46_138_788,
            min_value=0,
            step=10_000,
            help="Additional income per hour of active clicking.",
        )

    with st.expander("📦 Warehouse Inventory", expanded=True):
        warehouse = {
            "workers":  int(st.number_input("👷 Workers",        value=0, min_value=0, step=1)),
            "metal":    int(st.number_input("⚙️ Metal (t)",      value=0, min_value=0, step=100)),
            "wood":     int(st.number_input("🪵 Wood (m³)",      value=0, min_value=0, step=100)),
            "concrete": int(st.number_input("🧱 Concrete (m³)", value=0, min_value=0, step=10)),
        }

    st.markdown("---")
    target_goal = st.number_input(
        "🎯 Financial Goal ($)",
        value=1_000_000_000,
        min_value=0,
        step=100_000_000,
    )

    st.markdown("---")
    st.caption("SimLife Empire Manager v2.0")
    st.caption(f"pandas {pd.__version__} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================================
# SECTION 8: HEADER
# ============================================================

st.markdown("# 🏦 SimLife Empire Manager")
st.markdown("*Real-time resource planning & ROI optimisation.*")
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

    inp_col1, inp_col2, inp_col3 = st.columns([2, 1, 1])

    with inp_col1:
        selected_b = st.selectbox("🏗️ Select Building Type", list(BUILDINGS.keys()))
        cash = st.number_input(
            "💵 Current Balance ($)",
            value=1_000_000,
            min_value=0,
            step=100_000,
        )
        st.session_state["cash"] = cash

    with inp_col2:
        click_h = st.slider("⏱️ Active Clicking Hours", 0, 12, 1)
        st.session_state["click_h"] = click_h

    with inp_col3:
        zero_out = st.checkbox(
            "♻️ Zero-Out Warehouse Mode",
            value=False,
            help="Prioritise consuming existing warehouse inventory first.",
        )
        st.session_state["zero_out"] = zero_out
        st.info(f"⏰ Build time: **{BUILDINGS[selected_b]['time_h']}h** per batch")

    building = BUILDINGS[selected_b]

    # ── Core Calculations ──────────────────────────────────────
    available_funds = calculate_available_funds(cash, passive_h, active_h, click_h)

    if zero_out:
        max_units = calculate_max_units_zero_out(available_funds, building, warehouse)
    else:
        max_units = calculate_max_units_by_cash(available_funds, building["cost"])

    total_cost    = max_units * building["cost"]
    total_revenue = max_units * building["revenue"]
    total_profit  = total_revenue - total_cost
    roi_pct       = calculate_roi(building["cost"], building["revenue"])

    # ── Metrics ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📈 Build Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏗️ Units to Build",  f"{max_units:,}",
              delta=f"+{max_units} vs 0")
    m2.metric("💰 Total Cost",       f"${total_cost:,.0f}",
              delta=f"${available_funds - total_cost:,.0f} remaining")
    m3.metric("📈 ROI per Unit",     f"{roi_pct:.1f}%",
              delta=f"${building['revenue'] - building['cost']:,.2f} profit/unit")
    m4.metric("🎯 Total Profit",     f"${total_profit:,.0f}",
              delta=f"Revenue ${total_revenue:,.0f}")

    # ── Funds Breakdown ────────────────────────────────────────
    with st.expander("💡 Available Funds Breakdown", expanded=False):
        fd1, fd2, fd3 = st.columns(3)
        fd1.metric("Cash on Hand",    f"${cash:,.0f}")
        fd2.metric("Passive Income",  f"${passive_h * click_h:,.0f}",
                   delta=f"${passive_h:,.0f}/h × {click_h}h")
        fd3.metric("Clicking Income", f"${active_h * click_h:,.0f}",
                   delta=f"${active_h:,.0f}/h × {click_h}h")
        st.markdown(f"**🏦 Total Available: ${available_funds:,.0f}**")

    # ── Shopping List ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🛒 Net Shopping List")
    st.caption(
        "Warehouse stock is subtracted before calculating 'To Buy'. "
        "**'To Buy' is always ≥ 0** — surpluses are shown separately."
    )

    if max_units == 0:
        st.warning(
            "⚠️ No units can be built with current funds. "
            "Increase your balance or reduce the active clicking hours."
        )
    else:
        shopping_df = build_shopping_list(max_units, building, warehouse)

        # ✅ FIX: uses safe_style_map() → .map() on pandas 2.1+
        styled_df = format_shopping_df(shopping_df)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # ── Bottleneck ─────────────────────────────────────────
        bottleneck = identify_bottleneck(shopping_df)
        if bottleneck:
            st.markdown(
                f'<div class="bottleneck-box">'
                f'⚠️ <strong>Bottleneck:</strong> '
                f'<strong>{bottleneck}</strong> is your most deficient resource. '
                f'Prioritise it in the Autoclicker.'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.success("✅ Warehouse fully covers all resources for this build!")

    # ── Save Build ─────────────────────────────────────────────
    st.markdown("---")
    if st.button("✅ Start Build & Save to History", type="primary"):
        if max_units > 0:
            finish_dt = datetime.now() + timedelta(hours=building["time_h"])
            st.session_state.history.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "building":  selected_b,
                "units":     max_units,
                "cost":      total_cost,
                "profit":    total_profit,
                "zero_out":  zero_out,
                "finish_at": finish_dt.strftime("%H:%M:%S"),
            })
            st.markdown(
                f'<div class="timer-box">'
                f'⏰ <strong>Build Started!</strong><br>'
                f'Completion: <strong>{finish_dt.strftime("%Y-%m-%d %H:%M:%S")}</strong>'
                f' ({building["time_h"]}h from now)'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.balloons()
        else:
            st.error("Cannot save a 0-unit build. Increase available funds.")

# ──────────────────────────────────────────────────────────────
# TAB 2 — NIGHT STRATEGY
# ──────────────────────────────────────────────────────────────
with tab_night:
    st.subheader("🌙 Night Strategy Planner")

    n1, n2 = st.columns([1, 2])
    with n1:
        sleep_h        = st.slider("😴 Sleep Duration (h)", 4, 12, 8)
        night_building = st.selectbox(
            "Overnight Building",
            list(BUILDINGS.keys()),
            key="night_building",
        )

    nb                   = BUILDINGS[night_building]
    night_passive_income = passive_h * sleep_h
    night_total_funds    = cash + night_passive_income
    night_units          = int(night_total_funds // nb["cost"])
    night_cost           = night_units * nb["cost"]
    night_profit         = night_units * (nb["revenue"] - nb["cost"])

    with n2:
        sn1, sn2, sn3 = st.columns(3)
        sn1.metric("💤 Sleep Duration",   f"{sleep_h}h")
        sn2.metric("💰 Passive Earned",   f"${night_passive_income:,.0f}")
        sn3.metric("🏗️ Suggested Units", f"{night_units:,}")

        sn4, sn5, _ = st.columns(3)
        sn4.metric("🧾 Build Cost",       f"${night_cost:,.0f}")
        sn5.metric("📈 Expected Profit",  f"${night_profit:,.0f}")

    st.markdown("---")
    wake_time  = datetime.now() + timedelta(hours=sleep_h)
    build_end  = datetime.now() + timedelta(hours=nb["time_h"])

    plan = {
        "Building":      night_building,
        "Units":         f"{night_units:,}",
        "Total Cost":    f"${night_cost:,.0f}",
        "Wakeup Time":   wake_time.strftime("%H:%M"),
        "Build Finish":  build_end.strftime("%H:%M"),
        "ROI":           f"{calculate_roi(nb['cost'], nb['revenue']):.1f}%",
    }
    for k, v in plan.items():
        ck, cv = st.columns([1, 2])
        ck.markdown(f"**{k}**")
        cv.markdown(v)

    if nb["time_h"] <= sleep_h:
        st.success(f"✅ Build completes BEFORE wakeup ({nb['time_h']}h < {sleep_h}h sleep).")
    else:
        st.info(f"ℹ️ Build finishes {nb['time_h'] - sleep_h}h after wakeup.")

# ──────────────────────────────────────────────────────────────
# TAB 3 — ROADMAP & HISTORY
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
        st.metric("🎯 Target Goal",    f"${target_goal:,.0f}")
        st.metric("💵 Balance",        f"${cash:,.0f}")
        st.metric("📉 Remaining",      f"${missing_cash:,.0f}")
    with gc2:
        st.metric("⚡ Max Rate",       f"${total_income_rate:,.0f}/h")
        st.metric("⏱️ Hours to Goal",  f"{hours_to_goal:.1f}h"
                  if hours_to_goal != float("inf") else "∞")
        eta = (
            datetime.now() + timedelta(hours=hours_to_goal)
            if hours_to_goal != float("inf") else None
        )
        st.metric("📅 ETA", eta.strftime("%Y-%m-%d %H:%M") if eta else "—")

    st.progress(progress_pct, text=f"Progress: {progress_pct * 100:.1f}%")

    st.markdown("---")
    st.markdown("#### 📜 Build History")

    if st.session_state.history:
        hist_df     = pd.DataFrame(st.session_state.history)
        display_df  = hist_df.copy()
        display_df["cost"]   = display_df["cost"].apply(lambda x: f"${x:,.0f}")
        display_df["profit"] = display_df["profit"].apply(lambda x: f"${x:,.0f}")
        display_df.columns   = [c.replace("_", " ").title() for c in display_df.columns]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        total_p = sum(h["profit"] for h in st.session_state.history)
        total_u = sum(h["units"]  for h in st.session_state.history)
        st.markdown(
            f"**Totals →** Builds: `{len(st.session_state.history)}` | "
            f"Units: `{total_u:,}` | Profit: `${total_p:,.0f}`"
        )
        if st.button("🗑️ Clear History", type="secondary"):
            st.session_state.history = []
            st.rerun()
    else:
        st.info("No builds saved yet. Use the Calculator tab to start.")

# ──────────────────────────────────────────────────────────────
# TAB 4 — ACHIEVEMENTS
# ──────────────────────────────────────────────────────────────
with tab_achieve:
    st.subheader("🏆 Empire Achievements")

    achieve_state = {
        "cash":    cash,
        "history": st.session_state.history,
        "click_h": click_h,
    }

    gained_count = 0
    ach_col1, ach_col2 = st.columns(2)

    for idx, (title, condition) in enumerate(ACHIEVEMENT_DEFINITIONS):
        gained = condition(achieve_state)
        gained_count += int(gained)
        css_class = "achievement-gained" if gained else "achievement-locked"
        icon      = "🌟" if gained else "🔒"
        html      = f'<div class="{css_class}">{icon} {title}</div>'
        (ach_col1 if idx % 2 == 0 else ach_col2).markdown(html, unsafe_allow_html=True)

    st.markdown("---")
    total_count = len(ACHIEVEMENT_DEFINITIONS)
    st.progress(
        gained_count / total_count,
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
            f'⏰ <strong>Last Build:</strong> {last["building"]} × {last["units"]:,} units<br>'
            f'🏁 <strong>Estimated Completion:</strong> {last["finish_at"]}'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No active builds. Start one in the Calculator tab.")

with f2:
    st.caption(f"SimLife Empire Manager v2.0")
    st.caption(f"pandas {pd.__version__} | streamlit {st.__version__}")
    st.caption(f"© {datetime.now().year}")
