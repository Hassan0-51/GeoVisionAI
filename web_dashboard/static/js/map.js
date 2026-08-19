let map;
let maskLayer    = null;   // Classification mask  (z-index 100, top)
let rgbLayer     = null;   // Original RGB TIF      (z-index  50, middle)
let roiPolygon   = null;

let baseStreetLayer = null;
let baseSatLayer    = null;
let activeBaseLayer = null;

const DASHBOARD_DEFAULT_YEAR   = typeof DEFAULT_YEAR   !== 'undefined' ? DEFAULT_YEAR   : 2024;
const DASHBOARD_DEFAULT_SEASON = typeof DEFAULT_SEASON !== 'undefined' ? DEFAULT_SEASON : 'spring';

// ── Helpers ──────────────────────────────────────────────────────────────
function _opVal()        { return parseFloat(document.getElementById('layer-opacity')?.value ?? 0.7); }
function _checked(id)    { const el = document.getElementById(id); return el ? el.checked : true; }

function _applyBasemap() {
    if (!map || !baseStreetLayer || !baseSatLayer) return;
    const useSat = _checked('toggle-basemap-satellite');
    if (activeBaseLayer) {
        map.removeLayer(activeBaseLayer);
    }
    activeBaseLayer = useSat ? baseSatLayer : baseStreetLayer;
    activeBaseLayer.addTo(map);
}

// ── Map initialisation ───────────────────────────────────────────────────
function initMap() {
    map = L.map('map', { zoomControl: false }).setView([31.5497, 74.3436], 11);
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    baseStreetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap'
    });
    // Google Maps satellite tiles (same style as Google Maps “Satellite”)
    baseSatLayer = L.tileLayer(
        'https://mt{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        {
            maxZoom: 20,
            subdomains: '0123',
            attribution: '© Google'
        }
    );

    const basemapToggle = document.getElementById('toggle-basemap-satellite');
    if (basemapToggle && !basemapToggle.checked) {
        activeBaseLayer = baseStreetLayer;
        baseStreetLayer.addTo(map);
    } else {
        activeBaseLayer = baseSatLayer;
        baseSatLayer.addTo(map);
    }
    if (basemapToggle) {
        basemapToggle.addEventListener('change', _applyBasemap);
    }

    // ── Initial layer load ──────────────────────────────────────────────
    const initYear   = document.getElementById('year-filter')?.value  || DASHBOARD_DEFAULT_YEAR;
    const initSeason = document.querySelector('input[name="season-filter"]:checked')?.id || DASHBOARD_DEFAULT_SEASON;
    updateMapLayer(initYear, initSeason);

    // ── Mask opacity slider ─────────────────────────────────────────────
    const opSlider = document.getElementById('layer-opacity');
    const opLabel  = document.getElementById('opacity-value');
    if (opSlider) {
        opSlider.addEventListener('input', function (e) {
            const val = parseFloat(e.target.value);
            if (opLabel) opLabel.textContent = Math.round(val * 100) + '%';
            if (maskLayer && _checked('toggle-mask')) maskLayer.setOpacity(val);
        });
    }

    // ── Toggle: Classification Mask ─────────────────────────────────────
    const toggleMask = document.getElementById('toggle-mask');
    if (toggleMask) {
        toggleMask.addEventListener('change', function (e) {
            if (maskLayer) maskLayer.setOpacity(e.target.checked ? _opVal() : 0);
        });
    }

    // ── Toggle: Original RGB TIF ────────────────────────────────────────
    const toggleRgb = document.getElementById('toggle-rgb');
    if (toggleRgb) {
        toggleRgb.addEventListener('change', function (e) {
            if (rgbLayer) rgbLayer.setOpacity(e.target.checked ? 1 : 0);
        });
    }

    // ── Download mask button ────────────────────────────────────────────
    const downloadBtn = document.getElementById('download-mask-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', function () {
            const year   = document.getElementById('year-filter')?.value  || DASHBOARD_DEFAULT_YEAR;
            const season = document.querySelector('input[name="season-filter"]:checked')?.id || DASHBOARD_DEFAULT_SEASON;
            downloadCurrentMask(year, season);
        });
    }
}

// ── Core layer update ────────────────────────────────────────────────────
function updateMapLayer(year, season) {
    if (!map) return;

    const resultId = typeof RESULT_ID !== 'undefined' ? RESULT_ID : null;
    const apiUrl   = resultId
        ? `/dashboard/api/map-layers/?result_id=${resultId}`
        : '/dashboard/api/map-layers/';

    const indicator = document.getElementById('loading-indicator');
    if (indicator) indicator.classList.remove('d-none');

    // Remove all existing overlays
    [maskLayer, rgbLayer].forEach(l => { if (l) map.removeLayer(l); });
    maskLayer = null;
    rgbLayer = null;

    fetch(apiUrl)
        .then(r => r.json())
        .then(data => {
            if (!data.bounds) return;

            // Leaflet bounds [[minLat, minLng], [maxLat, maxLng]]
            const roiBounds = [
                [data.bounds[1], data.bounds[0]],
                [data.bounds[3], data.bounds[2]]
            ];

            // ROI outline polygon
            if (roiPolygon) map.removeLayer(roiPolygon);
            roiPolygon = L.rectangle(roiBounds, {
                color: '#ef4444', weight: 2, fill: false, dashArray: '5, 10'
            }).addTo(map);
            map.fitBounds(roiBounds, { padding: [20, 20], maxZoom: 13 });

            if (!resultId) return;

            const s = String(season).toLowerCase();
            const ts = Date.now();

            // ── Layer 1 (middle): Original TIF (ROI satellite from Image-New/Image) ──
            rgbLayer = L.imageOverlay(
                `/api/rgb-image/${resultId}/${year}/${s}/?t=${ts}`,
                roiBounds,
                { opacity: _checked('toggle-rgb') ? 1 : 0, zIndex: 50 }
            ).addTo(map);

            // ── Layer 2 (top): Classification Mask ────────────────────
            maskLayer = L.imageOverlay(
                `/api/mask-image/${resultId}/${year}/${s}/?t=${ts}`,
                roiBounds,
                { opacity: _checked('toggle-mask') ? _opVal() : 0, interactive: true, zIndex: 100 }
            ).addTo(map);

            console.log(`[Map] Layers loaded — ${year} / ${s}`);
        })
        .catch(err => console.error('Map loading error:', err))
        .finally(() => { if (indicator) indicator.classList.add('d-none'); });
}

// ── Mask download ────────────────────────────────────────────────────────
function downloadCurrentMask(year, season) {
    const resultId = typeof RESULT_ID !== 'undefined' ? RESULT_ID : null;
    if (!resultId) return;

    const s = String(season || DASHBOARD_DEFAULT_SEASON).toLowerCase();
    const url = `/api/mask-image/${resultId}/${year}/${s}/?format=tif`;

    fetch(url)
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.blob(); })
        .then(blob => {
            const objUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = objUrl;
            a.download = `mask_${resultId}_${year}_${s}.tif`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(objUrl);
        })
        .catch(err => console.error('Mask download failed:', err));
}
