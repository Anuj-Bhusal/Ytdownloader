// API Configuration - Update this with your backend URL after deploying
const API_BASE_URL = 'https://your-backend.railway.app'; // Change this!

let currentVideoInfo = null;
let selectedFormat = null;

// Fetch video information
async function fetchVideoInfo() {
    const urlInput = document.getElementById('urlInput');
    const fetchBtn = document.getElementById('fetchBtn');
    const errorMsg = document.getElementById('errorMsg');
    const videoInfo = document.getElementById('videoInfo');
    
    const url = urlInput.value.trim();
    
    if (!url) {
        showError('Please enter a YouTube URL');
        return;
    }
    
    if (!isValidYouTubeUrl(url)) {
        showError('Please enter a valid YouTube URL');
        return;
    }
    
    // Show loading state
    setButtonLoading(fetchBtn, true);
    hideError();
    videoInfo.style.display = 'none';
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/info`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url }),
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to fetch video info');
        }
        
        currentVideoInfo = data;
        displayVideoInfo(data);
        
    } catch (error) {
        showError(error.message || 'Failed to fetch video information. Please try again.');
    } finally {
        setButtonLoading(fetchBtn, false);
    }
}

// Display video information
function displayVideoInfo(info) {
    const videoInfo = document.getElementById('videoInfo');
    
    // Set thumbnail
    document.getElementById('thumbnail').src = info.thumbnail;
    
    // Set title
    document.getElementById('videoTitle').textContent = info.title;
    
    // Set duration
    const duration = formatDuration(info.duration);
    document.getElementById('videoDuration').textContent = `⏱️ ${duration}`;
    
    // Set channel
    document.getElementById('videoChannel').textContent = `📺 ${info.channel}`;
    
    // Populate formats
    populateFormats(info.formats);
    
    // Show video info section
    videoInfo.style.display = 'block';
    
    // Scroll to video info
    videoInfo.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Populate format options
function populateFormats(formats) {
    const videoFormatsContainer = document.getElementById('videoFormats');
    const audioFormatsContainer = document.getElementById('audioFormats');
    
    // Filter and sort video formats
    const videoFormats = formats
        .filter(f => f.type === 'video')
        .sort((a, b) => (b.height || 0) - (a.height || 0));
    
    // Filter and sort audio formats
    const audioFormats = formats
        .filter(f => f.type === 'audio')
        .sort((a, b) => (b.bitrate || 0) - (a.bitrate || 0));
    
    // Render video formats
    videoFormatsContainer.innerHTML = videoFormats.map((format, index) => `
        <label class="format-option ${index === 0 ? 'selected' : ''}" data-format-id="${format.format_id}">
            <input type="radio" name="format" value="${format.format_id}" ${index === 0 ? 'checked' : ''}>
            <span class="format-radio"></span>
            <div class="format-info">
                <span class="format-quality">
                    ${format.quality}
                    ${format.height >= 1080 ? '<span class="badge">HD</span>' : ''}
                    ${format.height >= 2160 ? '<span class="badge">4K</span>' : ''}
                </span>
                <span class="format-size">${format.filesize || 'Size varies'}</span>
            </div>
        </label>
    `).join('') || '<p class="format-loading">No video formats available</p>';
    
    // Render audio formats
    audioFormatsContainer.innerHTML = audioFormats.map((format, index) => `
        <label class="format-option" data-format-id="${format.format_id}">
            <input type="radio" name="format" value="${format.format_id}">
            <span class="format-radio"></span>
            <div class="format-info">
                <span class="format-quality">${format.quality}</span>
                <span class="format-size">${format.filesize || 'Size varies'}</span>
            </div>
        </label>
    `).join('') || '<p class="format-loading">No audio formats available</p>';
    
    // Add click handlers
    document.querySelectorAll('.format-option').forEach(option => {
        option.addEventListener('click', () => selectFormat(option));
    });
    
    // Select first video format by default
    if (videoFormats.length > 0) {
        selectedFormat = videoFormats[0].format_id;
        document.getElementById('downloadBtn').disabled = false;
    }
}

// Select format
function selectFormat(option) {
    // Remove selected from all
    document.querySelectorAll('.format-option').forEach(opt => {
        opt.classList.remove('selected');
        opt.querySelector('input').checked = false;
    });
    
    // Add selected to clicked
    option.classList.add('selected');
    option.querySelector('input').checked = true;
    
    selectedFormat = option.dataset.formatId;
    document.getElementById('downloadBtn').disabled = false;
}

// Switch between video and audio tabs
function switchTab(tab) {
    const videoFormats = document.getElementById('videoFormats');
    const audioFormats = document.getElementById('audioFormats');
    const tabBtns = document.querySelectorAll('.tab-btn');
    
    tabBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    
    if (tab === 'video') {
        videoFormats.style.display = 'grid';
        audioFormats.style.display = 'none';
    } else {
        videoFormats.style.display = 'none';
        audioFormats.style.display = 'grid';
    }
    
    // Clear selection and select first in new tab
    selectedFormat = null;
    document.getElementById('downloadBtn').disabled = true;
    
    const firstOption = (tab === 'video' ? videoFormats : audioFormats).querySelector('.format-option');
    if (firstOption) {
        selectFormat(firstOption);
    }
}

// Download video
async function downloadVideo() {
    if (!currentVideoInfo || !selectedFormat) return;
    
    const downloadBtn = document.getElementById('downloadBtn');
    const progressSection = document.getElementById('downloadProgress');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    setButtonLoading(downloadBtn, true);
    progressSection.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Preparing download...';
    
    try {
        // Start download
        progressFill.style.width = '30%';
        progressText.textContent = 'Processing video...';
        
        const response = await fetch(`${API_BASE_URL}/api/download`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: document.getElementById('urlInput').value.trim(),
                format_id: selectedFormat,
            }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Download failed');
        }
        
        progressFill.style.width = '70%';
        progressText.textContent = 'Downloading...';
        
        // Get filename from header
        const contentDisposition = response.headers.get('content-disposition');
        let filename = 'video.mp4';
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="(.+)"/);
            if (match) filename = match[1];
        }
        
        // Download the file
        const blob = await response.blob();
        
        progressFill.style.width = '100%';
        progressText.textContent = 'Complete!';
        
        // Trigger download
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(downloadUrl);
        
        setTimeout(() => {
            progressSection.style.display = 'none';
        }, 2000);
        
    } catch (error) {
        showError(error.message || 'Download failed. Please try again.');
        progressSection.style.display = 'none';
    } finally {
        setButtonLoading(downloadBtn, false);
    }
}

// Utility functions
function isValidYouTubeUrl(url) {
    const patterns = [
        /^(https?:\/\/)?(www\.)?youtube\.com\/watch\?v=[\w-]+/,
        /^(https?:\/\/)?(www\.)?youtu\.be\/[\w-]+/,
        /^(https?:\/\/)?(www\.)?youtube\.com\/shorts\/[\w-]+/,
    ];
    return patterns.some(pattern => pattern.test(url));
}

function formatDuration(seconds) {
    if (!seconds) return 'Unknown';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    if (hrs > 0) {
        return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function setButtonLoading(button, loading) {
    const text = button.querySelector('.btn-text');
    const loader = button.querySelector('.btn-loader');
    
    button.disabled = loading;
    text.style.display = loading ? 'none' : 'inline';
    loader.style.display = loading ? 'inline-block' : 'none';
}

function showError(message) {
    const errorMsg = document.getElementById('errorMsg');
    errorMsg.textContent = message;
    errorMsg.style.display = 'block';
}

function hideError() {
    document.getElementById('errorMsg').style.display = 'none';
}

// Allow Enter key to submit
document.getElementById('urlInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        fetchVideoInfo();
    }
});
