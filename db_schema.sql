-- Script para crear tablas de memoria a largo plazo en PostgreSQL para n8n

-- 1. Tabla de Contactos / Conversaciones
-- Guarda el resumen de la última interacción para dar contexto al Agente IA
CREATE TABLE IF NOT EXISTS conversaciones (
    id SERIAL PRIMARY KEY,
    telefono VARCHAR(20) UNIQUE NOT NULL,
    nombre_contacto VARCHAR(100),
    ultimo_resumen TEXT,
    fecha_ultimo_mensaje TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    es_nombre_valido BOOLEAN DEFAULT FALSE
);

-- 2. Tabla de Reservas
-- Historial completo de reservas para saber si el cliente es recurrente
CREATE TABLE IF NOT EXISTS reservas (
    id SERIAL PRIMARY KEY,
    fk_telefono VARCHAR(20) REFERENCES conversaciones(telefono) ON DELETE CASCADE,
    apartamento_id VARCHAR(50) NOT NULL,
    nombre_reserva VARCHAR(100) NOT NULL,
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    num_huespedes INTEGER NOT NULL,
    precio_total NUMERIC(10, 2) NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices para búsquedas rápidas desde n8n
CREATE INDEX IF NOT EXISTS idx_conversaciones_telefono ON conversaciones(telefono);
CREATE INDEX IF NOT EXISTS idx_reservas_telefono ON reservas(fk_telefono);
CREATE INDEX IF NOT EXISTS idx_reservas_fechas ON reservas(check_in, check_out);

COMMENT ON TABLE conversaciones IS 'Tabla para que el Agente IA recuerde la última charla con el cliente';
COMMENT ON TABLE reservas IS 'Historial de reservas confirmadas por el Agente IA';
