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
    app.run(host='0.0.0.0', port=port)
