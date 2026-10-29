# ValerIA · Validación de cuentas de cobro

Aplicativo Streamlit para cargar **uno o varios PDF**, unirlos en memoria y obtener alertas con la regla, los valores extraídos, la página y la acción de revisión. Implementa el instructivo **VF_VALIDACION 2 26052026** como reglas de Python, sin necesidad de una API de IA.

## Uso

1. Cargar el listado CRP en la barra lateral (XLSX o CSV). Es una referencia privada de la sesión.
2. Opcionalmente, cargar la base de valor mensual de los contratistas.
3. Cargar uno o varios PDF que reúnan certificado de cumplimiento F1_P2_F, informe F1_P10_C, planilla PILA y cuenta de cobro. Se unen en el orden mostrado; para cambiarlo, retirar los archivos y agregarlos en el orden deseado. Se puede descargar el PDF consolidado antes de analizarlo.
4. Pulsar **Revisar cuenta de cobro**.
5. Consultar **Todas las validaciones** y **Consultar PDF**. Descargar el PDF analizado y el reporte TXT, CSV o JSON.

La falta de una base no bloquea el análisis: las reglas que dependen de ella quedan como **REVISAR**. Un archivo que contiene solo un análisis anterior no sustituye el expediente original.

## Despliegue en Streamlit Community Cloud

- Repositorio: `Camilalozano/ValidacionCuentasCobro`.
- Rama: `main`.
- Archivo principal: **`app.py`**.
- Python recomendado: **3.12**.
- `requirements.txt` instala los paquetes Python y `packages.txt` instala Tesseract con español e inglés para OCR.
- No hacen falta claves de OpenAI ni secretos para iniciar la aplicación.
- En Cloud, los revisores pueden cargar las bases CRP y de honorarios en la barra lateral. Para una instalación institucional con archivos privados montados, configurar `CRP_PATH` y `MONTHLY_PATH` en Secrets, siguiendo `.streamlit/secrets.example.toml`. Una ruta del computador de quien despliega no es accesible desde Cloud.

Referencia oficial: [dependencias en Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

## Ejecución local

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Para OCR local, instalar Tesseract con los idiomas `spa` y `eng` y dejar su ejecutable en `PATH`. Si no está disponible, la aplicación muestra la limitación de lectura. No se requiere OCR para los tres ejemplos con texto suministrados.

## Alcance y estados

- **VALIDADO**: coincidencia o cálculo comprobado con los campos que pudo extraer el motor. No equivale a aprobación del pago.
- **REVISAR / Inconsistencia**: valores extraídos que difieren.
- **REVISAR / Evidencia incompleta**: dato ausente, ambiguo, soporte o base no disponible.
- **REVISAR / Revisión visual o de contenido**: intervención del revisor, especialmente firmas, titularidad de soportes y coherencia semántica.
- **NO APLICA**: soportes adicionales de primera cuenta cuando ambos consecutivos coinciden y son posteriores a 1.

La aplicación cubre 18 reglas numeradas 1–16, 18 y 19. El documento fuente omite el número 17. El control técnico 00 informa documentos no identificados o problemas de lectura. Véase [criterios y decisiones de implementación](docs/REGLAS.md).

**Límites explícitos:** extracción orientada a los formatos ATENEA y a la estructura PILA de los ejemplos. Otros diseños pueden requerir ajuste de patrones y se marcan para revisar. OCR reconoce texto, no prueba la presencia ni autenticidad de firmas. La validación 19 siempre pide inspección visual; la 14 ejecuta comprobaciones de coherencia y mantiene revisión humana del contenido. Esta versión no reproduce el razonamiento libre ni la visión de un MyGPT.

La fórmula de aportes reproduce el instructivo recibido (40% del certificado y tasas indicadas). No incorpora todos los mínimos, topes, clases de riesgo o excepciones de cotización. La comparación del mes de la planilla es una regla interna y no determina por sí sola la existencia de mora legal.

## Bases de referencia

**CRP:** lectura de todas las hojas, coincidencia exacta del documento o nombre completo, y comprobación de CDP, CRP y código interno en la misma fila. Cuando existen encabezados reconocibles se comprueba también la asociación con cada campo. Si hay un número de contrato explícito, se exige coincidencia para evitar usar otro contrato o vigencia del mismo beneficiario. No se mezclan códigos de personas o filas diferentes.

**Valor mensual:** la referencia debe tener una columna denominada `valor mensual`, `honorarios mensuales` o `mensualidad`, además de documento o nombre. Se admite una columna `contrato`. Si existen varios valores distintos para la persona y contrato, el resultado queda pendiente. No se toma el monto más cercano al nombre: podría ser un documento de identidad o el valor total del contrato.

Ejemplo ficticio:

```csv
documento,nombre,contrato,valor mensual
123456789,PERSONA DE PRUEBA,142-2026,9360000
```

## Tratamiento de los archivos

Los PDF y las bases nominales no forman parte del repositorio. Las cargas se procesan en memoria por sesión, sin caché global ni envío a servicios externos de IA. OCR utiliza archivos temporales de una página. Los reportes contienen evidencia del expediente y los descarga únicamente la sesión que lo revisa. La instalación y sus controles de acceso corresponden al administrador del despliegue.

Límites: 40 MB y 100 páginas en total entre los PDF cargados y en el consolidado, hasta 15 páginas OCR, tiempo total de lectura 180 segundos. Las páginas que exceden los límites de texto u OCR generan una advertencia. Las bases admiten hasta 10 MB, 30.000 filas y 100 columnas por hoja. Cambiar el PDF, las bases o las opciones invalida el resultado anterior.

## Pruebas

```bash
python -m unittest discover -v
```

Las pruebas usan datos ficticios. Cubren normalización, rangos parciales, aportes, faltantes, ambigüedad, códigos cruzados, consecutivos, primera cuenta, firmas pendientes, errores de lectura y arranque de Streamlit. Los tres expedientes privados suministrados se probaron localmente, sin añadirlos al repositorio.

## Estructura

`app.py`: interfaz. `valeria/pdf.py` y `pdf_worker.py`: lectura aislada y OCR. `extract.py`: clasificación y campos. `references.py`: bases de contraste. `rules.py`: validaciones. `service.py`: análisis y exportación. `tests/`: pruebas de regresión.
