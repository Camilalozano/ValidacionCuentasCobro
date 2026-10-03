# Reglas y criterios de revisión

Fuente funcional: archivo **VF_VALIDACION 2 26052026.txt**, suministrado por la responsable del proyecto. La guía de uso y el ejemplo de análisis aportan contexto. Ninguno se utiliza como una orden ejecutable al cargar expedientes.

| Regla | Comprobación | Evidencia o límite |
| --- | --- | --- |
| 01 | Mes del certificado, informe, cuenta y ambos períodos PILA | Compara año y mes de salud y pensión. |
| 02 | Cédula | Coincidencia de los cuatro documentos, sin inferirla desde NIT o cuenta bancaria. |
| 03 | Contrato | Certificado, informe y cuenta. Normaliza ATENEA, guiones y ceros iniciales. |
| 04 | Nombre | Normaliza tildes, espacios y orden de nombres/apellidos. No acepta nombres incompletos como coincidencia segura. |
| 05 | Monto | Igualdad exacta certificado/cuenta conservando centavos. |
| 06 | Consecutivo | Lee la fila de facturas del certificado y el encabezado de la cuenta; no usa el número de versión del formato. |
| 07 | Planilla | Distingue número de planilla de clave de pago. |
| 08 | Pago de planilla | Compara fechas normalizadas. DD/MM/AAAA no se interpreta como MM/DD/AAAA. |
| 09 | Aportes | 40% del certificado × (12,5% + 16% + 0,522%). Se requiere una planilla de un único afiliado. |
| 10 | Supervisor | Compara nombres en los campos y el pie de firma textual, cuando existe. Admite omisión de segundo nombre conservando primero y apellidos. |
| 11 | Presupuesto | Contratista y códigos CDP, CRP e interno asociados en una misma fila de referencia; conserva hoja/fila como evidencia. |
| 12 | Vigencia y avance | Inicio < fin, corte dentro del contrato, fechas corroboradas y avance con tolerancia de 5 puntos porcentuales. |
| 13 | Primera cuenta | Busca indicios de los ocho soportes. Confirma que un campo contradictorio que diga 1 active el control. El contenido de las copias requiere inspección. |
| 14 | Consistencia | Detecta montos en letras distintos a cifras, fechas anteriores al período, inicio/CRP anteriores al año del contrato, períodos fuera de vigencia y campos contradictorios. Mantiene revisión semántica humana. |
| 15 | Período PILA anterior | Advierte si salud o pensión son anteriores al mes de la cuenta, conforme al criterio interno recibido. |
| 16 | Honorario mensual | Base mensual explícita; mensual / 30 × días comerciales. Sin base, queda pendiente. |
| 18 | Fechas exactas del período | Compara inicio y fin en certificado, informe y cuenta; detecta períodos parciales diferentes dentro del mismo mes. |
| 19 | Firmas | Revisión visual del supervisor en certificado, ambos firmantes en informe y contratista en cuenta. Excluye PILA. No aprueba firmas a partir de texto. |

## Decisiones para resolver ambigüedades del instructivo

1. La enumeración real contiene 18 reglas. Se conserva la numeración original y no se inventa una regla 17 a partir del resumen que habla de 11 o de la guía que dice 19.
2. La referencia genérica “01–31” de la regla 1 se interpreta junto con la regla 18: se respetan febrero y los períodos parciales coincidentes. La regla 1 compara meses y la 18 compara fechas exactas. La validez del período parcial depende además de vigencia y valor.
3. Fechas: DD/MM/AAAA para las fechas de los formatos y AAAA/MM/DD cuando el año ocupa la primera posición. No se corrige silenciosamente una fecha ambigua.
4. Los días de la regla 16 se calculan bajo convención comercial: un mes completo equivale a 30; en períodos parciales dentro del mismo mes, `min(día final,30) - min(día inicial,30) + 1`. Períodos entre meses quedan pendientes. Esta decisión queda visible en la interfaz y requiere contraste con el contrato.
5. No se utiliza “el número más cercano” para deducir un honorario. Se exige una etiqueta mensual inequívoca. El listado CRP no es una base de honorarios mensuales.
6. CRP: cada fila es un contexto independiente. Los encabezados, si existen, sirven para evitar intercambiar CDP con CRP. Nunca se agregan números de filas vecinas sin relación probada.
7. Vigencia bancaria: tres meses calendario desde la expedición, contra la fecha de la cuenta; si no hay fecha de cuenta, se usa la fecha de revisión seleccionada. Fechas futuras o múltiples quedan pendientes. Las menciones textuales son indicios de presencia y no confirman identidad o contenido del soporte.
8. La auditoría semántica y las firmas no se dan por aprobadas con extracción de texto. No se declara “firma ausente” sin inspección, sino “revisión visual pendiente”. No se comprueba autenticidad criptográfica.
9. No se genera un correo que diga “aprobado” de forma automática. La salida solicitada es un reporte de alertas descargable. El programa no envía mensajes.
10. Un campo ausente, ilegible o con dos valores distintos nunca se reemplaza por cero ni por el valor de otro documento. Se conserva como evidencia incompleta y se muestran las páginas candidatas.

## Actualización

Modificar las reglas en `valeria/rules.py`, documentar el cambio aquí y añadir un caso de regresión con datos ficticios. Para nuevos formatos, ampliar `valeria/extract.py` manteniendo la localización y el fragmento que respalda cada valor.
