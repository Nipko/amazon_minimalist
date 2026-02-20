const fs = require('fs');
const d = JSON.parse(fs.readFileSync('n8n_workflow.json', 'utf8'));

// Fix Procesar Fotos script to be robust
const procesar = d.nodes.find(n => n.name === '🖼️ Procesar Fotos');

const newCode = `// Extract text from the active branch (Agent or Quick Reply)
const json = $input.first().json;
let text = '';

// Try to get text from input first
if (json.output) {
    text = json.output; // From Sales Agent
} else if (json.quick_reply) {
    text = json.quick_reply; // From Quick Reply
} else {
    // Fallback: try to resolve from node references safely
    try { text = $('🤖 Sales Agent').first().json.output; } catch(e) {}
    if (!text) try { text = $('💬 Respuesta Rápida').first().json.quick_reply; } catch(e) {}
}

text = text || '';

// Extract [FOTO:apartment_id] tags
const photoMatches = text.match(/\\[FOTO:(\\w+)\\]/gi) || [];
const photo_apartments = photoMatches.map(m => m.match(/FOTO:(\\w+)/i)[1]);

// Clean text: remove tags
const clean_text = text.replace(/\\[FOTO:\\w+\\]/gi, '').replace(/\\[VIDEO:\\w+\\]/gi, '').trim();

// Get context from Router (always available)
const router = $('🧭 Router Inteligente').first().json;

return [{
    json: {
        clean_text,
        has_photos: photo_apartments.length > 0,
        photo_apartments,
        account_id: router.account_id,
        conversation_id: router.conversation_id,
        sender_name: router.sender_name
    }
}];`;

procesar.parameters.jsCode = newCode;

fs.writeFileSync('n8n_workflow.json', JSON.stringify(d, null, 4));
console.log('Fixed Procesar Fotos script for robustness.');
