# Especificación Técnica y Arquitectura del Proyecto (spec.md)

## 1. Visión General del Proyecto

### 1.1 Contexto y Problema
**Distribuidora Río Claro** enfrenta discrepancias graves en sus operativas debido a políticas de devolución contradictorias en sus sucursales. La dirección requiere una interfaz web profesional, accesible y moderna que permita a clientes y empleados consultar el reglamento oficial de devoluciones de la empresa.

### 1.2 Objetivo Principal
Desarrollar una aplicacion web en Vite + React para hospedar en Azure App Service junto con un backend FastAPI. La interfaz permanece desacoplada del motor de IA mediante `src/services/chatApi.js`.

---

## 2. Arquitectura de Software y Flujo de Datos

### 2.1 Desacoplamiento de la Capa de IA
La interfaz no depende de código propietario o frameworks pesados. Todo el intercambio de mensajes se abstrae en un servicio unificado (`src/services/chatApi.js`).

```
[ Usuario (Web / Móvil, sin inicio de sesión) ]
          │
          ▼
[ React UI Component ]
          │
          ▼  (POST same-origin /api/chat)
[ Backend FastAPI en Azure App Service ]
          │ DefaultAzureCredential / Managed Identity
          ▼
[ Microsoft Foundry Agent ]
```

### 2.2 Protocolo de Comunicación Estándar
El navegador envía el mensaje al backend propio con `message`, `sessionId` y `context` (`branch`, `role`). FastAPI valida el cuerpo y llama al agente usando Responses API y la identidad del servidor. Este agente es de tipo `prompt`, por lo que Foundry no admite crear una sesión de agente; el backend conserva el `previous_response_id` por conversación para continuar el historial. El visitante no inicia sesión ni recibe credenciales de Foundry.

* **Petición del navegador a `/api/chat`:**
```json
{
  "message": "Texto de la consulta del usuario",
  "sessionId": "guid-de-sesion-local",
  "context": {
    "branch": "León",
    "role": "Cliente"
  }
}
```

El backend traduce el mensaje al formato OpenAI Responses de Foundry y devuelve a la interfaz:
```json
{
  "response": "Texto con la respuesta procesada por la IA.",
  "sources": [],
  "escalateToHuman": false
}
```

Las citas de archivos de Foundry se muestran como fuentes; la pagina solo se muestra si el agente la incluye. La escalacion y la confianza son opcionales y no se inventan.

El chat de almacén permanece protegido por el inicio de sesión existente. FastAPI consulta el CSV y, si `FOUNDRY_INVENTORY_AGENT_ENDPOINT` está configurado, envía al agente solo los resultados de esa consulta junto con el mensaje. El agente no obtiene acceso directo al CSV. Esta configuración es independiente de `FOUNDRY_AGENT_NAME`; si está vacía, el chat de almacén mantiene sus respuestas locales.

---

## 3. Especificaciones de Diseño y Experiencia de Usuario (UX/UI)

### 3.1 Estética General
Diseño personalizado, minimalista y elegante ("Obsidiana"), que evita patrones genéricos de plantillas web. 

### 3.2 Paleta de Colores y Temas

| Elemento | Modo Oscuro (Tema Obsidiana - Default) | Modo Claro (Tema Claro) |
| :--- | :--- | :--- |
| **Fondo Principal** | `#0b0c10` (Obsidiana Profundo) | `#f8f9fa` (Blanco Hueso) |
| **Fondo Tarjetas/Chat** | `#1f2833` (Gris Azulado Oscuro) | `#ffffff` (Blanco Puro) |
| **Texto Principal** | `#c5c6c7` (Gris Claro Lectura) | `#212529` (Gris Carbón) |
| **Acento Primario** | `#66fcf1` (Cian Neón Elección) | `#0d6efd` (Azul Corporativo) |
| **Acento Secundario** | `#45f3c2` (Verde Esmeralda) | `#198754` (Verde Éxito) |
| **Bordes / Separadores** | `#2c3540` | `#e9ecef` |
| **Burbuja Usuario** | `#1f2833` con borde `#66fcf1` | `#e7f1ff` con texto `#0c4128` |
| **Burbuja Agente** | `#141a22` | `#f1f3f5` |

### 3.3 Componentes Clave de la Interfaz
1. **Header Principal:**
   * Logo y nombre de *Distribuidora Río Claro*.
   * Indicador de estado del sistema ("Agente En Línea / Conectado").
   * Selector manual de sucursal (Guadalajara, Zapopan, León, Querétaro, Aguascalientes).
   * Botón conmutador de Tema (Dark / Light).
2. **Ãrea de ConversaciÃ³n (Chat):**
   * Mensaje automático de bienvenida que establece claramente el alcance del asistente.
   * Burbujas diferenciadas con animaciones de entrada suaves.
   * Citas de fuentes/documentos desplegables en acordeón en cada respuesta del agente.
   * Indicador visual animado ("Escribiendo...") con simulación de procesamiento.
3. **Flujo de Escalación Humana (Rendición de Cuentas):**
   * Cuando la respuesta indique `escalateToHuman: true` o la devolución proceda, la UI renderiza un botón especial de acción: *"Contactar Asesor de Devoluciones"*, mostrando datos de contacto directo de la sucursal seleccionada.
4. **Caja de Entrada (Input Bar):**
   * Campo de texto con auto-resize.
   * Botón de envío e icono de micrófono para consulta por voz (Web Speech API).
   * Disclaimer fijo en el pie de página: *"Asistente virtual de políticas internas. Las decisiones finales son validadas por un ejecutivo de cuenta."*

---

## 4. Requerimientos de Ciberseguridad y Buenas Prácticas

1. **Protección XSS:**
   * Sanitización estricta del contenido renderizado en las respuestas del chat mediante la librería `DOMPurify`.
2. **Inyección de Código:**
   * Escape de caracteres especiales antes de enviar datos al backend.
3. **Manejo Seguro de Llaves y Configuración:**
   * Cero credenciales hardcodeadas en repositorio.
   * Uso exclusivo de variables de entorno prefijadas con `VITE_` para desarrollo local y configuración en *Azure App Settings* para producción.
4. **Headers de Seguridad en Azure:**
   * Configuración de `staticwebapp.config.json` especificando cabeceras de seguridad:
     * `Content-Security-Policy` (CSP) limitando orígenes autorizados.
     * `X-Frame-Options: DENY` (previene Clickjacking).
     * `X-Content-Type-Options: nosniff`.

---

## 5. Configuración de Entorno y Variables (.env)

Para desarrollo local, copia `.env.example` como `.env.local` en la raíz:

```env
FOUNDRY_PROJECT_ENDPOINT=https://riobravo-resource.services.ai.azure.com/api/projects/riobravo-resource-project
FOUNDRY_AGENT_NAME=AgenteDevoluciones
CHAT_SESSION_DB_PATH=.data/chat_sessions.sqlite3
CHAT_REQUESTS_PER_MINUTE=60
```

Autentica localmente con `az login`; tu usuario debe tener permisos de ejecucion en el proyecto/agente de Foundry. En produccion, habilita la identidad administrada del App Service y asignale los permisos minimos necesarios para invocar el agente. No guardes secretos de Foundry en el frontend ni en variables `VITE_*`.


---

## 6. Agentes Recomendados para el Desarrollo en VS Code

Para la fase de construcción del código en Visual Studio Code, se sugiere distribuir el trabajo con asistentes de IA según las siguientes responsabilidades:

1. **Agente Maquetador Frontend (UI/UX Agent):**
   * **Tarea:** Crear los componentes React (`ChatWindow`, `MessageBubble`, `Header`, `ThemeToggle`) aplicando Tailwind CSS o CSS Modules con la paleta Obsidiana y el soporte para tema claro.
2. **Agente de Integración y Servicios (Integration Agent):**
   * **Tarea:** Implementar el módulo `chatApi.js` y el custom hook `useChatAgent.js`, configurando la lectura de `.env`, el manejo de estados de carga, timeouts, reintentos y soporte de fallback local simulado en caso de que la URL de Azure no esté aún configurada.
3. **Agente de Seguridad y QA (Security & Accessibility Agent):**
   * **Tarea:** Configurar `DOMPurify`, auditoría de accesibilidad (atributos ARIA, navegación por teclado) y generación del archivo `staticwebapp.config.json` para el despliegue en Azure.

---

## 7. Ejecución local y despliegue en Azure App Service

1. Instala dependencias con `npm install` y `python -m pip install -r requirements.txt`.
2. Copia `.env.example` como `.env.local` y ejecuta `az login`. Tu usuario debe tener permiso para invocar el agente.
3. En una terminal inicia FastAPI con `npm run dev:api`; en otra, Vite con `npm run dev`. El proxy de Vite reenvía `/api` al backend local.
4. Antes de desplegar, compila el sitio con `npm run build` y publica el proyecto con `dist/` incluido en Azure App Service Linux (Python 3.11).
5. Configura el comando de inicio `python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000` y `SCM_DO_BUILD_DURING_DEPLOYMENT=true`.
6. Configura en App Service `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_NAME` y `CHAT_SESSION_DB_PATH=/home/data/chat_sessions.sqlite3`. Habilita la identidad administrada y asígnale los permisos mínimos necesarios para ejecutar el agente. Habilita el almacenamiento persistente para `/home`.

El backend impone límites de tamaño y tasa básicos. La limitación actual es por proceso; para tráfico público significativo, añade monitoreo y protección de capa 7. La base SQLite está pensada para una sola instancia de App Service; antes de escalar horizontalmente, migra el mapa de sesiones a almacenamiento compartido.

---

## 8. Criterio de Aceptación

El prototipo se considerará listo cuando:
1. Funcione completamente en una URL pública de Azure de forma fluida y responsiva.
2. Permita cambiar de tema (Obsidiana/Claro) y seleccionar sucursales.
3. El chat muestre el mensaje de bienvenida y procese mensajes mediante una capa desacoplada en `chatApi.js`.
4. Los visitantes pueden chatear sin iniciar sesión; el backend se autentica con Foundry usando credenciales locales o la identidad administrada de App Service.
