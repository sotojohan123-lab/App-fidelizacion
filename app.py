import streamlit as st
import pandas as pd
import io
import plotly.express as px
import plotly.graph_objects as go 
from datetime import timedelta

# --- 1. CONFIGURACIÓN INICIAL DEL DASHBOARD (Streamlit) ---
st.set_page_config(
    page_title="BI - Diagnóstico de Oferta (Streamlit)", 
    layout="wide", 
    initial_sidebar_state="expanded",
    # Mejorar el título mostrado en la pestaña del navegador
    page_icon="🛍️" 
)

# --- 2. CARGA Y MODELADO DE DATOS (Capa ETL/Model) ---

@st.cache_data
def load_and_model_data():
    """
    Carga los archivos CSV, realiza la limpieza inicial y ejecuta el modelado de datos 
    (JOINs) para crear el DataFrame Maestro.
    
    Retorna:
        - df_maestro (pd.DataFrame): DataFrame unificado con todas las dimensiones.
        - df_clientes (pd.DataFrame): DataFrame de clientes (usado para exportación).
    """
    try:
        # Rutas relativas simples funcionan en Streamlit Cloud
        df_ventas = pd.read_csv("Ventas.csv")
        df_clientes = pd.read_csv("Clientes.csv") 
        df_productos = pd.read_csv("Productos.csv")
        df_negocios = pd.read_csv("Negocios.csv")
    except FileNotFoundError as e:
        st.error(f"Error: No se encontró el archivo de datos {e}. Asegúrate de que todos los CSV estén en la misma carpeta.")
        return None, None

    # Normalización y Limpieza de Tipos de Datos
    df_ventas['Fecha'] = pd.to_datetime(df_ventas['Fecha'], errors="coerce")
    
    # --- MODELADO DE DATOS (JOINs) ---
    
    # 1. Ventas + Productos: Añadir detalles de Producto
    df_maestro = pd.merge(df_ventas, df_productos[['ProductoID', 'Categoria', 'NombreProducto']], 
                         on='ProductoID', how='left')
    
    # 2. Maestro + Clientes: Añadir dimensiones de Cliente (Nombre, Segmento, Ciudad)
    df_maestro = pd.merge(df_maestro, df_clientes[['ClienteID', 'Nombre', 'Segmento', 'Ciudad']], 
                         on='ClienteID', how='left')
    
    # 3. Maestro + Negocios: Añadir nombre de Tienda/Punto de Venta
    df_maestro = pd.merge(df_maestro, df_negocios[['NegocioID', 'NombreTienda']], 
                         on='NegocioID', how='left')
                         
    # Limpieza final: Eliminar filas sin datos esenciales
    df_maestro.dropna(subset=['Fecha', 'ClienteID', 'VentaID'], inplace=True)

    return df_maestro, df_clientes

# Ejecución de la Carga de Datos
df_maestro, df_clientes = load_and_model_data()

# --- 3. UI/UX: LAYOUT Y FILTROS ---

st.title("🛍️ Diagnóstico de Oferta y Fidelización")
st.markdown("Dashboard de Business Intelligence para el Jefe de Loyalty.")

if df_maestro is None:
    st.stop()
    
# Definición de rangos de fecha disponibles
min_date = df_maestro['Fecha'].min().date()
max_date = df_maestro['Fecha'].max().date()


# BARRA LATERAL (Filtros de Segmentación Ad-hoc)
with st.sidebar:
    st.header("⚙️ Configuración del Análisis")

    # 1. Filtro de Producto/Oferta (Ahora con un título más claro)
    prod_candidates = df_maestro['ProductoID'].astype(str).unique().tolist()
    offer_codes = st.multiselect(
        "1. Códigos de Producto en la Oferta", 
        options=sorted(prod_candidates), 
        default=prod_candidates,
        help="Seleccione los IDs de producto que forman parte de la campaña a analizar."
    )

    st.markdown("---")
    st.subheader("Segmentación Geográfica y Cliente")
    
    # 2. Filtros Adicionales (Segmentación Geográfica y Cliente)
    selected_ciudades = st.multiselect(
        "Filtrar por Ciudad", 
        options=df_maestro['Ciudad'].dropna().unique(), 
        default=df_maestro['Ciudad'].dropna().unique()
    )

    selected_segmentos = st.multiselect(
        "Filtrar por Segmento del Cliente", 
        options=df_maestro['Segmento'].dropna().unique(), 
        default=df_maestro['Segmento'].dropna().unique()
    )
    
    st.markdown("---")
    st.subheader("Período y Umbrales")

    # 3. Filtro de Período de Análisis
    col_date_start, col_date_end = st.columns(2)
    with col_date_start:
        start_date = st.date_input("Fecha Inicio", value=min_date, min_value=min_date, max_value=max_date)
    with col_date_end:
        end_date = st.date_input("Fecha Fin", value=max_date, min_value=min_date, max_value=max_date)

    # 4. Filtro de Umbral de Venta (Monto Mínimo)
    min_amount = st.number_input(
        "Monto Mínimo por Transacción (Oferta)", 
        value=55000, 
        step=1000, 
        format="%i", # Asegurar formato entero
        help="Umbral de $55.000 para definir un 'Cliente Qualifier' en el período principal."
    )
    
    st.markdown("---")
    # 5. Periodo Comparativo
    st.subheader("Análisis de Fidelización")
    use_compar = st.checkbox("Activar Período Comparativo", value=True)

v_period = pd.DataFrame() 

if offer_codes:
    
    # --- 4. LÓGICA DE FILTRADO Y CÁLCULOS ---
    
    # 1. Filtro Temporal (Período Principal)
    mask_date = (df_maestro['Fecha'].dt.date >= pd.to_datetime(start_date).date()) & \
                (df_maestro['Fecha'].dt.date <= pd.to_datetime(end_date).date())
    
    # 2. Filtro de Oferta (Productos Seleccionados)
    mask_offer = df_maestro['ProductoID'].astype(str).isin([str(x) for x in offer_codes])
    
    # 3. Filtros Ad-Hoc
    mask_adhoc_city = df_maestro['Ciudad'].isin(selected_ciudades)
    mask_adhoc_segment = df_maestro['Segmento'].isin(selected_segmentos)
    
    # DataFrame filtrado para el período principal
    v_period = df_maestro.loc[mask_date & mask_offer & mask_adhoc_city & mask_adhoc_segment].copy()

    
    # CÁLCULOS DE KPIS BÁSICOS Y QUALIFIERS
    
    # 1. Agregación a nivel Transacción: Sumar el monto vendido de la OFERTA por transacción
    trans_offer = v_period.groupby('VentaID').agg(
        ClienteID=('ClienteID', "first"),
        Fecha=('Fecha', "first"),
        VentaOferta=('ValorVenta', "sum"),
        ItemsOferta=('ProductoID', "count")
    ).reset_index()

    # 2. Identificación de Transacciones "Qualifying" (que cumplen el umbral)
    qualifying_trans = trans_offer[trans_offer["VentaOferta"] >= float(min_amount)]
    total_clients_qual = qualifying_trans['ClienteID'].nunique()
    
    # KPIs Generales
    venta_total = v_period['ValorVenta'].sum()
    transacciones = v_period['VentaID'].nunique()
    clientes_unicos = v_period['ClienteID'].nunique()
    
    # --- 5. VISUALIZACIÓN DE KPIS PRINCIPALES (Mejora estética con íconos y formato) ---
    
    st.subheader("📈 Indicadores Clave del Período de Oferta")
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("💰 Venta Total (Oferta)", f"${venta_total:,.0f}")
    col2.metric("🛒 Transacciones Únicas", f"{transacciones:,}")
    col3.metric("👤 Clientes Únicos", f"{clientes_unicos:,}")
    col4.metric("🏆 Clientes Qualifiers", f"{total_clients_qual:,}", 
                help=f"Clientes con al menos una transacción >= ${min_amount:,.0f}")
    
    
    # --- 6. ANÁLISIS DE FIDELIZACIÓN (Comparativo) ---
    st.markdown("---")
    st.subheader("🔄 Análisis de Fidelización y Retención")

    if use_compar:
        # Lógica para definir el período comparativo (misma duración, inmediatamente anterior)
        duration = end_date - start_date
        
        default_compar_start = max(min_date, start_date - duration - timedelta(days=1))
        default_compar_end = max(min_date, start_date - timedelta(days=1))
        
        # Filtros de UI para el período comparativo
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            compar_start = st.date_input("Compar. Inicio", value=default_compar_start, min_value=min_date, max_value=max_date, key="c_start")
        with col_c2:
            compar_end = st.date_input("Compar. Fin", value=default_compar_end, min_value=min_date, max_value=max_date, key="c_end")
        with col_c3:
            compar_min = st.number_input("Umbral Mín. Compar.", value=30000, step=1000, format="%i", help="Monto mínimo para calificar en el período anterior.")

        # Aplicación de filtros comparativos
        mask_compar = (df_maestro['Fecha'].dt.date >= pd.to_datetime(compar_start).date()) & \
                      (df_maestro['Fecha'].dt.date <= pd.to_datetime(compar_end).date())
        
        v_compar = df_maestro.loc[mask_compar & mask_offer].copy()
        
        # Cálculo de clientes Qualifiers en período Previo
        clients_prev_sum = v_compar.groupby('ClienteID').agg(
            Venta_Prev=(('ValorVenta', "sum"))
        ).reset_index()
        
        clients_with_prev_qual = clients_prev_sum[clients_prev_sum["Venta_Prev"] >= float(compar_min)]
        
        # Intersección: Clientes que cumplen en AMBOS períodos
        clientes_qual_actual = qualifying_trans['ClienteID'].unique()
        clientes_qual_previo = clients_with_prev_qual['ClienteID'].unique()
        fidelizados = set(clientes_qual_actual).intersection(set(clientes_qual_previo))
        
        # Métricas y Variación
        venta_compar_total = v_compar['ValorVenta'].sum()
        
        if venta_compar_total == 0:
            variacion = "N/A"
        else:
            variacion_calc = ((venta_total - venta_compar_total) / venta_compar_total) * 100
            variacion = f"{variacion_calc:+.1f}%" # Usar + para mostrar signo positivo
        
        
        # Visualización de Métricas de Fidelización
        col_f1, col_f2, col_f3 = st.columns(3)
        col_f1.metric("Venta Comparativo", f"${venta_compar_total:,.0f}", variacion)
        col_f2.metric("Clientes Previos Qualifiers", f"{len(clientes_qual_previo):,}")
        col_f3.metric("🎯 Clientes Fidelizados", f"{len(fidelizados):,}", 
                      help="Clientes que cumplen el umbral en AMBOS períodos, demostrando retención.")


    # --- 7. GRÁFICO DE TENDENCIA (Ajustes Estéticos) ---
    
    st.markdown("---")
    st.subheader("📉 Tendencia Diaria de Venta")
    
    sales_daily = v_period.groupby(v_period['Fecha'].dt.date).agg(VentaTotal=('ValorVenta', 'sum')).reset_index()
    sales_daily['Fecha'] = pd.to_datetime(sales_daily['Fecha'])
    
    fig_trend = go.Figure()
    
    # Añadir la línea y texto fijo (solicitud del usuario)
    fig_trend.add_trace(go.Scatter(
        x=sales_daily['Fecha'], 
        y=sales_daily['VentaTotal'], 
        mode='lines+markers+text', 
        name='Venta Diaria',
        text=[f"${v:,.0f}" for v in sales_daily['VentaTotal']], 
        textposition="top center", 
        line=dict(color='#007BFF', width=3), # Color azul corporativo, línea más gruesa
        marker=dict(size=8, color='#0056B3', line=dict(width=1, color='DarkSlateGrey')), 
        hovertemplate='<b>Fecha:</b> %{x|%Y-%m-%d}<br><b>Venta Total:</b> $%{y:,.0f}<extra></extra>' 
    ))

    # Mejorar el layout (ahora sin fondo blanco)
    fig_trend.update_layout(
        title='Evolución Diaria de la Venta de Productos de la Oferta',
        xaxis_title="Fecha",
        yaxis_title="Venta Total (COP)",
        xaxis=dict(tickformat="%Y-%m-%d"),
        margin=dict(l=20, r=20, t=60, b=20),
        # ELIMINAMOS explícitamente el fondo blanco para usar el fondo del Streamlit theme
        # plot_bgcolor='white',
        # paper_bgcolor='white', 
        hovermode="x unified"
    )
    
    st.plotly_chart(fig_trend, use_container_width=True)

    
    # --- 8. ANÁLISIS PARETO (Mejora estética de la tabla) ---
    
    st.markdown("---")
    st.subheader("🥇 Top Productos y Clientes (Principio 80/20)")
    
    # Cálculo del Pareto a nivel de Producto y Cliente (Detalle)
    pareto_detalle = v_period.groupby(['ProductoID', 'NombreProducto', 'ClienteID', 'Nombre']).agg(
        VentaTotal=('ValorVenta', "sum")
    ).reset_index().sort_values("VentaTotal", ascending=False)
    
    # Cálculo del Pareto a nivel de Producto (para el % Acumulado)
    pareto_productos = pareto_detalle.groupby(['ProductoID', 'NombreProducto']).agg(
        VentaProducto=('VentaTotal', "sum")
    ).reset_index().sort_values("VentaProducto", ascending=False)
    
    pareto_productos["VentaTotal_Cum"] = pareto_productos["VentaProducto"].cumsum()
    total = pareto_productos["VentaProducto"].sum()
    pareto_productos["%_Acumulado"] = pareto_productos["VentaTotal_Cum"] / total
    
    # Unión y Display
    pareto_df = pd.merge(pareto_detalle, pareto_productos[['ProductoID', '%_Acumulado']], on='ProductoID', how='left')
    
    # Filtramos para el 80% y preparamos las columnas para el display
    pareto_display = pareto_df[pareto_df["%_Acumulado"] <= 0.8].rename(
        columns={
            'VentaTotal': 'Venta por Cliente', 
            'Nombre': 'Nombre Cliente',
            'ClienteID': 'ID Cliente'
        }
    )

    st.markdown("#### Detalle de Clientes que generan el 80% de la Venta (Top 10)")
    
    # Mejora: Usar un dataframe con formato de columnas
    st.dataframe(
        pareto_display[['ProductoID', 'NombreProducto', 'Venta por Cliente', 'ID Cliente', 'Nombre Cliente', '%_Acumulado']].head(10), 
        use_container_width=True,
        hide_index=True,
        column_config={
            "Venta por Cliente": st.column_config.NumberColumn(
                "Venta por Cliente",
                format="$%i", # Formato de moneda
            ),
            "%_Acumulado": st.column_config.ProgressColumn(
                "Acumulado %",
                format="%.2f",
                min_value=0,
                max_value=1,
            )
        }
    )


    # --- 9. EXPORTAR RESULTADOS ---
    st.markdown("---")
    st.subheader("📥 Exportación de Resultados para Análisis Adicional")
    
    # Crear un buffer en memoria para el archivo Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        
        # 1. Clientes Qualifiers (Ahora con más contexto de Cliente)
        # Campos de contexto necesarios: Segmento, Ciudad, Nombre
        cliente_contexto = df_maestro[['ClienteID', 'Nombre', 'Segmento', 'Ciudad']].drop_duplicates()
        qualifying_clients = qualifying_trans[['ClienteID']].drop_duplicates().merge(
            cliente_contexto, 
            on='ClienteID', 
            how='left'
        )
        qualifying_clients.to_excel(writer, index=False, sheet_name="Clientes_Qualifiers")
        
        # 2. Transacciones que Cumplieron el Umbral (Ahora con Tienda y Categoría)
        # Unir las transacciones que calificaron (qualifying_trans) con el detalle maestro (v_period)
        trans_detalle = v_period.merge(
            qualifying_trans[['VentaID', 'VentaOferta']], # Solo las ventas que pasaron el umbral
            on='VentaID',
            how='inner'
        )
        
        # Seleccionar y renombrar las columnas relevantes para el análisis transaccional
        trans_export = trans_detalle[[
            'VentaID', 'Fecha', 'ClienteID', 'ProductoID', 'NombreProducto', 
            'Categoria', 'NombreTienda', 'ValorVenta' # ValorVenta es la venta del ítem, no la VentaOferta total
        ]]
        
        # Exportar
        trans_export.to_excel(writer, index=False, sheet_name="Transacciones_Umbral")
        
        # 3. Pareto de Productos (Exporta con Segmento, Ciudad y Tienda)
        # Unir el Pareto calculado con las dimensiones de Tienda (NegocioID) y Cliente (Segmento, Ciudad)
        pareto_full_context = v_period.groupby([
            'ProductoID', 'NombreProducto', 'ClienteID', 'Nombre', 
            'Segmento', 'Ciudad', 'NegocioID', 'NombreTienda'
        ]).agg(
            VentaTotal=('ValorVenta', "sum")
        ).reset_index().sort_values("VentaTotal", ascending=False)
        
        # Calcular el % Acumulado nuevamente sobre el nuevo detalle
        pareto_productos_venta = pareto_full_context.groupby(['ProductoID', 'NombreProducto']).agg(
            VentaProducto=('VentaTotal', "sum")
        ).reset_index().sort_values("VentaProducto", ascending=False)
        
        pareto_productos_venta["VentaTotal_Cum"] = pareto_productos_venta["VentaProducto"].cumsum()
        total_venta_oferta = pareto_productos_venta["VentaProducto"].sum()
        pareto_productos_venta["%_Acumulado"] = pareto_productos_venta["VentaTotal_Cum"] / total_venta_oferta
        
        # Unir para obtener el % Acumulado en el detalle final
        pareto_export = pd.merge(pareto_full_context, pareto_productos_venta[['ProductoID', '%_Acumulado']], on='ProductoID', how='left')
        
        # Exportar el detalle completo de Pareto
        pareto_export.to_excel(writer, index=False, sheet_name="Pareto_Detalle_Completo")
        
        # 4. Clientes Fidelizados (Intersección) - Sin cambios, solo añade contexto
        if use_compar:
            df_fidelizados_contexto = df_clientes[df_clientes['ClienteID'].isin(fidelizados)].merge(
                cliente_contexto, 
                on=['ClienteID', 'Nombre', 'Segmento', 'Ciudad'], 
                how='left'
            ).drop_duplicates()
            
            df_fidelizados_contexto.to_excel(writer, index=False, sheet_name="Clientes_Fidelizados")
            
    st.download_button(
        "💾 Descargar Reporte Completo (Excel)", 
        data=output.getvalue(), 
        file_name=f"diagnostico_oferta_{start_date}_a_{end_date}.xlsx", 
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("💡 Por favor, selecciona al menos un producto en la sección 'Códigos de Producto en la Oferta' en la barra lateral izquierda para comenzar el análisis.")
