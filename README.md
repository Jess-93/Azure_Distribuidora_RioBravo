# Distribuidora Río Claro

Aplicación web de demostración para consultar la política de devoluciones y buscar existencias en un catálogo de almacén. La interfaz está desarrollada con React y Vite; una API FastAPI conecta el chat de devoluciones con Microsoft Foundry y sirve las consultas del inventario de muestra.

> **Estado del proyecto:** Prototipo académico. No es un sistema oficial de Distribuidora Río Claro ni una certificación o solución validada por Microsoft. No lo uses para tomar decisiones comerciales ni introduzcas datos personales, credenciales, facturas reales o información confidencial.

**Demo alojada:** [Distribuidora Río Claro](https://rio-claro-demo-b5ebd3axgcf7bjex.westus-01.azurewebsites.net/) (su disponibilidad y configuración pueden cambiar).

## Funcionalidades

- **Devoluciones:** Envía consultas a un agente configurado en Microsoft Foundry y muestra las citas que este devuelva, cuando estén disponibles.
- **Almacén:** Después de iniciar sesión, busca por SKU, nombre o alias en un catálogo CSV de ejemplo. Presenta coincidencias, cantidades y fechas registradas.
- **Voz:** Ofrece dictado mediante Azure Speech cuando el servicio está configurado; requiere permiso de micrófono en el navegador.
- **Interfaz:** Incluye tema oscuro y claro, selección de sucursal, historial local y herramientas para compartir respuestas.

### Limitaciones importantes

- El inventario proviene de [`backend/data/inventario.csv`](backend/data/inventario.csv); no es información en vivo ni está conectado a un ERP.
- La API no valida tickets o facturas, no determina la elegibilidad de devoluciones y no crea folios de atención. La respuesta del agente puede ser incompleta o incorrecta; las decisiones deben confirmarse con una persona responsable.
- Las fuentes del mensaje inicial de bienvenida son ilustrativas; no representan una consulta ni una verificación real de documentos.
- El agente de inventario de Foundry es opcional. Si no se configura, las consultas se contestan con la lógica local.
- El historial del chat de devoluciones se guarda en el almacenamiento local (`localStorage`) del navegador.

## Tecnologías

- React 19, Vite 6 y JavaScript (ES modules).
- FastAPI, Uvicorn y Python.
- Microsoft Foundry y `DefaultAzureCredential` para el agente de devoluciones.
- Azure Speech para el dictado opcional.
- SQLite para conservar el contexto de las conversaciones en el backend.

## Requisitos previos

- Node.js 20 o posterior y npm.
- Python 3.11 o posterior.
- Acceso a un proyecto y agente de Microsoft Foundry para probar el chat de devoluciones.
- Azure CLI (`az`) y permisos para invocar el agente si se autentica localmente con Azure.

El frontend y las consultas locales del inventario pueden ejecutarse sin credenciales de Azure. Las funciones que dependen de Foundry o Azure Speech requieren su configuración correspondiente.

## Instalación y configuración

1. Clona el repositorio y entra en su directorio:

   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd <DIRECTORIO_DEL_REPOSITORIO>
   ```

2. Instala las dependencias del frontend:

   ```bash
   npm ci
   ```

3. Crea y activa un entorno virtual, e instala las dependencias de Python:

   **Windows (PowerShell):**

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

   **macOS o Linux:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

4. Crea el archivo local de configuración a partir de la plantilla:

   **Windows (PowerShell):**

   ```powershell
   Copy-Item .env.example .env.local
   ```

   **macOS o Linux:**

   ```bash
   cp .env.example .env.local
   ```

5. Edita `.env.local` en el backend según las funciones que necesites:

   | Variable | Uso |
   | --- | --- |
   | `FOUNDRY_PROJECT_ENDPOINT` | Endpoint del proyecto de Foundry. |
   | `FOUNDRY_AGENT_NAME` | Nombre del agente de devoluciones. |
   | `FOUNDRY_INVENTORY_AGENT_ENDPOINT` | Opcional: endpoint HTTPS del agente de inventario. Déjalo vacío para usar las respuestas locales. |
   | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Opcionales: habilitan el servicio de dictado de voz. |
   | `ALMACEN_USERNAME`, `ALMACEN_PASSWORD` | Credenciales de acceso al inventario. Usa valores propios y únicos; no publiques credenciales de demo. |
   | `INVENTORY_AUTH_SECRET` | Secreto de firma de sesión de inventario; debe tener al menos 32 caracteres aleatorios. |
   | `CHAT_SESSION_DB_PATH` | Ruta de la base SQLite de sesiones; por defecto, `.data/chat_sessions.sqlite3`. |

   Para probar Foundry localmente, inicia sesión con Azure CLI (`az login`) y asegúrate de que tu identidad tenga permisos sobre el proyecto/agente. En producción, usa identidad administrada y configuración segura del entorno. No pongas claves, tokens ni secretos en el código, en el frontend ni en variables `VITE_*`.

   `.env.local` está excluido por `.gitignore`; conserva allí tus valores locales y no lo subas a GitHub. `.env.example` es solo una plantilla: reemplaza sus marcadores en tu copia local.

## Ejecutar en desarrollo

Inicia el backend en una terminal:

```bash
npm run dev:api
```

Inicia Vite en otra terminal:

```bash
npm run dev
```

Abre la URL local que indique Vite (normalmente `http://localhost:5173`). El servidor de desarrollo reenvía las rutas `/api` al backend local.

Para compilar y previsualizar el frontend:

```bash
npm run build
npm run preview
```

`npm run preview` sirve el frontend compilado, pero no reenvía las rutas `/api` al backend. Para probar la aplicación completa en local, usa el servidor de desarrollo descrito arriba; para producción, sirve el frontend y la API desde el mismo origen.

## Pruebas

Con las dependencias de Python instaladas, ejecuta las pruebas de la API:

```bash
npm run test:api
```

Comprueba el build de producción del frontend:

```bash
npm run build
```

## API local

- `GET /api/health`: estado básico del backend.
- `POST /api/chat`: consulta el agente de devoluciones.
- `POST /api/inventory/login`: inicia sesión en el modo almacén.
- `POST /api/inventory/query` y `POST /api/inventory/chat`: consulta el catálogo autenticado.
- `GET /api/inventory/catalog`: devuelve el catálogo autenticado.
- `GET /api/speech/token`: obtiene un token temporal de Azure Speech cuando está configurado.

## Estructura del proyecto

```text
backend/
  app.py                 API, Foundry, autenticación y sesiones
  inventory.py           Validación y búsqueda del catálogo
  data/inventario.csv    Datos de inventario de muestra
  test_app.py            Pruebas de la API
src/
  components/            Interfaz y componentes de chat
  config/                Sucursales y datos de contacto de demostración
  context/               Contexto del tema
  services/              Clientes HTTP del frontend
  styles/                Estilos globales
  App.jsx                Composición principal de la aplicación
public/                  Recursos estáticos
assets/                  Imágenes y capturas de demostración
```

## Seguridad, privacidad y publicación

- Usa únicamente datos ficticios al probar la aplicación. No envíes información personal o confidencial: las consultas se procesan con servicios externos y el historial de devoluciones queda guardado localmente en el navegador.
- Configura las credenciales de almacén y los secretos con valores únicos, aleatorios y exclusivos para cada entorno. No uses credenciales de demostración ni las reutilices en producción.
- Antes de publicar, verifica que `.env.local`, credenciales, archivos de base de datos, datos privados y artefactos generados no estén incluidos en el commit ni en el historial del repositorio. Si un secreto ya se publicó, rótalo; borrarlo del último commit no invalida una exposición anterior.
- Revisa las capturas y recursos gráficos para confirmar que tienes permiso para publicarlos y que no muestran credenciales o información privada.
- El proyecto no incluye todavía un archivo `LICENSE`. Elige y añade una licencia antes de conceder permisos de reutilización; confirma también los derechos sobre el nombre, el logotipo y demás recursos de marca.

## Créditos

Microsoft, Azure y Foundry se mencionan únicamente para identificar las tecnologías utilizadas. Este proyecto no está afiliado, patrocinado ni certificado por Microsoft.
