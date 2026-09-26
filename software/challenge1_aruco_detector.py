#!/usr/bin/env python3
"""
Challenge 1: Aruco Marker Detection for Landing Zone Classification
Purpose: Detect landing pads via Aruco markers and classify as VALID/INVALID

Key points:
- Detect marker IDs and positions
- Extract depth at marker location
- Convert to world coordinates using camera intrinsics
"""

import cv2
import numpy as np
import json
from typing import List, Dict, Tuple, Optional


class ArucoMarkerDetector:
    """
    Detects Aruco markers in RGB images and extracts:
    - Marker ID
    - Marker center position (pixel coords)
    - Depth at marker (from depth image)
    - World coordinates (using camera intrinsics)
    """
    
    def __init__(self, aruco_dict_type=cv2.aruco.DICT_4X4_250):
        """
        Initialize Aruco detector
        
        Args:
            aruco_dict_type: Dictionary to use. (Provided on day of):
                - DICT_4X4_50
                - DICT_5X5_100
                - DICT_6X6_250  ← Most common, supports 250 unique markers
                - DICT_ARUCO_ORIGINAL
        """
        self.arucoDict = cv2.aruco.getPredefinedDictionary(aruco_dict_type)
        self.parameters = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(self.arucoDict, self.parameters)
        
        # Camera intrinsics (PLACEHOLDER - will be set from RealSense)
        # These are focal length and principal point
        # For RealSense D435: typically fx=615, fy=615, cx=320, cy=240
        self.fx = 615.0
        self.fy = 615.0
        self.cx = 320.0
        self.cy = 240.0
    
    def set_camera_intrinsics(self, fx: float, fy: float, cx: float, cy: float):
        """
        Set camera intrinsics (focal length and principal point)
        These are needed to convert pixel coordinates to world coordinates
        
        For RealSense: camera.get_camera_matrix() provides these
        """
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
    
    def detect_markers(self, color_image: np.ndarray, depth_image: Optional[np.ndarray] = None) -> List[Dict]:
        """
        Detect all Aruco markers in image
        
        Args:
            color_image: RGB/BGR image from camera
            depth_image: Depth image (optional, used to get depth at marker)
            
        Returns:
            List of detected markers with structure:
            [
                {
                    "marker_id": 1,
                    "center_pixel": (320, 240),
                    "corners": [(x1,y1), (x2,y2), (x3,y3), (x4,y4)],
                    "depth_mm": 1500,
                    "depth_m": 1.5,
                    "world_coords": {"X": 0.5, "Y": 0.3, "Z": 1.5},
                    "valid": True  # True if marker detected, False if depth invalid
                },
                ...
            ]
        """
        # Convert to grayscale for detection
        gray = cv2.cvtColor(color_image, cv2.COLOR_BGR2GRAY)
        
        # Detect markers
        corners, ids, rejected = self.detector.detectMarkers(gray)
        
        markers = []
        
        if ids is not None and len(corners) > 0:
            ids = ids.flatten()
            
            for (corner, marker_id) in zip(corners, ids):
                # Reshape corners to (4, 2)
                corner = corner.reshape((4, 2))
                
                # Extract corner coordinates
                (topLeft, topRight, bottomRight, bottomLeft) = corner
                topRight = (int(topRight[0]), int(topRight[1]))
                bottomRight = (int(bottomRight[0]), int(bottomRight[1]))
                bottomLeft = (int(bottomLeft[0]), int(bottomLeft[1]))
                topLeft = (int(topLeft[0]), int(topLeft[1]))
                
                # Calculate center
                cX = int((topLeft[0] + bottomRight[0]) / 2.0)
                cY = int((topLeft[1] + bottomRight[1]) / 2.0)
                
                marker_data = {
                    "marker_id": int(marker_id),
                    "center_pixel": (cX, cY),
                    "corners": [
                        (int(topLeft[0]), int(topLeft[1])),
                        (int(topRight[0]), int(topRight[1])),
                        (int(bottomRight[0]), int(bottomRight[1])),
                        (int(bottomLeft[0]), int(bottomLeft[1]))
                    ]
                }
                
                # If depth image provided, get depth at marker center
                if depth_image is not None:
                    depth_mm = depth_image[cY, cX]
                    depth_m = float(depth_mm) / 1000.0
                    
                    marker_data["depth_mm"] = int(depth_mm)
                    marker_data["depth_m"] = round(depth_m, 3)
                    
                    # Convert to world coordinates using camera intrinsics
                    # X = (u - cx) * depth / fx
                    # Y = (v - cy) * depth / fy
                    # Z = depth
                    if depth_mm > 0:  # Valid depth
                        X = (cX - self.cx) * depth_m / self.fx
                        Y = (cY - self.cy) * depth_m / self.fy
                        Z = depth_m
                        
                        marker_data["world_coords"] = {
                            "X": round(X, 3),
                            "Y": round(Y, 3),
                            "Z": round(Z, 3)
                        }
                        marker_data["valid"] = True
                    else:
                        marker_data["valid"] = False
                        marker_data["reason"] = "Invalid depth (0 or no data)"
                else:
                    marker_data["valid"] = True  # Assume valid if no depth check
                
                markers.append(marker_data)
        
        return markers
    
    def draw_markers_on_image(self, image: np.ndarray, markers: List[Dict]) -> np.ndarray:
        """
        Draw detected markers on image
        
        Shows:
        - Bounding box around marker
        - Marker ID
        - Center point
        - Depth value
        """
        output = image.copy()
        
        # Use OpenCV built-in drawing (already in markers)
        corners_list = [np.array(m["corners"], dtype=np.int32) for m in markers]
        ids_list = [m["marker_id"] for m in markers]
        
        if len(corners_list) > 0:
            # Draw marker borders
            for corners, marker_id in zip(corners_list, ids_list):
                cv2.polylines(output, [corners], True, (0, 255, 0), 3)
                
                # Get center and draw it
                cx, cy = int(corners.mean(axis=0)[0]), int(corners.mean(axis=0)[1])
                cv2.circle(output, (cx, cy), 8, (0, 0, 255), -1)
                
                # Draw marker ID
                cv2.putText(output, f"ID: {marker_id}", (cx - 30, cy - 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                
                # Draw depth if available
                marker = next((m for m in markers if m["marker_id"] == marker_id), None)
                if marker and "depth_m" in marker:
                    depth_text = f"D: {marker['depth_m']}m"
                    cv2.putText(output, depth_text, (cx - 30, cy + 20),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                
                # Draw VALID/INVALID status
                status = "VALID" if marker["valid"] else "INVALID"
                color = (0, 255, 0) if marker["valid"] else (0, 0, 255)
                cv2.putText(output, status, (cx - 30, cy + 50),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        return output
    
    def classify_landing_zones(self, markers: List[Dict]) -> Dict:
        """
        Classify each marker as VALID or INVALID landing zone
        
        Rules:
        - VALID: Marker detected + valid depth + reasonable distance (0.5m - 3.0m)
        - INVALID: No marker, invalid depth, or unreasonable distance
        """
        classification = {
            "total_zones_scanned": len(markers),
            "valid_zones": [],
            "invalid_zones": [],
            "timestamp": None
        }
        
        for marker in markers:
            zone = {
                "marker_id": marker["marker_id"],
                "center_pixel": marker["center_pixel"],
                "depth_m": marker.get("depth_m", None),
                "world_coords": marker.get("world_coords", None),
                "classification": "UNKNOWN",
                "reason": ""
            }
            
            # Classification logic
            if not marker.get("valid", False):
                zone["classification"] = "INVALID"
                zone["reason"] = marker.get("reason", "Unknown reason")
                classification["invalid_zones"].append(zone)
            
            elif "depth_m" in marker:
                depth = marker["depth_m"]
                
                # Check if depth is reasonable for landing (0.5m - 3.0m)
                if 0.5 <= depth <= 3.0:
                    zone["classification"] = "VALID"
                    zone["reason"] = "Marker detected with valid depth"
                    classification["valid_zones"].append(zone)
                else:
                    zone["classification"] = "INVALID"
                    zone["reason"] = f"Depth out of range ({depth}m)"
                    classification["invalid_zones"].append(zone)
            
            else:
                zone["classification"] = "VALID"
                zone["reason"] = "Marker detected (depth not checked)"
                classification["valid_zones"].append(zone)
        
        return classification


def test_with_webcam():
    """
    Test Aruco detection with live webcam
    Press 'q' to quit, 's' to save frame
    """
    detector = ArucoMarkerDetector()
    
    cap = cv2.VideoCapture(0)
    
    print("Testing Aruco detection with webcam")
    print("Show Aruco markers to camera")
    print("Press 'q' to quit, 's' to save frame")
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Detect markers
        markers = detector.detect_markers(frame, depth_image=None)
        
        # Draw on frame
        output = detector.draw_markers_on_image(frame, markers)
        
        # Show info
        cv2.putText(output, f"Markers detected: {len(markers)}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        cv2.imshow("Aruco Detection", output)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            # Save frame with detections
            cv2.imwrite(f"aruco_test_{frame_count}.jpg", output)
            
            # Save marker data
            classification = detector.classify_landing_zones(markers)
            with open(f"aruco_data_{frame_count}.json", "w") as f:
                json.dump(classification, f, indent=2)
            
            print(f"Saved frame and data (frame {frame_count})")
            frame_count += 1
    
    cap.release()
    cv2.destroyAllWindows()


def test_with_image(image_path: str, depth_path: Optional[str] = None):
    """
    Test Aruco detection with saved image
    """
    detector = ArucoMarkerDetector()
    
    # Load color image
    color_image = cv2.imread(image_path)
    if color_image is None:
        print(f"Could not load image: {image_path}")
        return
    
    # Load depth image if provided
    depth_image = None
    if depth_path:
        depth_image = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
    
    # Detect markers
    markers = detector.detect_markers(color_image, depth_image)
    
    # Classify zones
    classification = detector.classify_landing_zones(markers)
    
    # Draw markers
    output = detector.draw_markers_on_image(color_image, markers)
    
    # Display results
    print("\n" + "="*60)
    print("ARUCO MARKER DETECTION RESULTS")
    print("="*60)
    print(f"Total zones scanned: {classification['total_zones_scanned']}")
    print(f"Valid zones: {len(classification['valid_zones'])}")
    print(f"Invalid zones: {len(classification['invalid_zones'])}")
    
    print("\nValid zones:")
    for zone in classification["valid_zones"]:
        print(f"  - Marker ID {zone['marker_id']}: {zone['reason']}")
        if zone["world_coords"]:
            print(f"    Position: X={zone['world_coords']['X']}, Y={zone['world_coords']['Y']}, Z={zone['world_coords']['Z']}")
    
    print("\nInvalid zones:")
    for zone in classification["invalid_zones"]:
        print(f"  - Marker ID {zone['marker_id']}: {zone['reason']}")
    
    # Save results
    with open("challenge1_results.json", "w") as f:
        json.dump(classification, f, indent=2)
    
    # Display image
    cv2.imshow("Detected Markers", output)
    cv2.imwrite("challenge1_detections.jpg", output)
    
    print("\nResults saved to challenge1_results.json")
    print("Image saved to challenge1_detections.jpg")
    
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Use provided image
        image_path = sys.argv[1]
        depth_path = sys.argv[2] if len(sys.argv) > 2 else None
        test_with_image(image_path, depth_path)
    else:
        # Use webcam
        test_with_webcam()
