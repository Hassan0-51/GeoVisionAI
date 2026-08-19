import json
import logging
import os
import pandas as pd
import numpy as np
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.views import View
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.shortcuts import render, redirect

from .models import AnalysisHistory, UserPreferences

logger = logging.getLogger(__name__)
RESULTS_DIR = os.path.join(settings.MEDIA_ROOT, 'analysis_results')

def get_latest_result_id():
    """Helper to find the most recent result folder."""
    try:
        if os.path.exists(RESULTS_DIR):
            subdirs = [
                d for d in os.listdir(RESULTS_DIR) 
                if os.path.isdir(os.path.join(RESULTS_DIR, d)) and 
                os.path.exists(os.path.join(RESULTS_DIR, d, 'results.json'))
            ]
            if subdirs:
                return max(subdirs, key=lambda d: os.path.getmtime(os.path.join(RESULTS_DIR, d)))
    except Exception as e:
        logger.error(f"Error finding latest result: {e}")
    return None


def _save_history_entry(user, result_id, dashboard_mode, result_dir):
    """Create (or skip duplicate) an AnalysisHistory entry for an authenticated user."""
    if not user or not user.is_authenticated or not result_id:
        return
    try:
        if AnalysisHistory.objects.filter(result_id=result_id).exists():
            return  # already recorded

        # Build a human-friendly title
        title = f"{dashboard_mode.title()} Analysis — {result_id[:8]}"
        summary_text = ''
        llm_path = os.path.join(result_dir, 'llm_insights.json')
        if os.path.exists(llm_path):
            try:
                with open(llm_path, 'r', encoding='utf-8') as f:
                    import re
                    raw = f.read()
                    raw = re.sub(r'\bNaN\b', 'null', raw)
                    raw = re.sub(r'\bInfinity\b', 'null', raw)
                    raw = re.sub(r'\b-Infinity\b', 'null', raw)
                    llm = json.loads(raw)
                # Grab first insight paragraph if present
                for key in ('summary', 'executive_summary', 'overview', 'key_findings'):
                    val = llm.get(key, '')
                    if val and isinstance(val, str):
                        summary_text = val[:300]
                        break
            except Exception:
                pass

        AnalysisHistory.objects.create(
            user=user,
            result_id=result_id,
            title=title,
            analysis_type=dashboard_mode if dashboard_mode in ('current', 'temporal', 'upload') else 'current',
            summary=summary_text,
        )
    except Exception as e:
        logger.warning(f"Could not save history entry for {result_id}: {e}")


class DashboardView(TemplateView):
    template_name = 'dashboard_temporal.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'GeoAI Land Cover Analysis'
        
        result_id = self.request.GET.get('result_id')
        if not result_id:
            result_id = get_latest_result_id()
            
        context['result_id'] = result_id or ''
        context['analysis_years'] = list(range(2016, 2025))

        # Resolve dashboard mode from persisted result metadata.
        context['dashboard_mode'] = 'temporal'
        result_dir = None
        if result_id:
            result_dir = os.path.join(RESULTS_DIR, result_id)
            try:
                result_path = os.path.join(result_dir, 'results.json')
                if os.path.exists(result_path):
                    with open(result_path, 'r', encoding='utf-8') as f:
                        result_data = json.load(f)
                    analysis_type = str(result_data.get('analysis_type', '')).lower()
                    input_method = str(result_data.get('input_method', '')).lower()
                    if analysis_type == 'temporal':
                        context['dashboard_mode'] = 'temporal'
                    elif input_method == 'upload':
                        context['dashboard_mode'] = 'upload'
                    else:
                        context['dashboard_mode'] = 'current'
            except Exception as e:
                logger.warning(f"Could not resolve dashboard mode for {result_id}: {e}")

        # Auto-save history entry whenever an authenticated user views a result
        if result_id and result_dir:
            _save_history_entry(
                self.request.user,
                result_id,
                context['dashboard_mode'],
                result_dir,
            )

        # Attach user preferences for template use
        if self.request.user.is_authenticated:
            prefs, _ = UserPreferences.objects.get_or_create(user=self.request.user)
            context['prefs'] = prefs

        return context

    def get_template_names(self):
        mode = self.get_context_data().get('dashboard_mode', 'temporal')
        template_map = {
            'upload': 'dashboard_upload.html',
            'current': 'dashboard_current.html',
            'temporal': 'dashboard_temporal.html',
        }
        return [template_map.get(mode, 'dashboard_temporal.html')]

class MapLayersAPIView(View):
    def get(self, request, *args, **kwargs):
        result_id = request.GET.get('result_id')
        if not result_id:
            result_id = get_latest_result_id()
        if not result_id:
            return JsonResponse({'error': 'No data'}, status=404)
            
        result_path = os.path.join(RESULTS_DIR, result_id, 'results.json')
        if os.path.exists(result_path):
            try:
                with open(result_path, 'r') as f:
                    data = json.load(f)
                
                # Convert polygon bounds to bbox, or use bbox directly
                points = data.get('bounds')
                bbox = None
                if points and isinstance(points, list):
                    if len(points) == 4 and all(isinstance(v, (int, float)) for v in points):
                        # Already a flat bbox: [minx, miny, maxx, maxy]
                        bbox = points
                    elif len(points) >= 2 and isinstance(points[0], (list, tuple)):
                        # Polygon points: [[lat, lng], ...]
                        try:
                            lats = [p[0] for p in points]
                            lons = [p[1] for p in points]
                            bbox = [min(lons), min(lats), max(lons), max(lats)]
                        except:
                            bbox = None

                return JsonResponse({
                    'layers': data.get('layers', {}), 
                    'bounds': bbox
                })
            except:
                pass
        return JsonResponse({'error': 'Not found'}, status=404)

class AnalysisAPIView(View):
    def get(self, request, *args, **kwargs):
        result_id = request.GET.get('result_id')
        if not result_id:
            result_id = get_latest_result_id()
            
        if not result_id:
            return JsonResponse({'error': 'No data available'}, status=404)
            
        result_dir = os.path.join(RESULTS_DIR, result_id)
        llm_path = os.path.join(result_dir, 'llm_insights.json')
        adv_path = os.path.join(result_dir, 'advanced_analyses.json')

        def safe_load_json(path):
            """Read a JSON file, replacing Python NaN/Infinity tokens so it parses cleanly."""
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                # Replace bare NaN / Infinity / -Infinity (invalid JSON) with null
                import re
                raw = re.sub(r'\bNaN\b', 'null', raw)
                raw = re.sub(r'\bInfinity\b', 'null', raw)
                raw = re.sub(r'\b-Infinity\b', 'null', raw)
                return json.loads(raw)
            except Exception as e:
                logger.warning(f"Could not load {path}: {e}")
                return {}

        insights = {}
        advanced = {}

        if os.path.exists(llm_path):
            insights = safe_load_json(llm_path)

        if os.path.exists(adv_path):
            advanced = safe_load_json(adv_path)

        return JsonResponse({
            'llm_insights': insights,
            'advanced_analysis': advanced
        })

class ChartsAPIView(View):
    def get(self, request, *args, **kwargs):
        result_id = request.GET.get('result_id')
        selected_year = request.GET.get('year')
        selected_season = request.GET.get('season', 'average').lower()
        
        if not result_id:
            result_id = get_latest_result_id()
            
        if not result_id:
            return JsonResponse({'error': 'No data available'}, status=404)
            
        result_dir = os.path.join(RESULTS_DIR, result_id)
        
        try:
            # Load CSV files
            area_csv = os.path.join(result_dir, 'area_analysis.csv')
            temp_csv = os.path.join(result_dir, 'temperature_analysis.csv')
            
            df_area = pd.read_csv(area_csv) if os.path.exists(area_csv) else pd.DataFrame()
            df_temp = pd.read_csv(temp_csv) if os.path.exists(temp_csv) else pd.DataFrame()
            result_json_path = os.path.join(result_dir, 'results.json')
            
            # Process area data
            area_chart = {'years': [], 'urban': [], 'green': [], 'water': [], 'agriculture': [], 'trees': [], 'grass': [], 'soil': []}
            green_vs_nongreen = {'years': [], 'green': [], 'non_green': []}
            
            if not df_area.empty:
                # Ensure numeric types
                df_area['year'] = pd.to_numeric(df_area['year'], errors='coerce')
                df_area['season'] = df_area['season'].astype(str).str.lower()
                
                # Filter by season
                if selected_season == 'all':
                    # Get all seasons for the selected year
                    if selected_year:
                        df_filtered = df_area[df_area['year'] == int(selected_year)]
                    else:
                        df_filtered = df_area[df_area['season'] == 'average']
                else:
                    target_season = selected_season if selected_season in ['spring', 'summer', 'autumn', 'winter', 'average', 'single'] else 'average'
                    df_filtered = df_area[df_area['season'] == target_season].sort_values('year')
                    if df_filtered.empty and target_season != 'single':
                        # Fallback for uploaded-image analyses that are stored as "single".
                        df_filtered = df_area[df_area['season'] == 'single'].sort_values('year')
                
                if not df_filtered.empty:
                    area_chart['years'] = df_filtered['year'].tolist()
                    
                    # Map column names
                    col_map = {
                        'Urban_Area_Area': 'urban',
                        'Trees_Area': 'trees',
                        'Grasses_and_Bushes_Area': 'grass',
                        'Water_Area': 'water',
                        'Agricultural_Land_Area': 'agriculture',
                        'Soil_Area': 'soil'
                    }
                    
                    for old_col, new_col in col_map.items():
                        if old_col in df_filtered.columns:
                            area_chart[new_col] = df_filtered[old_col].round(2).tolist()
                    
                    # Calculate green space
                    green_total = (
                        df_filtered.get('Trees_Area', 0) + 
                        df_filtered.get('Grasses_and_Bushes_Area', 0)
                    )
                    area_chart['green'] = green_total.round(2).tolist()
                    
                    # Calculate green vs non-green
                    green_vs_nongreen['years'] = area_chart['years']
                    green_space = (
                        df_filtered.get('Trees_Area', 0) + 
                        df_filtered.get('Grasses_and_Bushes_Area', 0) + 
                        df_filtered.get('Agricultural_Land_Area', 0)
                    )
                    non_green_space = (
                        df_filtered.get('Urban_Area_Area', 0) + 
                        df_filtered.get('Soil_Area', 0) + 
                        df_filtered.get('Water_Area', 0)
                    )
                    green_vs_nongreen['green'] = green_space.round(2).tolist()
                    green_vs_nongreen['non_green'] = non_green_space.round(2).tolist()
            elif os.path.exists(result_json_path):
                # Fallback for custom uploads/current runs where CSVs may be missing.
                try:
                    with open(result_json_path, 'r', encoding='utf-8') as f:
                        result_data = json.load(f)

                    area_records = result_data.get('area_dict') or []
                    if isinstance(area_records, list) and area_records:
                        rec = area_records[-1]
                        fallback_year = int(rec.get('year') or selected_year or 2024)
                        area_chart['years'] = [fallback_year]
                        area_chart['urban'] = [round(float(rec.get('Urban_Area_Area', 0) or 0), 2)]
                        area_chart['trees'] = [round(float(rec.get('Trees_Area', 0) or 0), 2)]
                        area_chart['grass'] = [round(float(rec.get('Grasses_and_Bushes_Area', 0) or 0), 2)]
                        area_chart['water'] = [round(float(rec.get('Water_Area', 0) or 0), 2)]
                        area_chart['agriculture'] = [round(float(rec.get('Agricultural_Land_Area', 0) or 0), 2)]
                        area_chart['soil'] = [round(float(rec.get('Soil_Area', 0) or 0), 2)]
                        area_chart['green'] = [round(area_chart['trees'][0] + area_chart['grass'][0], 2)]

                    gvng = result_data.get('green_vs_nongreen') or {}
                    if isinstance(gvng, dict) and ('green' in gvng or 'nongreen' in gvng):
                        fallback_year = int(selected_year or 2024)
                        green_vs_nongreen['years'] = [fallback_year]
                        green_vs_nongreen['green'] = [round(float(gvng.get('green', 0) or 0), 2)]
                        green_vs_nongreen['non_green'] = [round(float(gvng.get('nongreen', 0) or 0), 2)]
                except Exception as fallback_err:
                    logger.warning(f"Could not build area fallback from results.json: {fallback_err}")
            
            # Process temperature data
            temp_chart = {'labels': [], 'aqua_day': [], 'aqua_night': [], 'terra_day': [], 'terra_night': [], 'mode': 'seasonal'}
            
            if not df_temp.empty:
                df_temp['year'] = pd.to_numeric(df_temp['year'], errors='coerce')
                df_temp['season'] = df_temp['season'].astype(str).str.lower()
                df_temp['sensor'] = df_temp['sensor'].str.replace(' ', '_').str.title()
                
                val_col = 'Mean_T' if 'Mean_T' in df_temp.columns else 'mean'
                
                season_order = ['spring', 'summer', 'autumn', 'winter']
                season_display = ['Spring', 'Summer', 'Autumn', 'Winter']
                
                if selected_year:
                    # MODE: Seasonal view for a specific year
                    df_year = df_temp[df_temp['year'] == int(selected_year)]
                    df_year = df_year[df_year['season'].isin(season_order)]
                    
                    temp_chart['mode'] = 'seasonal'
                    temp_chart['labels'] = season_display
                    
                    sensor_map = {
                        'Aqua_Day': 'aqua_day',
                        'Aqua_Night': 'aqua_night',
                        'Terra_Day': 'terra_day',
                        'Terra_Night': 'terra_night'
                    }
                    
                    for sensor_key, chart_key in sensor_map.items():
                        vals = []
                        for s in season_order:
                            row = df_year[(df_year['season'] == s) & (df_year['sensor'] == sensor_key)]
                            if not row.empty:
                                vals.append(round(float(row[val_col].iloc[0]), 2))
                            else:
                                vals.append(None)
                        temp_chart[chart_key] = vals
                else:
                    # MODE: Yearly view with the selected season
                    temp_chart['mode'] = 'yearly'
                    target_season = selected_season if selected_season in season_order else 'spring'
                    df_season = df_temp[df_temp['season'] == target_season]
                    
                    if not df_season.empty:
                        pivot = df_season.pivot_table(
                            index='year',
                            columns='sensor',
                            values=val_col
                        ).sort_index()
                        
                        temp_chart['labels'] = [int(y) for y in pivot.index.tolist()]
                        
                        sensor_map = {
                            'Aqua_Day': 'aqua_day',
                            'Aqua_Night': 'aqua_night',
                            'Terra_Day': 'terra_day',
                            'Terra_Night': 'terra_night'
                        }
                        
                        for old_name, new_name in sensor_map.items():
                            if old_name in pivot.columns:
                                temp_chart[new_name] = pivot[old_name].round(2).tolist()
            
            # Calculate green vs non-green percentages
            green_pct = {'labels': green_vs_nongreen.get('years', []), 'green_pct': [], 'non_green_pct': []}
            if green_vs_nongreen.get('green') and green_vs_nongreen.get('non_green'):
                for g, ng in zip(green_vs_nongreen['green'], green_vs_nongreen['non_green']):
                    total = g + ng
                    if total > 0:
                        green_pct['green_pct'].append(round((g / total) * 100, 1))
                        green_pct['non_green_pct'].append(round((ng / total) * 100, 1))
                    else:
                        green_pct['green_pct'].append(0)
                        green_pct['non_green_pct'].append(0)
            
            return JsonResponse({
                'area': area_chart,
                'temperature': temp_chart,
                'green_vs_nongreen': green_vs_nongreen,
                'green_pct': green_pct,
                'selected_year': selected_year
            })
            
        except Exception as e:
            logger.error(f"ChartsAPI Error: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)


class AreaTrendAPIView(View):
    """Returns all area_analysis.csv rows for the interactive trend chart."""
    def get(self, request, *args, **kwargs):
        result_id = request.GET.get('result_id')
        if not result_id:
            result_id = get_latest_result_id()
        if not result_id:
            return JsonResponse({'error': 'No data available'}, status=404)

        area_csv = os.path.join(RESULTS_DIR, result_id, 'area_analysis.csv')
        if not os.path.exists(area_csv):
            return JsonResponse({'error': 'area_analysis.csv not found'}, status=404)

        try:
            df = pd.read_csv(area_csv)
            df['year'] = pd.to_numeric(df['year'], errors='coerce').astype(int)
            df['season'] = df['season'].astype(str).str.lower()

            col_map = {
                'Agricultural_Land_Area': 'agriculture',
                'Grasses_and_Bushes_Area': 'grass',
                'Urban_Area_Area': 'urban',
                'Soil_Area': 'soil',
                'Water_Area': 'water',
                'Trees_Area': 'trees',
            }
            df = df.rename(columns=col_map)
            keep = ['year', 'season'] + list(col_map.values())
            df = df[[c for c in keep if c in df.columns]]

            seasons = ['spring', 'summer', 'autumn', 'winter', 'average']
            result = {}
            for season in seasons:
                subset = df[df['season'] == season].sort_values('year')
                if not subset.empty:
                    result[season] = subset.drop(columns='season').round(2).to_dict(orient='list')

            return JsonResponse({'data': result})
        except Exception as e:
            logger.error(f"AreaTrendAPI Error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


# ── History, Settings, Change Password ──────────────────────

class HistoryView(LoginRequiredMixin, TemplateView):
    template_name = 'history.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['history'] = AnalysisHistory.objects.filter(user=self.request.user)
        context['total_analyses'] = context['history'].count()
        context['temporal_count'] = context['history'].filter(analysis_type='temporal').count()
        context['current_count'] = context['history'].filter(analysis_type='current').count()
        context['upload_count'] = context['history'].filter(analysis_type='upload').count()
        return context


def delete_history_item(request, pk):
    """Delete a single history entry."""
    if request.method == 'POST' and request.user.is_authenticated:
        try:
            item = AnalysisHistory.objects.get(pk=pk, user=request.user)
            item.delete()
            messages.success(request, 'Analysis removed from history.')
        except AnalysisHistory.DoesNotExist:
            messages.error(request, 'History item not found.')
    return redirect('web_dashboard:history')


class AccountSettingsView(LoginRequiredMixin, View):
    template_name = 'settings.html'
    login_url = '/accounts/login/'

    def get(self, request):
        prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
        return render(request, self.template_name, {'user': request.user, 'prefs': prefs})

    def post(self, request):
        user = request.user
        section = request.POST.get('section', 'profile')

        if section == 'profile':
            user.full_name = request.POST.get('full_name', user.full_name).strip()
            user.institution = request.POST.get('institution', user.institution).strip()
            user.user_type = request.POST.get('user_type', user.user_type)
            user.newsletter = 'newsletter' in request.POST
            user.save()
            messages.success(request, 'Profile updated successfully.')

        elif section == 'preferences':
            prefs, _ = UserPreferences.objects.get_or_create(user=user)
            prefs.default_map_layer = request.POST.get('default_map_layer', prefs.default_map_layer)
            prefs.default_season = request.POST.get('default_season', prefs.default_season)
            prefs.show_temperature_chart = 'show_temperature_chart' in request.POST
            prefs.show_advanced_metrics = 'show_advanced_metrics' in request.POST
            prefs.save()
            messages.success(request, 'Display preferences saved.')

        elif section == 'notifications':
            prefs, _ = UserPreferences.objects.get_or_create(user=user)
            prefs.notify_analysis_complete = 'notify_analysis_complete' in request.POST
            prefs.notify_weekly_digest = 'notify_weekly_digest' in request.POST
            prefs.save()
            messages.success(request, 'Notification preferences saved.')

        elif section == 'export':
            prefs, _ = UserPreferences.objects.get_or_create(user=user)
            prefs.export_format = request.POST.get('export_format', prefs.export_format)
            prefs.include_map_in_report = 'include_map_in_report' in request.POST
            prefs.include_charts_in_report = 'include_charts_in_report' in request.POST
            prefs.save()
            messages.success(request, 'Export settings saved.')

        return redirect('web_dashboard:settings')


class ChangePasswordView(LoginRequiredMixin, View):
    template_name = 'change_password.html'
    login_url = '/accounts/login/'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('web_dashboard:change_password')

        if len(new_password) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
            return redirect('web_dashboard:change_password')

        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return redirect('web_dashboard:change_password')

        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, 'Password changed successfully!')
        return redirect('web_dashboard:change_password')
