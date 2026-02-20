# 🚀 Deploy en Easypanel — Availability Checker API

## Requisitos previos
- VPS Hostinger con Easypanel instalado
- Dominio apuntando al VPS (DNS tipo A → IP del VPS)
- Código subido a un repositorio GitHub

---

## Paso 1: Subir a GitHub

```bash
cd Amazon_minimalist
git init
git add api.py avail_checker.py block_dates.py apartments.json blocks.json \
        requirements.txt Dockerfile .dockerignore public/
git commit -m "feat: availability checker API"
git remote add origin https://github.com/TU-USUARIO/amazon-minimalist-api.git
git push -u origin main
```

> ⚠️ NO subas el `.env` ni las API Keys al repo.

---

## Paso 2: Crear el servicio en Easypanel

1. Abre **Easypanel** → `https://panel.tudominio.com`
2. Click **Create Project** → nombre: `availability-api`
3. Dentro del proyecto → **+ Service** → **App**
4. **Source**: GitHub → selecciona el repo `amazon-minimalist-api`
5. **Build**: Easypanel detecta el `Dockerfile` automáticamente
6. Click **Deploy**

---

## Paso 3: Variables de entorno

En el servicio creado → pestaña **Environment**:

| Variable | Valor |
|---|---|
| `API_KEY` | *(genera una clave segura)* |
| `DB_HOST` | *(host de tu PostgreSQL, ej: postgres)* |
| `DB_PORT` | `5432` *(por defecto)* |
| `DB_NAME` | *(nombre de tu bd, ej: postgres)* |
| `DB_USER` | *(tu usuario, ej: postgres)* |
| `DB_PASSWORD` | *(tu clave de postgres)* |
| `N8N_WEBHOOK_URL` | *(url de produccion de n8n para webhooks de chatwoot)* |

Para generar una clave segura de API_KEY:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Paso 4: Configurar dominio

En el servicio → pestaña **Domains**:

1. Agregar dominio: `api.tudominio.com`
2. Easypanel configura SSL automáticamente con Let's Encrypt
3. Puerto interno: `8000`

---

## Paso 5: Datos persistentes (importante)

En el servicio → pestaña **Mounts/Volumes**:

Crear un volumen para que `blocks.json` y `public/` persistan entre deploys:

| Mount Path | Tipo |
|---|---|
| `/app/blocks.json` | File |
| `/app/public` | Volume |

---

## Paso 6: Verificar

```bash
# Health check
curl https://api.tudominio.com/health

# Consultar disponibilidad
curl -H "X-API-Key: TU-CLAVE" \
     "https://api.tudominio.com/availability?apt=amazon_minimalist&start=2026-03-01&end=2026-03-05"
```

---

## Configurar n8n

### Nodo HTTP Request

| Campo | Valor |
|---|---|
| Method | GET |
| URL | `https://api.tudominio.com/availability` |
| Query Params | `apt={{$json.apartment}}`, `start={{$json.start_date}}`, `end={{$json.end_date}}` |
| Headers | `X-API-Key: TU-CLAVE` |

### Respuesta esperada

```json
{
  "apartment": "Amazon Minimalist",
  "check_in": "2026-03-01",
  "check_out": "2026-03-05",
  "available": true,
  "reason": "Dates are free",
  "conflicts": []
}
```

### En el nodo de WhatsApp Reply

- Si `available == true` → "✅ ¡Disponible del {{check_in}} al {{check_out}}!"
- Si `available == false` → "❌ No disponible. Conflictos: {{conflicts}}"

---

## Documentación automática

FastAPI genera Swagger UI automáticamente:
- `https://api.tudominio.com/docs` — Swagger UI interactivo
- `https://api.tudominio.com/redoc` — Documentación alternativa
