// Mobile Navigation Toggle
const hamburger = document.querySelector('.hamburger');
const navMenu = document.querySelector('.nav-menu');

if (hamburger) {
    hamburger.addEventListener('click', () => {
        navMenu.classList.toggle('active');
        hamburger.innerHTML = navMenu.classList.contains('active')
            ? '<i class="fas fa-times"></i>'
            : '<i class="fas fa-bars"></i>';
    });
}

// Close mobile menu when clicking on a link
document.querySelectorAll('.nav-menu a').forEach(link => {
    link.addEventListener('click', () => {
        navMenu.classList.remove('active');
        hamburger.innerHTML = '<i class="fas fa-bars"></i>';
    });
});

// Demo Upload Functionality
const uploadArea = document.getElementById('uploadArea');
const demoUpload = document.getElementById('demoUpload');
const originalPreview = document.getElementById('originalPreview');
const segmentedPreview = document.getElementById('segmentedPreview');
const greenArea = document.getElementById('greenArea');
const tempReduction = document.getElementById('tempReduction');
const areaSize = document.getElementById('areaSize');

// Demo data for simulation
const demoData = {
    'sample1.jpg': { green: '24%', temp: '2.5°C', area: '15.2 ha' },
    'sample2.jpg': { green: '18%', temp: '1.8°C', area: '8.7 ha' },
    'sample3.jpg': { green: '32%', temp: '3.2°C', area: '22.5 ha' }
};

// Handle file upload for demo
if (demoUpload && uploadArea) {
    // Drag and drop functionality
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, unhighlight, false);
    });

    function highlight() {
        uploadArea.style.backgroundColor = 'rgba(46, 125, 50, 0.1)';
        uploadArea.style.borderColor = 'var(--primary-dark)';
    }

    function unhighlight() {
        uploadArea.style.backgroundColor = '';
        uploadArea.style.borderColor = '';
    }

    uploadArea.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }

    demoUpload.addEventListener('change', function () {
        handleFiles(this.files);
    });

    function handleFiles(files) {
        if (files.length === 0) return;

        const file = files[0];

        // Check file type
        const validTypes = ['image/tiff', 'image/jpeg', 'image/png', 'image/jpg'];
        // Note: browser might not natively support TIFF for display, but we'll show it if it's JPEG/PNG

        if (file.size > 100 * 1024 * 1024) {
            alert('File size exceeds 100MB limit');
            return;
        }

        // Show original image preview immediately
        if (file.type !== 'image/tiff') {
            const reader = new FileReader();
            reader.onload = (e) => {
                originalPreview.style.backgroundImage = `url(${e.target.result})`;
                originalPreview.style.backgroundSize = 'cover';
                originalPreview.style.backgroundPosition = 'center';
                originalPreview.innerHTML = '';
            };
            reader.readAsDataURL(file);
        } else {
            originalPreview.style.background = '#333';
            originalPreview.innerHTML = '<div class="small text-white text-center p-2">TIFF File loaded (Binary preview limited)</div>';
        }

        // Simulate upload and processing
        simulateProcessing(file);
    }

    function simulateProcessing(file) {
        // Update upload area UI
        uploadArea.innerHTML = `
            <i class="fas fa-spinner fa-spin"></i>
            <h4>Processing Image...</h4>
            <p>${file.name}</p>
            <div class="progress-bar">
                <div class="progress"></div>
            </div>
        `;

        // Simulate progress
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress += 10;
            const progressBar = uploadArea.querySelector('.progress');
            if (progressBar) {
                progressBar.style.width = `${progress}%`;
            }

            if (progress >= 100) {
                clearInterval(progressInterval);

                // Get random demo data for simulation
                const keys = Object.keys(demoData);
                const randomKey = keys[Math.floor(Math.random() * keys.length)];
                const data = demoData[randomKey];

                // Update results
                updateDemoResults(file, data);

                // Reset upload area after 2 seconds
                setTimeout(() => {
                    uploadArea.innerHTML = `
                        <i class="fas fa-cloud-upload-alt"></i>
                        <h4>Upload Satellite Image</h4>
                        <p>Drag & drop or click to browse</p>
                        <p class="upload-note">Supports: TIFF, JPEG, PNG (Max 100MB)</p>
                        <button class="btn-upload" onclick="document.getElementById('demoUpload').click()">Browse Files</button>
                    `;
                }, 2000);
            }
        }, 200);
    }

    function updateDemoResults(file, data) {
        // Update stats
        greenArea.textContent = data.green;
        tempReduction.textContent = data.temp;
        areaSize.textContent = data.area;

        // Show segmented preview
        if (file.type !== 'image/tiff') {
            const reader = new FileReader();
            reader.onload = (e) => {
                segmentedPreview.style.backgroundImage = `url(${e.target.result})`;
                segmentedPreview.style.backgroundSize = 'cover';
                segmentedPreview.style.backgroundPosition = 'center';
                segmentedPreview.innerHTML = '<div class="demo-grid"><div class="green-overlay" style="background: rgba(76, 175, 80, 0.4); width: 100%; height: 100%;"></div></div>';
            };
            reader.readAsDataURL(file);
        } else {
            segmentedPreview.style.background = '#2e7d32';
            segmentedPreview.innerHTML = '<div class="small text-white text-center p-2">AI Mask generated for TIFF</div>';
        }
    }
}

// Smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();

        const targetId = this.getAttribute('href');
        if (targetId === '#') return;

        const targetElement = document.querySelector(targetId);
        if (targetElement) {
            // Close mobile menu if open
            if (navMenu.classList.contains('active')) {
                navMenu.classList.remove('active');
                hamburger.innerHTML = '<i class="fas fa-bars"></i>';
            }

            window.scrollTo({
                top: targetElement.offsetTop - 70,
                behavior: 'smooth'
            });
        }
    });
});

// Add active class to current section in navigation
const sections = document.querySelectorAll('section[id]');
window.addEventListener('scroll', () => {
    let current = '';
    const scrollPosition = window.pageYOffset + 100;

    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;

        if (scrollPosition >= sectionTop && scrollPosition < sectionTop + sectionHeight) {
            current = section.getAttribute('id');
        }
    });

    document.querySelectorAll('.nav-menu a').forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${current}`) {
            link.classList.add('active');
        }
    });
});

// Form validation for demo (would be connected to backend)
function validateDemoForm() {
    const fileInput = document.getElementById('demoUpload');

    if (!fileInput.files.length) {
        alert('Please select a file to upload');
        return false;
    }

    return true;
}

// Initialize tooltips (if using any)
function initTooltips() {
    const tooltips = document.querySelectorAll('[data-tooltip]');

    tooltips.forEach(element => {
        element.addEventListener('mouseenter', function () {
            const tooltipText = this.getAttribute('data-tooltip');
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.textContent = tooltipText;

            const rect = this.getBoundingClientRect();
            tooltip.style.position = 'fixed';
            tooltip.style.top = `${rect.top - 40}px`;
            tooltip.style.left = `${rect.left + rect.width / 2}px`;
            tooltip.style.transform = 'translateX(-50%)';

            document.body.appendChild(tooltip);

            this.addEventListener('mouseleave', function () {
                tooltip.remove();
            }, { once: true });
        });
    });
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function () {
    initTooltips();

    // Add CSS for tooltips
    const style = document.createElement('style');
    style.textContent = `
        .tooltip {
            background-color: var(--dark-color);
            color: white;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 0.9rem;
            z-index: 10000;
            white-space: nowrap;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        
        .tooltip::after {
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border-width: 5px;
            border-style: solid;
            border-color: var(--dark-color) transparent transparent transparent;
        }
    `;
    document.head.appendChild(style);
});

// Add animation on scroll
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('animate-in');
        }
    });
}, observerOptions);

// Observe elements for animation
document.querySelectorAll('.feature-card, .step, .pricing-card').forEach(el => {
    observer.observe(el);
});

// Add CSS for animations
const animationStyle = document.createElement('style');
animationStyle.textContent = `
    .feature-card, .step, .pricing-card {
        opacity: 0;
        transform: translateY(30px);
        transition: opacity 0.6s ease, transform 0.6s ease;
    }
    
    .feature-card.animate-in, .step.animate-in, .pricing-card.animate-in {
        opacity: 1;
        transform: translateY(0);
    }
`;
document.head.appendChild(animationStyle);

// Mobile menu toggle
document.addEventListener('DOMContentLoaded', function () {
    const hamburger = document.querySelector('.hamburger');
    const navMenu = document.querySelector('.nav-menu');

    // Toggle mobile menu
    if (hamburger) {
        hamburger.addEventListener('click', function () {
            navMenu.classList.toggle('active');
            hamburger.classList.toggle('active');
        });
    }

    // Close menu when clicking outside
    document.addEventListener('click', function (event) {
        if (!event.target.closest('.nav-container')) {
            navMenu.classList.remove('active');
            hamburger.classList.remove('active');
        }
    });

    // Close menu when clicking a link
    const navLinks = document.querySelectorAll('.nav-menu a:not(.user-btn)');
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            navMenu.classList.remove('active');
            hamburger.classList.remove('active');
        });
    });

    // Mobile user dropdown
    const userBtn = document.querySelector('.user-btn');
    if (userBtn && window.innerWidth <= 992) {
        userBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            const dropdown = this.closest('.user-dropdown').querySelector('.dropdown-options');
            dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
        });
    }
});

// Enhanced dropdown behavior
document.addEventListener('DOMContentLoaded', function () {
    const userDropdown = document.querySelector('.user-dropdown');

    if (userDropdown) {
        if (window.innerWidth > 992) {
            // Desktop - hover behavior
            userDropdown.addEventListener('mouseenter', function () {
                this.querySelector('.dropdown-options').style.display = 'block';
            });

            userDropdown.addEventListener('mouseleave', function () {
                this.querySelector('.dropdown-options').style.display = 'none';
            });
        } else {
            // Mobile - click behavior
            const userBtn = userDropdown.querySelector('.user-btn');
            userBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                const dropdown = userDropdown.querySelector('.dropdown-options');
                dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
            });

            // Close dropdown when clicking outside
            document.addEventListener('click', function (e) {
                if (!userDropdown.contains(e.target)) {
                    userDropdown.querySelector('.dropdown-options').style.display = 'none';
                }
            });
        }
    }
});

