// Dashboard functionality
document.addEventListener('DOMContentLoaded', function() {
    // Initialize chart for analysis history
    initAnalysisChart();
    
    // Load user projects
    loadUserProjects();
    
    // Initialize file upload for dashboard
    initDashboardUpload();
});

function initAnalysisChart() {
    const ctx = document.getElementById('analysisChart');
    if (!ctx) return;
    
    // Using Chart.js (you need to include Chart.js library)
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js is not loaded');
        return;
    }
    
    new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'],
            datasets: [{
                label: 'Images Analyzed',
                data: [12, 19, 8, 15, 12, 20, 25],
                borderColor: 'var(--primary-color)',
                backgroundColor: 'rgba(46, 125, 50, 0.1)',
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        drawBorder: false
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            }
        }
    });
}

function loadUserProjects() {
    const projectsGrid = document.getElementById('projectsGrid');
    if (!projectsGrid) return;
    
    // Simulated project data
    const projects = [
        {
            id: 1,
            name: 'Lahore Park Analysis',
            date: '2024-05-15',
            status: 'completed',
            greenArea: '24%',
            temperature: '2.5°C',
            thumbnail: 'park'
        },
        {
            id: 2,
            name: 'Urban Forest Study',
            date: '2024-05-10',
            status: 'completed',
            greenArea: '32%',
            temperature: '3.2°C',
            thumbnail: 'forest'
        },
        {
            id: 3,
            name: 'Residential Area',
            date: '2024-05-05',
            status: 'processing',
            greenArea: '18%',
            temperature: '1.8°C',
            thumbnail: 'residential'
        },
        {
            id: 4,
            name: 'Commercial Zone',
            date: '2024-04-28',
            status: 'completed',
            greenArea: '12%',
            temperature: '1.2°C',
            thumbnail: 'commercial'
        }
    ];
    
    // Clear loading state
    projectsGrid.innerHTML = '';
    
    // Add project cards
    projects.forEach(project => {
        const projectCard = createProjectCard(project);
        projectsGrid.appendChild(projectCard);
    });
}

function createProjectCard(project) {
    const card = document.createElement('div');
    card.className = 'project-card';
    
    const statusClass = project.status === 'completed' ? 'status-completed' : 'status-processing';
    const statusText = project.status === 'completed' ? 'Completed' : 'Processing';
    
    card.innerHTML = `
        <div class="project-thumbnail ${project.thumbnail}">
            <div class="project-overlay">
                <button class="btn-view" onclick="viewProject(${project.id})">View Details</button>
            </div>
        </div>
        <div class="project-info">
            <div class="project-header">
                <h4>${project.name}</h4>
                <span class="project-status ${statusClass}">${statusText}</span>
            </div>
            <div class="project-date">
                <i class="far fa-calendar"></i> ${project.date}
            </div>
            <div class="project-stats">
                <div class="project-stat">
                    <span class="stat-label">Green Area</span>
                    <span class="stat-value">${project.greenArea}</span>
                </div>
                <div class="project-stat">
                    <span class="stat-label">Temp Reduction</span>
                    <span class="stat-value">${project.temperature}</span>
                </div>
            </div>
            <div class="project-actions">
                <button class="btn-action" onclick="downloadReport(${project.id})" title="Download Report">
                    <i class="fas fa-download"></i>
                </button>
                <button class="btn-action" onclick="shareProject(${project.id})" title="Share">
                    <i class="fas fa-share-alt"></i>
                </button>
                <button class="btn-action btn-danger" onclick="deleteProject(${project.id})" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `;
    
    return card;
}

function initDashboardUpload() {
    const uploadBtn = document.getElementById('quickUploadBtn');
    const uploadModal = document.getElementById('uploadModal');
    const closeModal = document.querySelector('.close-modal');
    
    if (uploadBtn && uploadModal) {
        uploadBtn.addEventListener('click', () => {
            uploadModal.style.display = 'flex';
        });
        
        if (closeModal) {
            closeModal.addEventListener('click', () => {
                uploadModal.style.display = 'none';
            });
        }
        
        // Close modal when clicking outside
        window.addEventListener('click', (e) => {
            if (e.target === uploadModal) {
                uploadModal.style.display = 'none';
            }
        });
    }
}

function viewProject(projectId) {
    // In a real app, this would redirect to the project details page
    window.location.href = `analysis/results.html?project=${projectId}`;
}

function downloadReport(projectId) {
    // Simulate report download
    alert(`Downloading report for project ${projectId}...`);
    // In real app: window.location.href = `/api/report/${projectId}`;
}

function shareProject(projectId) {
    // Simulate sharing functionality
    const shareUrl = `${window.location.origin}/project/${projectId}`;
    
    if (navigator.share) {
        navigator.share({
            title: 'GreenSpace AI Project',
            text: 'Check out my urban green space analysis project',
            url: shareUrl
        });
    } else {
        // Fallback: copy to clipboard
        navigator.clipboard.writeText(shareUrl).then(() => {
            alert('Project link copied to clipboard!');
        });
    }
}

function deleteProject(projectId) {
    if (confirm('Are you sure you want to delete this project? This action cannot be undone.')) {
        // In a real app, send DELETE request to server
        console.log(`Deleting project ${projectId}`);
        alert('Project deleted successfully.');
        // Reload projects
        loadUserProjects();
    }
}

// Export data function
function exportUserData() {
    const exportBtn = document.getElementById('exportDataBtn');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            // Simulate data export
            alert('Preparing your data export... This may take a moment.');
            
            // In a real app, this would trigger a server-side export
            setTimeout(() => {
                const data = {
                    user: 'demo_user',
                    totalProjects: 4,
                    totalAnalyses: 15,
                    subscription: 'Professional',
                    joinDate: '2024-01-15'
                };
                
                const dataStr = JSON.stringify(data, null, 2);
                const dataBlob = new Blob([dataStr], { type: 'application/json' });
                const url = URL.createObjectURL(dataBlob);
                
                const a = document.createElement('a');
                a.href = url;
                a.download = 'greenspace-ai-data.json';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 1500);
        });
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', exportUserData);