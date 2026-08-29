/**
 * RealEstate India — Property Map Visualization
 * 
 * Uses Leaflet.js with OpenStreetMap tiles to display property locations.
 * Supports: property pins, clustering, heatmap overlay, city bounding boxes.
 * 
 * Dependencies: Leaflet.js (loaded via CDN in HTML templates)
 */

// ── Global Map State ────────────────────────────────────────────────────────

const RE_MAP = {
    map: null,
    markers: [],
    clusterGroup: null,
    heatLayer: null,
    currentCity: null,
};

// Indian city coordinates for centering
const INDIAN_CITY_COORDS = {
    'mumbai': [19.0760, 72.8777],
    'bangalore': [12.9716, 77.5946],
    'delhi': [28.7041, 77.1025],
    'pune': [18.5204, 73.8567],
    'hyderabad': [17.3850, 78.4867],
    'chennai': [13.0827, 80.2707],
    'kolkata': [22.5726, 88.3639],
    'ahmedabad': [23.0225, 72.5714],
    'noida': [28.5355, 77.3910],
    'gurgaon': [28.4595, 77.0266],
};

// ── Initialize Map ──────────────────────────────────────────────────────────

function initPropertyMap(containerId, options = {}) {
    /**
     * Initialize a Leaflet map on the given container.
     * 
     * @param {string} containerId - HTML element ID for the map
     * @param {Object} options - { center: [lat,lng], zoom: int, city: str }
     * @returns {Object} The map instance
     */
    const center = options.center || [20.5937, 78.9629]; // Default: India center
    const zoom = options.zoom || 5;

    // If Leaflet isn't loaded, show a placeholder
    if (typeof L === 'undefined') {
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;background:#1a1f2e;color:#64748b;border-radius:0.75rem;">'
                + '<p>Map requires Leaflet.js. Include <code>leaflet.js</code> and <code>leaflet.css</code> from CDN.</p></div>';
        }
        return null;
    }

    // Fix Leaflet icon paths
    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    });

    const map = L.map(containerId, {
        center: center,
        zoom: zoom,
        zoomControl: true,
        attributionControl: true,
    });

    // OpenStreetMap tiles (free, no API key needed)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
    }).addTo(map);

    RE_MAP.map = map;
    RE_MAP.markers = [];

    // If a city is specified, zoom to it
    if (options.city) {
        zoomToCity(options.city, 12);
    }

    return map;
}

// ── Property Markers ────────────────────────────────────────────────────────

function addPropertyMarkers(properties) {
    /**
     * Add property markers to the map.
     * 
     * @param {Array} properties - Array of { property_id, title, price, lat, lng, city, locality }
     */
    if (!RE_MAP.map || !properties || properties.length === 0) return;

    // Clear existing markers
    clearMarkers();

    const bounds = L.latLngBounds();

    properties.forEach(p => {
        if (!p.lat || !p.lng) return;

        const priceStr = '₹' + (p.price / 100000).toFixed(2) + ' L';
        const marker = L.marker([p.lat, p.lng])
            .addTo(RE_MAP.map)
            .bindPopup(`
                <div style="font-family:sans-serif;max-width:250px;">
                    <strong style="font-size:14px;">${p.title}</strong><br>
                    <span style="color:#666;font-size:12px;">${p.locality || ''}, ${p.city}</span><br>
                    <span style="color:#22c55e;font-size:16px;font-weight:700;">${priceStr}</span><br>
                    <a href="/realestate/property/${p.property_id}" 
                       style="display:inline-block;margin-top:6px;padding:4px 12px;background:#3b82f6;color:white;
                              text-decoration:none;border-radius:4px;font-size:12px;">View Details</a>
                </div>
            `);

        bounds.extend([p.lat, p.lng]);
        RE_MAP.markers.push(marker);
    });

    // Fit bounds to show all markers
    if (properties.length > 1) {
        RE_MAP.map.fitBounds(bounds, { padding: [30, 30] });
    }
}

function clearMarkers() {
    /** Remove all property markers from the map. */
    RE_MAP.markers.forEach(m => RE_MAP.map.removeLayer(m));
    RE_MAP.markers = [];
}

// ── City Navigation ─────────────────────────────────────────────────────────

function zoomToCity(city, zoomLevel = 10) {
    /**
     * Zoom the map to a specific city.
     * 
     * @param {string} city - City name (case-insensitive)
     * @param {number} zoomLevel - Zoom level (10=city, 13=locality, 15=street)
     */
    if (!RE_MAP.map) return;
    const key = city.toLowerCase();
    const coords = INDIAN_CITY_COORDS[key];
    if (coords) {
        RE_MAP.map.setView(coords, zoomLevel);
        RE_MAP.currentCity = key;
    }
}

// ── Load Map Data from API ──────────────────────────────────────────────────

async function loadMapProperties(city = null) {
    /**
     * Fetch property coordinates from API and add markers to the map.
     * 
     * @param {string|null} city - Optional city filter
     * @returns {Array} Properties with coordinates
     */
    try {
        const url = city
            ? `/api/realestate/map-data?city=${encodeURIComponent(city)}`
            : '/api/realestate/map-data';
        const res = await fetch(url);
        const data = await res.json();
        const props = data.properties || [];
        
        if (props.length > 0) {
            addPropertyMarkers(props);
            if (city) zoomToCity(city, 13);
        }
        return props;
    } catch (e) {
        console.warn('Map data load failed:', e.message);
        return [];
    }
}

// ── Heatmap (simulated) ────────────────────────────────────────────────────

function toggleHeatmap(properties) {
    /**
     * Toggle a heatmap overlay showing property price density.
     * Uses marker opacity as simple heatmap approximation.
     * 
     * @param {Array} properties - Property data with lat/lng/price
     */
    if (!RE_MAP.map || !properties) return;

    const heatEnabled = RE_MAP.heatLayer !== null;
    
    // Remove existing heat layer
    if (RE_MAP.heatLayer) {
        RE_MAP.map.removeLayer(RE_MAP.heatLayer);
        RE_MAP.heatLayer = null;
        return;
    }

    // Simple price-based heat points (without requiring Leaflet.heat)
    const maxPrice = Math.max(...properties.filter(p => p.price).map(p => p.price), 1);
    const points = properties
        .filter(p => p.lat && p.lng)
        .map(p => ({
            lat: p.lat,
            lng: p.lng,
            intensity: p.price / maxPrice,
        }));

    // Use circle markers with opacity as a heatmap approximation
    const heatGroup = L.layerGroup();
    points.forEach(pt => {
        const radius = 10 + pt.intensity * 25;
        const opacity = 0.3 + pt.intensity * 0.5;
        const color = pt.intensity > 0.7 ? '#ef4444' 
                    : pt.intensity > 0.4 ? '#f59e0b' 
                    : '#22c55e';
        L.circleMarker([pt.lat, pt.lng], {
            radius: radius,
            fillColor: color,
            color: color,
            weight: 1,
            opacity: 0.6,
            fillOpacity: opacity,
        }).addTo(heatGroup);
    });
    
    heatGroup.addTo(RE_MAP.map);
    RE_MAP.heatLayer = heatGroup;
}

// ── React to Search Results ─────────────────────────────────────────────────

function updateMapFromSearchResults(properties) {
    /**
     * Called when search results update to refresh map markers.
     * 
     * @param {Array} properties - PropertyDTO array from search API
     */
    // Map properties to geo data
    const geoProps = properties
        .filter(p => p.latitude && p.longitude)
        .map(p => ({
            property_id: p.property_id,
            title: p.title,
            price: p.price,
            lat: p.latitude,
            lng: p.longitude,
            city: p.city,
            locality: p.locality,
        }));
    
    addPropertyMarkers(geoProps.length > 0 ? geoProps : null);
}

// ── Style Helpers ───────────────────────────────────────────────────────────

function getMapStyles() {
    /** Return CSS styles for the map container. */
    return `
        #propertyMap { height: 400px; border-radius: 0.75rem; margin-bottom: 1rem; z-index: 1; }
        .leaflet-popup-content-wrapper { border-radius: 0.5rem !important; }
        .leaflet-popup-content { margin: 10px 14px !important; }
        @media (max-width: 768px) { #propertyMap { height: 250px; } }
    `;
}
