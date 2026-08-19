document.addEventListener('DOMContentLoaded', function () {
    console.log('Dashboard Initializing...');

    // Initialize Components
    if (typeof initMap === 'function') {
        initMap();
    }

    if (typeof initCharts === 'function') {
        initCharts();
    }

    if (typeof initDataDisplay === 'function') {
        initDataDisplay();
    }

    // Event Listeners for Filters
    const yearFilter = document.getElementById('year-filter');
    const seasonRadios = document.getElementsByName('season-filter');

    if (yearFilter) {
        yearFilter.addEventListener('change', function (e) {
            updateDashboard(e.target.value, getSelectedSeason());
        });
    }

    seasonRadios.forEach(radio => {
        radio.addEventListener('change', function (e) {
            updateDashboard(document.getElementById('year-filter').value, e.target.id);
        });
    });

    function getSelectedSeason() {
        const checkedRadio = document.querySelector('input[name="season-filter"]:checked');
        return checkedRadio ? checkedRadio.id : 'spring';
    }

    function updateDashboard(year, season) {
        console.log(`Updating dashboard for Year: ${year}, Season: ${season}`);

        // Show loading
        const loader = document.getElementById('loading-indicator');
        if (loader) loader.classList.remove('d-none');

        // Trigger updates in components
        if (typeof updateMapLayer === 'function') updateMapLayer(year, season);
        if (typeof updateCharts === 'function') updateCharts(year, season);
        if (typeof updateInsights === 'function') updateInsights(year, season);

        // Hide loading (simulated delay)
        setTimeout(() => {
            if (loader) loader.classList.add('d-none');
        }, 500);
    }
});
