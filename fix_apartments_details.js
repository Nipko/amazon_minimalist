const fs = require('fs');
const path = require('path');

function findDetailsFile() {
    if (fs.existsSync('apartments_details.json')) return 'apartments_details.json';
    if (fs.existsSync('data/apartments_details.json')) return 'data/apartments_details.json';
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
        console.log('apartments_details.json updated.');
    } else {
        console.log('apartments_details.json is clean.');
    }
} else {
    // List potential locations just in case
    console.log('apartments_details.json NOT FOUND. Listing root:');
    fs.readdirSync('.').forEach(f => console.log(' - ' + f));
    if (fs.existsSync('data')) {
        console.log('Listing data/:');
        fs.readdirSync('data').forEach(f => console.log(' - ' + f));
    }
}
