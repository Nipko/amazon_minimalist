const fs = require('fs');

try {
    const d = JSON.parse(fs.readFileSync('n8n_workflow.json', 'utf8'));

    // Find nodes that connect TO '📱 Enviar Respuesta'
    const preds = Object.keys(d.connections).filter(k => {
        const conn = d.connections[k];
        if (!conn || !conn.main) return false;
        return conn.main.some(branch => branch && branch.some(link => link.node === '📱 Enviar Respuesta'));
    });
    console.log('Predecessors of Enviar Respuesta:', preds.join(', '));

    // Also check parameters of Enviar Respuesta to see what it uses
    const env = d.nodes.find(n => n.name === '📱 Enviar Respuesta');
    if (env) {
        console.log('Enviar Respuesta Parameters Content:', JSON.stringify(env.parameters.bodyParameters || env.parameters.content || env.parameters));
    }

} catch (e) {
    console.error(e);
}
