// Updated Frontend with Real API Integration
class LandCoverAnalysisApp {
    constructor() {
        this.map = null;
        this.drawnItems = new L.FeatureGroup();
        this.coordinates = [];
        this.currentPolygon = null;
        this.analysisResults = null;
        this.charts = {};
        this.isAnalyzing = false;
        this.taskId = null;
        this.pollingInterval = null;
        
        this.baseURL = window.location.origin; // Django server URL
        this.endpoints = {
            analyze: '/api/analyze/',
            status: '/api/status/',
            results: '/api/results/',
            export: '/api/export/',
            history: '/api/history/',
            validate: '/api/validate/'
        };
        
        this.initializeApp();
    }
    
    initializeApp() {
        this.hideLoadingScreen();
        this.initializeMap();
        this.setupEventListeners();
        this.initializeCharts();
        this.checkServerStatus();
        this.showToast('System initialized successfully', 'success');
    }
    
    async checkServerStatus() {
        try {
            const response = await fetch(`${this.baseURL}/api/health/`);
            if (response.ok) {
                const data = await response.json();
                this.showToast(`Connected to server: ${data.status}`, 'success');
            }
        } catch (error) {
            this.showToast('Server connection failed. Using offline mode.', 'warning');
        }
    }
    
    async validateCoordinates(coordinates) {
        try {
            const response = await fetch(this.endpoints.validate, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ coordinates })
            });
            
            if (!response.ok) {
                throw new Error('Coordinate validation failed');
            }
            
            const data = await response.json();
            return data.valid;
        } catch (error) {
            console.error('Validation error:', error);
            return coordinates.length >= 3; // Basic client-side validation
        }
    }
    
    getCSRFToken() {
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    async startAnalysis() {
        // Validate inputs
        if (this.coordinates.length < 3) {
            this.showToast('Please define an area of interest with at least 3 points', 'error');
            return;
        }
        
        // Validate coordinates
        const isValid = await this.validateCoordinates(this.coordinates);
        if (!isValid) {
            this.showToast('Invalid coordinates. Please check your area boundaries.', 'error');
            return;
        }
        
        // Get analysis options
        const options = {
            coordinates: this.coordinates,
            purpose: document.getElementById('singleYear').classList.contains('active') ? 'current' : 'multi-year',
            year: parseInt(document.getElementById('yearSelect').value),
            years: Array.from(document.querySelectorAll('.year-checkboxes input:checked')).map(cb => parseInt(cb.value)),
            include_temperature: document.getElementById('optionTemperature').checked,
            include_landcover: document.getElementById('optionLandCover').checked,
            include_trends: document.getElementById('optionTrends').checked,
            include_ai: document.getElementById('optionAI').checked,
            save_results: document.getElementById('optionSave').checked,
            username: 'user_' + Date.now() // In production, get from auth
        };
        
        if (options.purpose === 'multi-year' && options.years.length === 0) {
            this.showToast('Please select at least one year for analysis', 'error');
            return;
        }
        
        this.isAnalyzing = true;
        this.showResultsSection(true);
        this.showToast('Analysis started. Processing may take 2-5 minutes...', 'info');
        
        // Show progress bar
        this.startProgressBar();
        
        try {
            // Send request to backend
            const response = await this.sendAnalysisRequest(options);
            
            if (response.success) {
                if (response.data.task_id) {
                    // Asynchronous processing
                    this.taskId = response.data.task_id;
                    this.startPolling(this.taskId);
                    this.showToast('Analysis queued successfully. Processing in background...', 'success');
                } else {
                    // Synchronous processing (small areas)
                    this.analysisResults = response.data;
                    this.displayResults(response.data);
                    this.showToast('Analysis completed successfully!', 'success');
                    this.completeProgressBar();
                }
            } else {
                throw new Error(response.error || 'Analysis request failed');
            }
        } catch (error) {
            console.error('Analysis error:', error);
            this.showToast(`Analysis failed: ${error.message}`, 'error');
            this.isAnalyzing = false;
            this.completeProgressBar();
        }
    }
    
    async sendAnalysisRequest(options) {
        const startTime = Date.now();
        
        try {
            const response = await fetch(this.endpoints.analyze, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(options)
            });
            
            const responseTime = Date.now() - startTime;
            console.log(`API Response time: ${responseTime}ms`);
            
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
            
            const data = await response.json();
            
            return {
                success: true,
                data: data,
                responseTime: responseTime
            };
        } catch (error) {
            console.error('API Request failed:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }
    
    startPolling(taskId) {
        // Clear any existing polling
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }
        
        // Start polling every 3 seconds
        this.pollingInterval = setInterval(async () => {
            await this.checkTaskStatus(taskId);
        }, 3000);
    }
    
    async checkTaskStatus(taskId) {
        try {
            const response = await fetch(`${this.endpoints.status}${taskId}/`, {
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            
            if (!response.ok) {
                throw new Error('Failed to check status');
            }
            
            const data = await response.json();
            
            // Update progress based on status
            this.updateProgress(data.status, data.progress);
            
            if (data.status === 'SUCCESS') {
                // Task completed, get results
                clearInterval(this.pollingInterval);
                this.pollingInterval = null;
                await this.getAnalysisResults(data.result_id);
            } else if (data.status === 'FAILURE') {
                // Task failed
                clearInterval(this.pollingInterval);
                this.pollingInterval = null;
                this.showToast(`Analysis failed: ${data.error || 'Unknown error'}`, 'error');
                this.completeProgressBar();
            }
            // If still running, continue polling
            
        } catch (error) {
            console.error('Status check error:', error);
        }
    }
    
    updateProgress(status, progress) {
        const statusMap = {
            'PENDING': 10,
            'STARTED': 20,
            'DATA_FETCHING': 40,
            'PROCESSING': 60,
            'GENERATING_REPORTS': 80,
            'SUCCESS': 100
        };
        
        let progressPercent = progress || statusMap[status] || 0;
        
        const progressFill = document.getElementById('progressFill');
        const progressPercentElement = document.getElementById('progressPercent');
        
        progressFill.style.width = `${progressPercent}%`;
        progressPercentElement.textContent = `${progressPercent}%`;
        
        // Update progress steps
        const steps = document.querySelectorAll('.progress-steps .step');
        if (progressPercent >= 25) steps[0].classList.add('active');
        if (progressPercent >= 50) steps[1].classList.add('active');
        if (progressPercent >= 75) steps[2].classList.add('active');
        if (progressPercent >= 100) steps[3].classList.add('active');
    }
    
    async getAnalysisResults(resultId) {
        try {
            const response = await fetch(`${this.endpoints.results}${resultId}/`, {
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            
            if (!response.ok) {
                throw new Error('Failed to fetch results');
            }
            
            const data = await response.json();
            this.analysisResults = data;
            this.displayResults(data);
            this.showToast('Analysis completed successfully!', 'success');
            this.completeProgressBar();
            
        } catch (error) {
            console.error('Results fetch error:', error);
            this.showToast('Failed to fetch analysis results', 'error');
            this.completeProgressBar();
        }
    }
    
    displayResults(data) {
        // Update summary cards
        if (data.summary) {
            document.getElementById('greenSpaceValue').textContent = `${data.summary.green_space || '--'}%`;
            document.getElementById('urbanAreaValue').textContent = `${data.summary.urban_area || '--'}%`;
            document.getElementById('avgTempValue').textContent = `${data.summary.avg_temperature || '--'}°C`;
            document.getElementById('waterValue').textContent = `${data.summary.water_area || '--'}%`;
        }
        
        // Update land cover chart
        if (data.land_cover_distribution) {
            this.updateLandCoverChart(data.land_cover_distribution);
        }
        
        // Update detailed charts
        if (data.area_data) {
            this.updateDetailedLandCoverChart(data.area_data);
        }
        
        if (data.temperature_data) {
            this.updateTemperatureChart(data.temperature_data);
        }
        
        if (data.trends) {
            this.updateTrendCharts(data.trends);
        }
        
        if (data.insights) {
            this.updateInsights(data.insights);
        }
        
        // Update download links
        if (data.download_urls) {
            this.updateDownloadLinks(data.download_urls);
        }
        
        // Show export tab
        this.switchTab('summary');
    }
    
    updateDownloadLinks(urls) {
        const exportTab = document.getElementById('exportTab');
        
        urls.forEach(url => {
            const button = exportTab.querySelector(`[data-format="${url.format}"]`);
            if (button) {
                button.onclick = () => {
                    window.location.href = url.url;
                };
                button.disabled = false;
            }
        });
    }
    
    async exportResults(format = 'csv') {
        if (!this.analysisResults?.id) {
            this.showToast('No results to export', 'warning');
            return;
        }
        
        this.showToast('Preparing export...', 'info');
        
        try {
            const response = await fetch(this.endpoints.export, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    analysis_id: this.analysisResults.id,
                    format: format,
                    include_charts: document.getElementById('exportCharts').checked,
                    include_data: document.getElementById('exportData').checked,
                    include_report: document.getElementById('exportReport').checked
                })
            });
            
            if (!response.ok) {
                throw new Error('Export failed');
            }
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `landcover_analysis_${new Date().toISOString().slice(0, 10)}.${format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.showToast('Export downloaded successfully', 'success');
            
        } catch (error) {
            console.error('Export error:', error);
            this.showToast(`Export failed: ${error.message}`, 'error');
        }
    }
    
    // ... Rest of the frontend methods remain the same ...
}