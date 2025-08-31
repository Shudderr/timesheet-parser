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

app = Flask(__name__)

# Configuration
TARGET_NAME = "Rohan"  # Change this to your target employee name
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# Regular expressions
DATE_RE = re.compile(r"(\d{2}[./-]\d{2}[./-]\d{4})")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*\d{1,2}:\d{2}")
WEEK_ENDING_RE = re.compile(r"Week ending (\d{2}/\d{2}/\d{4})")

@dataclass
class DayInfo:
    start: str = None
    note: str = None
    date: str = None

@dataclass
class WeekRecord:
    week_ending: str = None
    dates: list = None
    days: dict = None

def _col_bounds_from_weekday_headers(words):
    """Extract column boundaries from weekday headers in the PDF"""
    headers = {}
    for w in words:
        if w["text"] in WEEKDAYS and w["text"] not in headers:
            headers[w["text"]] = (w["x0"], w["x1"], w["top"], w["bottom"])
    
    if len(headers) < 5:
        return None
    
    weekday_centers = sorted([(wd, (pos[0]+pos[1])/2) for wd, pos in headers.items()], key=lambda t: t[1])
    centers = [c for _, c in weekday_centers]
    boundaries = [(centers[i] + centers[i+1])/2 for i in range(4)]
    left_bound = centers[0] - (boundaries[0] - centers[0])
    right_bound = centers[-1] + (centers[-1] - boundaries[-1])
    
    return [left_bound] + boundaries + [right_bound]

def _col_index(col_bounds, x_center):
    """Determine which column an x-coordinate falls into"""
    for i in range(5):
        if col_bounds[i] <= x_center < col_bounds[i+1]:
            return i
    return None

def _parse_dates_row_from_grid(grid):
    """Find the row containing dates and parse them"""
    for cells in grid:
        matches = [DATE_RE.search(c or "") for c in cells]
        if sum(1 for m in matches if m) >= 4:
            return [m.group(1).replace("-", ".") if m else "" for m in matches]
    return ["", "", "", "", ""]

def _is_time_row(cells):
    """Check if a row contains time ranges"""
    return sum(1 for c in cells if TIME_RE.search(c or "")) >= 3

def _get_time_starts(cells):
    """Extract start times from a time row"""
    out = []
    for c in cells:
        m = TIME_RE.search(c or "")
        out.append(m.group(1) if m else None)
    return out

def parse_timesheet_pdf(pdf_file, target_name=TARGET_NAME):
    """Parse a timesheet PDF and extract relevant data"""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            if not pdf.pages:
                return None
                
            page = pdf.pages[0]
            text = page.extract_text() or ""
            
            # Check if target name is in the PDF
            if target_name.lower() not in text.lower():
                return None
            
            # Extract week ending date
            week_ending = None
            m = WEEK_ENDING_RE.search(text)
            if m:
                week_ending = m.group(1)
            
            # Extract words and determine column structure
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            col_bounds = _col_bounds_from_weekday_headers(words)
            
            if not col_bounds:
                return None
            
            # Group words by row
            from collections import defaultdict
            rows = defaultdict(list)
            for w in words:
                if w["text"] in WEEKDAYS:
                    continue
                y_key = round(w["top"])
                rows[y_key].append(w)
            
            # Create grid structure
            row_keys = sorted(rows.keys())
            grid = []
            for y in row_keys:
                cells = [""]*5
                for w in rows[y]:
                    x_center = (w["x0"] + w["x1"]) / 2
                    ci = _col_index(col_bounds, x_center)
                    if ci is not None:
                        cells[ci] = (cells[ci] + " " + w["text"]).strip() if cells[ci] else w["text"]
                grid.append(cells)
            
            # Parse dates from header
            header_dates = _parse_dates_row_from_grid(grid)
            
            # Extract time and employee data
            last_time_starts = None
            captures = {d: [] for d in WEEKDAYS}
            notes = {d: [] for d in WEEKDAYS}
            
            for cells in grid:
                if _is_time_row(cells):
                    last_time_starts = _get_time_starts(cells)
                    continue
                    
                if last_time_starts:
                    for idx, day in enumerate(WEEKDAYS):
                        nm = (cells[idx] or "").strip()
                        if nm and target_name.lower() in nm.lower():
                            if last_time_starts[idx]:
                                captures[day].append(last_time_starts[idx])
                            if "ATM" in nm.upper():
                                notes[day].append("ATM")
            
            # Process captured data
            def to_minutes(tstr):
                h, m = map(int, tstr.split(":"))
                return h*60 + m
            
            days = {}
            for i, day in enumerate(WEEKDAYS):
                starts = captures[day]
                chosen = None
                if starts:
                    chosen = sorted(starts, key=to_minutes)[-1]  # Latest start time
                
                note = None
                if notes[day]:
                    unique_notes = []
                    for n in notes[day]:
                        if n not in unique_notes:
                            unique_notes.append(n)
                    note = ", ".join(unique_notes)
                
                days[day] = asdict(DayInfo(
                    start=chosen, 
                    note=note, 
                    date=header_dates[i] if i < len(header_dates) else None
                ))
            
            return WeekRecord(
                week_ending=week_ending,
                dates=header_dates,
                days=days
            )
            
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/parse', methods=['POST'])
def parse_pdf():
    if 'pdf' not in request.files:
        return jsonify({'error': 'No PDF file provided'}), 400
    
    file = request.files['pdf']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400
    
    try:
        # Parse the uploaded PDF
        pdf_stream = io.BytesIO(file.read())
        result = parse_timesheet_pdf(pdf_stream)
        
        if result is None:
            return jsonify({'error': f'Could not parse timesheet or {TARGET_NAME} not found'}), 400
        
        # Convert to JSON-serializable format
        response_data = {
            'week_ending': result.week_ending,
            'dates': result.dates,
            'days': result.days,
            'success': True
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({'error': f'Error processing PDF: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
