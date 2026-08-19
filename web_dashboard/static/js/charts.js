console.log('Charts: Initializing...');

function initCharts() {
    const year = document.getElementById('year-filter')?.value || 2024;
    const season = document.querySelector('input[name="season-filter"]:checked')?.id || 'spring';
    fetchChartsData(year, season);
}

function updateCharts(year, season) {
    fetchChartsData(year, season);
}


function fetchChartsData(year, season) {
    let resultId = typeof RESULT_ID !== 'undefined' ? RESULT_ID : null;

    // Defensive: Handle common JS pitfalls
    if (resultId === 'null' || resultId === 'undefined' || !resultId) {
        resultId = ''; // Let backend handle the default
    }

    let url = `/dashboard/api/charts/`;
    const params = new URLSearchParams();
    if (resultId) params.append('result_id', resultId);
    if (year) params.append('year', year);
    if (season) params.append('season', season);

    const queryString = params.toString();
    if (queryString) url += `?${queryString}`;

    console.log(`Charts: Fetching data from ${url}`);

    // Try to load pre-generated chart images first
    if (resultId) {
        tryLoadChartImages(resultId);
    }

    // Set loading state for interactive plots
    ['plot-aqua', 'plot-terra', 'plot-temp-2', 'plot-temp-3'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<div class="d-flex justify-content-center align-items-center h-100 text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Loading...</div>';
    });

    fetch(url)
        .then(response => {
            if (!response.ok) {
                if (response.status === 404) {
                    console.warn('Charts: No data found for this result/selection.');
                    showNoDataOverlay();
                }
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Charts Data Received:', data);

            // Debugging Temperature Data
            if (data.temperature) {
                console.log('Temperature Data:', data.temperature);
                console.log('Labels:', data.temperature.labels);
                if (!data.temperature.labels || data.temperature.labels.length === 0) {
                    console.warn('Temperature labels are missing or empty.');
                }
            } else {
                console.warn('Temperature object missing in response.');
            }

            if (!data.temperature || !data.temperature.labels || data.temperature.labels.length === 0) {
                showNoData('plot-aqua', 'No temperature data found');
                showNoData('plot-terra', '');
                showNoData('plot-temp-2', '');
                showNoData('plot-temp-3', '');
            } else {
                console.log('Rendering temperature charts...');
                try {
                    renderTemperatureChart(data.temperature);
                } catch (e) {
                    console.error('Error rendering temperature chart:', e);
                }
            }

            if (!data.area || !data.area.years || data.area.years.length === 0) {
                showNoData('plot-area-trends', 'No land cover trends found');
                showNoData('plot-composition', 'No composition data');
                showNoData('plot-green-ratio', '');
            } else {
                renderAreaCharts(data.area, data.green_vs_nongreen);
                const targetYear = data.selected_year || year;
                renderCompositionChart(data.area, targetYear);
            }

            // Render green vs non-green percentage display
            if (data.green_pct && data.green_pct.green_pct && data.green_pct.green_pct.length > 0) {
                renderGreenPercentage(data.green_pct);
            }
        })
        .catch(error => {
            console.error('Error loading charts data:', error);
            const msg = `Error: ${error.message}`;
            showNoData('plot-aqua', msg);
            showNoData('plot-terra', msg);
            showNoData('plot-temp-2', msg);
            showNoData('plot-temp-3', msg);
            showNoData('plot-area-trends', msg);
            showNoData('plot-composition', msg);
        });
}

function showNoData(containerId, message) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = `
        <div class="d-flex flex-column align-items-center justify-content-center h-100 text-muted opacity-50">
            <i class="fas fa-chart-area fa-3x mb-2"></i>
            <p class="small mb-0">${message || 'Data unavailable'}</p>
        </div>
    `;
    container.classList.remove('d-none');
}

function showNoDataOverlay(msg) {
    // Optional: Global overlay if entire dashboard is empty
    console.log("Showing global no-data status:", msg);
}

// tryLoadChartImages: Checks for the existence of pre-generated PNG files and shows them if found.
function tryLoadChartImages(resultId) {
    const basePath = `/media/analysis_results/${resultId}/`;

    // Area Charts
    const area6 = document.getElementById('img-area-6class');
    const area2 = document.getElementById('img-area-2class');
    if (area6) {
        area6.src = `${basePath}area_trends_6class.png`;
        area6.onload = () => { area6.classList.remove('d-none'); document.getElementById('plot-area-trends').classList.add('d-none'); };
    }
    if (area2) {
        area2.src = `${basePath}area_trends_2class.png`;
        area2.onload = () => { area2.classList.remove('d-none'); document.getElementById('plot-green-ratio').classList.add('d-none'); };
    }

    // Temperature Charts
    for (let i = 0; i < 4; i++) {
        const img = document.getElementById(`img-temp-${i}`);
        if (img) {
            img.src = `${basePath}temperature_trend_${i}.png`;
            img.onload = () => {
                img.classList.remove('d-none');
                // Previously hidden logic removed to allow stacking
            };
        }
    }
}

function renderAreaCharts(areaData, greenData) {
    if (!areaData || !Array.isArray(areaData.years)) return;

    const years = areaData.years;

    // Check if we have only one year (Current Analysis) or Seasonal Labels
    const isSingleYear = years.length === 1;
    const isSeasonalLabels = years.some(y => isNaN(y));
    const isBar = isSingleYear || isSeasonalLabels;

    const traces = [
        {
            x: years,
            y: Array.isArray(areaData.urban) ? areaData.urban : [],
            name: 'Urban',
            type: isBar ? 'bar' : 'scatter',
            stackgroup: isBar ? null : 'one',
            line: { color: 'red' },
            marker: { color: 'red' }
        },
        {
            x: years,
            y: Array.isArray(areaData.green) ? areaData.green : [],
            name: 'Green Space',
            type: isBar ? 'bar' : 'scatter',
            stackgroup: isBar ? null : 'one',
            line: { color: 'green' },
            marker: { color: 'green' }
        },
        {
            x: years,
            y: Array.isArray(areaData.water) ? areaData.water : [],
            name: 'Water',
            type: isBar ? 'bar' : 'scatter',
            stackgroup: isBar ? null : 'one',
            line: { color: 'blue' },
            marker: { color: 'blue' }
        },
        {
            x: years,
            y: Array.isArray(areaData.agriculture) ? areaData.agriculture : [],
            name: 'Agriculture',
            type: isBar ? 'bar' : 'scatter',
            stackgroup: isBar ? null : 'one',
            line: { color: 'yellow' },
            marker: { color: 'yellow' }
        }
    ];

    const layout = {
        margin: { t: 20, r: 20, b: 40, l: 40 },
        showlegend: true,
        legend: { orientation: 'h', y: -0.2 },
        barmode: isBar ? 'group' : undefined
    };

    Plotly.newPlot('plot-area-trends', traces, layout, { responsive: true });

    // Green vs Non-Green Chart (using backend-calculated data)
    if (greenData && Array.isArray(greenData.years)) {
        const greenTrace = {
            x: greenData.years,
            y: greenData.green,
            name: 'Green Space',
            type: isSingleYear ? 'bar' : 'scatter',
            mode: 'lines+markers',
            marker: { color: '#22c55e' },
            line: { color: '#22c55e', width: 3 },
            fill: isSingleYear ? undefined : 'tonexty'
        };

        const nonGreenTrace = {
            x: greenData.years,
            y: greenData.non_green,
            name: 'Non-Green Space',
            type: isSingleYear ? 'bar' : 'scatter',
            mode: 'lines+markers',
            marker: { color: '#ef4444' },
            line: { color: '#ef4444', width: 3 }
        };

        const greenLayout = {
            margin: { t: 20, r: 20, b: 60, l: 40 },
            yaxis: { title: 'Area (km²)' },
            showlegend: true,
            legend: { orientation: 'h', y: -0.3 },
            barmode: isSingleYear ? 'group' : undefined
        };

        Plotly.newPlot('plot-green-ratio', [greenTrace, nonGreenTrace], greenLayout, { responsive: true });
    }
}

function renderTemperatureChart(data) {
    // 1. Check if Plotly is loaded
    if (typeof Plotly === 'undefined') {
        console.error('Plotly library is not loaded!');
        ['plot-aqua', 'plot-terra', 'plot-temp-2', 'plot-temp-3'].forEach(id => {
            showNoData(id, 'Error: Plotly library not loaded. Check internet connection or ad-blocker.');
        });
        return;
    }

    if (!data || !Array.isArray(data.labels) || data.labels.length === 0) {
        console.warn('Temperature chart rendering aborted: No labels.');
        return;
    }

    const labels = data.labels;
    const isSeasonal = data.mode === 'seasonal';

    // Render into specific sensor containers as defined in plot_viewer.html
    const sensorConfigs = [
        { id: 'plot-aqua', data: data.aqua_day, name: 'Aqua Day', color: '#f59e0b' },
        { id: 'plot-terra', data: data.aqua_night, name: 'Aqua Night', color: '#3b82f6' },
        { id: 'plot-temp-2', data: data.terra_day, name: 'Terra Day', color: '#ef4444' },
        { id: 'plot-temp-3', data: data.terra_night, name: 'Terra Night', color: '#6366f1' }
    ];

    const layoutBase = {
        margin: { t: 20, r: 20, b: 40, l: 50 },
        yaxis: { title: 'Temp (°C)' },
        xaxis: isSeasonal ? {
            title: 'Season',
            type: 'category'
        } : {
            title: 'Year'
        },
        showlegend: true,
        legend: { orientation: 'h', y: -0.25 },
        hovermode: 'closest',
        height: 300 // Force height
    };

    sensorConfigs.forEach(cfg => {
        const el = document.getElementById(cfg.id);
        if (el) {
            // Data Validation to screen
            if (!cfg.data || cfg.data.length === 0) {
                showNoData(cfg.id, `No data for ${cfg.name}`);
                return;
            }

            try {
                const trace = {
                    x: labels,
                    y: Array.isArray(cfg.data) ? cfg.data : [],
                    name: cfg.name,
                    type: isSeasonal ? 'bar' : 'scatter',
                    mode: isSeasonal ? undefined : 'lines+markers',
                    line: isSeasonal ? undefined : { color: cfg.color, width: 2 },
                    marker: { color: cfg.color }
                };

                // Clear any previous error messages
                el.innerHTML = '';

                Plotly.newPlot(cfg.id, [trace], layoutBase, { responsive: true })
                    .catch(e => {
                        console.error(`Plotly error for ${cfg.id}:`, e);
                        showNoData(cfg.id, `Plot Draw Error: ${e.message}`);
                    });
            } catch (e) {
                console.error(`Error configuring plot ${cfg.id}:`, e);
                showNoData(cfg.id, `Config Error: ${e.message}`);
            }
        } else {
            console.warn(`Container #${cfg.id} not found.`);
        }
    });
}

function renderGreenPercentage(pctData) {
    // Render a professional gauge/summary in the green-percentage-display container
    const container = document.getElementById('green-pct-display');
    if (!container) return;

    // Use latest data point
    const lastIdx = pctData.green_pct.length - 1;
    const greenPct = pctData.green_pct[lastIdx];
    const nonGreenPct = pctData.non_green_pct[lastIdx];
    const label = pctData.labels[lastIdx];

    container.innerHTML = `
        <div class="d-flex align-items-center justify-content-between mb-2">
            <div class="d-flex align-items-center">
                <div class="rounded-circle bg-success bg-opacity-10 p-2 me-2">
                    <i class="fas fa-leaf text-success"></i>
                </div>
                <div>
                    <div class="small text-muted">Green Space</div>
                    <div class="fw-bold text-success fs-5">${greenPct}%</div>
                </div>
            </div>
            <div class="d-flex align-items-center">
                <div>
                    <div class="small text-muted text-end">Non-Green</div>
                    <div class="fw-bold text-danger fs-5 text-end">${nonGreenPct}%</div>
                </div>
                <div class="rounded-circle bg-danger bg-opacity-10 p-2 ms-2">
                    <i class="fas fa-city text-danger"></i>
                </div>
            </div>
        </div>
        <div class="progress" style="height: 12px; border-radius: 8px;">
            <div class="progress-bar bg-success" role="progressbar" style="width: ${greenPct}%" 
                 title="Green Space: ${greenPct}%"></div>
            <div class="progress-bar bg-danger" role="progressbar" style="width: ${nonGreenPct}%" 
                 title="Non-Green: ${nonGreenPct}%"></div>
        </div>
        <div class="text-center mt-1">
            <small class="text-muted">${label}</small>
        </div>
    `;
    container.classList.remove('d-none');
}

function renderCompositionChart(data, targetYear) {
    if (!data || !Array.isArray(data.years) || data.years.length === 0) return;

    // Find index for the target year, or use last point
    let idx = data.years.length - 1;
    if (targetYear) {
        const foundIdx = data.years.findIndex(y => y == targetYear);
        if (foundIdx !== -1) idx = foundIdx;
    }

    const yearLabel = data.years[idx];

    // Extract values
    const values = [
        data.urban ? data.urban[idx] : 0,
        data.water ? data.water[idx] : 0,
        data.agriculture ? data.agriculture[idx] : 0,
        data.trees ? data.trees[idx] : 0,
        data.grass ? data.grass[idx] : 0,
        data.soil ? data.soil[idx] : 0
    ];

    const labels = ['Urban', 'Water', 'Agriculture', 'Trees', 'Grass', 'Soil'];
    const colors = ['#ef4444', '#3b82f6', '#eab308', '#15803d', '#86efac', '#a16207'];

    // Filter out zero values to clean up the chart
    const filteredValues = [];
    const filteredLabels = [];
    const filteredColors = [];

    values.forEach((val, i) => {
        if (val > 0) {
            filteredValues.push(val);
            filteredLabels.push(labels[i]);
            filteredColors.push(colors[i]);
        }
    });

    const trace = {
        values: filteredValues,
        labels: filteredLabels,
        type: 'pie',
        marker: {
            colors: filteredColors
        },
        textinfo: 'label+percent',
        hoverinfo: 'label+percent+value',
        hole: 0.4 // Donut chart style
    };

    const layout = {
        title: { text: `Composition (${yearLabel})`, font: { size: 14 } },
        margin: { t: 30, r: 10, b: 10, l: 10 },
        showlegend: true,
        legend: { orientation: 'h', y: -0.1 }
    };

    Plotly.newPlot('plot-composition', [trace], layout, { responsive: true });
}

