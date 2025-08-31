// Timesheet Parser JavaScript

class TimesheetParser {
    constructor() {
        this.init();
        this.loadStoredData();
    }

    init() {
        // Get DOM elements
        this.uploadArea = document.getElementById('uploadArea');
        this.fileInput = document.getElementById('fileInput');
        this.uploadStatus = document.getElementById('uploadStatus');
        this.weekSection = document.getElementById('weekSection');
        this.weekSelect = document.getElementById('weekSelect');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.resultsSection = document.getElementById('resultsSection');
        this.scheduleTable = document.getElementById('scheduleTable');
        this.scheduleBody = document.getElementById('scheduleBody');

        // Setup event listeners
        this.setupEventListeners();
    }

    setupEventListeners() {
        // File upload events
        this.uploadArea.addEventListener('click', () => this.fileInput.click());
        this.fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        
        // Drag and drop events
        this.uploadArea.addEventListener('dragover', (e) => this.handleDragOver(e));
        this.uploadArea.addEventListener('dragleave', (e) => this.handleDragLeave(e));
        this.uploadArea.addEventListener('drop', (e) => this.handleDrop(e));
        
        // Week selection
        this.weekSelect.addEventListener('change', () => this.displaySelectedWeek());
        this.refreshBtn.addEventListener('click', () => this.refreshWeekList());
    }

    handleDragOver(e) {
        e.preventDefault();
        this.uploadArea.classList.add('dragover');
    }

    handleDragLeave(e) {
        e.preventDefault();
        this.uploadArea.classList.remove('dragover');
    }

    handleDrop(e) {
        e.preventDefault();
        this.uploadArea.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            this.processFile(files[0]);
        }
    }

    handleFileSelect(e) {
        const file = e.target.files[0];
        if (file) {
            this.processFile(file);
        }
    }

    async processFile(file) {
        if (!file.type.includes('pdf')) {
            this.showStatus('Please select a PDF file.', 'error');
            return;
        }

        this.showStatus('Processing PDF...', 'loading');

        const formData = new FormData();
        formData.append('pdf', file);

        try {
            const response = await fetch('/parse', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                this.showStatus('PDF processed successfully!', 'success');
                this.saveTimesheetData(data);
                this.refreshWeekList();
            } else {
                this.showStatus(data.error || 'Failed to process PDF', 'error');
            }
        } catch (error) {
            this.showStatus('Error uploading file: ' + error.message, 'error');
        }
    }

    saveTimesheetData(data) {
        const stored = this.getStoredData();
        const key = data.week_ending || data.dates.join('/');
        
        // Check for overlapping dates and remove old records
        const datesToCheck = data.dates.filter(d => d);
        const keysToRemove = [];
        
        for (const [existingKey, existingData] of Object.entries(stored)) {
            const existingDates = existingData.dates || [];
            if (datesToCheck.some(date => existingDates.includes(date))) {
                keysToRemove.push(existingKey);
            }
        }
        
        // Remove overlapping records
        keysToRemove.forEach(oldKey => {
            if (oldKey !== key) {
                delete stored[oldKey];
            }
        });
        
        // Add new record
        stored[key] = data;
        localStorage.setItem('timesheetData', JSON.stringify(stored));
    }

    getStoredData() {
        try {
            return JSON.parse(localStorage.getItem('timesheetData') || '{}');
        } catch {
            return {};
        }
    }

    loadStoredData() {
        const stored = this.getStoredData();
        if (Object.keys(stored).length > 0) {
            this.refreshWeekList();
        }
    }

    refreshWeekList() {
        const stored = this.getStoredData();
        const weeks = Object.entries(stored);
        
        if (weeks.length === 0) {
            this.weekSelect.innerHTML = '<option value="">No weeks available</option>';
            this.weekSection.style.display = 'none';
            this
