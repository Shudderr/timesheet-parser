#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import datetime
import io
from dataclasses import dataclass, asdict
from flask import Flask, render_template, request, jsonify
import pdfplumber
from collections import defaultdict

app = Flask(__name__)

# Configuration
TARGET_NAME = "Rohan"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# Regular expressions
DATE_RE = re.compile(r"(\d{2}[./-]\d{2}[./-]\d{4})")
# CHANGED: Regex now captures the entire time range (e.g., "9:30-18:00")
TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})")
WEEK_ENDING_RE = re.compile(r"Week ending (\d{2}/\d{2}/\d{4})")

@dataclass
class DayInfo:
    start: str = None
    end: str = None  # CHANGED: Added end time field
    note: str = None
    date: str = None
    area: str = None

@dataclass
class WeekRecord:
    week_ending: str = None
    dates: list = None
    days: dict = None

def _col_bounds_from_weekday_headers(words):
    headers = {}
    for w in words:
        if w["text"] in WEEKDAYS and w["text"] not in headers:
            headers[w["text"]] = (w["x0"], w["x1"], w["top"], w["bottom"])
    if len(headers) < 5: return None
    weekday_centers = sorted([(wd, (pos[0]+pos[1])/2) for wd, pos in headers.items()], key=lambda t: t[1])
    centers = [c for _, c in weekday_centers]
    boundaries = [(centers[i] + centers[i+1])/2 for i in range(4)]
    left_bound = centers[0] - (boundaries[0] - centers[0])
    right_bound = centers[-1] + (centers[-1] - boundaries[-1])
    return [left_bound] + boundaries + [right_bound]

def _col_index(col_bounds, x_center):
    for i in range(5):
        if col_bounds[i] <= x_center < col_bounds[i+1]:
            return i
    return None

def _parse_dates_row_from_grid(grid):
    for cells in grid:
        matches = [DATE_RE.search(c or "") for c in cells]
        if sum(1 for m in matches if m) >= 4:
            return [m.group(1).replace("-", ".") if m else "" for m in matches]
    return ["", "", "", "", ""]

def _is_time_row(cells):
    return sum(1 for c in cells if TIME_RE.search(c or "")) >= 3

# CHANGED: Function now gets the full time range string
def _get_time_ranges(cells):
    out = []
    for c in cells:
        m = TIME_RE.search(c or "")
        out.append(m.group(1) if m else None)
    return out

def parse_timesheet_pdf(pdf_file, target_name=TARGET_NAME):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            if not pdf.pages: return None
            page = pdf.pages[0]
            text = page.extract_text() or ""
            if target_name.lower() not in text.lower(): return None
            week_ending = WEEK_ENDING_RE.search(text).group(1) if WEEK_ENDING_RE.search(text) else None
            
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            col_bounds = _col_bounds_from_weekday_headers(words)
            if not col_bounds: return None
            
            rows = defaultdict(list)
            for w in words:
                if w["text"] in WEEKDAYS: continue
                y_key = round(w["top"])
                rows[y_key].append(w)
            
            row_keys, grid, areas = sorted(rows.keys()), [], []
            for y in row_keys:
                cells, area_text = [""] * 5, ""
                for w in sorted(rows[y], key=lambda w: w['x0']):
                    x_center = (w["x0"] + w["x1"]) / 2
                    ci = _col_index(col_bounds, x_center)
                    if ci is not None:
                        cells[ci] = (cells[ci] + " " + w["text"]).strip()
                    elif x_center < col_bounds[0]:
                        area_text = (area_text + " " + w["text"]).strip()
                grid.append(cells)
                areas.append(area_text)
            
            header_dates = _parse_dates_row_from_grid(grid)
            
            last_time_ranges, current_area = None, ""
            captures = {d: [] for d in WEEKDAYS}
            notes = {d: [] for d in WEEKDAYS}
            areas_by_day = {d: [] for d in WEEKDAYS}
            for row_idx, cells in enumerate(grid):
                if areas[row_idx]: current_area = areas[row_idx]
                if _is_time_row(cells):
                    last_time_ranges = _get_time_ranges(cells)
                    continue
                if last_time_ranges:
                    for day_idx, day_name in enumerate(WEEKDAYS):
                        cell_text = (cells[day_idx] or "").strip()
                        if cell_text and target_name.lower() in cell_text.lower():
                            if last_time_ranges[day_idx]:
                                captures[day_name].append(last_time_ranges[day_idx])
                                areas_by_day[day_name].append(current_area)
                            if "ATM" in cell_text.upper(): notes[day_name].append("ATM")
            
            def to_minutes(tstr):
                h, m = map(int, tstr.split(":"))
                return h * 60 + m
            
            days = {}
            for i, day in enumerate(WEEKDAYS):
                start_time, end_time, chosen_area = None, None, None
                if captures[day]:
                    indexed_ranges = list(zip(captures[day], areas_by_day[day]))
                    # Sort by the start time of the range
                    latest_entry = sorted(indexed_ranges, key=lambda t: to_minutes(t[0].split('-')[0].strip()))[-1]
                    chosen_range, chosen_area = latest_entry
                    # CHANGED: Split the range into start and end times
                    start_time, end_time = [t.strip() for t in chosen_range.replace(" ", "").split('-')]
                
                note = ", ".join(sorted(list(set(notes[day])))) if notes[day] else None
                days[day] = asdict(DayInfo(
                    start=start_time,
                    end=end_time, # CHANGED: Save the end time
                    note=note,
                    date=header_dates[i] if i < len(header_dates) else None,
                    area=chosen_area
                ))
            
            return WeekRecord(week_ending=week_ending, dates=header_dates, days=days)
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/parse', methods=['POST'])
def parse_pdf():
    if 'pdf' not in request.files: return jsonify({'error': 'No PDF file provided'}), 400
    file = request.files['pdf']
    if not file or not file.filename.lower().endswith('.pdf'): return jsonify({'error': 'Invalid file provided'}), 400
    try:
        result = parse_timesheet_pdf(io.BytesIO(file.read()))
        if result is None: return jsonify({'error': f'Could not parse timesheet or {TARGET_NAME} not found'}), 400
        response_data = asdict(result)
        response_data['success'] = True
        return jsonify(response_data)
    except Exception as e:
        return jsonify({'error': f'Error processing PDF: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)```

---

### 2. Frontend Update: Displaying the Full Shift Time (`script.js`)

Now we'll update the JavaScript to format the start and end times together in the "START TIME" column.

**Replace your entire `static/script.js` file with this code:**

```javascript
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
        this.scheduleBody = document.getElementById('scheduleBody');

        // Setup event listeners
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

    displaySelectedWeek() {
        const selectedKey = this.weekSelect.value;
        if (!selectedKey) { this.resultsSection.style.display = 'none'; return; }
        const stored = this.getStoredData();
        const weekData = stored[selectedKey];
        if (!weekData) { this.resultsSection.style.display = 'none'; return; }
        
        this.resultsSection.style.display = 'block';
        this.scheduleBody.innerHTML = '';
        
        const daysOrder = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
        daysOrder.forEach(dayName => {
            const day = weekData.days[dayName];
            const row = document.createElement('tr');
            
            // CHANGED: Format the full time range
            let timeText = 'Off';
            if (day.start && day.end) {
                timeText = `${day.start} - ${day.end}`;
            } else if (day.start) {
                timeText = day.start; // Fallback
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
    }

    showStatus(message, type) {
        this.uploadStatus.textContent = message;
        this.uploadStatus.className = `status-${type}`;
        this.uploadStatus.style.display = 'block';
    }
}

document.addEventListener('DOMContentLoaded', () => { new TimesheetParser(); });
