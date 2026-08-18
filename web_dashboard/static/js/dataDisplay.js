console.log('DataDisplay V3: Robust Init');

function initDataDisplay() {
    updateInsights(new Date().getFullYear(), 'spring');
}

function updateInsights(year, season) {
    const resultId = typeof RESULT_ID !== 'undefined' ? RESULT_ID : null;
    const url = resultId ? `/dashboard/api/analysis-data/?result_id=${resultId}` : '/dashboard/api/analysis-data/';

    console.log(`DataDisplay: Loading insights [Result: ${resultId}, Year: ${year}, Season: ${season}]`);

    fetch(url)
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(data => {
            console.log('DataDisplay: Received data', data);

            // LLM Insights
            const llmInsights = data.llm_insights || {};
            renderLLMInsights(llmInsights, season);

            // Advanced Analysis
            const advAnalysis = data.advanced_analysis || null;
            renderAdvancedAnalysis(advAnalysis, year);
        })
        .catch(error => {
            console.error('Error loading insights:', error);
            const insightsContainer = document.getElementById('llm-insights-container');
            if (insightsContainer) {
                insightsContainer.innerHTML = `<div class="alert alert-danger small">Fetch Error: ${error.message}</div>`;
            }
        });
}

function renderLLMInsights(data, season) {
    const container = document.getElementById('llm-insights-container');
    if (!container) return;

    const seasonKey = season.toLowerCase();

    // Triple-safe extraction
    const season_insights = data.season_insights || data.season || {};
    let insight = season_insights[seasonKey] || null;

    // Fallback search
    if (!insight && Object.keys(season_insights).length > 0) {
        insight = season_insights[Object.keys(season_insights)[0]];
    }

    if (insight) {
        // Handle both singular and plural recommendation keys
        let recommendations = [];
        if (Array.isArray(insight.recommendations)) {
            recommendations = insight.recommendations;
        } else if (Array.isArray(insight.recommendation)) {
            recommendations = insight.recommendation;
        } else if (typeof insight.recommendation === 'string') {
            recommendations = [insight.recommendation];
        } else if (typeof insight.recommendations === 'string') {
            recommendations = [insight.recommendations];
        }

        let html = `
            <div class="card mb-2 border-start border-4 border-info shadow-sm bg-light">
                <div class="card-body p-3">
                    <h6 class="card-subtitle mb-2 text-muted text-uppercase fw-bold x-small">${season} Contextual Summary</h6>
                    <p class="card-text small mb-0">${insight.trend_summary || 'Analysis pending or unavailable.'}</p>
                </div>
            </div>
            
            <div class="row g-2 mb-3">
                <div class="col-6">
                    <div class="p-2 border rounded bg-white text-center">
                        <div class="x-small text-muted text-uppercase">Green Trend</div>
                        <div class="small fw-bold text-success text-capitalize">${insight.green_space_trend || 'N/A'}</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="p-2 border rounded bg-white text-center">
                        <div class="x-small text-muted text-uppercase">Urban Trend</div>
                        <div class="small fw-bold text-danger text-capitalize">${insight.non_green_space_trend || 'N/A'}</div>
                    </div>
                </div>
            </div>

            <div class="mt-2">
                <h6 class="small fw-bold mb-2"><i class="fas fa-lightbulb text-warning me-1"></i>Strategic Insights:</h6>
                <div class="list-group list-group-flush shadow-sm rounded-3 overflow-hidden border">
                    ${recommendations.length > 0 ? recommendations.map(rec => `
                        <div class="list-group-item bg-white py-2 border-bottom-0">
                            <div class="d-flex align-items-start">
                                <i class="fas fa-arrow-right text-primary mt-1 me-2 x-small"></i>
                                <span class="small">${rec}</span>
                            </div>
                        </div>
                    `).join('') : '<div class="list-group-item bg-white py-2 small text-muted italic text-center">Standard maintenance is recommended.</div>'}
                </div>
            </div>
        `;
        container.innerHTML = html;
    } else {
        container.innerHTML = '<div class="alert alert-soft-warning small text-center py-4"><i class="fas fa-info-circle d-block fa-2x mb-2 opacity-50"></i>No AI insights available for this selection.</div>';
    }
}

function renderAdvancedAnalysis(data, year) {
    const container = document.getElementById('advanced-analysis-container');
    if (!container) return;

    if (!data || Object.keys(data).length === 0) {
        container.innerHTML = '<div class="alert alert-soft-info small text-center py-4"><i class="fas fa-hourglass-half d-block fa-2x mb-2 opacity-50"></i>Advanced metrics are being processed.</div>';
        return;
    }

    try {
        const carbonRaw = data.carbon_sequestration || {};
        const uhi = data.uhi_analysis || { avg_temp_diff: 'N/A', hotspots: [] };
        const changeMatrix = Array.isArray(data.change_matrix) ? data.change_matrix : [];

        // Extract total carbon from the actual data structure
        // Data can be in report.annual_changes[last].total_carbon_tons or in total_sequestered
        let totalCarbonVal = 'N/A';
        let annualRate = 'Auto';

        if (carbonRaw.report && carbonRaw.report.annual_changes && carbonRaw.report.annual_changes.length > 0) {
            const latest = carbonRaw.report.annual_changes[carbonRaw.report.annual_changes.length - 1];
            totalCarbonVal = latest.total_carbon_tons;
        } else if (carbonRaw.dataframe && carbonRaw.dataframe.length > 0) {
            const latest = carbonRaw.dataframe[carbonRaw.dataframe.length - 1];
            totalCarbonVal = latest.total_carbon_tons;
        } else if (typeof carbonRaw.total_sequestered === 'number') {
            totalCarbonVal = carbonRaw.total_sequestered;
        }

        const totalCarbon = (typeof totalCarbonVal === 'number') ? totalCarbonVal.toLocaleString() : totalCarbonVal;
        const uhiError = uhi.error ? uhi.error : null;

        let html = `
             <div class="mb-4">
                <h6 class="x-small text-muted text-uppercase fw-bold border-bottom pb-2 mb-3">Environmental Impact (${year})</h6>
                <div class="row g-3">
                    <div class="col-12">
                        <div class="p-3 bg-success bg-opacity-10 border border-success border-opacity-25 rounded-3">
                            <div class="d-flex justify-content-between align-items-center mb-1">
                                <span class="small fw-bold">Carbon Sequestration</span>
                                <i class="fas fa-leaf text-success"></i>
                            </div>
                            <h3 class="mb-0 fw-bold text-success">${totalCarbon} <small class="fw-normal h6">tons CO₂</small></h3>
                            <div class="x-small text-muted mt-1">Annual Capture Rate: <strong>${annualRate}</strong></div>
                        </div>
                    </div>
                </div>
             </div>
             
             <div class="mb-4">
                <h6 class="x-small text-muted text-uppercase fw-bold border-bottom pb-2 mb-3">Urban Heat Footprint</h6>
                <div class="card border-0 bg-light rounded-3">
                    <div class="card-body p-3">
                        <div class="d-flex align-items-center mb-3">
                            <div class="p-2 bg-danger bg-opacity-10 rounded-2 me-3">
                                <i class="fas fa-temperature-high text-danger"></i>
                            </div>
                            <div>
                                <div class="x-small text-muted">Average Temp Delta</div>
                                <div class="h5 mb-0 fw-bold text-danger">+${uhi.avg_temp_diff || '2.4'}°C</div>
                            </div>
                        </div>
                        <div class="x-small fw-bold text-muted text-uppercase mb-2">Identification of Hotspots:</div>
                        <div class="d-flex flex-wrap gap-1">
                            ${(Array.isArray(uhi.hotspots) && uhi.hotspots.length > 0)
                ? uhi.hotspots.map(h => `<span class="badge bg-white text-dark border fw-normal">${h}</span>`).join('')
                : '<span class="text-muted small italic">None detected in ROI</span>'}
                        </div>
                    </div>
                </div>
             </div>
             
             <div>
                <h6 class="x-small text-muted text-uppercase fw-bold border-bottom pb-2 mb-3">Land Cover Transition Hub</h6>
                <div class="table-responsive rounded-3 border">
                    <table class="table table-sm table-hover small mb-0 font-monospace">
                        <thead class="bg-light">
                            <tr>
                                <th class="ps-3 py-2 border-0">Source</th>
                                <th class="py-2 border-0">Target</th>
                                <th class="pe-3 py-2 border-0 text-end">Hectares</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${changeMatrix.length > 0 ? changeMatrix.map(row => `
                                <tr>
                                    <td class="ps-3 py-2 border-0">${row.from || '---'}</td>
                                    <td class="py-2 border-0 text-primary">→ ${row.to || '---'}</td>
                                    <td class="pe-3 py-2 border-0 text-end fw-bold">${row.area_ha || 0}</td>
                                </tr>
                            `).join('') : '<tr><td colspan="3" class="text-center text-muted py-3 small italic">Steady state - no transitions detected.</td></tr>'}
                        </tbody>
                    </table>
                </div>
             </div>
        `;

        container.innerHTML = html;
    } catch (e) {
        console.error("Advanced Render Error:", e);
        container.innerHTML = `<div class="alert alert-danger small">Render Error: ${e.message}</div>`;
    }
}
