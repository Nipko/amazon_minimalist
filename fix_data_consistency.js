const fs = require('fs');
const path = require('path');

function findDetailsFile() {
    if (fs.existsSync('details.json')) return 'details.json';
    if (fs.existsSync('data/details.json')) return 'data/details.json';
    return null;
}

const detailsPath = findDetailsFile();
if (detailsPath) {
    console.log(`Found details file at: ${detailsPath}`);
    let details = JSON.parse(fs.readFileSync(detailsPath, 'utf8'));
    let changed = false;

    for (const apt in details) {
        if (apt === 'legal' || apt === 'cross_apartment_policy') continue;

        const info = details[apt];

        // Fix Photos: remove broken links
        if (info.photos) {
            const originalCount = info.photos.length;
            info.photos = info.photos.filter(p => {
                const exists = fs.existsSync(path.join('multimedia', apt, p));
                if (!exists) console.log(`  Removing broken photo: ${apt}/${p}`);
                return exists;
            });
            if (info.photos.length !== originalCount) changed = true;
        }

        // Fix Videos: remove all (using YouTube links now)
        if (info.videos && info.videos.length > 0) {
            console.log(`  Removing ${info.videos.length} video refs from ${apt} (using YouTube)`);
            info.videos = [];
            changed = true;
        }
    }

    if (changed) {
        fs.writeFileSync(detailsPath, JSON.stringify(details, null, 4));
        console.log('details.json updated.');
    } else {
        console.log('details.json is clean.');
    }
} else {
    console.log('details.json NOT FOUND.');
}

// Fix n8n workflow
if (fs.existsSync('n8n_workflow.json')) {
    console.log('\nChecking n8n_workflow.json...');
    const d = JSON.parse(fs.readFileSync('n8n_workflow.json', 'utf8'));
    let n8nChanged = false;

    // 1. Ensure Descargar Foto continues on error (for resilience)
    const dl = d.nodes.find(n => n.name === '📥 Descargar Foto');
    if (dl) {
        if (dl.onError !== 'continueRegularOutput') {
            dl.onError = 'continueRegularOutput';
            console.log('  Fixed: Descargar Foto onError set to continueRegularOutput');
            n8nChanged = true;
        }
    }

    // 2. Ensure Photo Limit is 8
    const expand = d.nodes.find(n => n.name === '📸 Expandir URLs');
    if (expand) {
        let code = expand.parameters.jsCode || '';
        if (code.includes('slice(0, 3)')) {
            expand.parameters.jsCode = code.replace('slice(0, 3)', 'slice(0, 8)');
            console.log('  Fixed: Photo limit increased from 3 to 8');
            n8nChanged = true;
        }
    }

    if (n8nChanged) {
        fs.writeFileSync('n8n_workflow.json', JSON.stringify(d, null, 4));
        console.log('n8n_workflow.json updated.');
    } else {
        console.log('n8n_workflow.json is clean.');
    }
}
