import os
import json
import logging
import re
from dotenv import load_dotenv

load_dotenv()

from typing import List, Dict, Optional
from cachetools import TTLCache
import httpx
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import litellm

import avail_checker
from api import load_details

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Agent")

# --- Configure LLM Router (LiteLLM) ---
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# LiteLLM allows fallback and picks up standard env vars automatically:
# OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.
logger.info(f"Using LLM Model Router: {LLM_MODEL}")

# --- Caching for memory ---
chat_memory = TTLCache(maxsize=1000, ttl=7200)

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "amazonminimalist11@gmail.com")
CHATWOOT_API_URL = os.environ.get("CHATWOOT_API_URL", "https://chatwoot.parallext.cloud")
CHATWOOT_API_TOKEN = os.environ.get("CHATWOOT_API_TOKEN", "")

# Load System Prompt
try:
    with open('system_prompt.md', 'r', encoding='utf-8') as f:
        SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    SYSTEM_PROMPT = "Eres Sofía de Amazon Minimalist, una persona real."

# --- Helper Functions (Tools for Groq) ---
def query_apartment(
    question_type: str = "all", 
    apartment_id: str = None, 
    check_in: str = None, 
    check_out: str = None, 
    num_guests: int = None
) -> dict:
    """Check apartment availability, prices, details."""
    logger.info(f"Tool query_apartment called: type={question_type}, apt={apartment_id}, dates={check_in} to {check_out}")
    details = load_details()
    config = avail_checker.load_config()
    
    # SIEMPRE consultamos AMBOS apartamentos para evitar que la IA oculte disponibilidad cruzada
    apt_ids = [k for k in details.keys() if k not in ("legal", "cross_apartment_policy")]
        
    response_data = {}
    
    for apt in apt_ids:
        apt_data = details.get(apt, {})
        apt_info = {"name": apt_data.get("name", "")}
        
        if question_type in ("details", "all"):
            apt_info["description"] = apt_data.get("description", "")
            apt_info["amenities"] = apt_data.get("amenities", [])
            apt_info["rules"] = apt_data.get("rules", [])
        
        if question_type in ("prices", "all") and num_guests:
            pricing = apt_data.get("pricing", {})
            discount_map = pricing.get("discount_by_guests", {})
            applicable_price = pricing.get("base_price_per_night")
            if apt == "amazon_minimalist":
                if num_guests >= 3: applicable_price = discount_map.get("3_guests", applicable_price)
                elif num_guests == 2: applicable_price = discount_map.get("2_guests", applicable_price)
                else: applicable_price = discount_map.get("1_guest", applicable_price)
            elif apt == "family_amazon_minimalist":
                if num_guests >= 5: applicable_price = discount_map.get("5_6_guests", applicable_price)
                elif num_guests >= 3: applicable_price = discount_map.get("3_4_guests", applicable_price)
                else: applicable_price = discount_map.get("1_2_guests", applicable_price)
            apt_info["price_per_night"] = applicable_price
            
        if question_type in ("availability", "prices", "all"):
            if check_in and check_out:
                if not num_guests or num_guests <= 0:
                    apt_info["availability_status"] = "UNKNOWN"
                    apt_info["availability_error"] = "CRITICAL: Faltan el num_guests. No sabes para cuantas personas es. RESPONDE AL CLIENTE PREGUNTANDO (Ej: ¿Me confirmas cuántos viajan para validarte la disponibilidad?)."
                else:
                    max_guests_allowed = apt_data.get("capacity", {}).get("max_guests", 99)
                    if num_guests > max_guests_allowed:
                        apt_info["availability_status"] = "OCUPADO_Y_BLOQUEADO_NO_VENDER"
                        apt_info["availability_error"] = f"CRITICAL: OVERBOOKING. El apartamento solo admite un máximo de {max_guests_allowed} huéspedes. No puedes venderlo para {num_guests} bajo ninguna circunstancia."
                    else:
                        res = avail_checker.check_apartment_availability(apt, check_in, check_out, config)
                        if res.get("error", "").startswith("Invalid date format"):
                            apt_info["availability_status"] = "UNKNOWN"
                            apt_info["availability_error"] = "CRITICAL: Formato de fecha invalido. DEBES usar EXACTAMENTE YYYY-MM-DD. Vuelve a ejecutar la herramienta."
                        else:
                            apt_info["availability_status"] = "LIBRE" if res.get("available") else "OCUPADO_Y_BLOQUEADO_NO_VENDER"
                            error_msg = res.get("error", res.get("reason"))
                            if error_msg and "Error fetching" in error_msg:
                                apt_info["availability_error"] = error_msg
                            elif res.get("error"):
                                apt_info["availability_error"] = res.get("error")
                        if res.get("available") and apt_info.get("price_per_night"):
                            from datetime import datetime
                            try:
                                nights = (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days
                                apt_info["total_price_estimate_cop"] = nights * apt_info.get("price_per_night", 0)
                            except: pass
            else:
                apt_info["availability_status"] = "UNKNOWN"
                apt_info["availability_error"] = "CRITICAL: Faltan fechas exactas. DEBES responderle al cliente preguntando para qué días exactos (ingreso y salida) busca hospedaje porque sin fechas no puedes mirar el calendario ni dar precio total."
                
        # --- PREVENT HALLUCINATIONS: Strip sales data if Not Available ---
        avail_status = apt_info.get("availability_status")
        if avail_status in ("OCUPADO_Y_BLOQUEADO_NO_VENDER", "UNKNOWN"):
            apt_info.pop("description", None)
            apt_info.pop("amenities", None)
            apt_info.pop("rules", None)
            apt_info.pop("price_per_night", None)
            apt_info.pop("total_price_estimate_cop", None)
            
            if avail_status == "OCUPADO_Y_BLOQUEADO_NO_VENDER":
                apt_info["CRÍTICO"] = "¡NO VENDAS ESTE APARTAMENTO, ESTÁ TOTALMENTE OCUPADO O BLOQUEADO PARA ESTAS FECHAS!"

        response_data[apt] = apt_info
    return response_data

def include_photos(apartment_id: str, account_id: int = None, conversation_id: int = None) -> dict:
    """Send apartment photos to the user."""
    logger.info(f"Tool include_photos called: apt={apartment_id}")
    
    if not account_id or not conversation_id or not CHATWOOT_API_TOKEN:
        return {"status": "Photos queued", "apartment_id": apartment_id, "error": "Missing Chatwoot context"}

    # Definir las fotos más representativas de cada uno
    base_dir = os.path.dirname(os.path.abspath(__file__))
    photos_map = {
        "amazon_minimalist": [
            "multimedia/Amazon_minimalist/Casa_frente.jpg",
            "multimedia/Amazon_minimalist/Sala.jpg",
            "multimedia/Amazon_minimalist/habitacion_cama.jpg",
            "multimedia/Amazon_minimalist/balcon_mecedoras.jpg"
        ],
        "family_amazon_minimalist": [
            "multimedia/Family_Amazon_minimalist/Casa_frente.jpg",
            "multimedia/Family_Amazon_minimalist/Sala_principal.jpg",
            "multimedia/Family_Amazon_minimalist/Habitacion_1_camas.jpg",
            "multimedia/Family_Amazon_minimalist/balcon_mecedoras.jpg"
        ]
    }
    
    paths = photos_map.get(apartment_id, [])
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    data = {"message_type": "outgoing", "private": "false"}
    
    sent_count = 0
    for rel_path in paths:
        path = os.path.join(base_dir, rel_path)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    files = {"attachments[]": (os.path.basename(path), f, "image/jpeg")}
                    httpx.post(url, headers=headers, data=data, files=files, timeout=20.0)
                    sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send photo {path}: {e}")
                
    return {"status": f"Sent {sent_count} photos to the user", "apartment_id": apartment_id}

def confirm_booking(
    apartment_id: str, check_in: str, check_out: str, num_guests: int,
    guest_name: str, guest_email: str, guest_phone: str, guest_id: str,
    total_price: int, notes: str = ""
) -> dict:
    """Confirms a booking and blocks the dates."""
    logger.info(f"Tool confirm_booking called for {guest_name} at {apartment_id}")
    try:
        url = "http://localhost:8000/bookings"
        payload = {
            "apt": apartment_id, "check_in": check_in, "check_out": check_out,
            "num_guests": num_guests, "guest_name": guest_name, "guest_email": guest_email,
            "guest_phone": guest_phone, "guest_id": guest_id, "total_price": total_price,
            "price_per_night": int(total_price / max(1, num_guests)) if total_price else 0, # Approximation if not passed specifically
            "notes": notes
        }
        headers = {"X-API-Key": os.environ.get("API_KEY", "dev-key-change-me")}
        with httpx.Client() as client_http:
            resp = client_http.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                return {"success": True, "message": "Booking successful and dates blocked"}
            return {"success": False, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}

def label_conversation(conversation_id: int, labels: list) -> dict:
    """Labels the chatwoot conversation."""
    logger.info(f"Tool label_conversation called: {labels}")
    try:
        url = "http://localhost:8000/conversations/label"
        headers = {"X-API-Key": os.environ.get("API_KEY", "dev-key-change-me")}
        with httpx.Client() as client_http:
            client_http.post(url, json={"conversation_id": conversation_id, "labels": labels}, headers=headers)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# OPENAI-STYLE TOOLS (Agnostic format)
LLM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_apartment",
            "description": "Consultar disponibilidad de apartamentos, precios, detalles, amenidades y reglas. Usa esta funcion si el usuario pregunta por fechas, precios o detalles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_type": {
                        "type": "string",
                        "enum": ["all", "availability", "details", "prices", "photos"],
                        "description": "Que informacion se consulta"
                    },
                    "apartment_id": {
                        "type": "string",
                        "enum": ["amazon_minimalist", "family_amazon_minimalist"],
                        "description": "ID del apartamento. OMITELO TOTALMENTE si el cliente no dio un nombre explicito."
                    },
                    "check_in": {
                        "type": "string",
                        "description": "Fecha de check-in YYYY-MM-DD"
                    },
                    "check_out": {
                        "type": "string",
                        "description": "Fecha de check-out YYYY-MM-DD"
                    },
                    "num_guests": {
                        "type": "integer",
                        "description": "Cantidad de personas. Si el cliente no te lo ha especificado, DEBES enviar 0 (CERO). JAMAS INVENTES NI ASUMAS ESTE NUMERO."
                    }
                },
                "required": ["question_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "include_photos",
            "description": "Envia fotos del apartamento indicado SI Y SOLO SI el usuario pidio explicitamente ver fotos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "apartment_id": {
                        "type": "string",
                        "enum": ["amazon_minimalist", "family_amazon_minimalist"]
                    }
                },
                "required": ["apartment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_booking",
            "description": "Confirma la reserva SOLO despues de que el huesped acepto un resumen formal de precio y fechas, y te entrego sus datos, identificacion, nombres y el resto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "apartment_id": {"type": "string"},
                    "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                    "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                    "num_guests": {"type": "string", "description": "Cantidad de personas como texto"},
                    "guest_name": {"type": "string"},
                    "guest_email": {"type": "string"},
                    "guest_phone": {"type": "string"},
                    "guest_id": {"type": "string"},
                    "total_price": {"type": "string", "description": "Precio como texto"},
                    "notes": {"type": "string"}
                },
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Utiliza esta herramienta EXCLUSIVAMENTE cuando el usuario ponga una queja, pida hablar con un humano, o tenga un problema fuera de tu alcance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Razón para transferirlo"}
                },
                "required": ["reason"]
            }
        }
    }
]

# --- Router & Error Fallback Logic ---
def is_valid_name(name: str) -> bool:
    if not name or not name.strip(): return False
    if re.match(r'^\+?\d+$', name.strip()): return False
    if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ \-]+$', name.strip()): return False
    return True

def send_chatwoot_message(account_id: int, conversation_id: int, content: str):
    """Send message to Chatwoot."""
    logger.info(f"Sending message to Chatwoot conv_id={conversation_id}: {content}")
    if not CHATWOOT_API_TOKEN:
        logger.warning("No CHATWOOT_API_TOKEN set, cannot send message.")
        return
    
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    payload = {"content": content, "message_type": "outgoing", "private": False}
    try:
        with httpx.Client() as client_http:
            client_http.post(url, json=payload, headers=headers, timeout=5.0)
    except Exception as e:
        logger.error(f"Failed to send Chatwoot message: {e}")
        # Notify admin of exact silent failure
        if not SMTP_USER or not SMTP_PASSWORD: return
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import smtplib
            
            msg = MIMEMultipart()
            msg['From'] = SMTP_USER
            msg['To'] = ADMIN_EMAIL
            msg['Subject'] = "⚠️ ALERTA CRÍTICA: Fallo publicando mensaje en WhatsApp"
            body = f"🚨 ¡Hola Equipo!\n\nEl Agente IA generó una respuesta pero Chatwoot no respondió a tiempo o se cayó y el mensaje NO llegó al cliente (La IA se quedó en silencio).\n\nConversación ID: {conversation_id}\n\nMensaje que intentó enviar:\n{content}\n\nError Técnico:\n{e}"
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) if SMTP_PORT == 465 else smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            if SMTP_PORT != 465: server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
        except Exception as mail_e:
            logger.error(f"Failed to send critical alert email: {mail_e}")

def send_typing_indicator(account_id: int, conversation_id: int, status: str = "on"):
    """Toggle typing status in Chatwoot (on/off)."""
    if not CHATWOOT_API_TOKEN: return
    
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_typing_status"
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    payload = {"typing_status": status}
    try:
        with httpx.Client() as client_http:
            client_http.post(url, json=payload, headers=headers, timeout=2.0)
    except Exception as e:
        logger.warning(f"Failed to toggle typing status: {e}")

def trigger_error_contingency(account_id: int, conversation_id: int, sender_name: str, sender_phone: str, last_message: str, error_detail: str = "Error desconocido"):
    """Sends email to admin and fallback message to user."""
    logger.error(f"Triggering Error Contingency: {error_detail}")
    send_chatwoot_message(account_id, conversation_id, "Disculpa, regálame un momento por favor y ya te confirmo el dato.")
    label_conversation(conversation_id, ["requiere-humano"])
    
    if not SMTP_USER or not SMTP_PASSWORD: return
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = "⚠️ ALERTA: Intervención requerida en WhatsApp"
        body = f"""🚨 ¡Hola Equipo!

El agente IA (Sofía) no pudo generar una respuesta debido a un fallo inferencial del Motor LLM. Por favor atiendan este chat de inmediato.

👤 Nombre: {sender_name}
📱 Teléfono: {sender_phone}
💬 Último Mensaje: {last_message}
🔗 Link Chatwoot: {CHATWOOT_API_URL}/app/accounts/{account_id}/conversations/{conversation_id}

🛠️ DETALLE TÉCNICO DEL ERROR:
{error_detail}"""
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) if SMTP_PORT == 465 else smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        if SMTP_PORT != 465: server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info("Alert email sent.")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")

def fetch_chatwoot_history(account_id: int, conversation_id: int) -> list:
    """Fetch last 20 messages from Chatwoot to reconstruct short-term memory."""
    if not CHATWOOT_API_TOKEN:
        return []
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    try:
        with httpx.Client() as client_http:
            resp = client_http.get(url, headers=headers, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                payload = data.get("payload", [])
                history = []
                for m in reversed(payload[:15]):
                    if m.get("message_type") in (0, 1) and m.get("content"):
                        role = "user" if m["message_type"] == 0 else "assistant"
                        history.append({"role": role, "content": m["content"]})
                return history
    except Exception as e:
        logger.error(f"Failed to fetch history: {e}")
    return []

# --- Main Agent Processing ---
def process_message(account_id: int, conversation_id: int, sender_name: str, sender_phone: str, message_content: str):
    """Main workflow to process an incoming message natively with LLM Router."""
    logger.info(f"Processing message from {sender_name} - {sender_phone}: {message_content}")
    # 2. IA Processing (Multi-Model)
    
    # 2. IA Processing (Multi-Model)
    # The API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY, etc) 
    # are automatically picked up by LiteLLM. If missing, it will raise an Exception
    # that is safely caught at the bottom, triggering the Error Contingency flow.
    
    # Initialize memory if new
    if conversation_id not in chat_memory:
        # Fetch REST Short history
        history = fetch_chatwoot_history(account_id, conversation_id)
        
        # Fetch Long-Term context from Postgres (via internal API)
        long_term_prompt = ""
        try:
            url_context = f"http://localhost:8000/bookings/contact/{sender_phone}"
            headers_ctx = {"X-API-Key": os.environ.get("API_KEY", "dev-key-change-me")}
            with httpx.Client() as client_http:
                resp_ctx = client_http.get(url_context, headers=headers_ctx, timeout=5.0)
                if resp_ctx.status_code == 200:
                    data_ctx = resp_ctx.json()
                    contact_name = data_ctx.get("name", "")
                    last_summary = data_ctx.get("last_summary", "")
                    past_bookings = data_ctx.get("past_bookings", [])
                    
                    if contact_name or last_summary or past_bookings:
                        long_term_prompt = "--- CONTEXTO HISTÓRICO DE ESTE CONTACTO (NO VISIBLE PARA ÉL) ---\n"
                        if contact_name:
                            long_term_prompt += f"Nombre recordado: {contact_name}\n"
                        if last_summary:
                            long_term_prompt += f"Resumen última vez que hablaron: {last_summary}\n"
                        if past_bookings:
                            long_term_prompt += f"Cantidad de reservas previas exitosas: {len(past_bookings)}\n"
                        long_term_prompt += "------------------------------------------------------------\n"
        except Exception as e:
            logger.error(f"Failed to fetch long term context: {e}")

        base_msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # --- INJECT CURRENT DATE & TIME ---
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        time_prompt = f"--- RELOJ DEL SISTEMA ---\nLa fecha y hora actual es: {now_str}. SIEMPRE asume que cualquier mes o día solicitado ({now_str[:4]}) corresponde a fechas iguales o futuras respecto al reloj actual. NUNCA asumas años pasados.\n-------------------------\n"
        base_msgs.append({"role": "system", "content": time_prompt})
        
        if long_term_prompt:
            base_msgs.append({"role": "system", "content": long_term_prompt})
            
        if history and history[-1]["role"] == "user":
            history = history[:-1] # Pop the last message to avoid duplication with our prompt below
        if history:
            base_msgs.extend(history)
        chat_memory[conversation_id] = base_msgs

    # Reference the conversation
    messages = chat_memory[conversation_id]
    user_prompt = f"[Contact Name (if available): {sender_name}]\n[Contact Phone: {sender_phone}]\n[Message]: {message_content}"
    messages.append({"role": "user", "content": user_prompt})
    
    # Truncate memory safely to avoid splitting 'tool' and 'tool_calls' pairs
    if len(messages) > 21:
        sys_msgs = [m for m in messages if m["role"] == "system"]
        recent = messages[len(sys_msgs):]
        
        cut_idx = max(0, len(recent) - 20)
        # Move forward until we find a clean cut point (user or plain assistant msg)
        while cut_idx < len(recent):
            if recent[cut_idx]["role"] == "tool" or recent[cut_idx].get("tool_calls"):
                cut_idx += 1
            else:
                break
                
        messages = sys_msgs + recent[cut_idx:]
        chat_memory[conversation_id] = messages
    
    # Activar "escribiendo..."
    send_typing_indicator(account_id, conversation_id, "on")
    
    try:
        max_turns = 3
        turn_count = 0
        
        while turn_count < max_turns:
            response = litellm.completion(
                model=LLM_MODEL,
                messages=messages,
                tools=LLM_TOOLS,
                tool_choice="auto",
                max_tokens=600,
                temperature=0.8
            )
            response_message = response.choices[0].message
            # litellm returns its own Object classes, converting directly
            messages.append(response_message.model_dump(exclude_unset=True))
            
            tool_calls = getattr(response_message, 'tool_calls', None)
            
            if tool_calls:
                # Si el LLM adjuntó un texto junto a la petición de herramienta (ej. alucinaciones preliminares) lo silenciamos hacia el cliente para evitar confusiones.
                final_text = getattr(response_message, 'content', '') or ''
                if final_text.strip():
                    logger.info(f"LLM preliminary text hidden from user: {final_text.strip()}")

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except Exception:
                        function_args = {}
                    
                    # Convert string numbers to int to satisfy Python functions
                    for key in ['num_guests', 'total_price']:
                        if key in function_args:
                            try:
                                function_args[key] = int(function_args[key])
                            except Exception:
                                pass
                    
                    logger.info(f"LLM tool call [{turn_count}]: {function_name} with args {function_args}")
                    
                    # Execute mapped function
                    try:
                        if function_name == "query_apartment":
                            tool_result = query_apartment(**function_args)
                            label_conversation(conversation_id, ["cotizando"])
                        elif function_name == "include_photos":
                            function_args['account_id'] = account_id
                            function_args['conversation_id'] = conversation_id
                            tool_result = include_photos(**function_args)
                        elif function_name == "confirm_booking":
                            tool_result = confirm_booking(**function_args)
                            label_conversation(conversation_id, ["reservado"])
                        elif function_name == "escalate_to_human":
                            label_conversation(conversation_id, ["requiere-humano"])
                            tool_result = {"success": True, "message": "Atención humana solicitada."}
                        else:
                            tool_result = {"error": "Unknown function"}
                    except Exception as e:
                        tool_result = {"error": str(e)}

                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(tool_result)
                    })
                
                turn_count += 1
            else:
                # Normal Response
                send_typing_indicator(account_id, conversation_id, "off")
                final_text = getattr(response_message, 'content', '') or ''
                if not final_text.strip():
                    raise Exception("LLM response text empty. (Tool loop ended without text)")
                    
                send_chatwoot_message(account_id, conversation_id, final_text)
                
                # Auto-apply "interesado" on pure text responses without major tools in the first turn
                if turn_count == 0:
                    label_conversation(conversation_id, ["interesado"])

                break
                
        if turn_count >= max_turns:
            send_typing_indicator(account_id, conversation_id, "off")
            raise Exception("Maximum tool call loops exceeded.")
            
    except Exception as e:
        send_typing_indicator(account_id, conversation_id, "off")
        logger.error(f"Error during LLM Multi-Model inference: {e}")
        # En caso de Limit Quota o error interno, se detona el Error Contingency
        trigger_error_contingency(account_id, conversation_id, sender_name, sender_phone, message_content, str(e))
