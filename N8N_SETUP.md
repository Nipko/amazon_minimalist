# 🤖 Configuración del Agente de Ventas — n8n + Chatwoot

## Arquitectura

```
📱 WhatsApp → Chatwoot Bot → Webhook n8n → AI Agent (Gemini) → Chatwoot API → WhatsApp
                                              ↕
                                      API Disponibilidad
```

---

## Requisitos

| Servicio | URL | Costo |
|---|---|---|
| **n8n** | https://n8n.parallext.cloud | Gratis (self-hosted) |
| **Chatwoot** | https://chatwoot.parallext.cloud | Gratis (self-hosted) |
| **API** | https://availability-api.parallext.cloud | Gratis (self-hosted) |
| **Gemini API** | Google AI Studio | Gratis (15 RPM) |
| **SMTP** | Gmail/otro | Tu email |

---

## Paso 1: API Key de Gemini

1. Ve a **https://aistudio.google.com/apikey**
2. **"Crear clave de API"** → copia la key

## Paso 2: Importar Workflow en n8n

1. Abre n8n → **"⋮"** → **"Import from File"**
2. Selecciona **`n8n_workflow.json`**
3. Se importa el flujo completo

## Paso 3: Configurar Credenciales

### 3.1 — Chatwoot API Token
- **Tipo**: Header Auth
- **Name**: `api_access_token`
- **Value**: Tu token de Chatwoot (Settings → Account Settings → Access Token)
- **Usado en**: ⌨️ Escribiendo... + 📱 Enviar Respuesta

### 3.2 — API de Disponibilidad
- **Tipo**: Header Auth
- **Name**: `X-API-Key`
- **Value**: `9jnblHkZ13ykPnrn7h0hoDdctA_5ypTtx7w0inJi6YI`
- **Usado en**: 🔍 Query + 📅 Availability + ✅ Booking

### 3.3 — Gemini
- **Tipo**: Google Gemini API
- **API Key**: La clave del Paso 1

### 3.4 — Email Gmail (SMTP)
- **Tipo**: SMTP
- **Host**: `smtp.gmail.com`
- **Port**: `587`
- **SSL/TLS**: STARTTLS
- **User**: `amazonminimalist11@gmail.com`
- **Password**: App Password de Gmail ([crear aquí](https://myaccount.google.com/apppasswords))
- **Nota**: Ir a Google Account → Seguridad → Verificación en 2 pasos → App Passwords → Crear para "Mail"
- El email se envía **TO** a nirlevin89@gmail.com + sofia.henao96@gmail.com y **CC** al huésped (si dio su email)

## Paso 4: Configurar el System Prompt

1. Abre el nodo **"🤖 Sales Agent"**
2. En **"System Message"** → pega contenido de **`system_prompt.md`**

## Paso 5: Configurar Chatwoot Bot

1. En Chatwoot → **Settings → Integrations → Webhooks**
2. Agregar webhook: `https://n8n.parallext.cloud/webhook/1eff1133-3ba0-45cc-9ece-5f88d13c74d8`
3. Eventos: `message_created`

## Paso 6: Activar

1. **Save** el workflow en n8n
2. Toggle **"Active"** → ON
3. Envía mensaje de prueba por WhatsApp

---

## Flujo Visual

```
📱 Mensaje WhatsApp
    │
    ▼
🔗 Chatwoot Bot → Webhook n8n
    │
    ▼
🔒 Filtro (solo mensajes entrantes)
    │
    ├── ⌨️ "Escribiendo..." (Chatwoot API)
    │
    ▼
📋 Extraer datos (mensaje, contacto, conversación)
    │
    ▼
🤖 AI Agent (Gemini 2.0 Flash)
    ├── 🔍 POST /query (detalles, precios, fotos)
    ├── 📅 GET /availability (disponibilidad)
    └── ✅ POST /bookings (confirmar reserva)
    │
    ▼
📱 Respuesta → Chatwoot API → WhatsApp
    │
    ▼
📋 ¿Reserva confirmada?
    ├── SÍ → 📧 Email a nirlevin89@gmail.com + sofia.henao96@gmail.com
    └── NO → Fin
```

## Notas

- **Typing**: Chatwoot muestra "escribiendo..." real al activar `toggle_typing_status`
- **Memoria**: 20 mensajes por conversación (session key = conversation_id)
- **Videos**: Solo si el usuario pide explícitamente
- **Descuentos**: Solo si detecta resistencia al precio
- **Reservas**: Fechas se bloquean automáticamente via API
