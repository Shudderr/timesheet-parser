// Timesheet Parser JavaScript

class TimesheetParser {
    constructor() {
        this.init();
        this.loadStoredData();
    }

    init() {
        this.uploadArea = document.getElementById('uploadArea');
        this.fileInput = document.getElementById('fileInput');
        this.uploadStatus = document.getElementById('uploadStatus');
        this.weekSection = document.getElementById('weekSection');
        this.weekSelect = document.getElementById('weekSelect');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.resultsSection = document.getElementById('resultsSection');
        this.scheduleBody = document.getElementById('scheduleBody');
        // Get the summary element
        this.weekSummary = document.getElementById('weekSummary');
        this.setupEventListeners();
    }

    setupEventListeners() {
        this.uploadArea.addEventListener('click', () => this.fileInput.click());
        this.fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        this.uploadArea.addEventListener('dragover', (e) => this.handleDragOver(e));
        this.uploadArea.addEventListener('dragleave', (e) => this.handleDragLeave(e));
        this.uploadArea.addEventListener('drop', (e) => this.handleDrop(e));
        this.weekSelect.addEventListener('change', () => this.displaySelectedWeek());
        this.refreshBtn.addEventListener('click', () => this.refreshWeekList());
    }

    handleDragOver(e) { e.preventDefault(); this.uploadArea.classList.add('dragover'); }
    handleDragLeave(e) { e.preventDefault(); this.uploadArea.classList.remove('dragover'); }

    handleDrop(e) {
        e.preventDefault();
        this.uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) { this.processFile(files[0]); }
    }

    handleFileSelect(e) {
        const file = e.target.files[0];
        if (file) { this.processFile(file); }
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
            const response = await fetch('/parse', { method: 'POST', body: formData });
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
        const datesToCheck = data.dates.filter(d => d);
        for (const [existingKey, existingData] of Object.entries(stored)) {
            const existingDates = existingData.dates || [];
            if (datesToCheck.some(date => existingDates.includes(date)) && existingKey !== key) {
                delete stored[existingKey];
            }
        }
        stored[key] = data;
        localStorage.setItem('timesheetData', JSON.stringify(stored));
    }

    getStoredData() {
        try { return JSON.parse(localStorage.getItem('timesheetData') || '{}'); } 
        catch { return {}; }
    }

    loadStoredData() { this.refreshWeekList(); }

    refreshWeekList() {
        const stored = this.getStoredData();
        const weeks = Object.entries(stored);
        if (weeks.length === 0) {
            this.weekSelect.innerHTML = '<option value="">No weeks available</option>';
            this.weekSection.style.display = 'none';
            this.resultsSection.style.display = 'none';
            return;
        }
        this.weekSection.style.display = 'block';
        this.weekSelect.innerHTML = '';
        weeks.sort(([keyA], [keyB]) => new Date(keyB.split('/')[2], keyB.split('/')[1]-1, keyB.split('/')[0]) - new Date(keyA.split('/')[2], keyA.split('/')[1]-1, keyA.split('/')[0]));
        weeks.forEach(([key]) => {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = `Week Ending: ${key}`;
            this.weekSelect.appendChild(option);
        });
        this.displaySelectedWeek();
    }

    // Helper function to calculate hours from a time string like "9:30"
    _timeToHours(timeStr) {
        const [hours, minutes] = timeStr.split(':').map(Number);
        return hours + minutes / 60;
    }

    displaySelectedWeek() {
        const selectedKey = this.weekSelect.value;
        if (!selectedKey) { this.resultsSection.style.display = 'none'; return; }
        const stored = this.getStoredData();
        const weekData = stored[selectedKey];
        if (!weekData) { this.resultsSection.style.display = 'none'; return; }
        
        this.resultsSection.style.display = 'block';
        this.scheduleBody.innerHTML = '';
        
        let totalHours = 0; // Initialize total hours
        const daysOrder = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

        daysOrder.forEach(dayName => {
            const day = weekData.days[dayName];
            const row = document.createElement('tr');
            
            let timeText = 'Off';
            if (day.start && day.end) {
                timeText = `${day.start} - ${day.end}`;
                // Calculate and add to total hours
                const startHours = this._timeToHours(day.start);
                const endHours = this._timeToHours(day.end);
                totalHours += (endHours - startHours);
            } else if (day.start) {
                timeText = day.start;
            }

            const notes = [];
            if (day.area) notes.push(day.area);
            if (day.note) notes.push(day.note);
            const notesText = notes.join(', ');

            row.innerHTML = `
                <td>${dayName}</td>
                <td>${day.date || ''}</td>
                <td>${timeText}</td>
                <td>${notesText}</td>
            `;
            this.scheduleBody.appendChild(row);
        });

        // Update the summary text
        this.weekSummary.textContent = `Total hours for the week: ${totalHours.toFixed(2)}`;
    }

    showStatus(message, type) {
        this.uploadStatus.textContent = message;
        this.uploadStatus.className = `status-${type}`;
        this.uploadStatus.style.display = 'block';
    }
}

document.addEventListener('DOMContentLoaded', () => { new TimesheetParser(); });
