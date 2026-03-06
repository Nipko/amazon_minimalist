# 🏠 Amazon Minimalist — Sistema de Reservas con IA

Sistema automatizado de atención al cliente y reservas para apartamentos turísticos en Leticia, Amazonas (Colombia). Integra WhatsApp, Chatwoot y un Agente IA Nativo en Python (Llama 3 70B vía Groq).

---

## 📐 Arquitectura

```
📱 WhatsApp
    │
    ▼
🔗 Chatwoot (CRM) ──→ Webhook ──→ 🤖 agent.py (Llama 3 70B - Groq)
    │                                    │
    │                         ┌──────────┼──────────────┐
    │                         ▼          ▼              ▼
    │                    📅 /availability  📋 /query   ✅ /bookings
    │                         └──────────┼──────────────┘
    │                                    │
    │                          🗄️ PostgreSQL
    │                                    │
    ◄────────────────────────────────────┘
    │
    ▼
📱 Respuesta al usuario vía WhatsApp
```

---

## 📂 Estructura del Proyecto

| Archivo | Descripción |
|---|---|
| `api.py` | API principal (FastAPI). Endpoints de disponibilidad, reservas, webhook proxy, y etiquetado de conversaciones |
| `avail_checker.py` | Verificador de disponibilidad con Airbnb/Booking iCal sync |
| `block_dates.py` | Gestión de bloqueo manual de fechas |
| `system_prompt.md` | Prompt del agente IA con instrucciones de ventas, etiquetado y escalamiento |
| `db_schema.sql` | Esquema de las tablas PostgreSQL (`conversaciones`, `reservas`) |
| `agent.py` | Cerebro IA: Integración de LangChain/Herramientas llamando a Groq API |
| `Reglas_Caracteristicas_Apartamentos.txt` | Info de los apartamentos, reglas y precios |
| `Reglas_Caracteristicas_Apartamentos.txt` | Info de los apartamentos, reglas y precios |
| `postman_collection.json` | Colección Postman para pruebas de la API |

---

## 🚀 Despliegue

### Servicios requeridos (todos self-hosted en Easypanel)

| Servicio | URL | Puerto |
|---|---|---|
| API (FastAPI) | `https://availability-api.parallext.cloud` | 8000 |
| Chatwoot | `https://chatwoot.parallext.cloud` | — |
| PostgreSQL | Interno | 5432 |

### Variables de entorno (Easypanel → availability-api → Environment)

| Variable | Descripción | Ejemplo |
|---|---|---|
| `API_KEY` | Clave de autenticación de la API | `9jnblHkZ13ykPnrn...` |
| `DB_HOST` | Host de PostgreSQL | `postgres` |
| `DB_PORT` | Puerto de PostgreSQL | `5432` |
| `DB_NAME` | Nombre de la base de datos | `postgres` |
| `DB_USER` | Usuario de PostgreSQL | `postgres` |
| `DB_PASSWORD` | Contraseña de PostgreSQL | *(tu contraseña)* |
| `GROQ_API_KEY` | Clave API de Groq para LLM de Llama 3 | `gsk_...` |
| `CHATWOOT_API_URL` | URL base de Chatwoot | `https://chatwoot.parallext.cloud` |
| `CHATWOOT_API_TOKEN` | Token de acceso de Chatwoot | `bsK6Rw2kppzuYVVN8tKrYPFz` |
| `CHATWOOT_ACCOUNT_ID` | ID de la cuenta en Chatwoot | `1` |
| `SMTP_SERVER` | Servidor SMTP | `smtp.gmail.com` |
| `SMTP_PORT` | Puerto SMTP | `587` |
| `SMTP_USER` | Email del remitente | `amazonminimalist11@gmail.com` |
| `SMTP_PASSWORD` | App Password de Gmail | *(tu app password)* |

---

## 🔧 Configuración Manual Requerida

### 1. Base de datos

Ejecuta el script `db_schema.sql` en PostgreSQL para crear las tablas:

```sql
-- Conectar a PostgreSQL y ejecutar:
\i db_schema.sql
```

### 2. Etiquetas en Chatwoot

Ir a **Chatwoot → Settings → Labels → Add Label** y crear:

| Etiqueta | Color sugerido | Descripción |
|---|---|---|
| `nuevo` | 🔵 Azul | Contacto nuevo (auto-asignada) |
| `repetido` | 🟠 Naranja | Contacto con historial (auto-asignada) |
| `interesado` | 🟢 Verde | Preguntó por disponibilidad/precios |
| `cotizando` | 🟡 Amarillo | Se consultó disponibilidad con la herramienta |
| `reservado` | 🟣 Morado | Reserva confirmada |
| `requiere-humano` | 🔴 Rojo | Necesita atención de un agente humano |

> **Nota:** `nuevo` y `repetido` se asignan automáticamente por la API al recibir un mensaje. Las demás las asigna el agente IA durante la conversación.

### 3. Workflow de n8n

1. Abre n8n → **⋯ → Import from File**
2. Selecciona `🏠 Amazon Minimalist — Chatwoot Sales Agent.json`
3. Configura las credenciales:

| Credencial | Tipo | Dónde obtenerla |
|---|---|---|
| **Chatwoot User Token** | Header Auth (`api_access_token`) | Chatwoot → Profile → Access Token |
| **WhatsApp Bot Token** | Header Auth (`api_access_token`) | Chatwoot → Settings → Agent Bot → Token |
| **Availability API Key** | Header Auth (`X-API-Key`) | Variable `API_KEY` de tu API |
| **Google Gemini API** | Google PaLM API Key | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Gmail OAuth2** | Gmail OAuth2 | Account Amazon Minimalist Gmail |

4. Actualiza el **System Prompt** del nodo `🤖 Sales Agent` con el contenido de `system_prompt.md`
5. **Save** y toggle **Active → ON**

### 4. Webhook de Chatwoot

En Chatwoot → **Settings → Integrations → Webhooks**:
- URL: `https://n8n.parallext.cloud/webhook/1eff1133-3ba0-45cc-9ece-5f88d13c74d8`
- Eventos: `message_created`

### 5. DNS en Cloudflare

| Registro | Tipo | Nombre | Destino |
|---|---|---|---|
| API | A | `availability-api` | IP del VPS |
| Chatwoot | A | `chatwoot` | IP del VPS |
| n8n | A | `n8n` | IP del VPS |

> Asegurar SSL en modo **Full (strict)** y **Bot Fight Mode** desactivado para permitir webhooks de Meta.

---

## 🤖 Herramientas del Agente IA (n8n)

El agente de ventas tiene acceso a las siguientes herramientas:

| Herramienta | Endpoint | Descripción |
|---|---|---|
| `Query_Apartment` | `POST /query` | Consulta detalles, precios, fotos y disponibilidad |
| `Check_Availability` | `GET /availability` | Verificación rápida de disponibilidad |
| `Confirm_Booking` | `POST /bookings` | Confirma una reserva y bloquea fechas |
| `Label_Conversation` | `POST /conversations/label` | Etiqueta la conversación en Chatwoot |
| `Check_History` | `GET /bookings/contact/{phone}` | Consulta historial de reservas del contacto |

---

## 🏷️ Sistema de Etiquetado

### Automático (en la API, al recibir mensaje):
- **`nuevo`** → Si el contacto NO tiene reservas previas
- **`repetido`** → Si el contacto tiene reservas previas

### Manual (el agente IA decide):
- **`interesado`** → Cuando pregunta por fechas, precios, servicios
- **`cotizando`** → Cuando se consultó disponibilidad con la herramienta
- **`reservado`** → Cuando se confirma una reserva
- **`requiere-humano`** → Quejas, reembolsos, pide hablar con persona

---

## 📊 API Endpoints Principales

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/availability` | Consultar disponibilidad por fechas |
| `POST` | `/query` | Consulta inteligente de apartamentos |
| `POST` | `/bookings` | Crear reserva |
| `GET` | `/bookings/contact/{phone}` | Historial de un contacto |
| `POST` | `/conversations/label` | Etiquetar conversación en Chatwoot |
| `POST` | `/webhook/chatwoot` | Proxy de webhook Chatwoot → n8n |

> Documentación interactiva: `https://availability-api.parallext.cloud/docs`

---

## 🛠️ n8n Manager (CLI)

Herramienta de línea de comandos para gestionar workflows sin entrar a la UI:

```bash
# Configurar
export N8N_API_KEY=tu-api-key

# Comandos
python n8n_manager.py list                    # Listar workflows
python n8n_manager.py export <ID>             # Exportar a JSON
python n8n_manager.py update-prompt <ID>      # Actualizar system prompt
python n8n_manager.py activate <ID>           # Activar workflow
python n8n_manager.py executions <ID>         # Ver ejecuciones
```

---

## 📝 Notas Importantes

- **Typing indicator**: Chatwoot muestra "escribiendo..." real mientras el agente procesa
- **Memoria**: 20 mensajes de contexto por conversación
- **Descuentos**: El agente NUNCA ofrece descuentos primero, solo si el usuario muestra resistencia al precio
- **Cross-sell**: Si un apartamento no está disponible, el agente ofrece el otro automáticamente
- **Fotos**: Se envían automáticamente cuando el agente incluye tags `[FOTO:apartment_id]`
- **Reservas**: Las fechas se bloquean automáticamente al confirmar vía API
- **Email**: Se envía confirmación automática al propietario cuando se confirma una reserva
