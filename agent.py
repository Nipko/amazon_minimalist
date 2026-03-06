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
from groq import Groq

import avail_checker
from api import load_details

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Agent")

# --- Configure Groq ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)
else:
    logger.warning("No Groq API key found in environment variables (GROQ_API_KEY).")
    client = None

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
    apt_ids = [apartment_id] if apartment_id and apartment_id in details else [k for k in details.keys() if k not in ("legal", "cross_apartment_policy")]
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
            
        if question_type in ("availability", "all") and check_in and check_out:
            res = avail_checker.check_apartment_availability(apt, check_in, check_out, config)
            apt_info["availability_status"] = "Available" if res.get("available") else "Not Available"
            if res.get("error"):
                apt_info["availability_error"] = res["error"]
            if res.get("available") and num_guests and apt_info.get("price_per_night"):
                from datetime import datetime
                try:
                    nights = (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days
                    apt_info["total_price_estimate_cop"] = nights * apt_info.get("price_per_night", 0)
                except: pass
        response_data[apt] = apt_info
    return response_data

def include_photos(apartment_id: str) -> dict:
    """Send apartment photos to the user."""
    logger.info(f"Tool include_photos called: apt={apartment_id}")
    return {"status": "Photos queued to be sent to the user", "apartment_id": apartment_id}

def confirm_booking(
    apartment_id: str, check_in: str, check_out: str, num_guests: int,
    guest_name: str, guest_email: str, guest_phone: str, guest_id: str,
    total_price: int, notes: str = ""
) -> dict:
    """Confirms a booking and blocks the dates."""
    logger.info(f"Tool confirm_booking called for {guest_name} at {apartment_id}")
    try:
        url = "http://localhost:8000/confirm-booking"
        payload = {
            "apartment_id": apartment_id, "check_in": check_in, "check_out": check_out,
            "num_guests": num_guests, "guest_name": guest_name, "guest_email": guest_email,
            "guest_phone": guest_phone, "guest_id": guest_id, "total_price": total_price,
            "notes": notes, "source": "WhatsApp Bot"
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

# GROQ OAI TOOLS
GROQ_TOOLS = [
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
                        "description": "ID del apartamento, omite si el usuario no especifico uno en particular"
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
                        "description": "Cantidad de personas"
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
                    "num_guests": {"type": "integer"},
                    "guest_name": {"type": "string"},
                    "guest_email": {"type": "string"},
                    "guest_phone": {"type": "string"},
                    "guest_id": {"type": "string"},
                    "total_price": {"type": "integer"},
                    "notes": {"type": "string"}
                },
                "required": ["apartment_id", "check_in", "check_out", "num_guests", "guest_name", "total_price"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "label_conversation",
            "description": "Etiqueta el chatwoot segun la intencion: 'interesado', 'cotizando', 'reservado', 'requiere-humano'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "integer"},
                    "labels": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["conversation_id", "labels"]
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

GREETINGS = re.compile(r'^(hola|hi|hello|hey|buenas?|buenos?\s*(dias|tardes|noches)|que\s*tal|saludos?)$', re.IGNORECASE)
ACKS = re.compile(r'^(ok|okay|listo|vale|perfecto|genial|gracias|muchas\s*gracias|de\s*acuerdo|entendido|claro|super|excelente|buenisimo|chevere)$', re.IGNORECASE)

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

El agente IA (Sofía) no pudo generar una respuesta debido a un error del sistema Groq. Por favor atiendan este chat de inmediato.

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

# --- Main Agent Processing ---
def process_message(account_id: int, conversation_id: int, sender_name: str, sender_phone: str, message_content: str):
    """Main workflow to process an incoming message natively with Groq."""
    logger.info(f"Processing message from {sender_name} - {sender_phone}: {message_content}")
    clean_msg = re.sub(r'[!¡¿?.,;:]', '', message_content).strip().lower()
    
    # 1. Router Inteligente
    if GREETINGS.match(clean_msg):
        msg = f"¡Hola, {sender_name.strip()}! 👋 Soy Sofía de Amazon Minimalist. ¿En qué puedo ayudarte? 😊" if is_valid_name(sender_name) else "¡Hola! Soy Sofía de Amazon Minimalist. ¿Con quién tengo el gusto? 😊"
        send_chatwoot_message(account_id, conversation_id, msg)
        return
    elif ACKS.match(clean_msg):
        send_chatwoot_message(account_id, conversation_id, '¡Con gusto! Si necesitas algo más, aquí estoy 😊')
        return

    # 2. IA Processing (Groq - Llama 3)
    if not client:
        trigger_error_contingency(account_id, conversation_id, sender_name, sender_phone, message_content, "GROQ_API_KEY no configurada.")
        return

    # Initialize memory if new
    if conversation_id not in chat_memory:
        chat_memory[conversation_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    # Reference the conversation
    messages = chat_memory[conversation_id]
    
    user_prompt = f"[Contact Name (if available): {sender_name}]\n[Contact Phone: {sender_phone}]\n[Message]: {message_content}"
    messages.append({"role": "user", "content": user_prompt})
    
    # Truncate memory to avoid context window explosion (keep system prompt + last 20 messages max)
    if len(messages) > 21:
        messages = [messages[0]] + messages[-20:]
        chat_memory[conversation_id] = messages
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=GROQ_TOOLS,
            tool_choice="auto",
            max_tokens=600
        )
        response_message = response.choices[0].message
        
        # Guardar en historial el output real sin modificar
        messages.append(response_message)
        
        tool_calls = getattr(response_message, 'tool_calls', None)
        
        # Si hubo llamados a herramientas
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                try:
                    function_args = json.loads(tool_call.function.arguments)
                except Exception:
                    function_args = {}
                
                logger.info(f"Groq tool call: {function_name} with args {function_args}")
                
                # Execute mapped function
                try:
                    if function_name == "query_apartment":
                        tool_result = query_apartment(**function_args)
                    elif function_name == "include_photos":
                        tool_result = include_photos(**function_args)
                    elif function_name == "confirm_booking":
                        tool_result = confirm_booking(**function_args)
                    elif function_name == "label_conversation":
                        tool_result = label_conversation(**function_args)
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
            
            # Segunda llamada al LLM con el resultado
            second_response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=GROQ_TOOLS,
                max_tokens=600
            )
            final_text = second_response.choices[0].message.content
            messages.append({"role": "assistant", "content": final_text})
            
            # Validate output
            if not final_text or not final_text.strip():
                raise Exception("Groq second response text empty.")
                
            send_chatwoot_message(account_id, conversation_id, final_text)
            
        else:
            # Respuesta normal sin herramientas
            final_text = getattr(response_message, 'content', '') or ''
            if not final_text.strip():
                raise Exception("Groq first response text empty.")
            send_chatwoot_message(account_id, conversation_id, final_text)
            
    except Exception as e:
        logger.error(f"Error during Groq LLM inference: {e}")
        # En caso de Limit Quota o error interno, se detona el Error Contingency
        trigger_error_contingency(account_id, conversation_id, sender_name, sender_phone, message_content, str(e))
