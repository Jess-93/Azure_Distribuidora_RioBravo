# Guía para agentes — Distribuidora Río Claro

## Contexto del proyecto

Aplicación web en Vite + React 19 y backend FastAPI para consultar la política de devoluciones de Distribuidora Río Claro. Se publica en Azure App Service; el backend se comunica con Foundry y el frontend permanece desacoplado mediante `src/services/chatApi.js`.

## Responsabilidades según la tarea

- **Interfaz y experiencia (frontend):** trabajar en los componentes React y estilos existentes. Mantener la experiencia responsive, accesible por teclado y coherente con los temas oscuro y claro.
- **Integración Azure:** mantener el transporte y el contrato HTTP en `src/services/chatApi.js`; comprobar configuración, errores y formato de respuesta. No acoplar componentes de interfaz a un proveedor de IA.
- **Calidad y revisión (QA):** comprobar los flujos afectados, estados de carga y error, accesibilidad y riesgos de seguridad. Informar hallazgos con archivo y líneas; distinguir defectos de mejoras opcionales.

Los agentes especializados disponibles están definidos en `.github/agents/`: `frontend.agent.md`, `azure-integration.agent.md` y `qa-review.agent.md`. Esta guía contiene las convenciones compartidas por todos ellos.

## Arquitectura y convenciones

- Usa JavaScript ESM y los componentes funcionales/patrones ya presentes. Evita introducir dependencias o capas nuevas sin necesidad.
- Mantén la separación entre `src/components/`, `src/services/`, `src/context/` y `src/styles/`.
- El navegador llama a `/api/chat`; el backend de `backend/app.py` usa el SDK de Foundry y `DefaultAzureCredential` para invocar el agente. Mantén credenciales en el servidor, valida respuestas y propaga errores explícitos; no presentes fallos de red como respuestas exitosas.
- La interfaz y los mensajes del producto están en español. No inventes ni modifiques las reglas de devolución; consulta `Spec.md.md` y las fuentes oficiales cuando la tarea afecte contenido de política.
- Conserva el diseño Obsidiana, la alternativa clara, la selección de sucursal, las fuentes de respuestas y el flujo de escalación humana definidos en `Spec.md.md`.
- React escapa texto al renderizarlo: conserva las respuestas como texto. Si una función requiere renderizar HTML recibido del agente, sanitízalo con DOMPurify antes de insertarlo y limita ese uso al mínimo necesario.
- Serializa datos con `JSON.stringify`; no apliques escape HTML manual a los mensajes enviados por JSON.

## Configuración y seguridad

- Configura `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_NAME` y `FOUNDRY_AGENT_VERSION` mediante variables de entorno del backend. `.env.example` documenta valores de ejemplo no sensibles.
- El backend usa Azure CLI localmente y la identidad administrada en App Service; nunca pongas claves, tokens ni secretos en el frontend o el bundle.
- El navegador solo conecta al mismo origen para llamar a `/api/chat`; conserva CSP restrictiva en cualquier configuración de hosting que se utilice.
- Valida explícitamente los datos externos que la UI utiliza, incluidas las fuentes de respuesta, y muestra errores de forma clara.

## Verificación

- Ejecuta `npm run build` para comprobar los cambios de la aplicación.
- El proyecto no define actualmente scripts de pruebas ni lint en `package.json`; no afirmes que se ejecutaron.
- Para cambios de configuración de Azure, comprueba también que la regla o cabecera modificada siga siendo compatible con el endpoint y las rutas del sitio.
