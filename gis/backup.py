import os
from PyPDF2 import PdfReader, PdfWriter
from django.http import HttpResponse
from django.shortcuts import render,get_object_or_404,redirect
from google import genai
from django.db.models import Count,Q
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from gis.model_execution import model_execution
from django.shortcuts import render

def index(request):
    return render(request, "index.html")

def academic_request(request):
    return render(request, "academic_request.html")

def help(request):
    return render(request, "help.html")
# views.py
import json
import os
import tempfile
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import FileSystemStorage
import shutil
# views.py
import json
import os
import tempfile
import shutil
import uuid
from django.shortcuts import render
from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import threading

# Import your model_execution class
# Dictionary to store active analysis results (in-memory cache)
# In production, use Redis or database
active_results = {}
cleanup_timer = threading.Timer(3600, lambda: cleanup_old_results())  # 1 hour cleanup

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
        MODEL_PATH ="storage/models/best_multiclass_model.pth"
        
        if not os.path.exists(MODEL_PATH):
            return JsonResponse({
                'error': f'Model file not found at: {MODEL_PATH}'
            }, status=500)
        
        # Create a temporary directory for this analysis
        temp_dir = tempfile.mkdtemp(prefix='greenspace_')
        
        try:
            # Initialize the model execution class
            executor = model_execution(MODEL_PATH=MODEL_PATH)
            
            # Set output paths in temp directory
            executor.output_image_tif = os.path.join(temp_dir, "image")
            executor.output_mask_tif = os.path.join(temp_dir, "mask")
            executor.cordinate_cropped_image = os.path.join(temp_dir, "cropped")
            executor.output_dir_from_patching = os.path.join(temp_dir, "patched_image_tiles")
            executor.output_dir_from_prediction = os.path.join(temp_dir, "patched_mask_tiles")
            
            # Check if it's an image upload or coordinates
            if request.FILES.get('image_file'):
                # Handle image upload
                uploaded_file = request.FILES['image_file']
                
                # Save uploaded file temporarily
                input_path = os.path.join(temp_dir, 'uploaded_image.tif')
                with open(input_path, 'wb') as f:
                    for chunk in uploaded_file.chunks():
                        f.write(chunk)
                
                executor.input_tif = input_path
                executor.cordinates = None
                
            elif request.POST.get('coordinates'):
                # Handle coordinates
                coordinates = json.loads(request.POST.get('coordinates'))
                executor.cordinates = coordinates
                executor.input_tif = None
                
            else:
                return JsonResponse({'error': 'No input provided'}, status=400)
            
            # Execute the pipeline
            executor.invoke()
            
            # Check if area_dict was generated
            if not executor.area_dict:
                return JsonResponse({
                    'error': 'Analysis completed but no statistics were generated'
                }, status=500)
            
            # Check if mask file was created
            mask_path = f"{executor.output_mask_tif}.tif"
            if not os.path.exists(mask_path):
                return JsonResponse({
                    'error': f'Mask file not created at: {mask_path}'
                }, status=500)
            
            # Generate unique ID for this analysis
            result_id = str(uuid.uuid4())
            
            # Store result data in memory
            import time
            result_data = {
                'area_dict': executor.area_dict,
                'mask_path': mask_path,
                'temp_dir': temp_dir,
                'timestamp': time.time()
            }
            
            # Check if image file exists
            image_path = f"{executor.output_image_tif}.tif"
            if os.path.exists(image_path):
                result_data['image_path'] = image_path
            
            # Store in active results
            active_results[result_id] = result_data
            
            # Prepare response data
            response_data = {
                'success': True,
                'result_id': result_id,
                'area_dict': executor.area_dict,
                'message': 'Analysis completed successfully',
                'files': {
                    'mask': True,
                    'image': os.path.exists(image_path)
                }
            }
            
            return JsonResponse(response_data)
            
        except Exception as e:
            # Clean up temp directory on error
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def serve_result_file(request, result_id, file_type):
    """Serve the generated mask or image file"""
    if result_id not in active_results:
        return JsonResponse({'error': 'Result not found or expired'}, status=404)
    
    result_data = active_results[result_id]
    
    if file_type == 'mask':
        file_path = result_data.get('mask_path')
        content_type = 'image/tiff'
        filename = 'greenspace_mask.tif'
    elif file_type == 'image':
        file_path = result_data.get('image_path')
        content_type = 'image/tiff'
        filename = 'greenspace_image.tif'
    else:
        return JsonResponse({'error': 'Invalid file type'}, status=400)
    
    if not file_path or not os.path.exists(file_path):
        return JsonResponse({'error': 'File not found'}, status=404)
    
    # Serve file
    response = FileResponse(open(file_path, 'rb'), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def get_result_data(request, result_id):
    """Get result data (area_dict) without files"""
    if result_id not in active_results:
        return JsonResponse({'error': 'Result not found or expired'}, status=404)
    
    result_data = active_results[result_id]
    return JsonResponse({
        'success': True,
        'area_dict': result_data.get('area_dict', {}),
        'has_mask': 'mask_path' in result_data,
        'has_image': 'image_path' in result_data
    })

@csrf_exempt
def cleanup_result(request, result_id):
    """Clean up temporary files"""
    cleanup_result_files(result_id)
    return JsonResponse({'success': True})
def get_results(request, result_id):
    # This view would serve the generated mask image
    # You need to implement file serving logic here
    pass
def documentation(request):
    return render(request, "documentation.html")

def api_documentation(request):
    return render(request, "api_documentation.html")

def api_integration(request):
    return render(request, "api_integration.html")

def blogs(request):
    return render(request, "blogs.html")

def case_studies(request):
    return render(request, "case_studies.html")

def login(request):
    return render(request, "login.html")

def register(request):
    return render(request, "register.html")

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
