// Django API Integration
class DjangoAPI {
    constructor(baseURL = '/api/') {
        this.baseURL = baseURL;
        this.csrfToken = this.getCSRFToken();
    }
    
    getCSRFToken() {
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
        return cookieValue;
    }
    
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            credentials: 'same-origin'
        };
        
        const config = { ...defaultOptions, ...options };
        
        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            return { success: true, data };
        } catch (error) {
            console.error('API Request failed:', error);
            return { success: false, error: error.message };
        }
    }
    
    // Analysis endpoints
    async analyzeArea(coordinates, options) {
        return this.request('analyze/', {
            method: 'POST',
            body: JSON.stringify({ coordinates, ...options })
        });
    }
    
    async getAnalysisStatus(taskId) {
        return this.request(`status/${taskId}/`);
    }
    
    async getAnalysisResults(analysisId) {
        return this.request(`results/${analysisId}/`);
    }
    
    async exportAnalysis(analysisId, format = 'csv') {
        return this.request(`export/${analysisId}/`, {
            method: 'POST',
            body: JSON.stringify({ format })
        });
    }
    
    // Data endpoints
    async getHistoricalData(areaId) {
        return this.request(`history/${areaId}/`);
    }
    
    async getSatelliteImagery(params) {
        return this.request('imagery/', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    }
    
    // User endpoints
    async saveAnalysis(name, data) {
        return this.request('save/', {
            method: 'POST',
            body: JSON.stringify({ name, data })
        });
    }
    
    async getSavedAnalyses() {
        return this.request('saved/');
    }
    
    async deleteAnalysis(analysisId) {
        return this.request(`delete/${analysisId}/`, {
            method: 'DELETE'
        });
    }
}

// Example usage in the main app
class LandCoverAnalysisAppWithAPI extends LandCoverAnalysisApp {
    constructor() {
        super();
        this.api = new DjangoAPI();
        this.setupAPIEventListeners();
    }
    
    setupAPIEventListeners() {
        // Override startAnalysis to use real API
        document.getElementById('analyzeBtn').addEventListener('click', async () => {
            await this.startAnalysisWithAPI();
        });
    }
    
    async startAnalysisWithAPI() {
        // Validate inputs (same as before)
        if (this.coordinates.length < 3) {
            this.showToast('Please define an area of interest with at least 3 points', 'error');
            return;
        }
        
        // Get analysis options
        const options = {
            coordinates: this.coordinates,
            singleYear: document.getElementById('singleYear').classList.contains('active'),
            year: document.getElementById('yearSelect').value,
            years: Array.from(document.querySelectorAll('.year-checkboxes input:checked')).map(cb => cb.value),
            temperature: document.getElementById('optionTemperature').checked,
            landCover: document.getElementById('optionLandCover').checked,
            trends: document.getElementById('optionTrends').checked,
            aiInsights: document.getElementById('optionAI').checked
        };
        
        if (options.years.length === 0) {
            this.showToast('Please select at least one year for analysis', 'error');
            return;
        }
        
        this.isAnalyzing = true;
        this.showResultsSection(true);
        this.startProgressBar();
        
        try {
            // Call real API
            const response = await this.api.analyzeArea(this.coordinates, options);
            
            if (response.success) {
                if (response.data.task_id) {
                    // Analysis is async, poll for status
                    await this.pollAnalysisStatus(response.data.task_id);
                } else {
                    // Immediate results
                    this.analysisResults = response.data;
                    this.displayResults(response.data);
                    this.showToast('Analysis completed successfully!', 'success');
                }
            } else {
                throw new Error(response.error);
            }
        } catch (error) {
            console.error('Analysis error:', error);
            this.showToast(`Analysis failed: ${error.message}`, 'error');
        } finally {
            this.isAnalyzing = false;
            this.completeProgressBar();
        }
    }
    
    async pollAnalysisStatus(taskId) {
        let attempts = 0;
        const maxAttempts = 60; // 5 minutes with 5-second intervals
        
        const poll = async () => {
            attempts++;
            
            const response = await this.api.getAnalysisStatus(taskId);
            
            if (response.success) {
                const status = response.data.status;
                
                // Update progress based on status
                this.updateProgressFromStatus(status);
                
                if (status === 'SUCCESS') {
                    // Get results
                    const resultsResponse = await this.api.getAnalysisResults(response.data.result_id);
                    if (resultsResponse.success) {
                        this.analysisResults = resultsResponse.data;
                        this.displayResults(resultsResponse.data);
                        this.showToast('Analysis completed successfully!', 'success');
                    }
                    return;
                } else if (status === 'FAILURE') {
                    this.showToast('Analysis failed on server', 'error');
                    return;
                } else if (attempts >= maxAttempts) {
                    this.showToast('Analysis timeout', 'warning');
                    return;
                } else {
                    // Continue polling
                    setTimeout(poll, 5000);
                }
            } else {
                this.showToast('Failed to check analysis status', 'error');
            }
        };
        
        await poll();
    }
    
    updateProgressFromStatus(status) {
        // Map status to progress percentage
        const statusMap = {
            'PENDING': 10,
            'STARTED': 30,
            'DATA_FETCHING': 50,
            'PROCESSING': 70,
            'GENERATING_REPORTS': 90,
            'SUCCESS': 100
        };
        
        const progress = statusMap[status] || 0;
        const progressFill = document.getElementById('progressFill');
        const progressPercent = document.getElementById('progressPercent');
        
        progressFill.style.width = `${progress}%`;
        progressPercent.textContent = `${progress}%`;
    }
    
    async exportResultsWithAPI(format) {
        if (!this.analysisResults?.id) {
            this.showToast('No results to export', 'warning');
            return;
        }
        
        try {
            const response = await this.api.exportAnalysis(this.analysisResults.id, format);
            
            if (response.success) {
                // Create download link
                const blob = new Blob([response.data], { type: 'text/csv' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `analysis_${new Date().toISOString().slice(0, 10)}.${format}`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                
                this.showToast('Export completed', 'success');
            } else {
                throw new Error(response.error);
            }
        } catch (error) {
            this.showToast(`Export failed: ${error.message}`, 'error');
        }
    }
}

// Usage:
// const app = new LandCoverAnalysisAppWithAPI();