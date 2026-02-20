const fs = require('fs');

try {
    const d = JSON.parse(fs.readFileSync('n8n_workflow.json', 'utf8'));

    // Check Wait node connections
    const waitNodeName = '⏳ Esperar 5s';
    const waitNode = d.nodes.find(n => n.name === waitNodeName);

    if (!waitNode) {
        console.log('ERROR: Wait node not found!');
    } else {
        const conns = d.connections[waitNodeName];
        if (!conns || !conns.main || !conns.main[0] || conns.main[0].length === 0) {
            console.log('ERROR: Wait node has NO outgoing connections! Loop is broken.');
        } else {
            const target = conns.main[0][0].node;
            console.log(`Wait node connects to: ${target}`);
            if (target !== '🔄 Una por Una') {
                console.log('WARNING: Wait node does not connect back to SplitInBatches!');
            } else {
                console.log('SUCCESS: Loop is correctly closed.');
            }
        }
    }

    // Check Enviar Respuesta connections
    const sendResp = '📱 Enviar Respuesta';
    const sendConns = d.connections[sendResp];
    if (sendConns && sendConns.main && sendConns.main[0]) {
        console.log(`Enviar Respuesta connects to: ${sendConns.main[0].map(c => c.node).join(', ')}`);
    } else {
        console.log('ERROR: Enviar Respuesta has no connections!');
    }

    // Check Data File
    if (fs.existsSync('data/apartments_details.json')) {
        const details = JSON.parse(fs.readFileSync('data/apartments_details.json', 'utf8'));
        console.log(`Amazon photos count: ${details.amazon_minimalist?.photos?.length || 0}`);
        console.log(`Family photos count: ${details.family_amazon_minimalist?.photos?.length || 0}`);
    } else {
        console.log('ERROR: data/apartments_details.json not found!');
    }

} catch (e) {
    console.error(e);
}
