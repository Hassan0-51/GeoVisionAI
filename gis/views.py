# views.py - Updated with temporal/current functionality
import json
import os
import glob
import tempfile
import shutil
import uuid
import base64
import io
from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import threading
from datetime import datetime
import logging
from pathlib import Path
from django.contrib.auth.decorators import login_required
import pandas as pd
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Configure logger
logger = logging.getLogger(__name__)

# Import your model_execution class
from gis.model_execution import ModelExecution

# Dictionary to store active analysis results
active_results = {}
# Add result storage directory
RESULTS_DIR = os.path.join(settings.MEDIA_ROOT, 'analysis_results')
import ee
import json

# Initialize Earth Engine (add this before using any EE functions)
try:
    ee.Initialize(project="project-gis-466709")
    EE_INITIALIZED = True
except Exception as e:
    # Try to authenticate if not initialized
    try:
        ee.Authenticate()  # This will prompt for authentication
        ee.Initialize()
        EE_INITIALIZED = True
    except:
        EE_INITIALIZED = False
        print("Earth Engine initialization failed. Temporal temperature data will not be available.")

def cleanup_old_results():
    """Clean up results older than 1 hour"""
    import time
    current_time = time.time()
    to_delete = []
    
    for result_id, result_data in active_results.items():
        if current_time - result_data.get('timestamp', 0) > 3600:
            to_delete.append(result_id)
    
    for result_id in to_delete:
        cleanup_result_files(result_id)

def cleanup_result_files(result_id):
    """Clean up temporary files for a result"""
    if result_id in active_results:
        result_data = active_results.pop(result_id)
        temp_dir = result_data.get('temp_dir')
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
def ensure_results_dir():
    """Ensure results directory exists"""
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

@csrf_exempt
def analysis(request):
    if request.method == 'POST':
        return handle_analysis_request(request)
    # GET request - render the analysis page
    return render(request, 'analysis.html')

@csrf_exempt
def handle_analysis_request(request):
    try:
        # Get model path from settings
        MODEL_PATH = "storage/models/best_multiclass_model.pth"
        
        if not os.path.exists(MODEL_PATH):
            return JsonResponse({
                'error': f'Model file not found at: {MODEL_PATH}'
            }, status=500)
        
        # Get analysis parameters
        analysis_type = request.POST.get('analysis_type', 'basic')
        time_analysis = request.POST.get('time_analysis', 'current')
        start_year = int(request.POST.get('start_year', 2016))
        end_year = int(request.POST.get('end_year', 2024))
        include_predictions = request.POST.get('include_predictions') == 'true'
        
        # Create a unique result directory
        result_id = str(uuid.uuid4())
        result_dir = os.path.join(RESULTS_DIR, result_id)
        os.makedirs(result_dir, exist_ok=True)
        
        # Define supported classes
        classes = ['Urban_Area', 'Trees', 'Water', 'Soil', 'Agricultural_Land', 'Grasses_and_Bushes']
        
        try:
            # Determine years if temporal
            years = None
            if time_analysis == 'temporal':
                years = list(range(start_year, end_year + 1))
            
            # Initialize the model execution class
            executor = ModelExecution(
                model_path=MODEL_PATH,
                purpose='temporal' if time_analysis == 'temporal' else 'current',
                years=years
            )
            
            # Check if it's an image upload or coordinates
            if request.FILES.get('image_file'):
                # Handle image upload (current analysis only)
                uploaded_file = request.FILES['image_file']
                input_path = os.path.join(result_dir, 'uploaded_image.tif')
                
                with open(input_path, 'wb') as f:
                    for chunk in uploaded_file.chunks():
                        f.write(chunk)
                
                executor.input_tif = input_path
                executor.coordinates = None
                
                # Execute single image analysis
                executor.base_dir = Path(result_dir)
                execution_result = executor.invoke(save_config=True, username='web_user', run_advanced_analyses=(analysis_type == 'advanced'))
                
                # Prepare response for current analysis (Upload)
                # Try to extract geographic bounds from the uploaded TIF
                upload_bounds = None
                try:
                    with rasterio.open(input_path) as src:
                        b = src.bounds  # left, bottom, right, top
                        if src.crs:
                            from pyproj import Transformer
                            transformer = Transformer.from_crs(src.crs, 'EPSG:4326', always_xy=True)
                            minx, miny = transformer.transform(b.left, b.bottom)
                            maxx, maxy = transformer.transform(b.right, b.top)
                            upload_bounds = [minx, miny, maxx, maxy]
                        elif b.left != 0 and b.top != 0:
                            upload_bounds = [b.left, b.bottom, b.right, b.top]
                except Exception as e:
                    logger.warning(f"Could not extract bounds from uploaded TIF: {e}")
                
                # Compute green vs nongreen from area_dict
                green_nongreen = {}
                try:
                    adf = executor.area_dict
                    if not adf.empty:
                        green = (adf.get('Agricultural_Land_Area', 0) or 0) + (adf.get('Grasses_and_Bushes_Area', 0) or 0) + (adf.get('Trees_Area', 0) or 0)
                        nongreen = (adf.get('Urban_Area_Area', 0) or 0) + (adf.get('Soil_Area', 0) or 0) + (adf.get('Water_Area', 0) or 0)
                        if hasattr(green, 'iloc'):
                            green = float(green.iloc[0])
                            nongreen = float(nongreen.iloc[0])
                        green_nongreen = {'green': round(green, 2), 'nongreen': round(nongreen, 2)}
                except Exception:
                    pass

                result_data = {
                    'analysis_type': 'current',
                    'input_method': 'upload',
                    'area_dict': executor.area_dict,
                    'green_vs_nongreen': green_nongreen,
                    'llm_insights': execution_result.get('llm_insights') or {},
                    'advanced_analyses': execution_result.get('advanced_analyses') or {},
                    'temperature_data': executor.temperature,
                    'result_id': result_id,
                    'timestamp': datetime.now().isoformat(),
                    'year': 2024,
                    'season': 'single',
                    'bounds': upload_bounds,
                    'files': {
                        'mask': 'predicted_mask.tif',
                        'rgb_image': 'rgb_2024_single.tif'
                    }
                }
                
                # Manual layer detection for upload
                result_data['layers'] = {'2024': {'single': classes}}
                
            elif request.POST.get('coordinates'):
                # Handle coordinates (temporal or current)
                coordinates = json.loads(request.POST.get('coordinates'))
                executor.coordinates = coordinates
                executor.input_tif = None
                
                # Set temporal parameters if needed
                if time_analysis == 'temporal':
                    years = list(range(start_year, end_year + 1))
                else:
                    years = [2024]  # Current year only
                
                # Store years in executor for temporal processing
                executor.years = years
                
                # Execute analysis
                # Enable advanced analyses for both 'advanced' and 'detailed' types
                run_advanced = analysis_type in ['advanced', 'detailed']
                executor.base_dir = Path(result_dir)
                execution_result = executor.invoke(save_config=True, username='web_user', run_advanced_analyses=run_advanced)
                
                # Prepare response based on analysis type
                if time_analysis == 'temporal':
                    generate_temporal_visualizations(executor, result_dir)
                    
                    result_data = {
                        'analysis_type': 'temporal',
                        'input_method': 'map',
                        'area_dict': executor.area_dict,
                        'green_vs_nongreen': {},  # Computed by ChartsAPIView from CSV
                        'llm_insights': execution_result.get('llm_insights') or {},
                        'advanced_analyses': execution_result.get('advanced_analyses') or {},
                        'temperature_data': executor.temperature,
                        'years': years,
                        'result_id': result_id,
                        'bounds': coordinates,
                        'timestamp': datetime.now().isoformat(),
                        'has_temporal_data': True
                    }
                else:
                    # Current analysis (single year, usually 2024)
                    result_data = {
                        'analysis_type': 'current',
                        'input_method': 'map',
                        'area_dict': executor.area_dict,
                        'llm_insights': execution_result.get('llm_insights') or {},
                        'advanced_analyses': execution_result.get('advanced_analyses') or {},
                        'temperature_data': executor.temperature,
                        'result_id': result_id,
                        'year': 2024,
                        'timestamp': datetime.now().isoformat(),
                        'bounds': coordinates,
                        'files': {
                            'mask': os.path.join(result_dir, 'mask_2024_spring.tif'),
                            'rgb_image': os.path.join(result_dir, 'rgb_2024_spring.tif')
                        }
                    }

                # --- UNIFIED LAYER DETECTION (for both temporal and current) ---
                detected_layers = {}
                
                # Check for masks for each year and season
                for yr in years:
                    yr_str = str(yr)
                    detected_layers[yr_str] = {}
                    for sn in ["spring", "summer", "autumn", "winter"]:
                        mask_file = f"mask_{yr}_{sn}.tif"
                        if os.path.exists(os.path.join(result_dir, mask_file)):
                            detected_layers[yr_str][sn] = classes
                
                result_data['layers'] = detected_layers

                # --- TEMPERATURE DATA SERIALIZATION ---
                serializable_temp = {}
                if hasattr(executor.temperature, 'empty') and not executor.temperature.empty:
                    try:
                        df = executor.temperature
                        if 'year' in df.columns and 'season' in df.columns:
                            for yr in df['year'].unique():
                                yr_str = str(yr)
                                serializable_temp[yr_str] = {}
                                year_df = df[df['year'] == yr]
                                for sn in year_df['season'].unique():
                                    sn_df = year_df[year_df['season'] == sn]
                                    serializable_temp[yr_str][sn] = sn_df.to_dict(orient='records')
                    except Exception as e:
                        logger.error(f"Error serializing temp data: {e}")
                
                result_data['temperature_data'] = serializable_temp
            
            else:
                return JsonResponse({'error': 'No input provided'}, status=400)
            
            # Recursive function to convert DataFrames to dicts
            def convert_dataframes(obj):
                if isinstance(obj, pd.DataFrame):
                    return obj.to_dict(orient='records')
                elif isinstance(obj, dict):
                    return {k: convert_dataframes(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_dataframes(i) for i in obj]
                return obj

            # Step 1: Convert all DataFrames to serializable dicts recursively
            result_data = convert_dataframes(result_data)
            
            # Step 2: Ensure result_id is a string for all path operations (Windows compatibility)
            result_id_str = str(result_id)
            result_dir = os.path.join(RESULTS_DIR, result_id_str)
            
            # Save results to disk
            results_file = os.path.join(result_dir, 'results.json')
            try:
                with open(results_file, 'w') as f:
                    json.dump(result_data, f, indent=2)
                logger.info(f"Successfully saved results.json to {results_file}")
            except Exception as e:
                logger.error(f"Failed to save results.json: {e}")
            
            # Write separate JSON files for the dashboard API views
            try:
                llm_data = result_data.get('llm_insights') or {}
                with open(os.path.join(result_dir, 'llm_insights.json'), 'w') as f:
                    json.dump(llm_data, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save llm_insights.json: {e}")
            
            try:
                adv_data = result_data.get('advanced_analyses') or {}
                with open(os.path.join(result_dir, 'advanced_analyses.json'), 'w') as f:
                    json.dump(adv_data, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save advanced_analyses.json: {e}")
            
            # Save to user's analysis history
            try:
                if request.user.is_authenticated:
                    from web_dashboard.models import AnalysisHistory
                    coords = result_data.get('bounds')
                    a_type = 'temporal' if time_analysis == 'temporal' else 'current'
                    if a_type == 'temporal':
                        title = f"Temporal Analysis ({start_year}-{end_year})"
                    else:
                        title = f"Current Analysis – {datetime.now().strftime('%b %d, %Y')}"
                    AnalysisHistory.objects.create(
                        user=request.user,
                        result_id=result_id_str,
                        title=title,
                        analysis_type=a_type,
                        coordinates=coords,
                    )
            except Exception as e:
                logger.error(f"Failed to save analysis history: {e}")
            
            # Store in active results
            active_results[result_id_str] = {
                'data': result_data,
                'result_dir': result_dir,
                'timestamp': datetime.now().timestamp()
            }
            
            # Schedule cleanup (24 hours)
            cleanup_timer = threading.Timer(86400, cleanup_result_files, args=[result_id])
            cleanup_timer.start()
            
            # Return response with redirect URL
            redirect_url = f'/dashboard/?result_id={result_id}'
            
            return JsonResponse({
                'success': True,
                'result_id': result_id,
                'redirect_url': redirect_url,
                'analysis_type': time_analysis,
                'message': 'Analysis completed successfully'
            })
            
        except Exception as e:
            # Clean up on error
            if os.path.exists(result_dir):
                shutil.rmtree(result_dir, ignore_errors=True)
            raise e
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

def generate_temporal_visualizations(executor, result_dir):
    """Generate plots and charts for temporal analysis"""
    
    # 1. Generate green space area trend chart
    years = list(executor.area_dict.keys())
    seasons = ['spring', 'summer', 'autumn', 'winter']
    
    # Prepare data for visualization
    green_space_data = {}
    
    for year in years:
        for season in seasons:
            if season in executor.area_dict[year]:
                area_data = executor.area_dict[year][season]
                # Calculate total vegetation area
                vegetation_classes = ["Agricultural Land", "Grasses & Bushes", "Trees"]
                total_vegetation = sum(
                    area_data['classes'][cls]['area_km2'] 
                    for cls in vegetation_classes 
                    if cls in area_data['classes']
                )
                
                if year not in green_space_data:
                    green_space_data[year] = {}
                green_space_data[year][season] = total_vegetation
    
    # Generate plot
    plt.figure(figsize=(12, 6))
    
    for season in seasons:
        season_data = []
        for year in sorted(years):
            if year in green_space_data and season in green_space_data[year]:
                season_data.append(green_space_data[year][season])
            else:
                season_data.append(0)
        
        plt.plot(sorted(years), season_data, marker='o', label=season.capitalize())
    
    plt.title('Green Space Area Trend (2016-2024)')
    plt.xlabel('Year')
    plt.ylabel('Vegetation Area (km²)')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    
    # Save plot
    plot_path = os.path.join(result_dir, 'green_space_trend.png')
    plt.savefig(plot_path, dpi=150)
    plt.close()
    
    # 2. Generate temperature trend plot
    if hasattr(executor, 'temperature') and hasattr(executor.temperature, 'empty') and not executor.temperature.empty:
        plt.figure(figsize=(12, 6))
        
        for year in sorted(years):
            if year in executor.temperature and 'spring' in executor.temperature[year]:
                temp_data = executor.temperature[year]['spring']
                if not temp_data.empty:
                    plt.plot(temp_data['date'], temp_data['Aqua_Day'], 
                            label=f'{year}', alpha=0.7, linewidth=1)
        
        plt.title('Land Surface Temperature Trend (Spring Seasons)')
        plt.xlabel('Date')
        plt.ylabel('Temperature (°C)')
        plt.grid(True, alpha=0.3)
        plt.legend(title='Year')
        plt.tight_layout()
        
        temp_plot_path = os.path.join(result_dir, 'temperature_trend.png')
        plt.savefig(temp_plot_path, dpi=150)
        plt.close()

# New views for dedicated results pages
def temporal_results(request, result_id):
    """Render temporal analysis results page."""
    result_id_str = str(result_id)
    if result_id_str not in active_results:
        # Try to load from disk
        result_dir = os.path.join(RESULTS_DIR, result_id_str)
        results_file = os.path.join(result_dir, 'results.json')
        
        if not os.path.exists(results_file):
            return render(request, 'error.html', {'message': 'Results not found or expired'})
        
        with open(results_file, 'r') as f:
            result_data = json.load(f)
    else:
        result_data = active_results[result_id_str]['data']
    
    # Prepare data for template
    context = {
        'result_id': result_id_str,
        'result_data': json.dumps(result_data),
        'years': list(result_data.get('area_dict', {}).keys()),
        'analysis_type': 'temporal'
    }
    
    return render(request, 'temporal_results.html', context)

def current_results(request, result_id):
    """Render current analysis results page."""
    result_id_str = str(result_id)
    if result_id_str not in active_results:
        result_dir = os.path.join(RESULTS_DIR, result_id_str)
        results_file = os.path.join(result_dir, 'results.json')
        
        if not os.path.exists(results_file):
            return render(request, 'error.html', {'message': 'Results not found or expired'})
        
        with open(results_file, 'r') as f:
            result_data = json.load(f)
    else:
        result_data = active_results[result_id_str]['data']
    
    context = {
        'result_id': result_id_str,
        'result_data': json.dumps(result_data),
        'analysis_type': 'current'
    }
    
    return render(request, 'current_results.html', context)

# API endpoints for data retrieval
@csrf_exempt
def get_temporal_data(request, result_id, year=None, season=None):
    """API endpoint to get temporal data."""
    result_id_str = str(result_id)
    if result_id_str not in active_results:
        return JsonResponse({'error': 'Result not found'}, status=404)
    
    result_data = active_results[result_id_str]['data']
    
    if year and season:
        # Get specific year/season data
        if (year in result_data['area_dict'] and 
            season in result_data['area_dict'][year]):
            return JsonResponse({
                'area_data': result_data['area_dict'][year][season],
                'temperature_data': result_data['temperature_data'].get(year, {}).get(season, {})
            })
        else:
            return JsonResponse({'error': 'Data not found'}, status=404)
    else:
        # Get all data
        return JsonResponse(result_data)


def _fyp_data_root():
    return os.environ.get('FYP_DATA_ROOT', r'D:\FYP\Data')


def _season_name_order(season):
    s = str(season or 'spring').lower()
    order = [s, 'single', 'spring', 'summer', 'autumn', 'winter', 'average']
    seen = set()
    out = []
    for x in order:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _find_result_raster(result_dir, prefix, year, season):
    if not result_dir or not os.path.isdir(result_dir):
        return None
    y = int(year)
    s = str(season).lower()
    for name in (f'{prefix}_{y}_{season}.tif', f'{prefix}_{y}_{s}.tif', f'{prefix}_{y}_single.tif'):
        p = os.path.join(result_dir, name)
        if os.path.exists(p):
            return p
    matches = sorted(glob.glob(os.path.join(result_dir, f'{prefix}_{y}_*.tif')))
    if matches:
        return matches[0]
    if prefix == 'mask':
        for extra in ('predicted_mask.tif', 'mask.tif'):
            p = os.path.join(result_dir, extra)
            if os.path.exists(p):
                return p
    return None


def _find_satellite_tif(year, season):
    base = _fyp_data_root()
    y = str(int(year))
    for sub in ('Image-New', 'Image'):
        for sea in _season_name_order(season):
            p = os.path.join(base, y, sub, f'{sea}.tif')
            if os.path.exists(p):
                return p
    return None


def _tif_to_png_response_from_path(img_path):
    with rasterio.open(img_path) as src:
        num_bands = src.count
        if num_bands >= 3:
            rgb = src.read([1, 2, 3], out_dtype=np.float32)
        elif num_bands == 1:
            band = src.read(1, out_dtype=np.float32)
            rgb = np.stack([band, band, band], axis=0)
        else:
            bands = src.read(out_dtype=np.float32)
            while bands.shape[0] < 3:
                bands = np.vstack([bands, bands[-1:]])
            rgb = bands[:3]
        # Keep memory use low: avoid float64 temporaries.
        rgb_min = float(np.nanmin(rgb))
        rgb_max = float(np.nanmax(rgb))
        if rgb_max > rgb_min:
            rgb = ((rgb - rgb_min) / (rgb_max - rgb_min + 1e-8) * 255.0).astype(np.uint8)
        else:
            rgb = np.zeros(rgb.shape, dtype=np.uint8)
        rgb_hwc = np.transpose(rgb, (1, 2, 0))
    img = Image.fromarray(rgb_hwc)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type="image/png")


def _rgb_reprojected_to_mask(mask_path, sat_path):
    with rasterio.open(mask_path) as m:
        dst_h, dst_w = m.height, m.width
        dst_transform = m.transform
        dst_crs = m.crs

    out = np.zeros((dst_h, dst_w, 3), dtype=np.uint8)
    with rasterio.open(sat_path) as src:
        if dst_crs is None:
            dst_crs = src.crs
        for b in range(3):
            band_i = min(b + 1, max(1, src.count))
            dest = np.zeros((dst_h, dst_w), dtype=np.float32)
            reproject(
                source=rasterio.band(src, band_i),
                destination=dest,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )
            dmin = float(np.nanmin(dest))
            dmax = float(np.nanmax(dest))
            if dmax > dmin:
                out[:, :, b] = ((dest - dmin) / (dmax - dmin + 1e-8) * 255).astype(np.uint8)

    img = Image.fromarray(out)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type="image/png")


@csrf_exempt
def get_rgb_image(request, result_id, year, season):
    """Serve ROI satellite image from Image-New/Image, clipped to selected mask area."""
    result_dir = os.path.join(RESULTS_DIR, str(result_id))
    mask_path = _find_result_raster(result_dir, 'mask', year, season)
    sat_path = _find_satellite_tif(year, season)
    if mask_path and sat_path:
        try:
            return _rgb_reprojected_to_mask(mask_path, sat_path)
        except Exception as e:
            logger.error(f"Satellite ROI reproject failed: {e}")

    logger.info(f"Satellite ROI image unavailable for {result_id} {year} {season}.")
    return JsonResponse({'error': 'Satellite ROI image not available'}, status=404)

def _mask_to_png_response(mask_path):
    """Helper to colorize a mask tif and return an HttpResponse"""
    try:
        with rasterio.open(mask_path) as src:
            mask = src.read(1)
        
        # Diagnostic: Log unique values to see what we're serving
        unique_vals = np.unique(mask)
        logger.debug(f"Colorizing mask {mask_path}. Unique values: {unique_vals}")
        
        # Map classes to colors (Synchronized with ModelExecution._mask_to_rgb)
        # 0:BG, 1:Agricultural, 2:Grasses, 3:Urban, 4:Soil, 5:Water, 6:Trees
        color_map = {
            1: [60, 176, 67, 200],    # Agricultural (Parrot)
            2: [255, 255, 0, 200],    # Grasses (Yellow)
            3: [255, 0, 0, 200],      # Urban (Red)
            4: [139, 69, 19, 200],    # Soil (Brown)
            5: [0, 0, 255, 200],      # Water (Blue)
            6: [0, 128, 0, 200]       # Trees (Green)
        }
        
        rgb = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
        for val, color in color_map.items():
            rgb[mask == val] = color
        
        img = Image.fromarray(rgb)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        return HttpResponse(buf.getvalue(), content_type="image/png")
    except Exception as e:
        logger.error(f"Error serving mask {mask_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def get_mask_image(request, result_id, year, season):
    """Serve mask image with class colorsized according to model_execution.py"""
    logger.debug(f"Serving mask: Result={result_id}, Year={year}, Season={season}")
    result_id_str = str(result_id)
    result_dir = os.path.join(RESULTS_DIR, result_id_str)
    mask_path = _find_result_raster(result_dir, 'mask', year, season)

    if mask_path:
        requested_format = str(request.GET.get('format', '')).lower()
        if requested_format in ['tif', 'tiff']:
            try:
                return FileResponse(open(mask_path, 'rb'), content_type='image/tiff')
            except Exception as e:
                logger.error(f"Error serving TIFF mask {mask_path}: {e}")
                return JsonResponse({'error': str(e)}, status=500)
        return _mask_to_png_response(mask_path)
    
    return JsonResponse({'error': 'Mask file not found'}, status=404)

@csrf_exempt
def get_chart_image(request, result_id, chart_type):
    """Serve pre-generated chart PNG files."""
    result_id_str = str(result_id)
    result_dir = os.path.join(RESULTS_DIR, result_id_str)
    
    # Map chart types to filenames
    chart_files = {
        'area_2class': 'area_trends_2class.png',
        'area_6class': 'area_trends_6class.png',
        'temp_0': 'temperature_trend_0.png',
        'temp_1': 'temperature_trend_1.png',
        'temp_2': 'temperature_trend_2.png',
        'temp_3': 'temperature_trend_3.png'
    }
    
    if chart_type not in chart_files:
        return JsonResponse({'error': 'Invalid chart type'}, status=400)
    
    chart_path = os.path.join(result_dir, chart_files[chart_type])
    
    if not os.path.exists(chart_path):
        return JsonResponse({'error': 'Chart image not found'}, status=404)
    
    try:
        from django.http import FileResponse
        return FileResponse(open(chart_path, 'rb'), content_type='image/png')
    except Exception as e:
        logger.error(f"Error serving chart image {chart_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def get_new_image(request, year, season):
    """Serve reference satellite TIF as PNG (Image-New or Image under FYP data root)."""
    img_path = _find_satellite_tif(year, season)
    if not img_path:
        return JsonResponse({'error': 'Satellite image not found for this year/season'}, status=404)
    try:
        return _tif_to_png_response_from_path(img_path)
    except Exception as e:
        logger.error(f"Error serving satellite {img_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def get_new_image_bounds(request, year, season):
    """Return [minx, miny, maxx, maxy] in WGS84 for the reference satellite TIF."""
    img_path = _find_satellite_tif(year, season)
    if not img_path:
        return JsonResponse({'error': 'File not found'}, status=404)

    try:
        with rasterio.open(img_path) as src:
            b = src.bounds
            if src.crs:
                from pyproj import Transformer
                transformer = Transformer.from_crs(src.crs, 'EPSG:4326', always_xy=True)
                minx, miny = transformer.transform(b.left, b.bottom)
                maxx, maxy = transformer.transform(b.right, b.top)
                bounds = [minx, miny, maxx, maxy]
            else:
                bounds = [b.left, b.bottom, b.right, b.top]
        return JsonResponse({'bounds': bounds})
    except Exception as e:
        logger.error(f"Error getting satellite bounds {img_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def documentation(request):
    return render(request, "documentation.html")

# @login_required(login_url='login')
def index(request):
    return render(request, "index.html")

def help(request):
    return render(request, "help.html")

def academic_request(request):
    return render(request, "academic_request.html")

def api_documentation(request):
    return render(request, "api_documentation.html")

def api_integration(request):
    return render(request, "api_integration.html")

def blogs(request):
    return render(request, "blogs.html")

def case_studies(request):
    return render(request, "case_studies.html")

# Redundant views removed. Authentication is handled by 'accounts' app.

def research_paper(request):
    return render(request, "research_paper.html")

def tutorials(request):
    return render(request, "tutorials.html")

def delhi_lahore(request):
    return render(request, "delhi_lahore.html")

def faisalabad_industrial(request):
    return render(request, "faisalabad_industrial.html")

def karachi_research(request):
    return render(request, "karachi_research.html")

def lahore_2023(request):
    return render(request, "lahore_2023.html")

def punjab_forestry(request):
    return render(request, "punjab_forestry.html")

def rawalpindi_smart(request):
    return render(request, "rawalpindi_smart.html")

def contact_sales(request):
    return render(request, "contact_sales.html")

def cookies_policy(request):
    return render(request, "cookies_policy.html")

def custom_models(request):
    return render(request, "custom_models.html")

def data_catalog(request):
    return render(request, "data_catalog.html")

def enterprise(request):
    return render(request, "enterprise.html")

def faqs(request):
    return render(request, "faqs.html")

def forgot_password(request):
    return render(request, "forgot_password.html")

def getting_started(request):
    return render(request, "getting_started.html")

def gis_export(request):
    return render(request, "gis_export.html")

def model_library(request):
    return render(request, "model_library.html")

def privacy_policy(request):
    return render(request, "privacy_policy.html")

def support(request):
    return render(request, "support.html")

def temporal_analysis(request):
    return render(request, "temporal_analysis.html")

def terms(request):
    return render(request, "terms.html")

def understanding_result(request):
    return render(request, "understanding_result.html")

def upgrade_plan(request):
    return render(request, "upgrade_plan.html")

def verify_academic(request):
    return render(request, "verify_academic.html")
