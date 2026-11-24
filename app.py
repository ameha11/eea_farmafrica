"""
Farm Africa HARNESS Baseline - Household Survey dashboard
Live data from the Ona API (api.ona.io).

Setup (once):
  python -m pip install -r requirements.txt
  .streamlit/secrets.toml next to this file:
      ONA_SERVER  = "https://api.ona.io"
      ONA_TOKEN   = "your_ona_api_token"
      HH_FORM_ID  = "897306"
Run:
  python -m streamlit run app.py
"""

import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import requests
import streamlit as st

st.set_page_config(page_title="Farm Africa HARNESS – Household Survey", layout="wide")

# ---------------------------------------------------------------- colours
# Farm Africa brand palette (farmafrica.org/toolkit/brand-guidelines)
FIELD = "#4BAE44"      # Field green – main colour
FOREST = "#00521A"     # Forest – dark green
FLAME = "#F47E28"      # Flame – orange
SKY = "#4CB9D1"        # Sky – blue
SUNSHINE = "#F6CE40"   # Sunshine – yellow
MINT = "#C7ED9F"       # Mint – light green
NIGHT = "#1D2E23"      # Night – text colour
STONE = "#E4DCCA"      # Dark Stone – neutral
PALE = "#FBF8F2"       # Pale Stone – card background
PALETTE = [FIELD, FOREST, FLAME, SKY, SUNSHINE, MINT, "#7A8C7E", STONE]

pio.templates["farmafrica"] = pio.templates["plotly_white"]
pio.templates["farmafrica"].layout.colorway = PALETTE
pio.templates["farmafrica"].layout.update(
    font=dict(family="Arial, Helvetica, sans-serif", size=13, color=NIGHT),
    title=dict(font=dict(size=16, color=NIGHT), x=0, xanchor="left", y=0.98, yanchor="top"),
    margin=dict(l=10, r=30, t=80, b=10),
    legend=dict(title_text="", orientation="h", x=1, xanchor="right", y=1.0, yanchor="bottom"),
    bargap=0.25)
pio.templates["farmafrica"].layout.xaxis.update(gridcolor="#ECE7DC", zeroline=False)
pio.templates["farmafrica"].layout.yaxis.update(gridcolor="#ECE7DC", zeroline=False)
pio.templates.default = "farmafrica"
px.defaults.color_discrete_sequence = PALETTE

st.markdown(f"""
<style>
  h1, h2, h3 {{ color: {NIGHT}; }}
  h1 {{ border-bottom: 4px solid {FIELD}; padding-bottom: .3rem; }}
  [data-testid="stMetricValue"] {{ color: {FOREST}; }}
  [data-testid="stMetric"] {{ background: {PALE}; border-left: 5px solid {FIELD};
                             border-radius: 6px; padding: .7rem 1rem; }}
</style>""", unsafe_allow_html=True)

SERVER = st.secrets.get("ONA_SERVER", "https://api.ona.io").rstrip("/")
TOKEN = st.secrets["ONA_TOKEN"]
FORM_ID = str(st.secrets["HH_FORM_ID"])
HEADERS = {"Authorization": f"Token {TOKEN}"}
LANG = "English (en)"

# ---------------------------------------------------------------- form facts
MAIN_VARS = {
    "cluster": "Cluster",
    "woreda": "Woreda",
    "kebele": "Kebele",
    "enumerator": "Enumerator",
}
BREAKDOWNS = {**MAIN_VARS, "B4": "Sex of household head",
              "s0_16": "Location stratum", "s0_14": "Kebele stratum"}

# Kebele of each woreda (kebele list of the XLSForm)
KEBELE_WOREDA = {str(k): str(w) for k, w in [
    (1, 1), (2, 1), (3, 1), (4, 1), (5, 2), (6, 2), (7, 2), (8, 3), (9, 3), (10, 3), (11, 3),
    (12, 4), (13, 4), (14, 4), (15, 4), (16, 5), (17, 5), (18, 5), (19, 6), (20, 6), (21, 6),
    (22, 7), (23, 7), (24, 7), (25, 7), (26, 7)]}
N_WOREDAS = len(set(KEBELE_WOREDA.values()))

# Target households per kebele. Fill in when the sample allocation is final,
# e.g. {"1": 25, "2": 25, ...}. Kebeles left out use the number of households
# drawn that enumerators record at 0.18 (largest value reported for the kebele).
KEBELE_TARGETS = {}

AGE_BANDS = {"a": "0–4", "b": "5–14", "c": "15–17", "d": "18–29", "e": "30–59", "f": "60–64", "g": "65+"}
H1_ITEMS = [f"H1_{i}" for i in range(1, 13)]
NUMERIC_VARS = (["B2_total", "B2_male", "B2_female", "B3_dependency", "B5", "B17_sum",
                 "B_age_15_64", "C15", "F2", "F15_total_sold", "F15_garden_sold",
                 "F15_semi_forest_sold", "F15_forest_sold", "F15a_a", "F15a_b", "F15a_c",
                 "F15a_d", "F15a_e", "F15a_f", "F15a_price", "H1_hdds", "H2_rcsi",
                 "O1_duration_minutes", "s0_18_drawn_total", "s0_18_drawn_surrounding", "s0_18_drawn_adjacent", "ntfp_producer", "forest_seller",
                 "any_shock", "lat", "lon"]
                + [f"B1{b}_{s}" for b in AGE_BANDS for s in ("m", "f")])
# Filter ("gate") questions and the answer that skips the follow-up questions.
# An enumerator who picks the skip answer much more often than others may be shortening interviews.
GATES = {"C1": "0", "C4": "2", "C6": "0", "C7": "0", "C11": "0", "C12": "0", "E1": "0", "E2": "0",
         "E11": "0", "F3": "0", "F15_producer": "0", "H3": "0", "I4": "0", "K1": "0", "K6": "0",
         "L6a": "0", "N2": "0", "N4": "0", "N12": "0", "A6": "2", "J0_consent": "0", "P1_available": "0",
         **{f"D4a_{i}": "0" for i in range(1, 11)}, **{f"F1a_{i}": "0" for i in range(1, 12)}}
GATE_LABELS = {"C1": "C1 Land", "C4": "C4 Certificate", "C6": "C6 Forest use", "C7": "C7 Forest rights",
               "C11": "C11 Land process", "C12": "C12 Land conflict", "E1": "E1 PFMC exists",
               "E2": "E2 PFMC member", "E11": "E11 Benefit", "F3": "F3 Crops", "F15_producer": "F15 Coffee",
               "H3": "H3 Food shortage", "I4": "I4 Fuelwood", "K1": "K1 Credit", "K6": "K6 Incentive",
               "L6a": "L6a Forest coping", "N2": "N2 Office used", "N4": "N4 Complaint",
               "N12": "N12 Past project", "A6": "A6 Woman available", "J0_consent": "J0 Woman module",
               "P1_available": "P1 Youth module", "D4a": "D4a NTFPs (10)", "F1a": "F1a Activities (11)"}

# Select questions whose codes the dashboard compares directly
CODE_VARS = (["A1", "B4", "B6", "B8", "B9", "B10", "B12", "C6", "D1", "E1", "F15_producer",
              "s0_14", "s0_16", "s0_20_exposed", "cluster", "region", "zone", "woreda", "kebele",
              "enumerator", "supervisor"] + H1_ITEMS + list(GATES))
NEEDED = (list(BREAKDOWNS) + ["start", "end", "A1", "B8", "B9", "B10", "B12", "C6", "D1", "D2", "E1",
                              "F15_producer", "s0_20_exposed", "gps_coord", "today",
                              "date_of_interviiew", "supervisor"] + NUMERIC_VARS)


# ---------------------------------------------------------------- data access
@st.cache_data(ttl=600, show_spinner="Downloading submissions from Ona...")
def fetch_submissions() -> pd.DataFrame:
    rows, page, size = [], 1, 5000
    while True:
        r = requests.get(f"{SERVER}/api/v1/data/{FORM_ID}",
                         params={"page": page, "page_size": size},
                         headers=HEADERS, timeout=180)
        if r.status_code == 404 and page > 1:   # past the last page
            break
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < size:
            break
        page += 1
    return pd.json_normalize(rows, max_level=0)


def _label(x):
    if isinstance(x, dict):
        return x.get(LANG) or next(iter(x.values()), None)
    return x


@st.cache_data(ttl=3600)
def fetch_form():
    """Question labels and choice labels from the form definition (pyxform JSON)."""
    r = requests.get(f"{SERVER}/api/v1/forms/{FORM_ID}/form.json", headers=HEADERS, timeout=60)
    r.raise_for_status()
    js = r.json()
    top_choices = {ln: {str(c["name"]): _label(c.get("label")) for c in items}
                   for ln, items in (js.get("choices") or {}).items()}
    questions, choices = {}, {}

    def walk(node):
        for ch in node.get("children", []) or []:
            t = ch.get("type", "")
            if t in ("group", "repeat", "survey"):
                walk(ch)
                continue
            name = ch.get("name")
            if not name:
                continue
            lst = None
            if t.startswith("select"):
                lst = ch.get("list_name") or ch.get("itemset") or name
                if isinstance(ch.get("children"), list) and ch["children"]:
                    choices[lst] = {str(c["name"]): _label(c.get("label")) for c in ch["children"]}
                elif lst in top_choices:
                    choices[lst] = top_choices[lst]
            questions[name] = {"label": _label(ch.get("label")) or name, "type": t, "list": lst}

    walk(js)
    for ln, items in top_choices.items():
        choices.setdefault(ln, items)
    return questions, choices


def code_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return pd.NA
    t = str(v).strip()
    if t.endswith(".0") and t[:-2].lstrip("-").isdigit():
        t = t[:-2]
    return t if t else pd.NA


def choice_map(qname):
    """Code -> label for a select question, found through the question itself."""
    q = questions.get(qname, {})
    return choices.get(q.get("list"), {}) or choices.get(qname, {})


def prepare(raw, questions, choices):
    d = raw.copy()
    d.columns = [c.split("/")[-1] for c in d.columns]
    d = d.loc[:, ~d.columns.duplicated()]
    for c in NEEDED:
        if c not in d.columns:
            d[c] = pd.NA
    # GPS "lat lon alt acc" (or Ona's _geolocation [lat, lon])
    gps = d["gps_coord"].astype("string").str.split(" ", expand=True)
    if gps.shape[1] >= 2:
        d["lat"], d["lon"] = gps[0], gps[1]
    elif "_geolocation" in d:
        d["lat"] = d["_geolocation"].map(lambda g: g[0] if isinstance(g, list) and g else None)
        d["lon"] = d["_geolocation"].map(lambda g: g[1] if isinstance(g, list) and len(g) > 1 else None)
    for c in NUMERIC_VARS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    # Ona can return codes as numbers (1, 1.0) or text ("1"): make them all text "1"
    sel = {n for n, q in questions.items() if q["type"] in ("select one", "select_one")}
    for name in sel | set(CODE_VARS):
        if name in d.columns:
            d[name] = d[name].map(code_str)
    for name in sel:
        if name in d.columns:
            d[name + "_lbl"] = d[name].map(choice_map(name)).fillna(d[name])
    for c in BREAKDOWNS:
        if c + "_lbl" not in d.columns:
            d[c + "_lbl"] = d[c]
        d[c + "_lbl"] = d[c + "_lbl"].fillna("Missing")
    # interview length from the start/end timestamps (the O1 calculation is often blank)
    if "start" in d and "end" in d:
        t0 = pd.to_datetime(d["start"], errors="coerce", utc=True)
        t1 = pd.to_datetime(d["end"], errors="coerce", utc=True)
        d["duration_min"] = ((t1 - t0).dt.total_seconds() / 60).round(1)
    else:
        d["duration_min"] = pd.NA
    d["duration_min"] = pd.to_numeric(d["duration_min"], errors="coerce").fillna(d["O1_duration_minutes"])
    # questions answered (Ona leaves unanswered questions out)
    meta = {"start", "end", "today", "deviceid", "username", "instanceID", "deprecatedID", "formhub", "meta"}
    qcols = [c for c in d.columns if not c.startswith("_") and c not in meta and not c.endswith("_lbl")
             and c in questions and questions[c]["type"] not in ("calculate", "note")]
    d["n_answered"] = d[qcols].notna().sum(axis=1) if qcols else pd.NA
    # skip answers at gate questions
    gcols = [g for g in GATES if g in d.columns]
    if gcols:
        answered = pd.concat([d[g].notna() for g in gcols], axis=1).sum(axis=1)
        skipped = pd.concat([d[g] == GATES[g] for g in gcols], axis=1).sum(axis=1)
        d["gate_answered"], d["gate_skipped"] = answered, skipped
        d["skip_rate"] = (100 * skipped / answered.where(answered > 0)).round(1)
    else:
        d["gate_answered"] = d["gate_skipped"] = d["skip_rate"] = pd.NA
    # "don't know" answers on select questions
    dk_cols = []
    for name, q in questions.items():
        if name in d.columns and q["type"] in ("select one", "select_one"):
            codes = [c for c, lab in choice_map(name).items()
                     if lab and re.search(r"don.?t know|do not know|unknown", str(lab), re.I)]
            if codes:
                dk_cols.append(d[name].isin(codes))
    d["n_dont_know"] = pd.concat(dk_cols, axis=1).sum(axis=1) if dk_cols else 0
    sub = pd.to_datetime(d["_submission_time"], errors="coerce")
    d["date"] = (pd.to_datetime(d["date_of_interviiew"], errors="coerce")
                 .fillna(pd.to_datetime(d["today"], errors="coerce")).fillna(sub).dt.date)
    return d


# ---------------------------------------------------------------- helpers
def pct(mask, base):
    n = int(base.sum())
    return (round(100 * (mask & base).sum() / n, 1) if n else None), n


def mean_of(s, digits=1):
    s = s.dropna()
    return (round(s.mean(), digits) if len(s) else None), len(s)


def median_of(s):
    s = s.dropna()
    return (round(s.median()) if len(s) else None), len(s)


def fmt(val, unit=""):
    if val is None:
        return "–"
    if unit == "%":
        return f"{val:.0f}%"
    if unit == "min":
        return f"{val:.0f} min"
    if unit == "ETB":
        return f"{val:,.0f} ETB"
    return f"{val:.1f}"


def share_chart(d, col, title, order=None, split=None, color=FIELD):
    sub = d.dropna(subset=[col])
    sub = sub[sub[col] != "Missing"]
    if sub.empty:
        st.info(f"No data yet for {title.lower()}.")
        return
    if split:
        t = (sub.groupby([split, col]).size() / sub.groupby(split).size() * 100).rename("%").reset_index()
        fig = px.bar(t, x="%", y=split, color=col, orientation="h", title=title,
                     category_orders={col: order} if order else None,
                     labels={split: "", col: ""}, text=t["%"].round(0))
        fig.update_traces(texttemplate="%{text:.0f}", textposition="inside")
        fig.update_layout(barmode="stack", xaxis=dict(range=[0, 100], title=""),
                          height=max(300, 34 * t[split].nunique() + 140))
    else:
        t = sub[col].value_counts(normalize=True).mul(100).rename("%").reset_index()
        if order:
            t[col] = pd.Categorical(t[col], order, ordered=True)
            t = t.sort_values(col, ascending=False)
        else:
            t = t.sort_values("%")
        fig = px.bar(t, x="%", y=col, orientation="h", title=title, text=t["%"].round(0),
                     color_discrete_sequence=[color], labels={col: ""})
        fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside", cliponaxis=False,
                          width=0.55)
        fig.update_layout(xaxis=dict(range=[0, 108], title="", showticklabels=False, showgrid=False),
                          height=max(260, 40 * len(t) + 110))
    st.plotly_chart(fig, width="stretch")


def split_picker(key, extra=None):
    opts = ["(none)"] + (extra or []) + list(BREAKDOWNS.values())
    lab = st.selectbox("Split charts by", opts, key=key)
    if lab == "(none)":
        return None
    if extra and lab in extra:
        return lab
    return {v: k_ for k_, v in BREAKDOWNS.items()}[lab] + "_lbl"


# ---------------------------------------------------------------- load
try:
    raw = fetch_submissions()
    questions, choices = fetch_form()
except requests.HTTPError as e:
    st.error(f"Ona API error: {e}. Check the token, form ID and server in secrets.toml.")
    st.stop()

if raw.empty:
    st.warning("No submissions yet.")
    st.stop()

raw_names = {c.split("/")[-1] for c in raw.columns}
data = prepare(raw, questions, choices)

# ---------------------------------------------------------------- sidebar
st.sidebar.markdown(f"<h2 style='color:{FIELD};margin-bottom:0'>FARM AFRICA</h2>"
                    "<p style='margin-top:0'>HARNESS Baseline · Household Survey</p>",
                    unsafe_allow_html=True)
if st.sidebar.button("Refresh data from Ona"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.header("Filters")
dmin, dmax = data["date"].min(), data["date"].max()
dr = st.sidebar.date_input("Interview date", (dmin, dmax), min_value=dmin, max_value=dmax)
df = data
if isinstance(dr, tuple) and len(dr) == 2:
    df = df[(df["date"] >= dr[0]) & (df["date"] <= dr[1])]
for var, label in MAIN_VARS.items():
    pick = st.sidebar.multiselect(label, sorted(df[var + "_lbl"].astype(str).unique()))
    if pick:
        df = df[df[var + "_lbl"].astype(str).isin(pick)]

# Data quality tab: hidden from everyone. The password box appears only when the
# link ends with ?admin=1, and the tab opens only with the right DQ_PASSWORD.
DQ_PASSWORD = st.secrets.get("DQ_PASSWORD", "")
SHOW_DQ = False
if st.query_params.get("admin") == "1":
    st.sidebar.divider()
    pw = st.sidebar.text_input("Admin password", type="password")
    SHOW_DQ = bool(DQ_PASSWORD) and pw == DQ_PASSWORD
    if pw and not SHOW_DQ:
        st.sidebar.error("Wrong password")

hh = df[df["A1"] == "1"]          # consented interviews
all_hh = data[data["A1"] == "1"]

# ---------------------------------------------------------------- targets
drawn = all_hh.groupby("kebele")["s0_18_drawn_total"].max()
targets = {k: KEBELE_TARGETS.get(k, drawn.get(k)) for k in KEBELE_WOREDA}
targets = {k: int(v) for k, v in targets.items() if pd.notna(v) and v > 0}
target = sum(targets.values())

# ---------------------------------------------------------------- header
st.title("Farm Africa HARNESS Baseline – Household Survey")
st.caption(f"Live from Ona · last submission "
           f"{pd.to_datetime(data['_submission_time']).max():%d %b %Y %H:%M} · "
           f"{len(hh)} households interviewed")

k = st.columns(5)
k[0].metric("Households interviewed", f"{len(hh):,}")
k[1].metric("Refusals", f"{int((df['A1'] == '2').sum()):,}",
            help="A1 = No (sidebar filters applied)")
k[2].metric("Target (so far)", f"{target:,}" if target else "–",
            help="Sum of kebele targets. Kebeles without a set target use households drawn (0.18).")
k[3].metric("Kebeles visited", f"{hh['kebele'].nunique()} of {len(KEBELE_WOREDA)}")
k[4].metric("Woredas covered", f"{hh['woreda'].nunique()} of {N_WOREDAS}")

tab_names = ["Fieldwork progress"] + (["Data quality"] if SHOW_DQ else []) + [
    "Household profile", "Forest & livelihoods", "Food security", "Explore a question"]
tabs = dict(zip(tab_names, st.tabs(tab_names)))

# ---------------------------------------------------------------- fieldwork
with tabs["Fieldwork progress"]:
    keb_lbl = choice_map("kebele")
    wor_lbl = choice_map("woreda")
    done = all_hh.groupby("kebele").size()
    prog = pd.DataFrame({"code": list(KEBELE_WOREDA)})
    prog["Kebele"] = prog["code"].map(keb_lbl).fillna(prog["code"])
    prog["Woreda"] = prog["code"].map(KEBELE_WOREDA).map(lambda w: wor_lbl.get(w, w))
    prog["Done"] = prog["code"].map(done).fillna(0).astype(int)
    prog["Target"] = prog["code"].map(targets)
    prog["Progress"] = (100 * prog["Done"] / prog["Target"]).round(0)
    prog["Status"] = "Not started"
    prog.loc[prog["Done"] > 0, "Status"] = "In progress"
    prog.loc[prog["Progress"] >= 100, "Status"] = "Completed"
    total_done = int(prog["Done"].sum())

    c1, c2 = st.columns([1, 2], gap="large")
    with c1:
        if target:
            fig = go.Figure(go.Pie(values=[min(total_done, target), max(target - total_done, 0)],
                                   labels=["Interviewed", "Remaining"], hole=0.7, sort=False,
                                   marker=dict(colors=[FIELD, STONE]), textinfo="none",
                                   hovertemplate="%{label}: %{value}<extra></extra>"))
            fig.update_layout(title="Overall progress", height=340,
                              legend=dict(x=0.5, xanchor="center", y=-0.02, yanchor="top"),
                              annotations=[dict(text=f"<b>{100 * total_done / target:.0f}%</b><br>"
                                                     f"<span style='font-size:13px'>{total_done} of {target}</span>",
                                                x=0.5, y=0.5, showarrow=False, font=dict(size=30, color=FOREST))])
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No targets yet: add KEBELE_TARGETS in app.py, or wait for 0.18 (households drawn).")
        s_counts = prog["Status"].value_counts()
        pill = ("<span style='display:inline-block;margin:0 .6rem .4rem 0;padding:.25rem .7rem;"
                "border-radius:1rem;background:{bg};color:{fg};font-size:.9rem'><b>{n}</b> {t}</span>")
        st.markdown(
            "<div style='text-align:center'><div style='color:#6E6E6D;margin-bottom:.3rem'>Kebeles</div>"
            + pill.format(bg=FOREST, fg="white", n=int(s_counts.get("Completed", 0)), t="completed")
            + pill.format(bg=FIELD, fg="white", n=int(s_counts.get("In progress", 0)), t="in progress")
            + pill.format(bg=STONE, fg=NIGHT, n=int(s_counts.get("Not started", 0)), t="not started")
            + "</div>", unsafe_allow_html=True)
    with c2:
        w = prog.groupby("Woreda", as_index=False)[["Done", "Target"]].sum(min_count=1)
        w["Target"] = w["Target"].fillna(0)
        w = w.sort_values(["Done", "Woreda"], ascending=[True, False])
        fig = go.Figure()
        fig.add_bar(y=w["Woreda"], x=w["Target"], orientation="h", name="Target",
                    marker_color=STONE, width=0.75,
                    text=[f"{d} / {int(t)}" if t else f"{d}" for d, t in zip(w["Done"], w["Target"])],
                    textposition="outside", textfont=dict(size=12, color=NIGHT), cliponaxis=False,
                    hovertemplate="%{y}: target %{x}<extra></extra>")
        fig.add_bar(y=w["Woreda"], x=w["Done"], orientation="h", name="Interviewed",
                    marker_color=FIELD, width=0.45,
                    hovertemplate="%{y}: %{x} interviewed<extra></extra>")
        xmax = max(w["Target"].max(), w["Done"].max(), 1)
        fig.update_layout(title="Households interviewed vs target, by woreda", barmode="overlay",
                          height=max(360, 40 * len(w) + 100), xaxis=dict(range=[0, xmax * 1.2], title=""))
        st.plotly_chart(fig, width="stretch")

    c3, c4 = st.columns([3, 2], gap="large")
    with c3:
        st.markdown("##### Progress by kebele")
        show = st.segmented_control("Show", ["All", "Not started", "In progress", "Completed"],
                                    default="All", key="keb_status", label_visibility="collapsed")
        tbl = prog if show in (None, "All") else prog[prog["Status"] == show]
        st.dataframe(tbl.sort_values(["Woreda", "Kebele"])[["Woreda", "Kebele", "Done", "Target", "Progress", "Status"]],
                     hide_index=True, width="stretch", height=430,
                     column_config={"Progress": st.column_config.ProgressColumn(
                         "Progress", format="%d%%", min_value=0, max_value=100),
                         "Done": st.column_config.NumberColumn("Interviewed")})
    with c4:
        e = hh.groupby("enumerator_lbl").size().reset_index(name="Households").sort_values("Households")
        fig = px.bar(e, x="Households", y="enumerator_lbl", orientation="h", text="Households",
                     title="Households by enumerator", color_discrete_sequence=[FOREST])
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(height=max(380, 26 * len(e) + 90), yaxis_title="", xaxis_title="",
                          xaxis_range=[0, e["Households"].max() * 1.15 if len(e) else 1])
        st.plotly_chart(fig, width="stretch")

    pts = hh.dropna(subset=["lat", "lon"])
    if len(pts):
        fig = px.scatter_map(pts, lat="lat", lon="lon", zoom=6, height=520, color="woreda_lbl",
                             hover_name="kebele_lbl", hover_data={"enumerator_lbl": True,
                                                                 "lat": False, "lon": False},
                             labels={"enumerator_lbl": "Enumerator", "woreda_lbl": "Woreda"},
                             title="Interview locations")
        fig.update_traces(marker=dict(size=9, opacity=0.85))
        fig.update_layout(map_style="carto-positron", margin=dict(l=0, r=0, t=50, b=0))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No GPS points yet (0.9 is optional and captured only with permission).")

# ---------------------------------------------------------------- data quality
if SHOW_DQ:
  with tabs["Data quality"]:
      SHORT = 45      # minutes: flag interviews shorter than this
      dq = hh.copy()
      dur = dq["duration_min"].where(dq["duration_min"].between(0, 24 * 60))
      all_skip = dq["gate_skipped"].sum() / dq["gate_answered"].sum() * 100 if dq["gate_answered"].sum() else None
      k = st.columns(4)
      k[0].metric("Skip answers", fmt(None if all_skip is None else round(all_skip, 1), "%"),
                  help="Share of filter questions (C1, C6, F3, F15, K1, D4a, F1a …) answered with the "
                       "answer that skips the follow-up questions")
      k[1].metric("Don't know per interview", fmt(mean_of(dq["n_dont_know"])[0]),
                  help="Average number of 'Don't know' answers per interview")
      k[2].metric(f"Under {SHORT} min", fmt(pct(dur < SHORT, dur.notna())[0], "%"))
      k[3].metric("Missing GPS", fmt(pct(dq["lat"].isna(), pd.Series(True, index=dq.index))[0], "%"))

      st.markdown("##### Enumerator comparison")
      st.caption("Each enumerator against the team. ⚠ marks a value far from the team: skip answers 15 points "
                 "above the team, 'don't know' twice the team rate, or questions answered / duration below 75% "
                 "of the team median. A flag is a reason to check, not proof of a problem: some kebeles really "
                 "have fewer forest users or coffee growers.")
      team = {"skip": all_skip or 0, "dk": dq["n_dont_know"].mean(), "nq": dq["n_answered"].median(),
              "dur": dur.median()}
      by_e = dq.assign(dur=dur).groupby("enumerator_lbl").agg(
          Interviews=("dur", "size"), gs=("gate_skipped", "sum"), ga=("gate_answered", "sum"),
          DK=("n_dont_know", "mean"), NQ=("n_answered", "median"), Minutes=("dur", "median"),
          Short=("dur", lambda x: int((x < SHORT).sum()))).reset_index()
      by_e["Skip answers %"] = (100 * by_e["gs"] / by_e["ga"].where(by_e["ga"] > 0)).round(0)
      by_e["Flags"] = ""
      by_e.loc[by_e["Skip answers %"] > team["skip"] + 15, "Flags"] += "⚠ skips  "
      if team["dk"] and team["dk"] > 0:
          by_e.loc[by_e["DK"] > 2 * team["dk"], "Flags"] += "⚠ don't know  "
      if pd.notna(team["nq"]):
          by_e.loc[by_e["NQ"] < 0.75 * team["nq"], "Flags"] += "⚠ few questions  "
      if pd.notna(team["dur"]):
          by_e.loc[by_e["Minutes"] < 0.75 * team["dur"], "Flags"] += "⚠ fast  "
      show = by_e.rename(columns={"enumerator_lbl": "Enumerator", "DK": "Don't know / interview",
                                  "NQ": "Questions answered (median)", "Minutes": "Median minutes",
                                  "Short": f"Under {SHORT} min"})
      show = show[["Enumerator", "Interviews", "Skip answers %", "Don't know / interview",
                   "Questions answered (median)", "Median minutes", f"Under {SHORT} min", "Flags"]]
      st.dataframe(show.sort_values("Skip answers %", ascending=False).round(1), hide_index=True,
                   width="stretch",
                   column_config={"Skip answers %": st.column_config.ProgressColumn(
                       "Skip answers %", format="%d%%", min_value=0, max_value=100)})

      c1, c2 = st.columns(2)
      with c1:
          e = by_e.dropna(subset=["Skip answers %"]).sort_values("Skip answers %")
          if len(e):
              colors = [FLAME if v > team["skip"] + 15 else FIELD for v in e["Skip answers %"]]
              fig = go.Figure(go.Bar(x=e["Skip answers %"], y=e["enumerator_lbl"], orientation="h",
                                     marker_color=colors, text=e["Skip answers %"].map(lambda v: f"{v:.0f}%"),
                                     textposition="outside", cliponaxis=False,
                                     hovertemplate="%{y}: %{x:.0f}%<extra></extra>"))
              fig.add_vline(x=team["skip"], line_dash="dash", line_color=NIGHT,
                            annotation_text=f"Team {team['skip']:.0f}%", annotation_position="top")
              fig.update_layout(title="Skip answers at filter questions, by enumerator", height=max(360, 28 * len(e) + 110),
                                xaxis=dict(range=[0, 105], title=""), yaxis_title="")
              st.plotly_chart(fig, width="stretch")
      with c2:
          if dur.notna().any():
              fig = px.histogram(dur.clip(upper=240), nbins=24, title="Interview duration (minutes, capped at 240)",
                                 color_discrete_sequence=[FIELD])
              fig.add_vline(x=SHORT, line_dash="dash", line_color=FLAME)
              fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Interviews")
              st.plotly_chart(fig, width="stretch")

      # which filter questions each enumerator skips
      rows = {}
      for g_key, g_lab in GATE_LABELS.items():
          cols = [c for c in GATES if c == g_key or c.startswith(g_key + "_")] if g_key in ("D4a", "F1a") else [g_key]
          cols = [c for c in cols if c in dq.columns]
          if not cols:
              continue
          ans = pd.concat([dq[c].notna() for c in cols], axis=1).sum(axis=1)
          skp = pd.concat([dq[c] == GATES[c] for c in cols], axis=1).sum(axis=1)
          agg = pd.DataFrame({"e": dq["enumerator_lbl"], "a": ans, "s": skp}).groupby("e").sum()
          if agg["a"].sum() > 0:
              rows[g_lab] = (100 * agg["s"] / agg["a"].where(agg["a"] > 0)).round(0)
      if rows:
          hm = pd.DataFrame(rows).T
          fig = go.Figure(go.Heatmap(z=hm.values, x=hm.columns, y=hm.index, zmin=0, zmax=100,
                                     colorscale=[[0, PALE], [0.5, SUNSHINE], [1, FLAME]],
                                     text=hm.values, texttemplate="%{text:.0f}", showscale=False,
                                     hovertemplate="%{x} · %{y}: %{z:.0f}% skip answer<extra></extra>",
                                     xgap=2, ygap=2))
          fig.update_layout(title="% skip answer per filter question and enumerator",
                            height=max(420, 24 * len(hm) + 160), xaxis=dict(title="", tickangle=-40),
                            yaxis=dict(title="", autorange="reversed"))
          st.plotly_chart(fig, width="stretch")
          st.caption("Compare each column with the others: an enumerator whose column is much darker than "
                     "colleagues in the same woreda is worth a call.")

      st.markdown("##### Refusals by kebele")
      ref = df.groupby("kebele_lbl").agg(Visited=("A1", lambda s: int(s.notna().sum())),
                                         Refused=("A1", lambda s: int((s == "2").sum()))).reset_index()
      ref["Refusal rate %"] = (100 * ref["Refused"] / ref["Visited"].where(ref["Visited"] > 0)).round(0)
      st.dataframe(ref.rename(columns={"kebele_lbl": "Kebele"}).sort_values("Refusal rate %", ascending=False),
                   hide_index=True, width="stretch")

      st.markdown("##### Interviews to check")
      flags = dq.assign(dur=dur.round(0))
      flags["Issue"] = ""
      flags.loc[flags["dur"] < SHORT, "Issue"] += f"Under {SHORT} min; "
      flags.loc[flags["lat"].isna(), "Issue"] += "No GPS; "
      flags.loc[(flags["B2_total"] == 0), "Issue"] += "Household size 0; "
      flags.loc[flags["skip_rate"] >= 85, "Issue"] += "Skip answer at almost every filter; "
      flags.loc[flags["n_dont_know"] >= 5, "Issue"] += "5+ 'don't know'; "
      flags = flags[flags["Issue"] != ""]
      cols = [c for c in ["_id", "date", "woreda_lbl", "kebele_lbl", "enumerator_lbl", "hh_name", "dur", "Issue"]
              if c in flags]
      flags_out = flags[cols].rename(columns={"woreda_lbl": "Woreda", "kebele_lbl": "Kebele",
                                              "enumerator_lbl": "Enumerator", "dur": "Minutes"})
      st.dataframe(flags_out, hide_index=True, width="stretch")
      st.download_button("Download this list (CSV)", flags_out.to_csv(index=False).encode("utf-8-sig"),
                         "farm_africa_interviews_to_check.csv", "text/csv")

      with st.expander("Data check: variables the dashboard expects"):
          st.caption("If a chart is empty, look here. Ona leaves out questions that nobody has answered, "
                     "so 'No answers yet' usually means the question was skipped for every household so far "
                     "(for example F15a, which is asked only when coffee was sold). If it stays like this "
                     "after many interviews, the name may differ from the deployed form.")
          rows = []
          for v in sorted(set(NEEDED) - {"lat", "lon"}):
              if v not in raw_names:
                  status = "No answers yet"
              elif v in hh and hh[v].isna().all():
                  status = "All empty"
              else:
                  status = "OK"
              rows.append({"Variable": v, "Status": status,
                           "Answered": int(hh[v].notna().sum()) if v in hh else 0})
          chk = pd.DataFrame(rows)
          st.dataframe(chk[chk["Status"] != "OK"] if (chk["Status"] != "OK").any() else chk,
                       hide_index=True, width="stretch")

# ---------------------------------------------------------------- household profile
EDU_ORDER = ["No education", "Read and write / religious", "Primary", "Secondary", "TVET or higher"]
EDU_MAP = {"0": "No education", "1": "Read and write / religious", "8": "Read and write / religious",
           "2": "Primary", "3": "Primary", "4": "Secondary", "5": "Secondary",
           "6": "TVET or higher", "7": "TVET or higher"}

with tabs["Household profile"]:
    st.caption(f"{len(hh)} households interviewed (sidebar filters applied).")
    p = hh.copy()
    p["Head sex"] = p["B4"].map({"1": "Male", "2": "Female"})
    p["Head age group"] = pd.cut(p["B5"], [0, 29, 44, 59, 200],
                                 labels=["Under 30", "30–44", "45–59", "60 and above"]).astype("object")
    p["Head education"] = p["B8"].map(EDU_MAP)
    p["Female-headed"] = p["B12"].isin(["2", "3"])

    k = st.columns(4)
    k[0].metric("Female-headed", fmt(pct(p["Female-headed"], p["B12"].notna())[0], "%"),
                help="B12 = female-headed, de jure or de facto")
    k[1].metric("Avg. age of head", fmt(mean_of(p["B5"])[0]), help="B5, years")
    k[2].metric("Avg. household size", fmt(mean_of(p["B2_total"])[0]), help="B2_total")
    k[3].metric("Dependency ratio", fmt(mean_of(p["B3_dependency"], 2)[0]),
                help="Mean of B3 = (0–14 + 65+) ÷ 15–64")
    k = st.columns(4)
    youth = (p["B1c_m"] + p["B1c_f"] + p["B1d_m"] + p["B1d_f"]) > 0
    k[0].metric("Has youth (15–29)", fmt(pct(youth, p["B2_total"].notna())[0], "%"))
    k[1].metric("Has member with disability", fmt(pct(p["B17_sum"] > 0, p["B17_sum"].notna())[0], "%"),
                help="Any B17 (a)–(f) above 0 (Washington Group)")
    k[2].metric("Elderly-headed (65+)", fmt(pct(p["B5"] >= 65, p["B5"].notna())[0], "%"))
    k[3].metric("Youth-headed (15–29)", fmt(pct(p["B5"].between(15, 29), p["B5"].notna())[0], "%"))

    split = split_picker("prof_by")

    rows = []
    for b, band in AGE_BANDS.items():
        rows.append({"Age": band, "Sex": "Male", "Members": -p[f"B1{b}_m"].sum()})
        rows.append({"Age": band, "Sex": "Female", "Members": p[f"B1{b}_f"].sum()})
    pyr = pd.DataFrame(rows)
    if pyr["Members"].abs().sum() > 0:
        fig = px.bar(pyr, x="Members", y="Age", color="Sex", orientation="h",
                     category_orders={"Age": list(AGE_BANDS.values())[::-1]},
                     color_discrete_map={"Male": FOREST, "Female": FLAME},
                     title=f"Household members by age and sex (total {int(pyr['Members'].abs().sum()):,})",
                     custom_data=[pyr["Members"].abs()])
        fig.update_traces(hovertemplate="%{y}: %{customdata[0]:,}")
        mx = pyr["Members"].abs().max()
        fig.update_layout(barmode="relative", yaxis_title="", xaxis_title="Household members", height=380,
                          xaxis=dict(tickvals=[-mx, -mx / 2, 0, mx / 2, mx],
                                     ticktext=[f"{int(mx):,}", f"{int(mx / 2):,}", "0",
                                               f"{int(mx / 2):,}", f"{int(mx):,}"]))
        st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        share_chart(p, "B12_lbl" if "B12_lbl" in p else "B12", "Household headship type (%)", split=split)
    with c2:
        share_chart(p, "Head age group", "Age of household head (%)",
                    ["Under 30", "30–44", "45–59", "60 and above"], split)
    c3, c4 = st.columns(2)
    with c3:
        share_chart(p, "Head education", "Education of household head (%)", EDU_ORDER, split)
    with c4:
        share_chart(p, "B9_lbl" if "B9_lbl" in p else "B9",
                    "Main activity of household head, past 12 months (%)", split=split)
    c5, c6 = st.columns(2)
    with c5:
        share_chart(p, "B10_lbl" if "B10_lbl" in p else "B10", "Ethnic group of household head (%)", split=split)
    with c6:
        share_chart(p, "B6_lbl" if "B6_lbl" in p else "B6", "Marital status of household head (%)", split=split)

# ---------------------------------------------------------------- forest & livelihoods
D2_LABELS = choice_map("D2")

with tabs["Forest & livelihoods"]:
    st.caption(f"{len(hh)} households interviewed (sidebar filters applied).")
    f = hh.copy()
    k = st.columns(4)
    k[0].metric("Use natural forest", fmt(pct(f["C6"] == "1", f["C6"].notna())[0], "%"), help="C6 = Yes")
    k[1].metric("Walk to forest edge", fmt(median_of(f["C15"])[0], "min"), help="Median C15, minutes")
    k[2].metric("Active PFMC/FMG known", fmt(pct(f["E1"] == "1", f["E1"].notna())[0], "%"), help="E1 = Yes")
    k[3].metric("HARNESS activity in kebele", fmt(pct(f["s0_20_exposed"] == "1", f["s0_20_exposed"].notna())[0], "%"),
                help="0.20 = Yes")
    k = st.columns(4)
    k[0].metric("Coffee producers", fmt(pct(f["F15_producer"] == "1", f["F15_producer"].notna())[0], "%"),
                help="F15 = Yes")
    k[1].metric("NTFP producers", fmt(pct(f["ntfp_producer"] == 1, f["ntfp_producer"].notna())[0], "%"),
                help="Any D4 product produced")
    k[2].metric("Sell forest products", fmt(pct(f["forest_seller"] == 1, f["forest_seller"].notna())[0], "%"),
                help="Coffee, NTFP or forest sales (forest_seller)")
    k[3].metric("Median annual income", fmt(median_of(f["F2"])[0], "ETB"), help="F2 (sum of F1c)")

    split = split_picker("forest_by")
    c1, c2 = st.columns(2)
    with c1:
        share_chart(f, "D1_lbl" if "D1_lbl" in f else "D1", "How often household enters the forest (%)",
                    order=[choice_map("D1").get(str(i), str(i)) for i in range(1, 7)], split=split)
    with c2:
        # D2 multi-select: space-separated codes
        d2 = f["D2"].dropna().astype(str).str.split()
        if len(d2):
            cnt = d2.explode().map(D2_LABELS).value_counts()
            t = (100 * cnt / len(d2)).round(0).rename("%").reset_index().rename(columns={"D2": "Purpose"})
            t.columns = ["Purpose", "%"]
            fig = px.bar(t.sort_values("%"), x="%", y="Purpose", orientation="h", text="%",
                         title="Forest uses (% of forest users, multi-select)",
                         color_discrete_sequence=[FOREST])
            fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside", cliponaxis=False)
            fig.update_layout(xaxis=dict(range=[0, 110], showticklabels=False, title=""), yaxis_title="",
                              height=max(300, 32 * len(t) + 110))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No forest-use data yet (D2 is asked only when C6 = Yes).")

    st.subheader("Coffee")
    cof = f[f["F15_total_sold"] > 0]
    c3, c4 = st.columns(2)
    with c3:
        kinds = pd.DataFrame({"Type": ["Garden", "Semi-forest", "Forest"],
                              "kg sold": [f["F15_garden_sold"].sum(), f["F15_semi_forest_sold"].sum(),
                                          f["F15_forest_sold"].sum()]})
        if kinds["kg sold"].sum() > 0:
            fig = go.Figure(go.Pie(labels=kinds["Type"], values=kinds["kg sold"], hole=0.6, sort=False,
                                   marker=dict(colors=[SUNSHINE, FIELD, FOREST]),
                                   texttemplate="%{label}<br>%{percent:.0%}", textposition="outside"))
            fig.update_layout(title=f"Coffee sold by type ({kinds['kg sold'].sum():,.0f} kg)",
                              height=340, showlegend=False)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No coffee sales recorded yet.")
    with c4:
        ch_cols = {"F15a_a": "Cooperative / PFMC / union", "F15a_b": "Certified buyer",
                   "F15a_c": "Traceable (registered plot / EUDR)", "F15a_d": "Local trader, no traceability",
                   "F15a_e": "Other", "F15a_f": "Not known"}
        chs = pd.DataFrame({"Channel": list(ch_cols.values()),
                            "kg": [cof[c].sum() for c in ch_cols]})
        if chs["kg"].sum() > 0:
            chs["%"] = (100 * chs["kg"] / chs["kg"].sum()).round(0)
            fig = px.bar(chs.sort_values("%"), x="%", y="Channel", orientation="h", text="%",
                         title="Coffee sold by buyer channel (% of kg)", color_discrete_sequence=[FLAME])
            fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside", cliponaxis=False)
            fig.update_layout(xaxis=dict(range=[0, 110], showticklabels=False, title=""), yaxis_title="")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No buyer-channel data yet (F15a is asked only when coffee was sold).")
    if len(cof):
        st.caption(f"{len(cof)} households sold coffee · median price for main channel "
                   f"{fmt(median_of(cof['F15a_price'])[0], 'ETB')}/kg")

# ---------------------------------------------------------------- food security
with tabs["Food security"]:
    st.caption("HDDS = number of 12 food groups eaten in the past 24 hours. "
               "rCSI = reduced Coping Strategies Index (0–56).")
    k = st.columns(4)
    k[0].metric("Dietary diversity (HDDS)", fmt(mean_of(hh["H1_hdds"])[0]), help="Mean H1_hdds (0–12)")
    k[1].metric("Low diversity (HDDS ≤ 3)", fmt(pct(hh["H1_hdds"] <= 3, hh["H1_hdds"].notna())[0], "%"))
    k[2].metric("Coping index (rCSI)", fmt(mean_of(hh["H2_rcsi"])[0]), help="Mean H2_rcsi")
    k[3].metric("Shock in past 3 years", fmt(pct(hh["any_shock"] == 1, hh["any_shock"].notna())[0], "%"),
                help="Any L1 shock = Yes")
    split = split_picker("food_by")

    def cat_chart(series, order, colors, title):
        tmp = hh.assign(_cat=series).dropna(subset=["_cat"])
        if tmp.empty:
            st.info(f"No data yet for {title}.")
            return
        if split:
            t = (tmp.groupby([split, "_cat"]).size() / tmp.groupby(split).size() * 100).rename("%").reset_index()
            fig = px.bar(t, x=split, y="%", color="_cat", category_orders={"_cat": order},
                         color_discrete_map=dict(zip(order, colors)), title=title, labels={"_cat": "", split: ""})
        else:
            t = tmp["_cat"].value_counts(normalize=True).mul(100).reindex(order).fillna(0).rename("%").reset_index()
            t.columns = ["_cat", "%"]
            t["x"] = "All households"
            fig = px.bar(t, x="x", y="%", color="_cat", category_orders={"_cat": order},
                         color_discrete_map=dict(zip(order, colors)), title=title,
                         labels={"_cat": "", "x": ""}, text=t["%"].round(0))
        fig.update_layout(barmode="stack", yaxis_range=[0, 100])
        st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        cat_chart(pd.cut(hh["H1_hdds"], [-1, 3, 5, 12], labels=["Low (0–3)", "Medium (4–5)", "High (6–12)"]).astype("object"),
                  ["Low (0–3)", "Medium (4–5)", "High (6–12)"], [FLAME, SUNSHINE, FIELD], "Dietary diversity groups")
    with c2:
        cat_chart(pd.cut(hh["H2_rcsi"], [-1, 3, 18, 100], labels=["Minimal (0–3)", "Stressed (4–18)", "Crisis+ (19+)"]).astype("object"),
                  ["Crisis+ (19+)", "Stressed (4–18)", "Minimal (0–3)"], [FLAME, SUNSHINE, FIELD],
                  "Reduced Coping Strategies Index (rCSI)")

    fg = pd.DataFrame({"Food group": [questions.get(v, {}).get("label", v).split(":")[-1].strip() for v in H1_ITEMS],
                       "%": [pct(hh[v] == "1", hh[v].isin(["0", "1"]))[0] if v in hh else None for v in H1_ITEMS]})
    fg = fg.dropna()
    if len(fg):
        fig = px.bar(fg.sort_values("%"), x="%", y="Food group", orientation="h", text="%",
                     title="Food groups eaten in the past 24 hours (% of households)",
                     color_discrete_sequence=[FIELD])
        fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside", cliponaxis=False)
        fig.update_layout(xaxis=dict(range=[0, 110], showticklabels=False, title=""), yaxis_title="", height=460)
        st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- explore
with tabs["Explore a question"]:
    selects = {f"{q['label']}  [{name}]": name for name, q in questions.items()
               if q["type"] in ("select one", "select_one") and name + "_lbl" in hh}
    if selects:
        qlabel = st.selectbox("Question", list(selects))
        qname = selects[qlabel]
        split = st.selectbox("Split by", ["(none)"] + list(BREAKDOWNS.values()), key="ex_by")
        sub = hh.dropna(subset=[qname])
        if split == "(none)":
            vc = sub[qname + "_lbl"].value_counts().reset_index()
            vc.columns = ["Answer", "n"]
            vc["%"] = (100 * vc["n"] / vc["n"].sum()).round(1)
            st.plotly_chart(px.bar(vc, x="n", y="Answer", orientation="h", text="%",
                                   color_discrete_sequence=[FIELD], title=qlabel), width="stretch")
        else:
            sv = {v: k_ for k_, v in BREAKDOWNS.items()}[split] + "_lbl"
            ct = pd.crosstab(sub[sv], sub[qname + "_lbl"], normalize="index") * 100
            long = ct.round(1).reset_index().melt(id_vars=sv, var_name="Answer", value_name="%")
            st.plotly_chart(px.bar(long, x=sv, y="%", color="Answer", title=qlabel,
                                   labels={sv: split}), width="stretch")
        st.caption(f"Answered by {len(sub)} of {len(hh)} households.")
