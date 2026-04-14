import streamlit as st
import pandas as pd
from datetime import date
from st_supabase_connection import SupabaseConnection

# ── Configuración de página ──────────────────────────────────────────────────
st.set_page_config(
    page_title="¿QuiénSigue?",
    page_icon="🌙",
    layout="wide",
)

INGENIEROS = [
    "Pedro Zapata",
    "Pedro Quezada",
    "Juan Zuniga",
    "Felipe Becerra",
    "Felipe Dominguez",
    "Moises Diaz",
]

# ── Conexión a Supabase ──────────────────────────────────────────────────────
conn = st.connection("supabase", type=SupabaseConnection)


# ── Helpers ──────────────────────────────────────────────────────────────────
def dias_ganados_por_fecha(f: date) -> int:
    """Lunes–Viernes → 1 | Sábado–Domingo → 2."""
    return 2 if f.weekday() >= 5 else 1


@st.cache_data(ttl=30)
def get_controles() -> pd.DataFrame:
    resp = conn.table("controles").select("*").order("fecha", desc=True).execute()
    if resp.data:
        return pd.DataFrame(resp.data)
    return pd.DataFrame(
        columns=["id", "created_at", "ingeniero", "fecha",
                 "tipo", "dias_ganados", "dias_usados", "descripcion"]
    )


def insertar_control(ingeniero, fecha, tipo, dias_ganados, dias_usados, descripcion=""):
    conn.table("controles").insert({
        "ingeniero": ingeniero,
        "fecha": str(fecha),
        "tipo": tipo,
        "dias_ganados": int(dias_ganados),
        "dias_usados": int(dias_usados),
        "descripcion": descripcion,
    }).execute()
    st.cache_data.clear()  # Invalida la caché tras cada escritura


# ── Título ───────────────────────────────────────────────────────────────────
st.title("🌙 ¿QuiénSigue?")
st.caption("Gestión de turnos nocturnos y días compensatorios")

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_dash, tab_turno, tab_canje, tab_hist = st.tabs([
    "📊 Dashboard",
    "📝 Registrar Turno",
    "☀️ Solicitar Compensatorio",
    "📋 Historial",
])


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.header("Saldo de Compensatorios", divider="blue")

    df = get_controles()

    if df.empty:
        st.info("Aún no hay registros en la base de datos.")
    else:
        # Resumen agregado
        resumen = (
            df.groupby("ingeniero")
            .agg(ganados=("dias_ganados", "sum"), usados=("dias_usados", "sum"))
            .assign(saldo=lambda x: x["ganados"] - x["usados"])
            .reset_index()
        )

        # Incluir ingenieros sin movimientos
        base = pd.DataFrame({"ingeniero": INGENIEROS})
        resumen = base.merge(resumen, on="ingeniero", how="left").fillna(0)
        resumen[["ganados", "usados", "saldo"]] = (
            resumen[["ganados", "usados", "saldo"]].astype(int)
        )

        # Métricas en tarjetas
        cols = st.columns(len(INGENIEROS))
        for i, row in resumen.iterrows():
            with cols[i]:
                st.metric(
                    label=row["ingeniero"].split()[0],
                    value=f"{row['saldo']} día{'s' if abs(row['saldo']) != 1 else ''}",
                    delta=f"+{row['ganados']} ganados / -{row['usados']} usados",
                    delta_color="normal" if row["saldo"] >= 0 else "inverse",
                    help=row["ingeniero"],
                )

        st.divider()

        # Tabla resumen con color en saldo
        tabla = resumen.copy()
        tabla.columns = ["Ingeniero", "Días Ganados", "Días Usados", "Saldo Neto"]

        def _color_saldo(val):
            if not isinstance(val, (int, float)):
                return ""
            return "color: green" if val > 0 else ("color: red" if val < 0 else "color: gray")

        st.dataframe(
            tabla.style.map(_color_saldo, subset=["Saldo Neto"]),
            use_container_width=True,
            hide_index=True,
        )


# ════════════════════════════════════════════════════════════════════════════
# REGISTRAR TURNO NOCTURNO
# ════════════════════════════════════════════════════════════════════════════
with tab_turno:
    st.header("Registrar Control Nocturno", divider="blue")

    with st.form("form_turno", clear_on_submit=True):
        ingeniero = st.selectbox("Ingeniero", INGENIEROS)
        fecha = st.date_input("Fecha del turno", value=date.today())
        descripcion = st.text_area(
            "Descripción (opcional)",
            placeholder="Ej: Deploy versión 3.2 en producción…",
        )

        dias = dias_ganados_por_fecha(fecha)
        tipo_dia = "fin de semana 🎉" if fecha.weekday() >= 5 else "día laboral"
        st.info(
            f"📅 **{fecha.strftime('%A %d/%m/%Y')}** ({tipo_dia}) → "
            f"**+{dias} día(s) compensatorio(s)**"
        )

        submitted = st.form_submit_button(
            "💾 Guardar turno", use_container_width=True, type="primary"
        )

    if submitted:
        insertar_control(
            ingeniero, fecha,
            tipo="Control Nocturno",
            dias_ganados=dias,
            dias_usados=0,
            descripcion=descripcion,
        )
        st.balloons()
        st.success(
            f"✅ Turno de **{ingeniero}** del **{fecha.strftime('%d/%m/%Y')}** "
            f"registrado correctamente (+{dias} día(s))."
        )


# ════════════════════════════════════════════════════════════════════════════
# SOLICITAR COMPENSATORIO (CANJE)
# ════════════════════════════════════════════════════════════════════════════
with tab_canje:
    st.header("Solicitar Día Compensatorio", divider="orange")
    st.caption("Registra un canje: se descuenta 1 día del saldo del ingeniero.")

    df_canje = get_controles()

    with st.form("form_canje", clear_on_submit=True):
        ingeniero_c = st.selectbox("Ingeniero", INGENIEROS, key="ing_canje")

        # Saldo actual antes de descontar
        if not df_canje.empty and ingeniero_c in df_canje["ingeniero"].values:
            filtro = df_canje["ingeniero"] == ingeniero_c
            saldo_actual = int(
                df_canje.loc[filtro, "dias_ganados"].sum()
                - df_canje.loc[filtro, "dias_usados"].sum()
            )
        else:
            saldo_actual = 0

        icono = "🟢" if saldo_actual > 0 else ("🔴" if saldo_actual < 0 else "⚪")
        st.write(f"Saldo actual de **{ingeniero_c}**: {icono} **{saldo_actual} día(s)**")

        if saldo_actual <= 0:
            st.warning("⚠️ Este ingeniero no tiene días disponibles.")

        fecha_c = st.date_input("Fecha del día libre", value=date.today(), key="fecha_canje")
        descripcion_c = st.text_area("Motivo (opcional)", key="desc_canje")

        submitted_c = st.form_submit_button(
            "📤 Registrar canje", use_container_width=True, type="primary"
        )

    if submitted_c:
        insertar_control(
            ingeniero_c, fecha_c,
            tipo="Canje de Día",
            dias_ganados=0,
            dias_usados=1,
            descripcion=descripcion_c,
        )
        st.success(
            f"✅ Día compensatorio de **{ingeniero_c}** el "
            f"**{fecha_c.strftime('%d/%m/%Y')}** registrado (-1 día)."
        )


# ════════════════════════════════════════════════════════════════════════════
# HISTORIAL
# ════════════════════════════════════════════════════════════════════════════
with tab_hist:
    st.header("Últimos 10 Movimientos", divider="blue")

    df_hist = get_controles()

    if df_hist.empty:
        st.info("No hay registros aún.")
    else:
        mostrar = df_hist.head(10)[
            ["ingeniero", "fecha", "tipo", "dias_ganados", "dias_usados", "descripcion"]
        ].copy()
        mostrar["fecha"] = pd.to_datetime(mostrar["fecha"]).dt.strftime("%d/%m/%Y")
        mostrar.columns = [
            "Ingeniero", "Fecha", "Tipo",
            "Días Ganados", "Días Usados", "Descripción",
        ]

        def _color_tipo(val):
            if val == "Control Nocturno":
                return "background-color: #1e3a5f; color: white"
            if val == "Canje de Día":
                return "background-color: #3a1e1e; color: white"
            return ""

        st.dataframe(
            mostrar.style.map(_color_tipo, subset=["Tipo"]),
            use_container_width=True,
            hide_index=True,
        )

        if st.button("🔄 Actualizar historial"):
            st.cache_data.clear()
            st.rerun()
