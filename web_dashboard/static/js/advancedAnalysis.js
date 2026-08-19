function initAdvancedAnalysis() {
    const resultId = typeof RESULT_ID !== 'undefined' ? RESULT_ID : null;
    if (!resultId) return;

    fetchAdvancedData(resultId);
}

function fetchAdvancedData(resultId) {
    // Use the existing analysis-data endpoint which returns both llm_insights and advanced_analysis
    const url = `/dashboard/api/analysis-data/?result_id=${resultId}`;

    // Show loading
    const loadingEl = document.getElementById('advanced-loading');
    const contentEl = document.getElementById('advanced-content-body');
    const errorEl = document.getElementById('advanced-error');

    if (loadingEl) loadingEl.classList.remove('d-none');
    if (contentEl) contentEl.classList.add('d-none');
    if (errorEl) errorEl.classList.add('d-none');

    fetch(url)
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(responseData => {
            // The endpoint returns { llm_insights: {...}, advanced_analysis: {...} }
            const data = responseData.advanced_analysis || {};
            renderAdvancedData(data);
            if (loadingEl) loadingEl.classList.add('d-none');
            if (contentEl) contentEl.classList.remove('d-none');
        })
        .catch(error => {
            console.error('Error loading advanced analysis:', error);
            if (loadingEl) loadingEl.classList.add('d-none');
            if (errorEl) errorEl.classList.remove('d-none');
        });
}

function renderAdvancedData(data) {
    renderCarbon(data.carbon_sequestration);
    renderMetrics(data.spatial_metrics);
    renderAnomalies(data.anomaly_detection);
}

function renderCarbon(carbonData) {
    if (!carbonData || !carbonData.report || !carbonData.report.annual_changes) return;

    // Get latest year data
    const latest = carbonData.report.annual_changes[carbonData.report.annual_changes.length - 1];
    if (!latest) return;

    document.getElementById('total-carbon').textContent = formatNumber(latest.total_carbon_tons);
    // Rough estimate: Carbon * 3.67 = CO2
    const co2 = latest.total_carbon_tons * 3.67;
    document.getElementById('total-co2').textContent = formatNumber(co2);

    // Populate table
    const tableBody = document.querySelector('#carbon-table tbody');
    tableBody.innerHTML = '';

    if (latest.main_contributors) {
        latest.main_contributors.forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${item.class}</td>
                <td class="text-end">${formatNumber(item.carbon_tons)}</td>
                <td class="text-end text-muted">${item.percentage.toFixed(1)}%</td>
            `;
            tableBody.appendChild(row);
        });
    }
}

function renderMetrics(metricsData) {
    if (!metricsData || !metricsData.landscape) return;

    const landscape = metricsData.landscape;

    document.getElementById('shannon-index').textContent = landscape.shannon_diversity_index?.toFixed(2) || '--';
    document.getElementById('simpson-index').textContent = landscape.simpson_diversity_index?.toFixed(2) || '--';

    // Patch density might be in classes
    // Use fragmentation index if available, else 0
    document.getElementById('patch-density').textContent = landscape.fragmentation_index?.toFixed(2) || '0.00';
}

function renderAnomalies(anomalyData) {
    const listContainer = document.getElementById('anomalies-list');
    const noAnomaliesMsg = document.getElementById('no-anomalies');
    listContainer.innerHTML = '';

    if (!anomalyData || !anomalyData.detected_anomalies || anomalyData.detected_anomalies.length === 0) {
        noAnomaliesMsg.classList.remove('d-none');
        return;
    }

    noAnomaliesMsg.classList.add('d-none');

    anomalyData.detected_anomalies.forEach(anomaly => {
        const isHigh = anomaly.significance === 'Very High' || anomaly.significance === 'High';
        const badgeClass = isHigh ? 'bg-danger' : 'bg-warning text-dark';
        const iconInfo = anomaly.direction === 'increase' ? 'fa-arrow-up' : 'fa-arrow-down';

        const item = document.createElement('div');
        item.className = 'list-group-item d-flex justify-content-between align-items-center';
        item.innerHTML = `
            <div>
                <div class="fw-bold mb-1">
                    ${anomaly.class} 
                    <span class="badge ${badgeClass} ms-2">${anomaly.significance}</span>
                </div>
                <small class="text-muted">
                    Deviated by ${anomaly.deviation.toFixed(1)}% from historical mean.
                </small>
            </div>
            <div class="text-end">
                <span class="fs-5 fw-bold ${anomaly.direction === 'increase' ? 'text-danger' : 'text-primary'}">
                    <i class="fas ${iconInfo} me-1"></i>${Math.abs(anomaly.deviation).toFixed(1)}%
                </span>
            </div>
        `;
        listContainer.appendChild(item);
    });
}

function formatNumber(num) {
    if (num === null || num === undefined) return '--';
    return num.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

// Hook into the tab change to load data
// Hook into the page load to load data
document.addEventListener('DOMContentLoaded', function () {
    initAdvancedAnalysis();
});
