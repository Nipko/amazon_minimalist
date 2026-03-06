# 🏠 Amazon Minimalist — Sistema de Reservas con IA Nativa

Sistema automatizado de atención al cliente y reservas para apartamentos turísticos en Leticia, Amazonas (Colombia). Integra WhatsApp, Chatwoot y un Agente IA Completamente Nativo en Python (soportando GPT-4o, Llama 3 vía Groq, Claude y Gemini) sin depender de plataformas de terceros como n8n.

---

## 📐 Arquitectura Nativa

```
📱 WhatsApp
    │
    ▼
🔗 Chatwoot (Bandeja / CRM) ──→ Webhook ──→ 🤖 agent.py (Motor IA Local)
                                                 │
                          ┌──────────────────────┼───────────────────────┐
                          ▼                      ▼                       ▼
                     📅 /availability       📋 /query                ✅ /bookings
                     (Chequeo iCal)      (Info/Base Datos)       (Cierre y Correos)
                          │                      │                       │
                          └──────────────────────┼───────────────────────┘
                                                 │
                                       �️ PostgreSQL (Memoria Larga)
```

---

## 📂 Estructura del Proyecto

| Archivo | Descripción |
|---|---|
| `api.py` | API principal (FastAPI). Gestiona endpoints, webhooks, base de datos y envío de correos V2 premium |
| `agent.py` | Cerebro IA local. Usa `litellm` para orquestar la conversación, memoria segura y llamadas a herramientas (Tool-calling) |
| `avail_checker.py` | Verificador de disponibilidad real cruzando iCals de Airbnb/Booking.com |
| `system_prompt.md` | Personalidad, reglas ESCNNA, precios y tácticas de embudo (ventas) de "Sofía" |
| `db_schema.sql` | Esquema de las tablas PostgreSQL (`conversaciones`, `reservas`) |
| `postman_collection.json` | Colección Postman para probar los endpoints y actualizar orígenes de calendarios |

---

## 🚀 Despliegue

El sistema corre en un solo bloque contenedor Docker servido en **Easypanel**.

| Servicio | URL |
|---|---|
| API (FastAPI) | `https://availability-api.parallext.cloud` |
| Chatwoot | `https://chatwoot.parallext.cloud` |

### Variables de entorno críticas (Easypanel)

| Variable | Descripción |
|---|---|
| `API_KEY` | Clave global para la API de operaciones |
| `DB_HOST`, `DB_USER`, `DB_PASSWORD` | Credenciales BBDD |
| `LLM_MODEL` | Modelo a inyectar en litellm (Default: `gpt-4o-mini`) |
| `OPENAI_API_KEY` o `GROQ_API_KEY` | Llaves del proveedor de IA elegido |
| `CHATWOOT_API_URL` | `https://chatwoot.parallext.cloud` |
| `CHATWOOT_API_TOKEN` | Token de BOT (Agent Bot en Chatwoot) para responder |
| `CHATWOOT_USER_TOKEN` | Token de USUARIO (Perfil de Admin en Chatwoot) para modificar el estado y etiquetas de la conversación |
| `SMTP_USER` / `SMTP_PASSWORD` | Correo puente (ej. Gmail App Password) para mandar recibos |

---

## 🔧 Configuración Rápida (Pasos 1-2-3)

### 1. Base de datos
Inicia el `db_schema.sql` en el pgAdmin de PostgreSQL del Easypanel. El LLM conectará para inyectar a su historial ("Super Memory") los recuentos de las reservas.

### 2. Creación de Etiquetas en el CRM
En Chatwoot → **Settings → Labels → Add Label**:
- `nuevo` (Azul - Asignada auto)
- `repetido` (Naranja - Asignada auto)
- `interesado` (Verde - Asigna IA)
- `cotizando` (Amarillo - Asigna IA)
- `reservado` (Morado - Asigna IA)
- `requiere-humano` (Rojo - Cuando se cae la IA o el cliente exige gerente)

### 3. Webhook de Chatwoot Directo a la API
En Chatwoot → **Settings → Integrations → Webhooks**:
- **URL**: `https://availability-api.parallext.cloud/webhook/chatwoot`
- Eventos: `message_created`

¡Y listo! Ya la inteligencia artificial embebida procesará el tráfico en tiempo real, evaluando si debe aplicar fotos (`/multimedia/`), verificar calendarios o cobrar. Funciona cruzado con Meta Cloud API gracias a la proxy de Chatwoot.
