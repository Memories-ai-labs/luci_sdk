# Stereo Camera Calibration and Depth Estimation — Complete Workflow

This README provides a **comprehensive pipeline** for calibrating **camera intrinsics** and **stereo extrinsics**,  
then validating results via **OpenCV-based depth reconstruction** and **AI-based CREStereo depth estimation**.

> Designed for reproducibility on Windows/macOS/Linux with OpenCV 4.x.  
> Supports both **Chessboard** and **Charuco** calibration targets.  
> Outputs are YAML-compatible and can be reused for 3D reconstruction, robot vision, or LUCI dual-eye experiments.

---

## 🧩 1) Environment Setup

```bash
pip install opencv-python opencv-contrib-python numpy pyyaml matplotlib
# Optional for depth visualization & AI models
pip install open3d torch torchvision timm
```

> ⚠️ Make sure your OpenCV build includes **contrib** modules (for Charuco / ximgproc).

---

## 📷 2) Calibration Target

- **Chessboard** (recommended): e.g. inner corners = 8×5 (9 × 6 total squares)  
- **Charuco Board**: e.g. `DICT_5X5_100`, specify both square & marker sizes  
- Measure **square size** precisely in **meters** (e.g. `--square 0.030`)

> Keep the target **flat**, **matte**, and **rigid** to minimize reflections and warping.

---

## 🎞️ 3) Data Capture (Stereo Images or Videos)

Capture **20–40 synchronized pairs** from diverse poses:  
- Vary distance, tilt, and rotation  
- Cover all corners of the field of view  
- Ensure both cameras capture the **same moments**

**Example folder:**
```
calibration_images_dual_eye/
├── cam1_0001.png
├── cam1_0002.png
│   ...
├── cam2_0001.png
├── cam2_0002.png
│   ...
```
> `cam1` = left, `cam2` = right.  
> If using video, extract frames before calibration.

---

## 🎯 4) Intrinsic Calibration

Run separately for each camera (left/right):

```bash
python calibration_images_dual_eye/calibration_intrinsics.py
```

**Output YAML (per camera):**
- `K` – 3×3 intrinsic matrix  
- `D` – distortion coefficients `[k1, k2, p1, p2, k3, …]`  
- `size` – (width, height)  
- `rms` – reprojection error  

> 🎯 **Good target RMS:** < 0.5 px (ideal), < 1.0 px (acceptable)

---

## 🔗 5) Stereo Extrinsic Calibration

After both intrinsics are available:

```bash
python calibration_images_dual_eye/stereo_calibration.py
```

**Outputs (`stereo_params.yaml`):**
- `K1`, `D1`, `K2`, `D2`
- `R`, `T` – rotation & translation (left→right)
- `R1`, `R2`, `P1`, `P2`, `Q` – rectification & projection matrices
- `rms_stereo` – stereo reprojection error
- `baseline` – distance between camera centers (in m) 

> If RMS > 1.0 px or baseline is unrealistic, remove poor frames and re-run calibration.

---

## 🌈 6) Depth Estimation & Point-to-Point Measurement  
*( OpenCV Stereo Pipeline)*

After successful calibration, use the provided **`stereo_depth_enhanced_en.py`**  
to generate accurate near-field depth maps and interactively measure distances.

```bash
python depth_estimation_opencv/stereo_depth_opencv.py
```

---

### ⚙️ Processing Pipeline

| Stage | Algorithm | Description |
|-------|------------|-------------|
| **1. Rectification** | OpenCV Rectify | Uses YAML `K1,D1,K2,D2,R,T` |
| **2. Dual SGBM** | StereoSGBM (block=3 & 7) | Fine + coarse detail disparity |
| **3. Edge-Aware Fusion** | Sobel + Confidence Mask | Blends disparities by edge strength |
| **4. WLS Filtering** | `cv2.ximgproc` | Removes speckle & halo artifacts |
| **5. Superpixel Plane Fill** | SLIC + RANSAC | Fills holes and flats with fitted planes |
| **6. Guided Filtering** | Edge-preserving | Smooths depth without losing edges |
| **7. 3D Reprojection** | `cv2.reprojectImageTo3D` | Disparity → metric depth via `Q` matrix |
| **8. Interactive Measurement UI** | Mouse input | Click two points → 3D distance (meters) |

---

### 🧠 Features

- Dual-scale SGBM fuses fine and smooth structure  
- Confidence- and edge-aware fusion for accuracy  
- Optional superpixel plane reconstruction on flat surfaces  
- Real-time 2-point distance measurement  
- Automatic outputs:
  - Rectified left image `*_rectL.jpg`  
  - Depth visualization `*_depth_vis.jpg`  
  - Metric depth PNG `*_depth_mm.png`  
  - Raw float depth `*_depth.npy`

**Output Directory:**
```
./depth_out_enhanced/
├── pair_000_rectL.jpg
├── pair_000_depth_vis.jpg
├── pair_000_depth_mm.png
└── pair_000_depth.npy
```

> 🧩 Depth units: meters (`.npy`), millimeters (`.png`)

---

### 📐 Interactive 2-Point Distance UI

- **Left click ×2 :** measure distance between points  
- **c :** clear annotations  
- **q / ESC :** exit  

Example console output:
```
Selected: (520,310) → (580,320)
Distance = 0.084 m
```

---

### 🎯 Use Cases

- Validate stereo calibration accuracy  
- Obtain ground-truth depth for AI training  
- Evaluate LUCI Pin dual-eye setup in near-field 3D interaction  

---

## 🧠 7) AI Depth Estimation — CREStereo Integration

For deeper evaluation, the same stereo pairs can be processed with **CREStereo**,  
a learning-based stereo matching model by Megvii Research.

```bash
python calibration_images_dual_eye/depth_demo_crestereo.py \
  --left cam1_0001.png --right cam2_0001.png
```

**Model Highlights:**

- Cross-scale cost-volume aggregation with attention mechanisms  
- Handles low-texture and reflective regions better than classical SGBM  
- Compatible with pretrained weights (`crestereo_init_iter5.pth`)  

**Outputs:**

- `crestereo_depth.png` – visualized depth map  
- `crestereo_depth.npy` – raw depth values (meters)

You can compare CREStereo depths with OpenCV SGBM outputs to evaluate precision, smoothness, and robustness.

> 💡 Recommendation: use CREStereo for final visual datasets or AI fusion training;  
> keep OpenCV SGBM for fast calibration validation and metric evaluation.

---

## 📁 8) File Structure Overview

```
calibration_images_dual_eye/
├── calibration_intrinsics.py
├── stereo_calibration.py
├── stereo_depth_enhanced_en.py
├── depth_demo_crestereo.py
├── measure_distance.py
├── dual_eye_calibration.yaml
└── outputs/
     ├── disparity.png
     ├── depth_map.npy
     ├── crestereo_depth.png
     └── cloud.ply
```

---

## ✅ 9) Validation Checklist

- Rectified images → epipolar lines are **horizontal**  
- Depth maps → smooth and consistent with object distance  
- Measured distances → within **±1–2 cm** of real-world value  
- CREStereo → superior performance in low-texture or glossy regions  

---

## 📚 10) References

- OpenCV Camera Calibration — <https://docs.opencv.org/master/dc/dbb/tutorial_py_calibration.html>  
- Stereo Depth (SGBM) — <https://docs.opencv.org/master/dd/d53/tutorial_py_depthmap.html>  
- **CREStereo:** Megvii Research, *Learning Cross-Scale Cost Volume for Stereo Matching*, CVPR 2022  
- Hartley & Zisserman, *Multiple View Geometry in Computer Vision*, 2nd Ed.  
- Zach & Pock, *A Practical Guide to Optical Flow and Stereo Matching*, 2017  

---

### 📄 Citation

If this pipeline or its outputs contribute to your research or publication,  
please cite your repository or related paper accordingly.


