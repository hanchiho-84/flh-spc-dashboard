import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
import glob

st.set_page_config(
    page_title="BIW CMM 量測分析",
    page_icon="🚗",
    layout="wide"
)

DATA_FOLDER = os.path.dirname(os.path.abspath(__file__))
META_COLS = ['Date', 'Time', 'Collector ID', 'OPERATOR', 'SHIFT',
             'Serial No.', 'MODEL', 'Build', 'MSA', 'PART']

# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    files = sorted(glob.glob(os.path.join(DATA_FOLDER, "BIW*.csv")))
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, skiprows=2, header=0)
            df = df.dropna(how='all')
            df = df[df['Date'].notna() & (df['Date'].astype(str).str.strip() != '')]
            dfs.append(df)
        except Exception as e:
            st.warning(f"讀取 {os.path.basename(f)} 失敗: {e}")
    if not dfs:
        return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)
    meas_cols = [c for c in combined.columns if c not in META_COLS
                 and not c.startswith('Code') and not c.startswith('E-level')
                 and not c.startswith('LD') and not c.startswith('FLH')
                 and not c.startswith('MF_') and not c.startswith('CX')]
    for col in meas_cols:
        combined[col] = pd.to_numeric(combined[col], errors='coerce')
    # Build a short x-label per row
    combined['_label'] = combined['Serial No.'].astype(str) + '\n(' + combined['Date'].astype(str) + ')'
    return combined

# ── Capability calculation ────────────────────────────────────────────────────

def calc_capability(series, usl, lsl):
    data = series.dropna()
    n = len(data)
    if n < 2:
        return dict(n=n, mean=None, std=None, cp=None, cpk=None,
                    cpu=None, cpl=None, min=None, max=None)
    mean = data.mean()
    std = data.std(ddof=1)
    mn = data.min()
    mx = data.max()
    if std == 0:
        return dict(n=n, mean=round(mean, 4), std=0, cp=None, cpk=None,
                    cpu=None, cpl=None, min=round(mn, 4), max=round(mx, 4))
    cp  = (usl - lsl) / (6 * std)
    cpu = (usl - mean) / (3 * std)
    cpl = (mean - lsl) / (3 * std)
    cpk = min(cpu, cpl)
    return dict(n=n, mean=round(mean, 4), std=round(std, 4),
                cp=round(cp, 3), cpk=round(cpk, 3),
                cpu=round(cpu, 3), cpl=round(cpl, 3),
                min=round(mn, 4), max=round(mx, 4))

def cpk_color(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    if val >= 1.67:
        return "background-color:#1a7a1a;color:white;font-weight:bold"
    if val >= 1.33:
        return "background-color:#4CAF50;color:white;font-weight:bold"
    if val >= 1.00:
        return "background-color:#FFC107;color:#333;font-weight:bold"
    return "background-color:#f44336;color:white;font-weight:bold"

# ── Column helpers ────────────────────────────────────────────────────────────

def get_meas_cols(df, col_type):
    return [c for c in df.columns
            if col_type in c and c not in META_COLS and not c.startswith('_')]

def apply_filters(cols, sides, axes):
    out = []
    for c in cols:
        side_ok = not sides or any(c.startswith(s) for s in sides)
        axis_ok = not axes  or any(c.endswith(a)  for a in axes)
        if side_ok and axis_ok:
            out.append(c)
    return out

# ── Load ──────────────────────────────────────────────────────────────────────

df = load_data()
if df.empty:
    st.error("找不到 BIW*.csv 檔案，請確認資料夾。")
    st.stop()

af_all = get_meas_cols(df, 'AF')
am_all = get_meas_cols(df, 'AM')

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ 設定")

    st.subheader("公差 (Tolerance)")
    tol_mode = st.radio("公差模式", ["對稱 ±", "自訂 USL / LSL"])
    if tol_mode == "對稱 ±":
        tol = st.number_input("± 公差 (mm)", value=1.5, step=0.1, min_value=0.01)
        usl, lsl = tol, -tol
    else:
        usl = st.number_input("USL (mm)", value=1.5, step=0.1)
        lsl = st.number_input("LSL (mm)", value=-1.5, step=0.1)
    st.caption(f"USL = **+{usl}**  |  LSL = **{lsl}**")

    st.divider()
    st.subheader("篩選")
    sides = st.multiselect("左 / 右 / 中", ['L', 'R', 'C'], default=['L', 'R', 'C'])
    axes  = st.multiselect("量測軸向",     ['X', 'Y', 'Z'], default=['X', 'Y', 'Z'])

    st.divider()
    st.caption(f"載入 **{len(df)}** 筆數據  |  **{len(af_all)}** 個 AF 點位")

af_cols = apply_filters(af_all, sides, axes)
am_cols = apply_filters(am_all, sides, axes)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🚗 BIW CX743 MF — CMM 量測分析")
st.caption("車身尺寸 Trend Chart  |  Cp / Cpk 製程能力分析")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_cap, tab_trend, tab_detail = st.tabs([
    "📋 製程能力總覽 (Cp / Cpk)",
    "📈 趨勢圖 (Trend Chart)",
    "🔍 單點深度分析",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – Capability Summary
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cap:
    st.subheader("AF 點位製程能力一覽")
    st.caption(f"公差: LSL = {lsl} mm  |  USL = +{usl} mm  |  目標 Cpk ≥ 1.33")

    if not af_cols:
        st.info("目前篩選條件下沒有 AF 欄位，請調整左側篩選。")
    else:
        rows = []
        for col in af_cols:
            r = calc_capability(df[col], usl, lsl)
            r['點位'] = col
            rows.append(r)

        sdf = pd.DataFrame(rows)[['點位', 'n', 'mean', 'std', 'min', 'max', 'cp', 'cpk']]
        sdf.columns = ['點位', '樣本數', '平均值', '標準差', '最小值', '最大值', 'Cp', 'Cpk']

        def style_table(df_s):
            styles = pd.DataFrame('', index=df_s.index, columns=df_s.columns)
            for col_name in ['Cp', 'Cpk']:
                for idx in df_s.index:
                    styles.loc[idx, col_name] = cpk_color(df_s.loc[idx, col_name])
            return styles

        st.dataframe(sdf.style.apply(style_table, axis=None),
                     use_container_width=True, height=520)

        valid_cpk = sdf['Cpk'].dropna()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("總點位數",          len(sdf))
        c2.metric("✅ Cpk ≥ 1.33",     int((valid_cpk >= 1.33).sum()))
        c3.metric("⚠️ 1.0 ≤ Cpk < 1.33", int(((valid_cpk >= 1.0) & (valid_cpk < 1.33)).sum()))
        c4.metric("❌ Cpk < 1.0",       int((valid_cpk < 1.0).sum()))

        # Cpk bar chart
        sdf_valid = sdf[sdf['Cpk'].notna()].sort_values('Cpk')
        bar_colors = [
            '#4CAF50' if v >= 1.33 else '#FFC107' if v >= 1.0 else '#f44336'
            for v in sdf_valid['Cpk']
        ]
        fig_bar = go.Figure(go.Bar(
            x=sdf_valid['點位'], y=sdf_valid['Cpk'],
            marker_color=bar_colors,
            text=sdf_valid['Cpk'].round(3),
            textposition='outside',
        ))
        fig_bar.add_hline(y=1.33, line_dash='dash', line_color='green',
                          annotation_text='目標 1.33', annotation_position='right')
        fig_bar.add_hline(y=1.00, line_dash='dash', line_color='orange',
                          annotation_text='警戒 1.00', annotation_position='right')
        fig_bar.update_layout(
            title='各點位 Cpk',
            xaxis_tickangle=-60,
            yaxis_title='Cpk',
            height=420,
            margin=dict(b=120)
        )
        st.plotly_chart(fig_bar, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 – Trend Charts
# ═══════════════════════════════════════════════════════════════════════════════
with tab_trend:
    st.subheader("AF 量測趨勢圖")

    if not af_cols:
        st.info("目前篩選條件下沒有 AF 欄位。")
    else:
        selected = st.multiselect(
            "選擇點位（可多選）",
            af_cols,
            default=af_cols[:min(6, len(af_cols))]
        )
        n_per_row = st.select_slider("每行圖表數", [1, 2, 3], value=2)

        x_idx    = list(range(len(df)))
        x_labels = df['_label'].tolist()

        for i in range(0, len(selected), n_per_row):
            cols_ui = st.columns(n_per_row)
            for j, col_name in enumerate(selected[i:i + n_per_row]):
                with cols_ui[j]:
                    y = df[col_name].values
                    r = calc_capability(df[col_name], usl, lsl)

                    fig = go.Figure()

                    # tolerance band
                    fig.add_hrect(y0=lsl, y1=usl, fillcolor='green',
                                  opacity=0.05, line_width=0)

                    # limit lines
                    fig.add_hline(y=usl, line_dash='dash', line_color='red',
                                  annotation_text=f'USL={usl}',
                                  annotation_position='top right')
                    fig.add_hline(y=lsl, line_dash='dash', line_color='red',
                                  annotation_text=f'LSL={lsl}',
                                  annotation_position='bottom right')
                    fig.add_hline(y=0, line_dash='dot', line_color='gray',
                                  annotation_text='Nom', annotation_position='right')

                    if r['mean'] is not None:
                        fig.add_hline(y=r['mean'], line_color='blue', line_width=1.2,
                                      annotation_text=f"x̄={r['mean']:.3f}",
                                      annotation_position='right')

                    # data
                    pt_colors = []
                    for v in y:
                        if np.isnan(v):
                            pt_colors.append('lightgray')
                        elif v > usl or v < lsl:
                            pt_colors.append('red')
                        else:
                            pt_colors.append('#1f77b4')

                    fig.add_trace(go.Scatter(
                        x=x_idx, y=y,
                        mode='lines+markers',
                        text=x_labels,
                        hovertemplate='%{text}<br><b>%{y:.3f} mm</b><extra></extra>',
                        marker=dict(color=pt_colors, size=9, line=dict(width=1, color='white')),
                        line=dict(color='#1f77b4', width=1.5)
                    ))

                    # Cpk annotation
                    if r['cpk'] is not None:
                        ann_color = ('green' if r['cpk'] >= 1.33
                                     else 'orange' if r['cpk'] >= 1.0 else 'red')
                        fig.add_annotation(
                            x=0.02, y=0.97, xref='paper', yref='paper',
                            text=f"Cp={r['cp']:.2f} | Cpk={r['cpk']:.2f}",
                            showarrow=False, align='left', valign='top',
                            font=dict(size=11, color=ann_color),
                            bgcolor='rgba(255,255,255,0.85)',
                            bordercolor=ann_color, borderwidth=1.5, borderpad=4
                        )

                    fig.update_layout(
                        title=dict(text=col_name, font_size=13),
                        xaxis=dict(
                            tickmode='array', tickvals=x_idx,
                            ticktext=[str(s) for s in df['Serial No.']],
                            tickangle=40, title='車身序號'
                        ),
                        yaxis_title='偏差 (mm)',
                        height=310,
                        showlegend=False,
                        margin=dict(t=40, b=70, l=55, r=110)
                    )
                    st.plotly_chart(fig, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 – Single Point Deep Analysis
# ═══════════════════════════════════════════════════════════════════════════════
with tab_detail:
    st.subheader("單點深度分析")

    all_analysis_cols = af_cols + am_cols
    if not all_analysis_cols:
        st.info("目前篩選條件下沒有可分析的欄位。")
        st.stop()

    sel = st.selectbox("選擇量測點位", all_analysis_cols,
                       format_func=lambda c: f"{'[AF]' if 'AF' in c else '[AM]'} {c}")

    data_s = df[sel].dropna()
    r = calc_capability(data_s, usl, lsl)
    is_af = 'AF' in sel

    left, right = st.columns([3, 1])

    with left:
        # ── Trend chart ──
        y     = df[sel].values
        x_idx = list(range(len(df)))

        fig_t = go.Figure()
        if is_af:
            fig_t.add_hrect(y0=lsl, y1=usl, fillcolor='green', opacity=0.06, line_width=0)
            fig_t.add_hline(y=usl, line_dash='dash', line_color='red',
                            annotation_text=f'USL={usl}', annotation_position='top right')
            fig_t.add_hline(y=lsl, line_dash='dash', line_color='red',
                            annotation_text=f'LSL={lsl}', annotation_position='bottom right')
            fig_t.add_hline(y=0, line_dash='dot', line_color='gray')

        if r['mean'] is not None:
            fig_t.add_hline(y=r['mean'], line_color='blue', line_width=1.5,
                            annotation_text=f"x̄={r['mean']:.4f}", annotation_position='right')
            if r['std'] and r['std'] > 0:
                for sigma, label in [(3, '+3σ'), (-3, '-3σ')]:
                    val = r['mean'] + sigma * r['std']
                    fig_t.add_hline(y=val, line_dash='dashdot', line_color='orange',
                                    annotation_text=f"{label}={val:.3f}",
                                    annotation_position='right')

        pt_col = []
        for v in y:
            if np.isnan(v):
                pt_col.append('lightgray')
            elif is_af and (v > usl or v < lsl):
                pt_col.append('red')
            else:
                pt_col.append('#1f77b4')

        fig_t.add_trace(go.Scatter(
            x=x_idx, y=y,
            mode='lines+markers',
            text=df['_label'].tolist(),
            hovertemplate='%{text}<br><b>%{y:.4f} mm</b><extra></extra>',
            marker=dict(color=pt_col, size=11, line=dict(width=1.5, color='white')),
            line=dict(color='#1f77b4', width=2)
        ))
        fig_t.update_layout(
            title=f"趨勢圖：{sel}",
            xaxis=dict(tickmode='array', tickvals=x_idx,
                       ticktext=[str(s) for s in df['Serial No.']],
                       tickangle=30, title='車身序號'),
            yaxis_title='值 (mm)',
            height=380, showlegend=False,
            margin=dict(t=45, b=70, l=55, r=120)
        )
        st.plotly_chart(fig_t, use_container_width=True)

        # ── Histogram ──
        if len(data_s) >= 2:
            fig_h = go.Figure()
            fig_h.add_trace(go.Histogram(
                x=data_s, nbinsx=max(5, len(data_s)),
                marker_color='#1f77b4', opacity=0.75, name='量測值'
            ))
            if is_af:
                fig_h.add_vline(x=usl, line_dash='dash', line_color='red',
                                annotation_text=f'USL={usl}')
                fig_h.add_vline(x=lsl, line_dash='dash', line_color='red',
                                annotation_text=f'LSL={lsl}')
            if r['mean'] is not None:
                fig_h.add_vline(x=r['mean'], line_color='blue',
                                annotation_text=f"x̄={r['mean']:.4f}")
            fig_h.update_layout(title='量測值分佈', height=270,
                                showlegend=False, margin=dict(t=40, b=40))
            st.plotly_chart(fig_h, use_container_width=True)

    with right:
        st.subheader("統計摘要")
        st.metric("樣本數 (n)", r['n'])
        if r['mean'] is not None:
            st.metric("平均值", f"{r['mean']:.4f} mm")
            st.metric("標準差", f"{r['std']:.4f} mm")
            st.metric("最小值", f"{r['min']:.4f} mm")
            st.metric("最大值", f"{r['max']:.4f} mm")

        if is_af:
            st.divider()
            st.subheader("製程能力")
            if r['cp'] is not None:
                def badge(v):
                    if v >= 1.33: return "✅ 合格"
                    if v >= 1.00: return "⚠️ 注意"
                    return "❌ 不合格"

                st.metric("Cp",  f"{r['cp']:.3f}",  badge(r['cp']))
                st.metric("Cpk", f"{r['cpk']:.3f}", badge(r['cpk']))
                st.metric("CPU", f"{r['cpu']:.3f}")
                st.metric("CPL", f"{r['cpl']:.3f}")

                if r['cpk'] < 1.0:
                    st.error(f"Cpk = {r['cpk']:.3f}，製程能力不足")
                elif r['cpk'] < 1.33:
                    st.warning(f"Cpk = {r['cpk']:.3f}，建議改善")
                else:
                    st.success(f"Cpk = {r['cpk']:.3f}，製程能力良好")
            else:
                st.info("樣本數不足")

        st.divider()
        st.subheader("原始數據")
        raw = pd.DataFrame({
            '車身序號': df['Serial No.'],
            '日期':     df['Date'],
            '量測值':   df[sel].round(4)
        })
        st.dataframe(raw, use_container_width=True, hide_index=True)
