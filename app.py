from datetime import datetime
import hashlib
import io

from pypdf import PdfReader, PdfWriter
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from valeria import RULESET
from valeria.models import LABELS
from valeria.pdf import render_page
from valeria.references import read_reference
from valeria.service import analyze, report_text, report_csv

st.set_page_config(page_title="ValerIA · Cuentas de cobro",page_icon="📋",layout="wide")


def secret(name):
    try: return str(st.secrets.get(name,""))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError): return ""


def reference_input(title, key, setting):
    uploaded=st.file_uploader(title,type=["xlsx","csv"],key=key,max_upload_size=10)
    data=None; name=""
    if uploaded is not None:
        data=uploaded.getvalue(); name=uploaded.name
    elif secret(setting):
        try:
            file=Path(secret(setting))
            if file.stat().st_size>10*1024*1024: raise ValueError("Base mayor a 10 MB.")
            data=file.read_bytes(); name=file.name
            st.caption(f"Base del servidor: {name}")
        except (OSError,ValueError):
            st.warning("La base configurada no se puede leer. Puede cargarla aquí.")
    return data,name


def merge_pdfs(files):
    """Une los archivos en orden y conserva intacto un PDF único."""
    if not files:
        return None
    if sum(len(data) for name, data in files) > 40 * 1024 * 1024:
        raise ValueError("Los PDF cargados superan el límite total de 40 MB.")
    writer = PdfWriter()
    total_pages = 0
    try:
        for name, data in files:
            if not data.startswith(b"%PDF-"):
                raise ValueError(f"El archivo {name} no es un PDF válido.")
            try:
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted:
                    raise ValueError(f"El archivo {name} tiene contraseña. Carga una copia sin contraseña.")
                count = len(reader.pages)
                if not count:
                    raise ValueError(f"El archivo {name} no contiene páginas.")
                total_pages += count
                if total_pages > 100:
                    raise ValueError("Los PDF cargados superan el límite total de 100 páginas.")
                if len(files) > 1:
                    writer.append(reader, import_outline=False)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"No se pudo leer {name}. Comprueba que el PDF esté completo y sin contraseña.") from exc
        if len(files) == 1:
            return files[0][1]
        output = io.BytesIO()
        writer.write(output)
        result = output.getvalue()
        if len(result) > 40 * 1024 * 1024:
            raise ValueError("El PDF consolidado supera el límite de 40 MB.")
        return result
    finally:
        writer.close()


st.title("ValerIA")
st.subheader("Revisión de cuentas de cobro")
st.write("Carga uno o varios PDF. ValerIA los unirá para revisar la cuenta de cobro y señalar las páginas y los datos que debes verificar.")

with st.sidebar:
    st.header("Bases de referencia")
    secop_url=st.text_input("Ruta PAR de la base SECOP",value=secret("ORACLE_PAR_URL"),type="password",help="Consulta automática por contrato del informe. El enlace no se incluye en los reportes.")
    st.caption("SECOP prima sobre los PDF. Honorarios inferidos: referencia orientativa; alerta si la diferencia supera el 10 %.")
    crp_data,crp_name=reference_input("Listado CRP (Excel o CSV)","crp_upload","CRP_PATH")
    monthly_data,monthly_name=reference_input("Valor mensual de contratistas (opcional)","monthly_upload","MONTHLY_PATH")
    st.caption("Sin una base, su validación queda como REVISAR. El valor del CRP no sustituye los honorarios mensuales.")
    with st.expander("Opciones de lectura"):
        ocr=st.checkbox("Leer páginas escaneadas con OCR",value=True)
        review_date=st.date_input("Fecha de revisión",value=datetime.now(ZoneInfo("America/Bogota")).date())
        st.caption("La vigencia bancaria usa la fecha de la cuenta, si existe, y esta fecha como alternativa.")
    st.caption(f"Reglas: {RULESET}. Los documentos se procesan en el servidor, sin envío a una API de IA.")

uploaded=st.file_uploader("Archivos PDF de la cuenta de cobro",type=["pdf"],key="account_pdfs",
                          accept_multiple_files=True,max_upload_size=40,
                          help="Carga un PDF consolidado o varios soportes. Límite total: 40 MB y 100 páginas.")
files=[(file.name,file.getvalue()) for file in uploaded]
pdf_name=files[0][0] if len(files)==1 else "expediente_consolidado.pdf"
pdf_data=None
if files:
    st.caption("Los archivos se unirán en el orden mostrado. Para cambiarlo, retíralos y vuelve a agregarlos en el orden deseado.")
    for index,(name,data) in enumerate(files,1):
        st.text(f"{index}. {name}")
    try:
        pdf_data=merge_pdfs(files)
    except ValueError as exc:
        st.error(str(exc))
if pdf_data is not None and len(files)>1:
    st.download_button("Descargar PDF consolidado",pdf_data,file_name=pdf_name,mime="application/pdf",key="merged_pdf_download")

fingerprint=hashlib.sha256()
for block in (pdf_data or b"",crp_data or b"",monthly_data or b"",str(review_date).encode(),str(ocr).encode(),secop_url.encode()):
    fingerprint.update(len(block).to_bytes(8,"big")); fingerprint.update(block)
fingerprint.update((crp_name+monthly_name+repr([name for name,data in files])).encode())
current=fingerprint.hexdigest()
if st.session_state.get("review_fingerprint") != current:
    st.session_state.pop("review",None)

if st.button("Revisar cuenta de cobro",type="primary",disabled=pdf_data is None):
    st.session_state.pop("review",None)
    try:
        with st.spinner("Leyendo documentos y contrastando las reglas…"):
            crp=read_reference(crp_data,crp_name) if crp_data is not None else None
            monthly=read_reference(monthly_data,monthly_name) if monthly_data is not None else None
            result=analyze(pdf_data,pdf_name,crp,monthly,review_date,ocr,secop_url=secop_url)
            st.session_state.review=result
            st.session_state.review_fingerprint=current
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("No se pudo completar la revisión. Comprueba el PDF y las bases de referencia e inténtalo de nuevo.")

review=st.session_state.get("review")
if review is None:
    st.info("Los PDF cargados deben reunir certificado, informe de ejecución, planilla y cuenta de cobro. Para la primera cuenta, incluye también los soportes adicionales.")
    with st.expander("Qué revisa ValerIA"):
        st.write("Períodos, identidad, contrato, valores, consecutivos, planilla, aportes, supervisor, códigos CRP, vigencia, avance y soportes de primera cuenta.")
        st.write("Las firmas y la coherencia del contenido requieren inspección humana. La aplicación no da por cumplido un campo que no puede leer.")
        st.caption("Se conserva la numeración del instructivo y se excluye la regla 14. Las reglas 20 y 21 contrastan la base SECOP.")
    st.stop()

alerts=[f for f in review.findings if f.status=="REVISAR"]
ok=[f for f in review.findings if f.status=="VALIDADO"]
na=[f for f in review.findings if f.status=="NO APLICA"]
cols=st.columns(4)
cols[0].metric("Para revisar",len(alerts))
cols[1].metric("Sin diferencia detectada",len(ok))
cols[2].metric("No aplica",len(na))
cols[3].metric("Páginas",len(review.pages))
st.warning("Revisión pendiente. Las alertas orientan la verificación; este resultado no autoriza el pago.")

summary_tab,pdf_tab=st.tabs(["Todas las validaciones","Consultar PDF"])
with summary_tab:
    st.dataframe([{"Regla":f.rule,"Validación":f.title,"Estado":f.status,"Tipo":f.category,"Detalle":f.message}
                  for f in review.findings],hide_index=True,width="stretch")
    st.caption("La fórmula de aportes reproduce el instructivo: 40% × (12,5% + 16% + 0,522%). Requiere revisión para excepciones, mínimos, topes o riesgos diferentes.")
    st.caption("Honorarios: mes completo = 30 días; período parcial dentro de un mes = días comerciales inclusivos, con día máximo 30. La base mensual debe identificar explícitamente el honorario.")
with pdf_tab:
    st.dataframe([{"Documento":LABELS[k],"Páginas":", ".join(map(str,d.pages)) or "No identificado"}
                  for k,d in review.documents.items()],hide_index=True,width="stretch")
    page=st.selectbox("Página del PDF",[p.number for p in review.pages],
                      format_func=lambda n:f"Página {n} · {LABELS[review.pages[n-1].kind]}")
    try: st.image(render_page(pdf_data,page),caption=f"Página {page}",width="stretch")
    except Exception: st.error("No se pudo mostrar esta página. Descarga el PDF analizado para revisarla.")
    with st.expander("Texto detectado en esta página"):
        st.text(review.pages[page-1].text or "Sin texto legible.")
    st.download_button("Descargar PDF analizado",pdf_data,file_name=pdf_name,mime="application/pdf")

st.subheader("Descargar resultados")
downloads=st.columns(2)
downloads[0].download_button("Reporte de revisión (.txt)",report_text(review),"revision_valeria.txt","text/plain; charset=utf-8")
downloads[1].download_button("Tabla de alertas y resultados (.csv)",report_csv(review),"revision_valeria.csv","text/csv")
st.caption("Los archivos y resultados permanecen en la memoria de esta sesión. No se guardan expedientes en el repositorio ni se usa una caché compartida entre usuarios.")
if st.button("Borrar resultado de esta sesión"):
    st.session_state.pop("review",None)
    st.session_state.pop("review_fingerprint",None)
    st.rerun()
