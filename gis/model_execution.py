
import os

AWS_REGION = os.environ.get('AWS_REGION', 'ap-south-1')
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

if AWS_REGION:
    os.environ.setdefault('AWS_REGION', AWS_REGION)
if AWS_ACCESS_KEY_ID:
    os.environ['AWS_ACCESS_KEY_ID'] = AWS_ACCESS_KEY_ID
if AWS_SECRET_ACCESS_KEY:
    os.environ['AWS_SECRET_ACCESS_KEY'] = AWS_SECRET_ACCESS_KEY

import time
import logging
import os
import math
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any, Union
from dataclasses import dataclass, field
from collections import defaultdict
import warnings
from math import ceil

import numpy as np
import pandas as pd
try:
    import rasterio
    from rasterio.mask import mask
    from rasterio.transform import array_bounds
    from rasterio.plot import show
    from rasterio import features
except ImportError:
    rasterio = None

try:
    from shapely.geometry import Polygon, box, mapping, shape
except ImportError:
    Polygon = box = mapping = shape = None

try:
    from pyproj import Transformer
except ImportError:
    Transformer = None

try:
    import geopandas as gpd
except ImportError:
    gpd = None

try:
    import torch
    import segmentation_models_pytorch as smp
except (ImportError, OSError):
    torch = None
    smp = None

if torch is None:
    class DummyTorch:
        @staticmethod
        def no_grad():
            def decorator(func):
                return func
            return decorator
        
        @staticmethod
        def set_num_threads(n):
            pass
            
    torch = DummyTorch()

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    matplotlib = None
    plt = None

try:
    import cv2
except ImportError:
    cv2 = None

from scipy.stats import linregress, zscore

try:
    import pymannkendall as mk
except ImportError:
    mk = None

from pydantic import BaseModel
try:
    from langchain_core.prompts import PromptTemplate
    from langchain_openai import ChatOpenAI
    from langchain_core.output_parsers import PydanticOutputParser
except ImportError:
    pass
import ee
try:
    ee.Initialize(project="auspicious-env-472806-c6")
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


try:
    from rasterio.env import Env
except ImportError:
    Env = None

from sklearn.metrics import confusion_matrix, classification_report
from skimage import measure, filters

try:
    import folium
    from folium import plugins
except ImportError:
    folium = None

from scipy.ndimage import binary_dilation
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import base64
from io import BytesIO

# Suppress warnings
warnings.filterwarnings('ignore')

# Configure logging with enhanced formatting
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
logger = logging.getLogger(__name__)

# Set environment variables
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

@dataclass
class PipelineConfig:
    """Configuration for the model execution pipeline."""
    tile_size: int = 512
    device: str = "cpu"
    num_threads: int = 8
    class_names: Dict[int, str] = None
    carbon_coefficients: Dict[str, float] = None
    change_detection_threshold: float = 3.0
    anomaly_detection_threshold: float = 2.5
    
    def __post_init__(self):
        if self.class_names is None:
            self.class_names = {
                0: "Background",
                1: "Agricultural Land",
                2: "Grasses & Bushes",
                3: "Urban Area",
                4: "Soil",
                5: "Water",
                6: "Trees"
            }
        
        if self.carbon_coefficients is None:
            # IPCC default values (tons/ha/year)
            self.carbon_coefficients = {
                "Trees": 6.0,
                "Agricultural Land": 0.5,
                "Grasses & Bushes": 1.2,
                "Urban Area": 0.1,
                "Soil": 0.8,
                "Water": 0.0,
                "Background": 0.0
            }

class ChangeDetection:
    """Handle change detection between time periods."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    def compute_change_matrix(self, mask1: np.ndarray, mask2: np.ndarray) -> Dict:
        """Create transition matrix showing class changes."""
        n_classes = len(self.config.class_names)
        matrix = np.zeros((n_classes, n_classes), dtype=np.int32)
        
        for i in range(n_classes):
            for j in range(n_classes):
                matrix[i, j] = np.sum((mask1 == i) & (mask2 == j))
        
        # Calculate statistics
        total_pixels = mask1.size
        changed_pixels = np.sum(mask1 != mask2)
        change_percentage = (changed_pixels / total_pixels) * 100
        
        # Identify major transitions
        transitions = []
        for i in range(n_classes):
            for j in range(n_classes):
                if i != j and matrix[i, j] > 0:
                    from_class = self.config.class_names[i]
                    to_class = self.config.class_names[j]
                    percentage = (matrix[i, j] / total_pixels) * 100
                    transitions.append({
                        'from': from_class,
                        'to': to_class,
                        'pixels': int(matrix[i, j]),
                        'percentage': round(percentage, 2)
                    })
        
        # Sort by magnitude
        transitions.sort(key=lambda x: x['percentage'], reverse=True)
        
        return {
            'change_matrix': matrix.tolist(),
            'change_percentage': round(change_percentage, 2),
            'changed_pixels': int(changed_pixels),
            'total_pixels': int(total_pixels),
            'major_transitions': transitions[:10],  # Top 10 transitions
            'net_change': self._calculate_net_change(matrix)
        }
    
    def _calculate_net_change(self, matrix: np.ndarray) -> Dict:
        """Calculate net gain/loss for each class."""
        net_changes = {}
        n_classes = len(self.config.class_names)
        
        for i in range(n_classes):
            loss = np.sum(matrix[i, :]) - matrix[i, i]
            gain = np.sum(matrix[:, i]) - matrix[i, i]
            net = gain - loss
            net_changes[self.config.class_names[i]] = {
                'gain': int(gain),
                'loss': int(loss),
                'net': int(net)
            }
        
        return net_changes
    
    def compute_change_intensity(self, masks: List[np.ndarray], years: List[int]) -> Dict:
        """Calculate rate of change metrics over time."""
        if len(masks) < 2:
            return {}
        
        changes = []
        change_rates = []
        
        for i in range(len(masks)-1):
            change_pixels = np.sum(masks[i] != masks[i+1])
            total_pixels = masks[i].size
            change_percentage = (change_pixels / total_pixels) * 100
            years_diff = years[i+1] - years[i]
            
            changes.append(change_percentage)
            if years_diff > 0:
                change_rates.append(change_percentage / years_diff)
        
        # Calculate statistics
        if changes:
            slope, intercept = np.polyfit(range(len(changes)), changes, 1)
            
            return {
                "mean_change_rate": np.mean(changes) if changes else 0,
                "max_change_rate": np.max(changes) if changes else 0,
                "annual_change_rate": np.mean(change_rates) if change_rates else 0,
                "trend_slope": slope,
                "trend": "increasing" if slope > 0 else "decreasing" if slope < 0 else "stable",
                "change_periods": [
                    {
                        'from_year': years[i],
                        'to_year': years[i+1],
                        'change_percentage': round(changes[i], 2)
                    }
                    for i in range(len(changes))
                ]
            }
        
        return {}

class UHIAnalysis:
    """Urban Heat Island analysis."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    def analyze_uhi_effect(self, land_cover_mask: np.ndarray, 
                          lst_data: Optional[np.ndarray] = None,
                          lat: float = None,
                          lon: float = None,
                          year: int = None,
                          season: str = None) -> Dict:
        """Analyze relationship between land cover and surface temperature."""
        
        results = {}
        
        # If LST data is not provided, try to fetch it
        if lst_data is None and lat is not None and lon is not None:
            lst_data = self._fetch_lst_data(lat, lon, year, season)
        
        if lst_data is None or lst_data.size == 0:
            logger.warning("No LST data available for UHI analysis")
            return {"error": "No temperature data available"}
        
        # Ensure masks are aligned
        if land_cover_mask.shape != lst_data.shape:
            logger.warning(f"Shape mismatch: mask {land_cover_mask.shape}, LST {lst_data.shape}")
            # Resize LST to match mask
            lst_data = cv2.resize(lst_data, (land_cover_mask.shape[1], land_cover_mask.shape[0]))
        
        urban_class_id = [k for k, v in self.config.class_names.items() if v == "Urban Area"][0]
        urban_mask = land_cover_mask == urban_class_id
        
        if not np.any(urban_mask):
            return {"error": "No urban areas found in the region"}
        
        # Calculate urban temperature statistics
        urban_temp = lst_data[urban_mask]
        urban_stats = {
            'mean': float(np.nanmean(urban_temp)),
            'max': float(np.nanmax(urban_temp)),
            'min': float(np.nanmin(urban_temp)),
            'std': float(np.nanstd(urban_temp))
        }
        
        # Identify rural classes
        rural_classes = ["Agricultural Land", "Trees", "Grasses & Bushes"]
        rural_class_ids = [k for k, v in self.config.class_names.items() if v in rural_classes]
        
        if not rural_class_ids:
            return {"error": "No rural classes defined"}
        
        # Create rural mask
        rural_mask = np.isin(land_cover_mask, rural_class_ids)
        
        if not np.any(rural_mask):
            return {"error": "No rural areas found in the region"}
        
        # Calculate rural temperature statistics
        rural_temp = lst_data[rural_mask]
        rural_stats = {
            'mean': float(np.nanmean(rural_temp)),
            'max': float(np.nanmax(rural_temp)),
            'min': float(np.nanmin(rural_temp)),
            'std': float(np.nanstd(rural_temp))
        }
        
        # Calculate UHI intensity
        if not np.isnan(urban_stats['mean']) and not np.isnan(rural_stats['mean']):
            uhi_intensity = urban_stats['mean'] - rural_stats['mean']
            uhi_percentage = (uhi_intensity / rural_stats['mean']) * 100 if rural_stats['mean'] != 0 else 0
            
            results = {
                'urban_temperature': urban_stats,
                'rural_temperature': rural_stats,
                'uhi_intensity': {
                    'absolute': round(uhi_intensity, 2),
                    'percentage': round(uhi_percentage, 2),
                    'interpretation': self._interpret_uhi_intensity(uhi_intensity)
                },
                'spatial_distribution': self._analyze_spatial_pattern(urban_mask, lst_data)
            }
        
        return results
    
    def _interpret_uhi_intensity(self, intensity: float) -> str:
        """Interpret UHI intensity value."""
        if intensity <= 1:
            return "Weak UHI effect"
        elif 1 < intensity <= 3:
            return "Moderate UHI effect"
        elif 3 < intensity <= 5:
            return "Strong UHI effect"
        else:
            return "Very strong UHI effect"
    
    def _analyze_spatial_pattern(self, urban_mask: np.ndarray, lst_data: np.ndarray) -> Dict:
        """Analyze spatial pattern of UHI."""
        from scipy import ndimage
        
        # Calculate distance from urban centers
        distance_map = ndimage.distance_transform_edt(~urban_mask)
        
        # Analyze temperature gradient
        gradient_bins = [0, 100, 500, 1000, 5000]  # meters
        gradient_stats = []
        
        for i in range(len(gradient_bins)-1):
            mask_bin = (distance_map >= gradient_bins[i]) & (distance_map < gradient_bins[i+1])
            if np.any(mask_bin):
                temp_in_bin = lst_data[mask_bin]
                gradient_stats.append({
                    'distance_range': f"{gradient_bins[i]}-{gradient_bins[i+1]}m",
                    'mean_temperature': float(np.nanmean(temp_in_bin)),
                    'temperature_gradient': 0  # Will be calculated
                })
        
        return {
            'temperature_gradient': gradient_stats,
            'urban_core_temperature': float(np.nanmean(lst_data[urban_mask])) if np.any(urban_mask) else 0
        }
    
    def _fetch_lst_data(self, lat: float, lon: float, year: int, season: str) -> Optional[np.ndarray]:
        """Fetch LST data for UHI analysis."""
        # This would integrate with the existing LST fetching logic
        # For now, return None and rely on external data
        return None

class CarbonSequestration:
    """Estimate carbon sequestration based on land cover."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    def estimate_carbon(self, area_df: pd.DataFrame, pixel_area_km2: float = None) -> pd.DataFrame:
        """Calculate carbon sequestration potential."""
        result = area_df.copy()
        
        for idx, row in result.iterrows():
            total_carbon = 0
            total_co2_eq = 0
            
            for class_name, coeff in self.config.carbon_coefficients.items():
                area_col = f"{class_name.replace(' ', '_')}_Area"
                if area_col in row:
                    # Convert percentage to area in km²
                    if pixel_area_km2:
                        # If we have pixel area, calculate absolute area
                        total_area_km2 = row['Total_Area']
                        percentage = row[area_col]
                        area_km2 = total_area_km2 * (percentage / 100)
                    else:
                        # Assume percentage represents area percentage
                        area_km2 = row[area_col]  # Already in km² or percentage?
                    
                    area_ha = area_km2 * 100  # Convert km² to ha
                    carbon_tons = area_ha * coeff
                    co2_eq_tons = carbon_tons * 3.67  # CO2 equivalent
                    
                    total_carbon += carbon_tons
                    total_co2_eq += co2_eq_tons
                    
                    # Add per-class columns
                    result.at[idx, f'{class_name.replace(" ", "_")}_Carbon_tons'] = round(carbon_tons, 2)
                    result.at[idx, f'{class_name.replace(" ", "_")}_CO2_eq_tons'] = round(co2_eq_tons, 2)
            
            result.at[idx, 'total_carbon_tons'] = round(total_carbon, 2)
            result.at[idx, 'total_co2_eq_tons'] = round(total_co2_eq, 2)
            
            # Calculate sequestration rate if multiple years
            if 'year' in result.columns and idx > 0:
                prev_row = result.iloc[idx-1]
                if prev_row['year'] < row['year']:
                    years_diff = row['year'] - prev_row['year']
                    carbon_diff = total_carbon - prev_row['total_carbon_tons']
                    result.at[idx, 'annual_carbon_change_tons'] = round(carbon_diff / years_diff, 2)
        
        return result
    
    def generate_carbon_report(self, carbon_df: pd.DataFrame) -> Dict:
        """Generate carbon sequestration report."""
        if 'year' not in carbon_df.columns:
            return {"error": "Year column required for carbon report"}
        
        report = {
            'summary': {},
            'annual_changes': [],
            'recommendations': []
        }
        
        # Calculate summary statistics
        years = sorted(carbon_df['year'].unique())
        if len(years) >= 2:
            first_year = carbon_df[carbon_df['year'] == years[0]]
            last_year = carbon_df[carbon_df['year'] == years[-1]]
            
            if not first_year.empty and not last_year.empty:
                first_carbon = first_year['total_carbon_tons'].iloc[0]
                last_carbon = last_year['total_carbon_tons'].iloc[0]
                total_change = last_carbon - first_carbon
                annual_change = total_change / (years[-1] - years[0])
                
                report['summary'] = {
                    'total_carbon_sequestered': round(total_change, 2),
                    'annual_sequestration_rate': round(annual_change, 2),
                    'percent_change': round((total_change / first_carbon) * 100, 2) if first_carbon > 0 else 0,
                    'co2_equivalent_offset': round(total_change * 3.67, 2)
                }
        
        # Calculate annual changes
        for year in years:
            year_data = carbon_df[carbon_df['year'] == year]
            if not year_data.empty:
                report['annual_changes'].append({
                    'year': int(year),
                    'total_carbon_tons': float(year_data['total_carbon_tons'].iloc[0]),
                    'main_contributors': self._get_main_contributors(year_data.iloc[0])
                })
        
        # Generate recommendations
        report['recommendations'] = self._generate_carbon_recommendations(carbon_df)
        
        return report
    
    def _get_main_contributors(self, row: pd.Series) -> List[Dict]:
        """Get main carbon contributing classes."""
        contributors = []
        for class_name in self.config.carbon_coefficients.keys():
            carbon_col = f"{class_name.replace(' ', '_')}_Carbon_tons"
            if carbon_col in row:
                contributors.append({
                    'class': class_name,
                    'carbon_tons': float(row[carbon_col]),
                    'percentage': float((row[carbon_col] / row['total_carbon_tons']) * 100) if row['total_carbon_tons'] > 0 else 0
                })
        
        # Sort by contribution
        contributors.sort(key=lambda x: x['carbon_tons'], reverse=True)
        return contributors[:3]  # Top 3 contributors
    
    def _generate_carbon_recommendations(self, carbon_df: pd.DataFrame) -> List[str]:
        """Generate carbon sequestration recommendations."""
        recommendations = []
        
        # Check for decreasing carbon stock
        if 'annual_carbon_change_tons' in carbon_df.columns:
            last_change = carbon_df['annual_carbon_change_tons'].iloc[-1]
            if last_change < 0:
                recommendations.append(
                    "Carbon stock is decreasing. Consider implementing reforestation "
                    "and sustainable land management practices."
                )
        
        # Check urban vs green space ratio
        if 'Urban_Area_Carbon_tons' in carbon_df.columns and 'Trees_Carbon_tons' in carbon_df.columns:
            last_row = carbon_df.iloc[-1]
            urban_carbon = last_row['Urban_Area_Carbon_tons']
            tree_carbon = last_row['Trees_Carbon_tons']
            
            if urban_carbon > tree_carbon * 2:  # Urban carbon storage is more than double tree carbon
                recommendations.append(
                    "Urban areas dominate carbon storage. Consider increasing urban "
                    "greenery and implementing green infrastructure."
                )
        
        # General recommendations
        recommendations.extend([
            "Increase tree cover through afforestation and reforestation programs.",
            "Implement sustainable agricultural practices to enhance soil carbon sequestration.",
            "Protect and restore wetlands and natural grasslands for carbon storage.",
            "Promote urban forestry and green roofs to enhance urban carbon sequestration."
        ])
        
        return recommendations

class SpatialMetrics:
    """Calculate spatial pattern metrics for land cover."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    def calculate_spatial_metrics(self, mask: np.ndarray, transform: dict) -> Dict:
        """Calculate landscape pattern metrics."""
        
        if transform is None:
            return {"error": "Transform metadata not available for spatial metrics"}
        
        metrics = {'classes': {}, 'landscape': {}}
        
        try:
            pixel_area_m2 = abs(transform[0] * transform[4]) if isinstance(transform, tuple) else abs(transform.a * transform.e)
        except:
            # Default pixel area if transform cannot be parsed
            pixel_area_m2 = 100  # Default 10m x 10m pixel
        
        # Landscape-level metrics
        total_area_m2 = mask.size * pixel_area_m2
        metrics['landscape']['total_area_ha'] = total_area_m2 / 10000
        
        # Class-level metrics
        for class_id, class_name in self.config.class_names.items():
            binary_mask = (mask == class_id).astype(np.uint8)
            
            if np.any(binary_mask):
                class_metrics = self._calculate_class_metrics(binary_mask, pixel_area_m2, class_name)
                metrics['classes'][class_name] = class_metrics
        
        # Landscape diversity metrics
        metrics['landscape'].update(self._calculate_diversity_metrics(mask))
        
        # Fragmentation index
        metrics['landscape']['fragmentation_index'] = self._calculate_fragmentation_index(metrics['classes'])
        
        return metrics
    
    def _calculate_class_metrics(self, binary_mask: np.ndarray, pixel_area_m2: float, class_name: str) -> Dict:
        """Calculate metrics for a single class."""
        
        # Label connected components
        labeled, num_patches = measure.label(binary_mask, connectivity=2, return_num=True)
        
        if num_patches == 0:
            return {
                'area_ha': 0,
                'number_of_patches': 0,
                'patch_density': 0,
                'mean_patch_size_ha': 0,
                'max_patch_size_ha': 0,
                'edge_density': 0
            }
        
        regions = measure.regionprops(labeled)
        patch_areas = [r.area * pixel_area_m2 / 10000 for r in regions]  # Convert to ha
        
        # Calculate edge pixels
        kernel = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=np.uint8)
        edges = cv2.filter2D(binary_mask, -1, kernel)
        edge_pixels = np.sum((edges > 0) & (binary_mask == 1))
        
        total_pixels = binary_mask.size
        class_area_ha = np.sum(patch_areas)
        
        return {
            'area_ha': round(class_area_ha, 2),
            'number_of_patches': num_patches,
            'patch_density': round(num_patches / class_area_ha, 2) if class_area_ha > 0 else 0,
            'mean_patch_size_ha': round(np.mean(patch_areas), 2),
            'max_patch_size_ha': round(np.max(patch_areas), 2),
            'edge_density': round((edge_pixels / total_pixels) * 100, 2),
            'largest_patch_index': round((np.max(patch_areas) / class_area_ha) * 100, 2) if class_area_ha > 0 else 0
        }
    
    def _calculate_diversity_metrics(self, mask: np.ndarray) -> Dict:
        """Calculate landscape diversity metrics."""
        
        # Shannon's diversity index
        class_counts = []
        for class_id in range(len(self.config.class_names)):
            count = np.sum(mask == class_id)
            if count > 0:
                proportion = count / mask.size
                class_counts.append(proportion)
        
        shannon = 0
        for p in class_counts:
            shannon -= p * math.log(p) if p > 0 else 0
        
        # Simpson's diversity index
        simpson = 1 - sum(p**2 for p in class_counts)
        
        # Evenness
        max_shannon = math.log(len(class_counts)) if class_counts else 0
        evenness = shannon / max_shannon if max_shannon > 0 else 0
        
        return {
            'shannon_diversity_index': round(shannon, 3),
            'simpson_diversity_index': round(simpson, 3),
            'evenness_index': round(evenness, 3),
            'number_of_classes': len(class_counts)
        }
    
    def _calculate_fragmentation_index(self, class_metrics: Dict) -> float:
        """Calculate overall landscape fragmentation index."""
        
        if not class_metrics:
            return 0
        
        total_patches = sum(m['number_of_patches'] for m in class_metrics.values())
        total_area = sum(m['area_ha'] for m in class_metrics.values())
        
        if total_area == 0:
            return 0
        
        # Fragmentation index: patches per 100 ha
        fragmentation = (total_patches / total_area) * 100
        return round(fragmentation, 2)

class AnomalyDetection:
    """Detect unusual land cover patterns."""
    
    def __init__(self, config: PipelineConfig, threshold: float = 2.5):
        self.config = config
        self.threshold = threshold
    
    def detect_anomalies(self, historical_masks: List[np.ndarray], 
                        current_mask: np.ndarray,
                        years: List[int]) -> Dict:
        """Detect statistically significant changes."""
        
        if len(historical_masks) < 3:  # Need enough historical data
            return {"error": "Insufficient historical data for anomaly detection"}
        
        anomalies = {
            'detected_anomalies': [],
            'summary': {},
            'threshold': self.threshold
        }
        
        # Calculate historical statistics for each class
        historical_stats = {}
        for class_id, class_name in self.config.class_names.items():
            percentages = []
            for mask in historical_masks:
                percentage = np.sum(mask == class_id) / mask.size * 100
                percentages.append(percentage)
            
            if percentages:
                historical_stats[class_name] = {
                    'mean': np.mean(percentages),
                    'std': np.std(percentages),
                    'min': np.min(percentages),
                    'max': np.max(percentages),
                    'trend': self._calculate_trend(percentages, years[:len(historical_masks)])
                }
        
        # Detect anomalies in current mask
        for class_id, class_name in self.config.class_names.items():
            current_percentage = np.sum(current_mask == class_id) / current_mask.size * 100
            
            if class_name in historical_stats:
                stats = historical_stats[class_name]
                
                if stats['std'] > 0:
                    z_score = abs(current_percentage - stats['mean']) / stats['std']
                    
                    if z_score > self.threshold:
                        deviation = current_percentage - stats['mean']
                        
                        anomaly = {
                            'class': class_name,
                            'current_percentage': round(current_percentage, 2),
                            'historical_mean': round(stats['mean'], 2),
                            'z_score': round(z_score, 2),
                            'deviation': round(deviation, 2),
                            'direction': 'increase' if deviation > 0 else 'decrease',
                            'significance': self._get_significance_level(z_score),
                            'potential_causes': self._suggest_causes(class_name, deviation)
                        }
                        
                        anomalies['detected_anomalies'].append(anomaly)
        
        # Sort by significance
        anomalies['detected_anomalies'].sort(key=lambda x: x['z_score'], reverse=True)
        
        # Generate summary
        anomalies['summary'] = {
            'total_anomalies': len(anomalies['detected_anomalies']),
            'most_significant': anomalies['detected_anomalies'][0] if anomalies['detected_anomalies'] else None,
            'affected_classes': [a['class'] for a in anomalies['detected_anomalies']]
        }
        
        return anomalies
    
    def _calculate_trend(self, values: List[float], years: List[int]) -> Dict:
        """Calculate trend of values over years."""
        # Check for sufficient data and variance in x-values (years)
        if len(values) < 2 or len(set(years)) < 2:
            return {
                'slope': 0, 
                'r_squared': 0, 
                'p_value': 1, 
                'direction': 'stable'
            }
        
        try:
            slope, intercept, r_value, p_value, std_err = linregress(years, values)
        except ValueError:
            # Fallback for any other regression errors (e.g., identical x values if set check misses something)
            return {
                'slope': 0, 
                'r_squared': 0, 
                'p_value': 1, 
                'direction': 'stable'
            }
        
        return {
            'slope': round(slope, 3),
            'r_squared': round(r_value**2, 3),
            'p_value': round(p_value, 3),
            'direction': 'increasing' if slope > 0 else 'decreasing' if slope < 0 else 'stable'
        }
    
    def _get_significance_level(self, z_score: float) -> str:
        """Get significance level based on z-score."""
        if z_score >= 3:
            return "Very High"
        elif z_score >= 2.5:
            return "High"
        elif z_score >= 2:
            return "Moderate"
        else:
            return "Low"
    
    def _suggest_causes(self, class_name: str, deviation: float) -> List[str]:
        """Suggest potential causes for anomalies."""
        causes = []
        
        if class_name == "Urban Area" and deviation > 0:
            causes.extend([
                "Rapid urbanization or city expansion",
                "Industrial development",
                "Infrastructure projects"
            ])
        elif class_name == "Trees" and deviation < 0:
            causes.extend([
                "Deforestation for agriculture or development",
                "Forest fires",
                "Disease or pest infestation"
            ])
        elif class_name == "Water" and deviation < 0:
            causes.extend([
                "Drought conditions",
                "Water extraction for agriculture",
                "Climate change impacts"
            ])
        elif class_name == "Agricultural Land" and deviation > 0:
            causes.extend([
                "Agricultural expansion",
                "Conversion from natural vegetation",
                "Government agricultural policies"
            ])
        
        if not causes:
            causes.append("Natural variability or measurement error")
        
        return causes

class ValidationModule:
    """Validate model predictions against ground truth."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    def calculate_metrics(self, prediction: np.ndarray, ground_truth: np.ndarray) -> Dict:
        """Calculate accuracy metrics."""
        
        # Flatten arrays
        y_true = ground_truth.flatten()
        y_pred = prediction.flatten()
        
        # Remove background class from evaluation if desired
        mask = y_true != 0  # Exclude background
        y_true_eval = y_true[mask]
        y_pred_eval = y_pred[mask]
        
        if len(y_true_eval) == 0:
            return {"error": "No valid ground truth pixels for evaluation"}
        
        # Calculate confusion matrix
        cm = confusion_matrix(y_true_eval, y_pred_eval, 
                             labels=list(self.config.class_names.keys())[1:])  # Exclude background
        
        # Calculate metrics
        class_report = classification_report(
            y_true_eval, y_pred_eval,
            target_names=list(self.config.class_names.values())[1:],  # Exclude background
            output_dict=True,
            zero_division=0
        )
        
        # Overall accuracy
        overall_accuracy = np.trace(cm) / np.sum(cm) if np.sum(cm) > 0 else 0
        
        # Kappa coefficient
        total = np.sum(cm)
        po = overall_accuracy
        pe = np.sum(np.sum(cm, axis=0) * np.sum(cm, axis=1)) / (total ** 2) if total > 0 else 0
        kappa = (po - pe) / (1 - pe) if pe < 1 else 0
        
        # Per-class accuracy
        class_accuracy = {}
        for i, class_name in enumerate(list(self.config.class_names.values())[1:]):
            if i < cm.shape[0]:
                tp = cm[i, i]
                total_class = np.sum(cm[i, :])
                class_accuracy[class_name] = tp / total_class if total_class > 0 else 0
        
        return {
            "overall_accuracy": round(overall_accuracy, 4),
            "kappa_coefficient": round(kappa, 4),
            "class_accuracy": class_accuracy,
            "class_metrics": class_report,
            "confusion_matrix": cm.tolist(),
            "confusion_matrix_classes": list(self.config.class_names.values())[1:]
        }
    
    def generate_validation_report(self, metrics: Dict, save_path: Optional[str] = None) -> Dict:
        """Generate comprehensive validation report."""
        
        report = {
            "validation_summary": {
                "overall_accuracy": metrics["overall_accuracy"],
                "kappa_coefficient": metrics["kappa_coefficient"],
                "interpretation": self._interpret_kappa(metrics["kappa_coefficient"])
            },
            "class_performance": {},
            "recommendations": []
        }
        
        # Add class performance
        for class_name, accuracy in metrics["class_accuracy"].items():
            report["class_performance"][class_name] = {
                "accuracy": round(accuracy, 4),
                "interpretation": self._interpret_accuracy(accuracy)
            }
        
        # Generate recommendations
        if metrics["overall_accuracy"] < 0.7:
            report["recommendations"].append(
                "Overall accuracy is below 70%. Consider improving training data quality "
                "or adjusting model parameters."
            )
        
        if metrics["kappa_coefficient"] < 0.6:
            report["recommendations"].append(
                "Kappa coefficient indicates moderate agreement. Consider addressing "
                "class imbalance or improving model calibration."
            )
        
        # Identify poorly performing classes
        poor_classes = [c for c, acc in metrics["class_accuracy"].items() if acc < 0.6]
        if poor_classes:
            report["recommendations"].append(
                f"Classes with low accuracy ({', '.join(poor_classes)}): "
                "Consider collecting more training samples for these classes."
            )
        
        # Save report if path provided
        if save_path:
            with open(save_path, 'w') as f:
                json.dump(report, f, indent=2)
        
        return report
    
    def _interpret_kappa(self, kappa: float) -> str:
        """Interpret Kappa coefficient."""
        if kappa < 0:
            return "No agreement"
        elif 0 <= kappa <= 0.20:
            return "Slight agreement"
        elif 0.20 < kappa <= 0.40:
            return "Fair agreement"
        elif 0.40 < kappa <= 0.60:
            return "Moderate agreement"
        elif 0.60 < kappa <= 0.80:
            return "Substantial agreement"
        else:
            return "Almost perfect agreement"
    
    def _interpret_accuracy(self, accuracy: float) -> str:
        """Interpret accuracy value."""
        if accuracy >= 0.9:
            return "Excellent"
        elif accuracy >= 0.8:
            return "Good"
        elif accuracy >= 0.7:
            return "Acceptable"
        elif accuracy >= 0.6:
            return "Moderate"
        else:
            return "Poor"

class DashboardGenerator:
    """Generate interactive visualizations and dashboards."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    def create_interactive_map(self, mask: np.ndarray, meta: dict, 
                              center_lat: float = None, 
                              center_lon: float = None) -> folium.Map:
        """Create interactive Folium map with land cover visualization."""
        
        # Determine center if not provided
        if center_lat is None or center_lon is None:
            try:
                bounds = array_bounds(meta['height'], meta['width'], meta['transform'])
                center_lon = (bounds[0] + bounds[2]) / 2
                center_lat = (bounds[1] + bounds[3]) / 2
            except:
                center_lat, center_lon = 31.5497, 74.3436  # Default to Lahore
        
        # Create base map
        m = folium.Map(location=[center_lat, center_lon], 
                      zoom_start=12,
                      tiles='CartoDB positron')
        
        # Convert mask to colored image
        colored_mask = self._mask_to_rgb(mask)
        
        try:
            # Create overlay
            bounds = array_bounds(mask.shape[0], mask.shape[1], meta['transform'])
            image_overlay = folium.raster_layers.ImageOverlay(
                colored_mask,
                bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
                opacity=0.7,
                name='Land Cover'
            )
            image_overlay.add_to(m)
        except:
            # If bounds calculation fails, use default bounds
            bounds = [[center_lat - 0.1, center_lon - 0.1], 
                     [center_lat + 0.1, center_lon + 0.1]]
            image_overlay = folium.raster_layers.ImageOverlay(
                colored_mask,
                bounds=bounds,
                opacity=0.7,
                name='Land Cover'
            )
            image_overlay.add_to(m)
        
        # Add layer control
        folium.LayerControl().add_to(m)
        
        # Add legend
        self._add_legend(m)
        
        # Add measurement tools
        plugins.MeasureControl(position='topleft').add_to(m)
        
        # Add fullscreen button
        plugins.Fullscreen(position='topright').add_to(m)
        
        return m
    
    def _mask_to_rgb(self, mask: np.ndarray) -> np.ndarray:
        """Convert mask to RGB image using class colors."""
        rgb = np.zeros((mask.shape[0], mask.shape[1], 3), dtype=np.uint8)
        
        colors = [
            [0, 0, 0],        # Background - Black
            [60, 176, 67],    # Agricultural Land - Parrot
            [255, 255, 0],    # Grasses & Bushes - Yellow
            [255, 0, 0],      # Urban Area - Red
            [139, 69, 19],    # Soil - Brown
            [0, 0, 255],      # Water - Blue
            [0, 128, 0]       # Trees - Green
        ]
        
        for class_id, color in enumerate(colors):
            rgb[mask == class_id] = color
        
        return rgb
    
    def _add_legend(self, map_obj: folium.Map) -> None:
        """Add legend to map."""
        
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 50px; left: 50px; width: 150px; 
                    border:2px solid grey; z-index:9999; font-size:14px;
                    background-color:white;
                    opacity: 0.8;">
        <p style="margin: 10px;"><b>Land Cover Classes</b></p>
        '''
        
        colors = [
            ('Background', '#000000'),
            ('Agricultural Land', '#3CB043'),
            ('Grasses & Bushes', '#FFFF00'),
            ('Urban Area', '#FF0000'),
            ('Soil', '#8B4513'),
            ('Water', '#0000FF'),
            ('Trees', '#008000')
        ]
        
        for name, color in colors:
            legend_html += f'''
            <p style="margin: 5px 10px;">
                <i style="background:{color}; width:20px; height:20px; 
                         display:inline-block; margin-right:5px;"></i>
                {name}
            </p>
            '''
        
        legend_html += '</div>'
        
        map_obj.get_root().html.add_child(folium.Element(legend_html))
    
    def create_interactive_charts(self, area_df: pd.DataFrame, 
                                 temp_df: pd.DataFrame) -> Dict[str, str]:
        """Create interactive Plotly charts."""
        
        charts = {}
        
        # 1. Area Trend Chart
        if not area_df.empty:
            fig_area = self._create_area_trend_chart(area_df)
            charts['area_trend'] = fig_area.to_html(full_html=False, include_plotlyjs='cdn')
        
        # 2. Temperature Trend Chart
        if not temp_df.empty:
            fig_temp = self._create_temperature_chart(temp_df)
            charts['temperature_trend'] = fig_temp.to_html(full_html=False, include_plotlyjs='cdn')
        
        # 3. Land Cover Composition Chart
        if not area_df.empty and 'season' in area_df.columns:
            fig_composition = self._create_composition_chart(area_df)
            charts['land_cover_composition'] = fig_composition.to_html(full_html=False, include_plotlyjs='cdn')
        
        return charts
    
    def _create_area_trend_chart(self, area_df: pd.DataFrame) -> go.Figure:
        """Create interactive area trend chart."""
        
        # Prepare data
        melted = area_df.melt(id_vars=['year', 'season'], 
                             value_vars=['Agricultural_Land_Area', 'Grasses_and_Bushes_Area',
                                        'Urban_Area_Area', 'Soil_Area', 'Water_Area', 'Trees_Area'],
                             var_name='Class', value_name='Percentage')
        
        melted['Class'] = melted['Class'].str.replace('_Area', '').str.replace('_', ' ')
        
        fig = px.line(melted, x='year', y='Percentage', color='Class',
                     facet_col='season', facet_col_wrap=2,
                     title='Land Cover Area Trends',
                     labels={'Percentage': 'Area (%)', 'year': 'Year'},
                     template='plotly_white')
        
        fig.update_layout(height=800, showlegend=True)
        return fig
    
    def _create_temperature_chart(self, temp_df: pd.DataFrame) -> go.Figure:
        """Create interactive temperature chart."""
        
        fig = make_subplots(rows=2, cols=2, 
                           subplot_titles=['Aqua Day', 'Aqua Night', 'Terra Day', 'Terra Night'],
                           shared_xaxes=True, shared_yaxes=True)
        
        sensors = [('Aqua', 'Day'), ('Aqua', 'Night'), ('Terra', 'Day'), ('Terra', 'Night')]
        
        for idx, (satellite, time_of_day) in enumerate(sensors, 1):
            sensor_df = temp_df[(temp_df['sensor'] == f'{satellite}_{time_of_day}') & 
                               (temp_df['season'] == 'average')]
            
            if not sensor_df.empty:
                row = (idx - 1) // 2 + 1
                col = (idx - 1) % 2 + 1
                
                fig.add_trace(
                    go.Scatter(x=sensor_df['year'], y=sensor_df['Mean_T'],
                              mode='lines+markers', name='Mean',
                              line=dict(color='green')),
                    row=row, col=col
                )
                
                fig.add_trace(
                    go.Scatter(x=sensor_df['year'], y=sensor_df['Max_T'],
                              mode='lines', name='Max',
                              line=dict(color='red', dash='dash')),
                    row=row, col=col
                )
                
                fig.add_trace(
                    go.Scatter(x=sensor_df['year'], y=sensor_df['Min_T'],
                              mode='lines', name='Min',
                              line=dict(color='blue', dash='dash')),
                    row=row, col=col
                )
        
        fig.update_layout(height=600, showlegend=True,
                         title_text='Temperature Trends by Sensor')
        fig.update_xaxes(title_text='Year')
        fig.update_yaxes(title_text='Temperature (°C)')
        
        return fig
    
    def _create_composition_chart(self, area_df: pd.DataFrame) -> go.Figure:
        """Create land cover composition chart."""
        
        # Get latest year's data
        latest_year = area_df['year'].max()
        latest_data = area_df[area_df['year'] == latest_year]
        
        if latest_data.empty:
            return go.Figure()
        
        # Prepare data for pie chart
        classes = ['Agricultural_Land_Area', 'Grasses_and_Bushes_Area',
                  'Urban_Area_Area', 'Soil_Area', 'Water_Area', 'Trees_Area']
        class_names = [c.replace('_Area', '').replace('_', ' ') for c in classes]
        
        values = []
        for c in classes:
            if c in latest_data.columns:
                values.append(latest_data[c].iloc[0])
        
        fig = go.Figure(data=[go.Pie(labels=class_names, values=values,
                                    hole=0.3, textinfo='label+percent')])
        
        fig.update_layout(title_text=f'Land Cover Composition ({latest_year})',
                         showlegend=True)
        
        return fig

class ModelExecution:
    """Main class for executing land cover segmentation and analysis pipeline."""
    
    def __init__(self, model_path: str, input_tif: str = None, 
                 coordinates: List[Tuple[float, float]] = None, 
                 purpose: str = None, config: PipelineConfig = None,
                 years: List[int] = None):
        """
        Initialize the model execution pipeline.
        
        Args:
            model_path: Path to the trained model weights
            input_tif: Path to local TIFF file (optional)
            coordinates: List of (lat, lon) coordinates for AOI (optional)
            purpose: "current" for single year or None for multi-year analysis
            config: Pipeline configuration object
        """
        self.input_tif = input_tif
        self.coordinates = coordinates
        self.purpose = purpose
        self.years = years
        self.shpfile = None
        self.MODEL_PATH = model_path
        self.base_dir = None
        
        # Initialize configuration
        self.config = config or PipelineConfig()
        
        # Set torch threads
        torch.set_num_threads(self.config.num_threads)
        
        # Initialize data structures
        self.temperature = pd.DataFrame(columns=['year', 'season', 'sensor', 'Mean_T', 'Max_T', 'Min_T'])
        self.area_dict = pd.DataFrame(columns=['year', 'season', 'Total_Area', 'Background_Area', 
                                               'Agricultural_Land_Area', 'Grasses_and_Bushes_Area', 
                                               'Urban_Area_Area', 'Soil_Area', 'Water_Area', 'Trees_Area'])
        
        # Initialize analysis modules
        self.change_detector = ChangeDetection(self.config)
        self.uhi_analyzer = UHIAnalysis(self.config)
        self.carbon_estimator = CarbonSequestration(self.config)
        self.spatial_metrics = SpatialMetrics(self.config)
        self.anomaly_detector = AnomalyDetection(self.config, 
                                                threshold=self.config.anomaly_detection_threshold)
        self.validator = ValidationModule(self.config)
        self.dashboard = DashboardGenerator(self.config)
        
        # Class colors for visualization
        self.CLASS_COLORS = np.array([
            [0, 0, 0],        # Background - Black
            [60, 176, 67],    # Agricultural Land - Parrot
            [255, 255, 0],    # Grasses & Bushes - Yellow
            [255, 0, 0],      # Urban Area - Red
            [139, 69, 19],    # Soil - Brown
            [0, 0, 255],      # Water - Blue
            [0, 128, 0]       # Trees - Green
        ], dtype=np.uint8)
        
        # Model initialized lazily
        self.model = None
        self.image = None
        self.meta = None
        self.global_percentiles = None
        
        # Store historical masks, images and metadata for analysis
        self.historical_masks = []
        self.historical_images = [] # Store original RGB images
        self.historical_metas = []  # Store metadata for each mask
        self.historical_years = []
        self.historical_seasons = []
        
        # Earth Engine initialization
        try:
            ee.Initialize(project="auspicious-env-472806-c6")
            ee.Authenticate()
            logger.info("Earth Engine initialized successfully")
        except Exception as e:
            logger.warning(f"Earth Engine initialization failed: {e}")
            logger.info("Earth Engine functions will not be available")
        
        logger.info(f"ModelExecution initialized with purpose: {purpose}")
    
    # -------------------- Model Loading --------------------
    def load_model(self) -> None:
        """Load the segmentation model with error handling."""
        if self.model is not None:
            return
        
        logger.info("Loading segmentation model...")
        start_time = time.perf_counter()
        
        try:
            self.model = smp.UnetPlusPlus(
                encoder_name="efficientnet-b5",
                encoder_weights=None,
                in_channels=4,
                classes=7,
                activation=None,
                decoder_attention_type="scse",
                decoder_channels=(256, 128, 64, 32, 16)
            ).to(self.config.device)
            
            checkpoint = torch.load(self.MODEL_PATH, map_location=self.config.device, weights_only=False)
            
            if "model_state_dict" in checkpoint:
                state_dict = checkpoint["model_state_dict"]
            else:
                state_dict = checkpoint
            
            # Handle potential key mismatches
            model_state_dict = self.model.state_dict()
            matched_state_dict = {}
            
            for k, v in state_dict.items():
                if k in model_state_dict:
                    if v.shape == model_state_dict[k].shape:
                        matched_state_dict[k] = v
                    else:
                        logger.warning(f"Shape mismatch for {k}: {v.shape} vs {model_state_dict[k].shape}")
                else:
                    # Try to match with different key naming
                    found = False
                    for mk in model_state_dict.keys():
                        if k.endswith(mk) or mk.endswith(k):
                            matched_state_dict[mk] = v
                            found = True
                            break
                    if not found:
                        logger.warning(f"Key {k} not found in model")
            
            self.model.load_state_dict(matched_state_dict, strict=False)
            self.model.eval()
            
            logger.info(f"[OK] Model loaded successfully in {time.perf_counter() - start_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    # -------------------- Shapefile Creation --------------------
    def set_shapefile(self, coords: List[Tuple[float, float]], 
                     output_dir: str = "data/shapefiles", 
                     name: str = "polygon") -> None:
        """Create a shapefile from coordinates."""
        logger.info(f"Creating shapefile from {len(coords)} coordinates")
        
        # Convert (lat, lon) to (lon, lat) for GeoPandas
        coords_transformed = [(lon, lat) for lat, lon in coords]
        
        # Close polygon if not closed
        if coords_transformed[0] != coords_transformed[-1]:
            coords_transformed.append(coords_transformed[0])
        
        try:
            poly = Polygon(coords_transformed)
            self.shpfile = gpd.GeoDataFrame(
                {"id": [1], "name": [name]},
                geometry=[poly],
                crs="EPSG:4326"
            )
            
            # Save shapefile
            os.makedirs(output_dir, exist_ok=True)
            shp_path = os.path.join(output_dir, f"{name}.shp")
            self.shpfile.to_file(shp_path)
            
            logger.info(f"[OK] Shapefile created and saved to {shp_path}")
            
        except Exception as e:
            logger.error(f"Failed to create shapefile: {e}")
            raise
    
    # -------------------- Raster Clipping --------------------
    def clip_from_s3(self, s3_path: str):
        """Clip raster from S3 using the shapefile boundary."""
        logger.info(f"Clipping raster from S3: {s3_path}")
        start_time = time.perf_counter()
        
        try:
            with Env(AWS_REQUEST_PAYER="requester"):
                with rasterio.open(s3_path) as src:
                    # Reproject shapefile if needed
                    gdf = self.shpfile.to_crs(src.crs) if self.shpfile.crs != src.crs else self.shpfile
                    
                    # Check intersection
                    if not gdf.geometry.intersects(box(*src.bounds)).any():
                        logger.warning("AOI is outside raster extent")
                        return None, None
                    
                    # Clip raster
                    clipped, transform = mask(
                        src, 
                        [mapping(g) for g in gdf.geometry], 
                        crop=True,
                        all_touched=True
                    )
                    
                    # Update metadata
                    meta = src.meta.copy()
                    meta.update({
                        "height": clipped.shape[1],
                        "width": clipped.shape[2],
                        "transform": transform
                    })
            
            logger.info(f"[OK] Raster clipped in {time.perf_counter() - start_time:.2f}s")
            return clipped, meta
            
        except rasterio.errors.RasterioIOError as e:
            logger.error(f"Failed to access S3 raster {s3_path}: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error during clipping: {e}")
            return None, None
        
    
    # -------------------- Local Raster Clipping --------------------
    def clip_local_raster(self, raster_path: str):
        """Clip raster from local file system using the shapefile boundary."""
        logger.info(f"Clipping raster from local path: {raster_path}")
        start_time = time.perf_counter()
        
        if not os.path.exists(raster_path):
            logger.warning(f"File not found: {raster_path}")
            return None, None

        try:
            with rasterio.open(raster_path) as src:
                # Reproject shapefile if needed
                gdf = self.shpfile.to_crs(src.crs) if self.shpfile.crs != src.crs else self.shpfile
                
                # Check intersection
                if not gdf.geometry.intersects(box(*src.bounds)).any():
                    logger.warning("AOI is outside raster extent")
                    return None, None
                
                # Clip raster
                clipped, transform = mask(
                    src, 
                    [mapping(g) for g in gdf.geometry], 
                    crop=True,
                    all_touched=True
                )
                
                # Update metadata
                meta = src.meta.copy()
                meta.update({
                    "height": clipped.shape[1],
                    "width": clipped.shape[2],
                    "transform": transform
                })
            
            logger.info(f"[OK] Raster clipped in {time.perf_counter() - start_time:.2f}s")
            return clipped, meta
            
        except rasterio.errors.RasterioIOError as e:
            logger.error(f"Failed to access local raster {raster_path}: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error during clipping: {e}")
            return None, None

    # -------------------- Local Image Loading --------------------
    def load_local_image(self) -> None:
        """Load and preprocess local TIFF image."""
        logger.info(f"Loading local image: {self.input_tif}")
        
        try:
            with rasterio.open(self.input_tif) as src:
                # Read available bands
                img = src.read().astype(np.float32)
                
                # Robust band handling: model expects 4 channels (RGB+NIR)
                # Many user uploads will be 3 channels (RGB)
                if img.shape[0] < 4:
                    logger.info(f"Padding image with {4 - img.shape[0]} dummy channels to match model expectation")
                    padding = np.zeros((4 - img.shape[0], img.shape[1], img.shape[2]), dtype=img.dtype)
                    img = np.concatenate([img, padding], axis=0)
                elif img.shape[0] > 4:
                    logger.info(f"Slicing image to 4 channels")
                    img = img[:4]
                
                # Handle invalid values
                img = np.nan_to_num(
                    img,
                    nan=0.0,
                    posinf=0.0,
                    neginf=0.0
                )
                
                self.image = img
                self.meta = src.meta.copy()
                
                # Sanitize nodata: if input has invalid nodata for uint8 (like 4294967295), reset it
                nodata = self.meta.get('nodata')
                if nodata is not None and (nodata < 0 or nodata > 255):
                    logger.info(f"Discarding invalid nodata value {nodata} for uint8 mask")
                    self.meta['nodata'] = 0 # Use 0 (Background) as nodata/default
                
                # Update meta for 4-channel representation in memory
                self.meta.update({"count": 4})
                
                logger.info(f"[OK] Image loaded and padded: shape={img.shape}, dtype={img.dtype}")
                
        except Exception as e:
            logger.error(f"Failed to load local image: {e}")
            raise
    
    # -------------------- Percentile Calculation --------------------
    def compute_global_percentiles(self) -> None:
        """Compute global percentiles for normalization."""
        logger.info("Computing global percentiles...")
        
        self.global_percentiles = []
        for i in range(4):
            # Remove zeros for better percentile calculation
            band_data = self.image[i]
            non_zero = band_data[band_data > 0]
            
            if len(non_zero) > 0:
                p1, p99 = np.percentile(non_zero, [1, 99])
            else:
                p1, p99 = np.percentile(band_data, [1, 99])
            
            self.global_percentiles.append((p1, p99))
            
            logger.debug(f"Band {i}: p1={p1:.2f}, p99={p99:.2f}")
        
        logger.info("[OK] Global percentiles computed")
    
    # -------------------- Tile Generation --------------------
    def tile_generator(self):
        """Generator for image tiles."""
        _, H, W = self.image.shape
        
        for y in range(0, H, self.config.tile_size):
            for x in range(0, W, self.config.tile_size):
                tile = np.zeros((4, self.config.tile_size, self.config.tile_size), dtype=np.float32)
                h = min(self.config.tile_size, H - y)
                w = min(self.config.tile_size, W - x)
                
                tile[:, :h, :w] = self.image[:, y:y+h, x:x+w]
                yield tile, x, y, h, w
    
    # -------------------- Tile Prediction --------------------
    @torch.no_grad()
    def predict_tile(self, tile: np.ndarray) -> np.ndarray:
        """Predict segmentation for a single tile."""
        # Preprocess tile
        tile = np.transpose(tile, (1, 2, 0))
        
        # Normalize using global percentiles
        for i in range(4):
            if i < len(self.global_percentiles):
                p1, p99 = self.global_percentiles[i]
                if p99 > p1:  # Avoid division by zero
                    tile[:, :, i] = np.clip((tile[:, :, i] - p1) / (p99 - p1 + 1e-8), 0, 1)
                else:
                    tile[:, :, i] = 0
            else:
                tile[:, :, i] = 0
        
        # Resize to model input size
        if tile.shape[:2] != (512, 512):
            tile = cv2.resize(tile, (512, 512))
        
        # Standardize
        for i in range(4):
            std = tile[:, :, i].std()
            if std > 0:
                tile[:, :, i] = (tile[:, :, i] - tile[:, :, i].mean()) / std
        
        # Convert to tensor and predict
        tensor = torch.from_numpy(np.transpose(tile, (2, 0, 1))).unsqueeze(0).float()
        with torch.no_grad():
            pred = self.model(tensor)
        
        return pred.argmax(1)[0].cpu().numpy().astype(np.uint8)

    def _reduce_tile_seam_gaps(self, mask: np.ndarray, passes: int = 2) -> np.ndarray:
        """Fill thin zero-class seams introduced between stitched tiles."""
        if mask is None or mask.size == 0:
            return mask

        fixed = mask.copy()
        h, w = fixed.shape
        for _ in range(max(1, passes)):
            seam_pixels = np.argwhere(fixed == 0)
            if seam_pixels.size == 0:
                break

            updates = 0
            for y, x in seam_pixels:
                y0 = max(0, y - 1)
                y1 = min(h, y + 2)
                x0 = max(0, x - 1)
                x1 = min(w, x + 2)
                neigh = fixed[y0:y1, x0:x1]
                candidates = neigh[neigh > 0]
                if candidates.size == 0:
                    continue

                vals, counts = np.unique(candidates, return_counts=True)
                fixed[y, x] = vals[np.argmax(counts)]
                updates += 1

            if updates == 0:
                break
        return fixed

    def _predict_from_array(self, img_array: np.ndarray) -> np.ndarray:
        """Predict land cover from an image array using tiling."""
        logger.info(f"Predicting from array of shape {img_array.shape}")
        
        # Ensure model is loaded
        if self.model is None:
            self.load_model()
            
        # Compute percentiles for this specific array
        self.global_percentiles = []
        for i in range(min(4, img_array.shape[0])):
            band_data = img_array[i]
            non_zero = band_data[band_data > 0]
            if len(non_zero) > 0:
                p1, p99 = np.percentile(non_zero, [1, 99])
            else:
                p1, p99 = np.percentile(band_data, [1, 99])
            self.global_percentiles.append((p1, p99))

        _, H, W = img_array.shape
        final_mask = np.zeros((H, W), dtype=np.uint8)
        
        # Tile processing
        tile_size = self.config.tile_size
        for y in range(0, H, tile_size):
            for x in range(0, W, tile_size):
                h = min(tile_size, H - y)
                w = min(tile_size, W - x)
                tile = np.zeros((4, tile_size, tile_size), dtype=np.float32)
                tile[:, :h, :w] = img_array[:4, y:y+h, x:x+w]
                
                pred = self.predict_tile(tile)
                final_mask[y:y+h, x:x+w] = pred[:h, :w]
                
        return final_mask

    # -------------------- Area Calculation --------------------
    def calculate_area(self, mask_band: np.ndarray, transform: dict) -> List[float]:
        """Calculate area proportions for each land cover class."""
        logger.info("Calculating land cover areas...")
        
        # Get pixel dimensions
        if isinstance(transform, tuple):
            # Affine transform tuple
            pixel_width = abs(transform[0])
            pixel_height = abs(transform[4])
        else:
            # Rasterio transform object
            pixel_width = abs(transform.a)
            pixel_height = abs(transform.e)
            
        pixel_area = pixel_width * pixel_height  # m² per pixel
        
        total_pixels = mask_band.size
        total_area_m2 = total_pixels * pixel_area
        
        results = [total_area_m2 / 1e6]  # Convert to km²
        
        # Calculate area for each class
        for cls_id in range(7):
            cls_pixels = np.sum(mask_band == cls_id)
            cls_area_m2 = cls_pixels * pixel_area
            cls_area_km2 = cls_area_m2 / 1e6
            cls_percentage = (cls_pixels / total_pixels) * 100 if total_pixels > 0 else 0
            
            results.append(round(cls_percentage, 2))
            
            logger.debug(f"{self.config.class_names[cls_id]}: {cls_percentage:.2f}% ({cls_area_km2:.2f} km²)")
        
        logger.info("[OK] Area calculation completed")
        return results
        
    # -------------------- Center Point Extraction --------------------
    def get_center_and_buffer(self, img_array: np.ndarray, meta: dict) -> Tuple[float, float, float]:
        """Get center coordinates and buffer distance from raster."""
        try:
            bounds = array_bounds(meta['height'], meta['width'], meta['transform'])
            crs = meta['crs']
            
            footprint = box(bounds[0], bounds[1], bounds[2], bounds[3])
            centroid = footprint.centroid
            
            # Transform to WGS84
            to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            center_lon, center_lat = to_wgs84.transform(centroid.x, centroid.y)
            
            # Calculate buffer distance (maximum distance from center to edge)
            to_meters = Transformer.from_crs(crs, "EPSG:3857", always_xy=True)
            cx_m, cy_m = to_meters.transform(centroid.x, centroid.y)
            
            max_dist = 0.0
            for x, y in footprint.exterior.coords:
                xm, ym = to_meters.transform(x, y)
                dist = math.hypot(xm - cx_m, ym - cy_m)
                max_dist = max(max_dist, dist)
            
            buffer_meters = round(max_dist, 2)
            
            logger.info(f"Center: ({center_lat:.6f}, {center_lon:.6f}), Buffer: {buffer_meters}m")
            
            return center_lat, center_lon, buffer_meters
            
        except Exception as e:
            logger.error(f"Failed to calculate center and buffer: {e}")
            # Return default values
            return 31.5497, 74.3436, 5000  # Default to Lahore center
    
    # -------------------- LST Extraction --------------------
    def extract_lst(self, image: ee.Image, lst_band: str, qc_band: str, geom: ee.Geometry) -> ee.Feature:
        """Extract LST values from MODIS image."""
        qc = image.select(qc_band)
        mask = qc.bitwiseAnd(3).lte(1)  # Good or average quality
        
        lst = (
            image.select(lst_band)
            .updateMask(mask)
            .multiply(0.02)
            .subtract(273.15)  # Kelvin to Celsius
        )
        
        mean_lst = lst.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=1000,
            maxPixels=1e9,
            bestEffort=True
        )
        
        return ee.Feature(None, {
            "date": image.date().format("YYYY-MM-dd"),
            "temperature_c": mean_lst.get(lst_band)
        })
    
    def fc_to_df(self, feature_collection: ee.FeatureCollection) -> pd.DataFrame:
        """Convert Earth Engine FeatureCollection to pandas DataFrame."""
        try:
            data = feature_collection.getInfo()["features"]
            rows = []
            
            for f in data:
                props = f["properties"]
                if props["temperature_c"] is not None:
                    rows.append({
                        "date": props["date"],
                        "temperature_c": props["temperature_c"]
                    })
            
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Failed to convert FeatureCollection: {e}")
            return pd.DataFrame()
    
    # -------------------- Temperature Data Processing --------------------
    def fetch_all_lst_data(self, lat: float, lon: float, buffer_meters: float, 
                          year: int, season: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Fetch LST data for all MODIS sensors."""
        logger.info(f"Fetching LST data for {year} {season}")
        
        # Season dates
        SEASONS = {
            "spring": ("03-01", "05-31"),
            "summer": ("06-01", "08-31"),
            "autumn": ("09-01", "11-30"),
            "winter": ("12-01", "02-28")
        }
        
        MODIS_SOURCES = {
            "Aqua": {
                "collection": "MODIS/061/MYD11A1",
                "bands": {"day": "LST_Day_1km", "night": "LST_Night_1km"},
                "qc": "QC_Day"
            },
            "Terra": {
                "collection": "MODIS/061/MOD11A1",
                "bands": {"day": "LST_Day_1km", "night": "LST_Night_1km"},
                "qc": "QC_Day"
            }
        }
        
        # Handle winter dates (cross-year)
        if season == "winter":
            start_date = f"{year}-12-01"
            end_date = f"{year+1}-02-28"
        else:
            start_date = f"{year}-{SEASONS[season][0]}"
            end_date = f"{year}-{SEASONS[season][1]}"
        
        # Create geometry
        geom = ee.Geometry.Point([lon, lat]).buffer(buffer_meters)
        
        dfs = {}
        
        for satellite, cfg in MODIS_SOURCES.items():
            try:
                collection = (
                    ee.ImageCollection(cfg["collection"])
                    .filterBounds(geom)
                    .filterDate(start_date, end_date)
                )
                
                for tod, band in cfg["bands"].items():
                    fc = (
                        collection
                        .map(lambda img: self.extract_lst(img, band, cfg["qc"], geom))
                        .filter(ee.Filter.notNull(["temperature_c"]))
                    )
                    
                    df = self.fc_to_df(fc)
                    if not df.empty:
                        df["satellite"] = satellite
                        df["time_of_day"] = tod
                        dfs[f"{satellite}_{tod}"] = df
                    else:
                        logger.warning(f"No data for {satellite}_{tod}")
                        
            except Exception as e:
                logger.error(f"Failed to fetch {satellite} data: {e}")
        
        # Return DataFrames with fallback to empty ones
        return (
            dfs.get("Aqua_day", pd.DataFrame()),
            dfs.get("Aqua_night", pd.DataFrame()),
            dfs.get("Terra_day", pd.DataFrame()),
            dfs.get("Terra_night", pd.DataFrame())
        )
    
    def merge_lst_dataframes(self, *dfs: pd.DataFrame) -> List[List[float]]:
        """Merge LST data from multiple sensors and compute statistics."""
        if len(dfs) != 4:
            logger.error(f"Expected 4 DataFrames, got {len(dfs)}")
            return [[0, 0, 0]] * 4
        
        # Create copies and rename columns
        aqua_day = dfs[0][['date', 'temperature_c']].copy()
        aqua_day.rename(columns={"temperature_c": "Aqua_Day"}, inplace=True)
        
        aqua_night = dfs[1][['date', 'temperature_c']].copy()
        aqua_night.rename(columns={"temperature_c": "Aqua_Night"}, inplace=True)
        
        terra_day = dfs[2][['date', 'temperature_c']].copy()
        terra_day.rename(columns={"temperature_c": "Terra_Day"}, inplace=True)
        
        terra_night = dfs[3][['date', 'temperature_c']].copy()
        terra_night.rename(columns={"temperature_c": "Terra_Night"}, inplace=True)
        
        # Convert dates
        for df in [aqua_day, aqua_night, terra_day, terra_night]:
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
        
        # Merge all data
        merged = aqua_day.copy()
        for df, name in [(aqua_night, "Aqua_Night"), 
                         (terra_day, "Terra_Day"), 
                         (terra_night, "Terra_Night")]:
            if not df.empty and not merged.empty:
                merged = pd.merge(merged, df, on='date', how='inner', suffixes=('', f'_{name}'))
        
        # Compute statistics
        sensors = ['Aqua_Day', 'Aqua_Night', 'Terra_Day', 'Terra_Night']
        statistics = []
        
        for sensor in sensors:
            if sensor in merged.columns:
                data = merged[sensor].dropna()
                if len(data) > 0:
                    statistics.append([data.mean(), data.max(), data.min()])
                else:
                    statistics.append([0, 0, 0])
            else:
                statistics.append([0, 0, 0])
        
        return statistics
    
    # -------------------- Data Preprocessing --------------------
    def preprocess_area_data(self, area_df: pd.DataFrame) -> pd.DataFrame:
        """Preprocess area data with outlier removal and aggregation."""
        logger.info("Preprocessing area data...")
        
        # Remove outliers from Background_Area
        if 'Background_Area' in area_df.columns:
            Q1 = area_df['Background_Area'].quantile(0.25)
            Q3 = area_df['Background_Area'].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            
            filtered_df = area_df[
                (area_df['Background_Area'] >= lower_bound) & 
                (area_df['Background_Area'] <= upper_bound)
            ].copy()
        else:
            filtered_df = area_df.copy()
        
        # Add yearly averages
        yearly_avg_rows = []
        for year in filtered_df['year'].unique():
            year_data = filtered_df[filtered_df['year'] == year]
            if not year_data.empty:
                avg_values = year_data.iloc[:, 2:].mean().tolist()
                yearly_avg_rows.append([year, "average"] + avg_values)
        
        yearly_avg_df = pd.DataFrame(
            yearly_avg_rows,
            columns=filtered_df.columns
        )
        
        result_df = pd.concat([filtered_df, yearly_avg_df], ignore_index=True)
        
        # Calculate green/non-green space
        if 'Agricultural_Land_Area' in result_df.columns:
            result_df['green_space'] = (
                result_df['Agricultural_Land_Area'] + 
                result_df['Grasses_and_Bushes_Area'] + 
                result_df['Trees_Area']
            )
        
        if 'Urban_Area_Area' in result_df.columns:
            result_df['non_green_space'] = (
                result_df['Urban_Area_Area'] + 
                result_df['Soil_Area'] + 
                result_df['Water_Area']
            )
        
        logger.info("[SUCCESS] Area data preprocessed")
        return result_df
    
    def preprocess_temperature_data(self, temp_df: pd.DataFrame) -> pd.DataFrame:
        """Preprocess temperature data with yearly averages."""
        logger.info("Preprocessing temperature data...")
        
        result_df = temp_df.copy()
        
        # Add yearly averages for each sensor
        sensors = ['Aqua_Day', 'Aqua_Night', 'Terra_Day', 'Terra_Night']
        yearly_avg_rows = []
        
        for year in result_df['year'].unique():
            for sensor in sensors:
                sensor_data = result_df[
                    (result_df['year'] == year) & 
                    (result_df['sensor'] == sensor)
                ]
                
                if not sensor_data.empty:
                    avg_values = sensor_data[['Mean_T', 'Max_T', 'Min_T']].mean().tolist()
                    yearly_avg_rows.append([year, "average", sensor] + avg_values)
        
        yearly_avg_df = pd.DataFrame(
            yearly_avg_rows,
            columns=result_df.columns
        )
        
        result_df = pd.concat([result_df, yearly_avg_df], ignore_index=True)
        
        logger.info("[SUCCESS] Temperature data preprocessed")
        return result_df
    
    # -------------------- Enhanced Visualization --------------------
    def generate_temperature_plots(self, temp_df: pd.DataFrame) -> List[plt.Figure]:
        """Generate temperature trend plots for all sensors."""
        logger.info("Generating temperature plots...")
        
        # Expanded seasons to include 'single' for local uploads
        seasons = ['autumn', 'winter', 'spring', 'summer', 'average', 'single']
        sensors = ['Aqua_Day', 'Aqua_Night', 'Terra_Day', 'Terra_Night']
        
        # Colors for metrics
        colors = {'Mean_T': 'green', 'Max_T': 'red', 'Min_T': 'blue'}
        
        # Subplot grid: 2 rows, 3 columns handles 6 seasons
        figures = []
        for sensor in sensors:
            fig, axes = plt.subplots(2, 3, figsize=(16, 9), sharex=False, sharey=False)
            axes = axes.flatten()
            
            # Filter for this sensor
            sensor_df = temp_df[temp_df['sensor'] == sensor]
            
            for i, (ax, season_name) in enumerate(zip(axes, seasons)):
                # Case-insensitive season filtering
                season_data = sensor_df[sensor_df['season'].str.lower() == season_name.lower()].sort_values('year')
                
                if season_data.empty:
                    ax.text(0.5, 0.5, f'No {season_name.capitalize()} Data', ha='center', va='center', color='gray')
                    ax.set_title(season_name.capitalize(), fontsize=12, fontweight='bold')
                    continue
                
                years = season_data['year'].values
                for metric, color in colors.items():
                    if metric in season_data.columns:
                        vals = season_data[metric].values
                        if len(years) == 1:
                            # Single point: Draw a bar instead of just a dot
                            ax.bar(years, vals, color=color, alpha=0.6, width=0.5, label=metric.replace('_', ' ').title())
                            # Add data label
                            ax.text(years[0], vals[0] + 0.5, f"{vals[0]:.1f}", ha='center', va='bottom', fontweight='bold', color=color)
                        else:
                            ax.plot(years, vals, color=color, linewidth=2, 
                                   marker='o', markersize=6, label=metric.replace('_', ' ').title())
                
                # Trend line only for multiple points
                if len(years) > 1:
                    z = np.polyfit(years, season_data['Mean_T'].values, 1)
                    trend = np.poly1d(z)
                    ax.plot(years, trend(years), color='black', linestyle='--', label='Trend')
                
                if len(years) == 1:
                    ax.set_xticks(years)
                
                ax.set_title(season_name.capitalize(), fontsize=12, fontweight='bold')
                ax.set_xlabel("Year")
                ax.set_ylabel("Temp (°C)")
                ax.grid(True, alpha=0.3)
            
            fig.suptitle(f"Temperature Trends - {sensor.replace('_', ' ')}", fontsize=16, fontweight='bold', y=0.98)
            fig.tight_layout(rect=[0, 0, 1, 0.95])
            figures.append(fig)
        
        return figures

    def generate_area_plots(self, area_df: pd.DataFrame) -> Tuple[plt.Figure, plt.Figure]:
        """Generate area trend plots for 6-class and 2-class views."""
        logger.info("Generating area plots...")
        
        seasons = ['autumn', 'winter', 'spring', 'summer', 'average', 'single']
        colors_6class = {
            'Agricultural_Land_Area': '#3CB043', 'Grasses_and_Bushes_Area': '#FFFF00',
            'Urban_Area_Area': '#FF0000', 'Soil_Area': '#8B4513',
            'Water_Area': '#0000FF', 'Trees_Area': '#008000'
        }
        colors_2class = {'green_space': 'green', 'non_green_space': 'red'}
        
        # Helper to render a specific type of chart
        def _render_fig(title, cols_dict):
            fig, axes = plt.subplots(2, 3, figsize=(16, 9), sharex=False)
            axes = axes.flatten()
            for ax, season_name in zip(axes, seasons):
                season_data = area_df[area_df['season'].str.lower() == season_name.lower()].sort_values('year')
                if season_data.empty:
                    ax.text(0.5, 0.5, f'No {season_name.capitalize()} Data', ha='center', va='center', color='gray')
                    ax.set_title(season_name.capitalize(), fontsize=12, fontweight='bold')
                    continue
                
                years = season_data['year'].values
                for col, color in cols_dict.items():
                    if col in season_data.columns:
                        vals = season_data[col].values
                        if len(years) == 1:
                            # Single point: Draw a bar
                            bars = ax.bar(years, vals, color=color, alpha=0.6, width=0.5, 
                                          label=col.replace('_Area', '').replace('_', ' ').title())
                            # Add data label
                            ax.text(years[0], vals[0] + 0.5, f"{vals[0]:.1f}%", ha='center', va='bottom', 
                                    fontweight='bold', color=color, fontsize=9)
                        else:
                            ax.plot(years, vals, color=color, linewidth=2, marker='o', markersize=6, 
                                   label=col.replace('_Area', '').replace('_', ' ').title())
                
                if len(years) == 1:
                    ax.set_xticks(years)
                    
                ax.set_title(season_name.capitalize(), fontsize=12, fontweight='bold')
                ax.set_xlabel("Year")
                ax.set_ylabel("Area (%)")
                ax.grid(True, alpha=0.3)
                
            fig.suptitle(title, fontsize=16, fontweight='bold', y=0.98)
            fig.tight_layout(rect=[0, 0, 1, 0.95])
            return fig

        fig_6class = _render_fig("Land Cover Area Trends (6 Classes)", colors_6class)
        fig_2class = _render_fig("Green vs Non-Green Space Trends", colors_2class)
        
        logger.info("[SUCCESS] Area plots generated")
        return fig_6class, fig_2class
        
        logger.info("[SUCCESS] Area plots generated")
        return fig_6class, fig_2class
    
    # -------------------- Advanced Analysis Methods --------------------
    
    def perform_change_detection(self, year1: int, season1: str, 
                                year2: int, season2: str) -> Dict:
        """Perform change detection between two time periods."""
        logger.info(f"Performing change detection: {year1}_{season1} -> {year2}_{season2}")
        
        # Find masks for the specified periods
        mask1, meta1 = self._find_mask_for_period(year1, season1)
        mask2, meta2 = self._find_mask_for_period(year2, season2)
        
        if mask1 is None or mask2 is None:
            return {"error": "Could not load masks for the specified periods"}
        
        # Perform change detection
        change_results = self.change_detector.compute_change_matrix(mask1, mask2)
        
        # Calculate change intensity
        if len(self.historical_masks) >= 2:
            change_intensity = self.change_detector.compute_change_intensity(
                self.historical_masks, self.historical_years
            )
            change_results['change_intensity'] = change_intensity
        
        return change_results
    
    def perform_uhi_analysis(self, year: int, season: str) -> Dict:
        """Perform Urban Heat Island analysis."""
        logger.info(f"Performing UHI analysis for {year} {season}")
        
        # Find mask for the period
        mask, meta = self._find_mask_for_period(year, season)
        if mask is None:
            return {"error": "Could not load mask for the specified period"}
        
        # Get center coordinates for LST data
        lat, lon, buffer_meters = self.get_center_and_buffer(mask, meta)
        
        # Perform UHI analysis
        uhi_results = self.uhi_analyzer.analyze_uhi_effect(
            mask, None, lat, lon, year, season
        )
        
        return uhi_results
    
    def estimate_carbon_sequestration(self, area_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """Estimate carbon sequestration from area data."""
        logger.info("Estimating carbon sequestration...")
        
        # Estimate carbon
        carbon_df = self.carbon_estimator.estimate_carbon(area_df)
        
        # Generate report
        carbon_report = self.carbon_estimator.generate_carbon_report(carbon_df)
        
        logger.info("[OK] Carbon sequestration estimation completed")
        return carbon_df, carbon_report
    
    def calculate_spatial_metrics(self, mask: np.ndarray, meta: dict) -> Dict:
        """Calculate spatial pattern metrics for land cover."""
        logger.info("Calculating spatial metrics...")
        
        spatial_results = self.spatial_metrics.calculate_spatial_metrics(mask, meta['transform'])
        
        logger.info("[OK] Spatial metrics calculated")
        return spatial_results
    
    def detect_anomalies(self) -> Dict:
        """Detect anomalies in land cover patterns."""
        logger.info("Detecting anomalies...")
        
        if len(self.historical_masks) < 3:
            return {"error": "Insufficient historical data for anomaly detection"}
        
        # Use the most recent mask as current
        current_mask = self.historical_masks[-1]
        current_year = self.historical_years[-1]
        
        # Historical masks (excluding current)
        historical_masks = self.historical_masks[:-1]
        historical_years = self.historical_years[:-1]
        
        # Detect anomalies
        anomalies = self.anomaly_detector.detect_anomalies(
            historical_masks, current_mask, historical_years + [current_year]
        )
        
        logger.info("[OK] Anomaly detection completed")
        return anomalies
    
    def validate_model(self, ground_truth_path: str) -> Dict:
        """Validate model predictions against ground truth."""
        logger.info("Validating model predictions...")
        
        # Load ground truth
        with rasterio.open(ground_truth_path) as src:
            ground_truth = src.read(1)
        
        # Load prediction (most recent)
        if not self.historical_masks:
            return {"error": "No predictions available for validation"}
        
        prediction = self.historical_masks[-1]
        
        # Calculate metrics
        metrics = self.validator.calculate_metrics(prediction, ground_truth)
        
        # Generate validation report
        validation_report = self.validator.generate_validation_report(metrics)
        
        logger.info("[OK] Model validation completed")
        return {
            "metrics": metrics,
            "report": validation_report
        }
    
    def generate_interactive_dashboard(self, mask: np.ndarray, meta: dict,
                                      area_df: pd.DataFrame,
                                      temp_df: pd.DataFrame) -> Dict:
        """Generate interactive dashboard components."""
        logger.info("Generating interactive dashboard...")
        
        dashboard_results = {}
        
        # Generate interactive map
        lat, lon, _ = self.get_center_and_buffer(mask, meta)
        interactive_map = self.dashboard.create_interactive_map(mask, meta, lat, lon)
        
        # Save map to HTML
        map_html = interactive_map._repr_html_()
        dashboard_results['interactive_map'] = map_html
        
        # Generate interactive charts
        charts = self.dashboard.create_interactive_charts(area_df, temp_df)
        dashboard_results.update(charts)
        
        logger.info("[OK] Interactive dashboard generated")
        return dashboard_results
    
    def _find_mask_for_period(self, year: int, season: str) -> Tuple[Optional[np.ndarray], Optional[dict]]:
        """Find mask and metadata for a specific period."""
        for i, (y, s) in enumerate(zip(self.historical_years, self.historical_seasons)):
            if y == year and s == season:
                return self.historical_masks[i], self.historical_metas[i]
        return None, None
    
    # -------------------- LLM Analysis --------------------
    def generate_llm_insights(self, area_json: List[dict], temp_json: List[dict]) -> Dict[str, Any]:
        """Generate insights using LLM."""
        logger.info("Generating LLM insights...")
        
        class SeasonInsights(BaseModel):
            trend_summary: str
            green_space_trend: str
            non_green_space_trend: str
            temperature_trend: str
            recommendations: List[str]
        
        class InsightsOutput(BaseModel):
            season: Dict[str, SeasonInsights]
        
        try:
            # Create parser
            parser = PydanticOutputParser(pydantic_object=InsightsOutput)
            
            # Create prompt
            prompt = PromptTemplate(
                template="""Analyze the following land cover and temperature data:

                Land Cover Data (Area % per season):
                {area_data}

                Temperature Data (°C per season):
                {temperature_data}

                Provide insights in this JSON format:
                {{
                "season": {{
                    "spring": {{
                        "trend_summary": "string",
                        "green_space_trend": "increasing/decreasing/stable",
                        "non_green_space_trend": "increasing/decreasing/stable",
                        "temperature_trend": "increasing/decreasing/stable",
                        "recommendations": ["string"]
                    }},
                    "summer": {{...}},
                    "autumn": {{...}},
                    "winter": {{...}},
                    "average": {{...}}
                }}
                }}

                Focus on:
                1. Main trends in green vs non-green land cover
                2. Seasonal patterns and anomalies
                3. Temperature trends and correlations with land cover
                4. Practical recommendations (minimum 2)""",
                input_variables=['area_data', 'temperature_data'],
                partial_variables={"format_instructions": parser.get_format_instructions()}
            )
            
            # Configure LLM
            model = ChatOpenAI(
                model="openai/gpt-oss-20b:novita",  # Free powerful model
                temperature=0.7,
                api_key="", #please enter the access token of your hugging face account
                base_url='',#Base url
                timeout=30
            )
            
            # Create chain
            chain = prompt | model | parser
            
            # Run analysis
            result = chain.invoke({
                'area_data': json.dumps(area_json, indent=2),
                'temperature_data': json.dumps(temp_json, indent=2)
            })
            
            logger.info("[SUCCESS] LLM insights generated")
            return result.dict()
            
        except Exception as e:
            logger.error(f"Failed to generate LLM insights: {e}")
            
            # Return fallback insights
            return {
                "season": {
                    season: {
                        "trend_summary": "Analysis unavailable due to LLM error",
                        "green_space_trend": "unknown",
                        "non_green_space_trend": "unknown",
                        "temperature_trend": "unknown",
                        "recommendations": ["Check LLM configuration", "Try with a different area of interest"]
                    }
                    for season in ["spring", "summer", "autumn", "winter", "average"]
                }
            }
    
    # -------------------- Main Execution --------------------
    def sub_invoke(self) -> None:
        """Main pipeline execution without saving."""
        overall_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("STARTING PIPELINE EXECUTION")
        logger.info("=" * 60)
        
        area_counter = 0
        temp_counter = 0
        
        # ========= CASE 1: S3 + Coordinates =========
        if self.coordinates is not None:
            logger.info("Processing S3 data with coordinates")
            
            # Create shapefile
            self.set_shapefile(self.coordinates)
            
            # Determine years to process
            if self.years:
                years = self.years
            else:
                years = [2024] if self.purpose == "current" else list(range(2016, 2026))
            
            seasons = ["spring", "summer", "autumn", "winter"]
            
            logger.info(f"Processing {len(years)} years × {len(seasons)} seasons")
            
            for year in years:
                logger.info(f"Year {year}: Processing started")
                
                for season in seasons:
                    logger.info(f"  Season: {season}")
                    
                    
                    # Construct S3 paths
                    # img_path = f"/vsis3/gis-fyp-project-1/Images/{year}/Image-New/{season}.tif"
                    # mask_path = f"/vsis3/gis-fyp-project-1/Images/{year}/Mask/{season}.tif"
                    
                    # Construct Local paths
                    base_local_path = r"D:\FYP\Data"
                    img_path = os.path.join(base_local_path, str(year), "Image-New", f"{season}.tif")
                    mask_path = os.path.join(base_local_path, str(year), "Mask", f"{season}.tif")
                    
                    # Clip images
                    # img, img_meta = self.clip_from_s3(img_path)
                    # msk, msk_meta = self.clip_from_s3(mask_path)
                    
                    img, img_meta = self.clip_local_raster(img_path)
                    msk, msk_meta = self.clip_local_raster(mask_path)
                    
                    if img is None:
                        logger.warning(f"    Skipped - image data unavailable at {img_path}")
                        continue
                    
                    # Fallback Logic: If mask is missing or empty, use the model to predict from image
                    if msk is None or np.sum(msk) == 0:
                        logger.info(f"    Mask empty or missing for {year} {season}. Running model prediction...")
                        try:
                            predicted_msk = self._predict_from_array(img)
                            msk = np.expand_dims(predicted_msk, axis=0)
                            msk_meta = img_meta.copy()
                            logger.info(f"    Model prediction successful for {year} {season}")
                        except Exception as e:
                            logger.error(f"    Fallback model prediction failed: {e}")
                            if msk is None: continue # Only skip if we have no mask at all
                    
                    # Save mask, image and metadata for historical analysis
                    self.historical_masks.append(msk[0])
                    self.historical_images.append(img)
                    self.historical_metas.append(msk_meta)
                    self.historical_years.append(year)
                    self.historical_seasons.append(season)
                    
                    # Get center and buffer for temperature data
                    lat, lon, buffer_meters = self.get_center_and_buffer(img, img_meta)
                    
                    # Fetch temperature data
                    try:
                        df_aqua_day, df_aqua_night, df_terra_day, df_terra_night = self.fetch_all_lst_data(
                            lat, lon, buffer_meters, year, season
                        )
                        
                        # Merge and process temperature data
                        temp_stats = self.merge_lst_dataframes(
                            df_aqua_day, df_aqua_night, df_terra_day, df_terra_night
                        )
                        
                        # Store temperature data
                        sensors = ["Aqua_Day", "Aqua_Night", "Terra_Day", "Terra_Night"]
                        for sensor, stats in zip(sensors, temp_stats):
                            self.temperature.loc[temp_counter] = [year, season, sensor] + stats
                            temp_counter += 1
                            
                    except Exception as e:
                        logger.error(f"    Temperature data error: {e}")
                    
                    # Calculate areas
                    try:
                        area_stats = self.calculate_area(msk[0], msk_meta["transform"])
                        self.area_dict.loc[area_counter] = [year, season] + area_stats
                        area_counter += 1
                        
                        logger.info(f"    Completed - Area: {area_stats[0]:.2f} km²")
                        
                    except Exception as e:
                        logger.error(f"    Area calculation error: {e}")
            
            logger.info(f"S3 processing completed: {area_counter} area records, {temp_counter} temp records")
        
        # ========= CASE 2: Local Image =========
        elif self.input_tif is not None:
            logger.info("Processing local image")
            
            try:
                # Load and process image
                self.load_local_image()
                self.compute_global_percentiles()
                self.load_model()
                
                # Initialize mask
                final_mask = np.zeros(
                    (self.meta["height"], self.meta["width"]),
                    dtype=np.uint8
                )
                
                # Process tiles
                total_tiles = (ceil(self.meta["height"] / self.config.tile_size) * 
                              ceil(self.meta["width"] / self.config.tile_size))
                logger.info(f"Processing {total_tiles} tiles")
                
                tile_start = time.perf_counter()
                for i, (tile, x, y, h, w) in enumerate(self.tile_generator(), 1):
                    pred = self.predict_tile(tile)
                    final_mask[y:y+h, x:x+w] = pred[:h, :w]
                    
                    if i % 20 == 0 or i == total_tiles:
                        logger.info(f"  Processed {i}/{total_tiles} tiles")
                
                logger.info(f"Tile processing completed in {time.perf_counter() - tile_start:.2f}s")
                final_mask = self._reduce_tile_seam_gaps(final_mask)
                
                # Save mask and metadata for historical analysis
                self.historical_masks.append(final_mask)
                self.historical_metas.append(self.meta)
                self.historical_years.append(datetime.now().year)
                self.historical_seasons.append("single")
                
                # Calculate areas
                area_stats = self.calculate_area(final_mask, self.meta["transform"])
                
                # For local image, use current year
                current_year = datetime.now().year
                self.area_dict.loc[0] = [current_year, "single"] + area_stats
                
                # Save output to base_dir if set (standard in web usage)
                self.meta.update({
                    "driver": "GTiff",
                    "count": 1,
                    "dtype": rasterio.uint8,
                    "compress": "LZW"
                })
                
                # Final safety check for nodata value compatibility with uint8
                if self.meta.get('nodata') is not None:
                    if self.meta['nodata'] < 0 or self.meta['nodata'] > 255:
                        logger.warning(f"Metadata nodata {self.meta['nodata']} incompatible with uint8, resetting to 0")
                        self.meta['nodata'] = 0
                
                output_path = self.base_dir / "predicted_mask.tif" if self.base_dir else Path("predicted_mask.tif")
                with rasterio.open(output_path, "w", **self.meta) as dst:
                    dst.write(final_mask, 1)
                
                # Also save RGB for comparison
                rgb_path = self.base_dir / "rgb_2024_single.tif" if self.base_dir else Path("rgb_2024_single.tif")
                rgb_meta = self.meta.copy()
                rgb_meta.update({"count": 3, "dtype": rasterio.uint8})
                
                # Convert float32 image back to uint8 RGB
                rgb_data = self.image[:3].copy()
                if rgb_data.max() > 255: # If not normalized
                    rgb_data = ((rgb_data - rgb_data.min()) / (rgb_data.max() - rgb_data.min() + 1e-8) * 255)
                rgb_data = rgb_data.astype(np.uint8)
                
                with rasterio.open(rgb_path, "w", **rgb_meta) as dst:
                    dst.write(rgb_data)

                logger.info(f"Local image processing completed. Output saved to {output_path}")
                
            except Exception as e:
                logger.error(f"Local image processing failed: {e}")
                raise
        
        else:
            logger.error("No input provided. Specify either coordinates or input_tif.")
            return
        
        total_time = time.perf_counter() - overall_start
        logger.info("=" * 60)
        logger.info(f"PIPELINE COMPLETED IN {total_time:.2f} SECONDS")
        logger.info("=" * 60)
    
    def invoke(self, save_config: bool = False, username: str = None,
              run_advanced_analyses: bool = True) -> Dict[str, Any]:
        """
        Execute the full pipeline with optional saving.
        
        Args:
            save_config: Whether to save outputs to disk
            username: Username for organizing output files
            run_advanced_analyses: Whether to run advanced analyses
            
        Returns:
            Dictionary containing all results and metadata
        """
        try:
            # Create output directory if saving and not already set
            if save_config and username and not self.base_dir:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_path = Path("outputs")
                self.base_dir = base_path / f"{username}_{timestamp}"
                self.base_dir.mkdir(parents=True, exist_ok=True)
                
                logger.info(f"Output will be saved to: {self.base_dir}")
            elif save_config and self.base_dir:
                self.base_dir = Path(self.base_dir) # Ensure Path object
                self.base_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Output will be saved to existing directory: {self.base_dir}")
            
            # Execute pipeline
            self.sub_invoke()
            
            # Process results
            processed_area = self.preprocess_area_data(self.area_dict)
            processed_temp = self.preprocess_temperature_data(self.temperature)
            
            # Generate visualizations
            area_fig_6class, area_fig_2class = self.generate_area_plots(processed_area)
            temp_figs = self.generate_temperature_plots(processed_temp)
            
            # Generate LLM insights
            area_json = processed_area.to_dict(orient="records")
            temp_json = processed_temp.to_dict(orient="records")
            llm_insights = self.generate_llm_insights(area_json, temp_json)
            
            # Run advanced analyses if requested
            advanced_results = {}
            if run_advanced_analyses and len(self.historical_masks) > 0:
                logger.info("Running advanced analyses...")
                
                # 1. Change detection (if multiple years)
                if len(self.historical_masks) >= 2:
                    # Find two different years for comparison
                    unique_years = sorted(list(set(self.historical_years)))
                    if len(unique_years) >= 2:
                        year1 = unique_years[-2]
                        year2 = unique_years[-1]
                        # Find seasons for these years
                        season1 = self.historical_seasons[self.historical_years.index(year1)]
                        season2 = self.historical_seasons[self.historical_years.index(year2)]
                        advanced_results['change_detection'] = self.perform_change_detection(
                            year1, season1, year2, season2
                        )
                
                # 2. UHI analysis (if urban areas present)
                if len(self.historical_masks) > 0:
                    current_year = self.historical_years[-1]
                    current_season = self.historical_seasons[-1]
                    advanced_results['uhi_analysis'] = self.perform_uhi_analysis(
                        current_year, current_season
                    )
                
                # 3. Carbon sequestration
                carbon_df, carbon_report = self.estimate_carbon_sequestration(processed_area)
                advanced_results['carbon_sequestration'] = {
                    'dataframe': carbon_df,
                    'report': carbon_report
                }
                
                # 4. Spatial metrics (using most recent mask)
                if len(self.historical_masks) > 0:
                    current_mask = self.historical_masks[-1]
                    current_meta = self.historical_metas[-1]
                    advanced_results['spatial_metrics'] = self.calculate_spatial_metrics(
                        current_mask, current_meta
                    )
                
                # 5. Anomaly detection
                if len(self.historical_masks) >= 3:
                    advanced_results['anomaly_detection'] = self.detect_anomalies()
                
                # 6. Interactive dashboard (using most recent mask)
                if len(self.historical_masks) > 0:
                    current_mask = self.historical_masks[-1]
                    current_meta = self.historical_metas[-1]
                    advanced_results['dashboard'] = self.generate_interactive_dashboard(
                        current_mask, current_meta, processed_area, processed_temp
                    )
                
                logger.info("[OK] Advanced analyses completed")
            
            # Save results if requested
            if save_config and username and self.base_dir:
                logger.info("Saving results...")
                
                # Save shapefile
                if self.shpfile is not None:
                    shp_dir = self.base_dir / "shapefile"
                    shp_dir.mkdir(exist_ok=True)
                    self.shpfile.to_file(shp_dir / "aoi.shp")
                
                # Save CSV files
                processed_area.to_csv(self.base_dir / "area_analysis.csv", index=False)
                processed_temp.to_csv(self.base_dir / "temperature_analysis.csv", index=False)
                
                # Save seasonal masks for web display (Crucial for MapLayersAPIView)
                for i, mask in enumerate(self.historical_masks):
                    if i < len(self.historical_years) and i < len(self.historical_seasons):
                        h_year = self.historical_years[i]
                        h_season = self.historical_seasons[i]
                        
                        # Get metadata for this mask
                        if i < len(self.historical_metas):
                            h_meta = self.historical_metas[i].copy()
                        else:
                            h_meta = self.meta.copy()
                            
                        # Update metadata for saving
                        h_meta.update({
                            "driver": "GTiff",
                            "count": 1,
                            "dtype": rasterio.uint8,
                            "compress": "LZW"
                        })
                        
                        # Use lowercase season to match map.js URL construction
                        mask_out_path = self.base_dir / f"mask_{h_year}_{h_season.lower()}.tif"
                        
                        try:
                            with rasterio.open(mask_out_path, "w", **h_meta) as dst:
                                dst.write(mask, 1)
                        except Exception as e:
                            logger.error(f"Failed to save mask for {h_year} {h_season}: {e}")
                        
                        # Save RGB if available
                        if i < len(self.historical_images):
                            img_out_path = self.base_dir / f"rgb_{h_year}_{h_season.lower()}.tif"
                            img_data = self.historical_images[i]
                            
                            # Prepare metadata for RGB saving (may have 3+ bands)
                            rgb_meta = h_meta.copy()
                            rgb_meta.update({
                                "count": img_data.shape[0],
                                "dtype": img_data.dtype
                            })
                            
                            try:
                                with rasterio.open(img_out_path, "w", **rgb_meta) as dst:
                                    dst.write(img_data)
                                logger.debug(f"Saved RGB to {img_out_path}")
                            except Exception as e:
                                logger.error(f"Failed to save RGB for {h_year} {h_season}: {e}")
                
                # Save plots
                area_fig_6class.savefig(self.base_dir / "area_trends_6class.png", dpi=300, bbox_inches='tight')
                area_fig_2class.savefig(self.base_dir / "area_trends_2class.png", dpi=300, bbox_inches='tight')
                
                for i, fig in enumerate(temp_figs):
                    fig.savefig(self.base_dir / f"temperature_trend_{i}.png", 
                              dpi=300, bbox_inches='tight')
                    plt.close(fig)
                
                plt.close(area_fig_6class)
                plt.close(area_fig_2class)
                
                # Save LLM insights
                with open(self.base_dir / "llm_insights.json", "w") as f:
                    json.dump(llm_insights, f, indent=2)
                
                # Save advanced results
                if advanced_results:
                    with open(self.base_dir / "advanced_analyses.json", "w") as f:
                        # Convert DataFrames to dict for JSON serialization
                        adv_json = {}
                        for key, value in advanced_results.items():
                            if key == 'carbon_sequestration':
                                adv_json[key] = {
                                    'dataframe': value['dataframe'].to_dict(orient='records'),
                                    'report': value['report']
                                }
                            elif key == 'dashboard':
                                # Save dashboard HTML files
                                for dash_key, dash_value in value.items():
                                    if 'html' in dash_key or 'map' in dash_key:
                                        dash_path = self.base_dir / f"{dash_key}.html"
                                        with open(dash_path, 'w') as dash_file:
                                            dash_file.write(str(dash_value))
                                adv_json[key] = {k: f"saved to {k}.html" for k in value.keys()}
                            else:
                                adv_json[key] = value
                        
                        json.dump(adv_json, f, indent=2)
                
                # Save summary report
                self._generate_summary_report(self.base_dir)
                
                logger.info(f"All results saved to {self.base_dir}")
            
            # Return results
            return {
                "area_data": processed_area,
                "temperature_data": processed_temp,
                "llm_insights": llm_insights,
                "area_plots": {"6class": area_fig_6class, "2class": area_fig_2class},
                "temperature_plots": temp_figs,
                "advanced_analyses": advanced_results,
                "output_directory": str(self.base_dir) if self.base_dir else None
            }
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _generate_summary_report(self, output_dir: Path) -> None:
        """Generate a summary report of the analysis."""
        report_path = output_dir / "analysis_summary.txt"
        
        with open(report_path, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("LAND COVER ANALYSIS SUMMARY\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Purpose: {self.purpose or 'Not specified'}\n\n")
            
            f.write("DATA SUMMARY:\n")
            f.write("-" * 40 + "\n")
            f.write(f"Area records: {len(self.area_dict)}\n")
            f.write(f"Temperature records: {len(self.temperature)}\n")
            f.write(f"Historical masks stored: {len(self.historical_masks)}\n\n")
            
            f.write("OUTPUT FILES:\n")
            f.write("-" * 40 + "\n")
            for file in output_dir.iterdir():
                if file.is_file():
                    f.write(f"  • {file.name}\n")
            
            f.write("\nANALYSIS MODULES USED:\n")
            f.write("-" * 40 + "\n")
            modules = [
                "Change Detection",
                "Urban Heat Island Analysis",
                "Carbon Sequestration Estimation",
                "Spatial Pattern Metrics",
                "Anomaly Detection",
                "Model Validation",
                "Interactive Dashboard"
            ]
            for module in modules:
                f.write(f"  • {module}\n")
            
            f.write("\nPROCESSING COMPLETE\n")
