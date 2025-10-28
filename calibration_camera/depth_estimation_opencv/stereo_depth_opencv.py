# -*- coding: utf-8 -*-
"""
 Batch stereo depth with optional interactive 2-point distance measuring.
- Reads your JSON-in-YAML calibration at ../stereo_out/stereo_params.yaml
- Scans ../test_images for cam1/cam2 pairs (filename contains 'cam1'/'cam2')
- For each pair:
    * Rectify, compute disparity (SGBM), reproject to 3D
    * Save rectified images, disparity pseudo-color, depth pseudo-color, and raw .npy arrays
    * (Optional) Interactive measuring: click 2 points -> press 'c' to log a distance
      Press 's' to save CSV of measurements and an annotated image; 'n' to move to next; 'q' to quit measurement for this pair
All algorithm parameters are kept the same as previous version.
"""
import os, glob, json, csv
import numpy as np
import cv2

# -------- Paths & naming (same as before) --------
PARAMS_PATH = "../stereo_calibration_result/stereo_params.yaml"
IMG_DIR     = "../test_images"
CAM1_KEY, CAM2_KEY = "cam1", "cam2"
SAVE_DIR    = "./depth_out"

# -------- Utilities --------
def _reshape_or_none(arr, shape):
    """Convert to numpy and reshape if possible."""
    if arr is None: return None
    a = np.array(arr, dtype=np.float64)
    try: return a.reshape(shape)
    except Exception: return a

def _read_text(path):
    """Read text file with BOM stripping."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")

def load_stereo_params(yaml_path):
    """
    Load calibration. First try OpenCV FileStorage; if it fails,
    parse the JSON object embedded in the YAML (your file structure).
    Returns dict with: size, K1,D1,K2,D2,R1,R2,P1,P2,Q,R,T
    If Q is missing but R/T exist, compute via stereoRectify.
    """
    # A) Try OpenCV FileStorage
    try:
        fs = cv2.FileStorage(yaml_path, cv2.FILE_STORAGE_READ)
        if fs.isOpened():
            def N(name):
                node = fs.getNode(name)
                return None if node.empty() else node.mat()
            K1,D1,K2,D2 = N("K1"),N("D1"),N("K2"),N("D2")
            R,T         = N("R"),N("T")
            R1,R2,P1,P2 = N("R1"),N("R2"),N("P1"),N("P2")
            Q           = N("Q")
            size = N("size")
            if size is None:
                w_node,h_node = fs.getNode("image_width"),fs.getNode("image_height")
                if not w_node.empty() and not h_node.empty():
                    size = np.array([int(w_node.real()), int(h_node.real())], dtype=np.int32)
            fs.release()
            if K1 is None or D1 is None or K2 is None or D2 is None:
                raise RuntimeError("K/D incomplete from FileStorage; fallback to JSON parse.")
            if Q is None:
                if R is None or T is None or size is None or size.size < 2:
                    raise RuntimeError("Insufficient info to compute Q; fallback to JSON parse.")
                w,h = int(size[0]), int(size[1])
                R1,R2,P1,P2,Q,_,_ = cv2.stereoRectify(K1,D1,K2,D2,(w,h),R,T,
                                                      flags=cv2.CALIB_ZERO_DISPARITY, alpha=0)
            else:
                if (R1 is None or R2 is None or P1 is None or P2 is None) and (R is not None and T is not None and size is not None):
                    w,h = int(size[0]), int(size[1])
                    R1,R2,P1,P2,_Q,_,_ = cv2.stereoRectify(K1,D1,K2,D2,(w,h),R,T,
                                                           flags=cv2.CALIB_ZERO_DISPARITY, alpha=0)
            return {"size": size, "K1":K1, "D1":D1, "K2":K2, "D2":D2,
                    "R1":R1, "R2":R2, "P1":P1, "P2":P2, "Q":Q, "R":R, "T":T}
    except Exception:
        try: fs.release()
        except Exception: pass

    # B) Parse JSON object embedded in your YAML
    txt = _read_text(yaml_path)
    l = txt.find("{"); r = txt.rfind("}")
    if l == -1 or r == -1 or r <= l:
        raise ValueError("Cannot locate JSON payload inside calibration file.")
    payload = json.loads(txt[l:r+1])

    # Image size: your file uses image_size: {w:960, h:1280}
    isz = payload.get("image_size", {})
    w,h = int(isz.get("w",0)), int(isz.get("h",0))
    if w<=0 or h<=0:
        raise ValueError("Missing valid image_size.w/h in calibration.")
    size = np.array([w,h], dtype=np.int32)

    K1 = _reshape_or_none(payload.get("K1"), (3,3))
    K2 = _reshape_or_none(payload.get("K2"), (3,3))
    D1 = _reshape_or_none(payload.get("D1"), (-1,))
    D2 = _reshape_or_none(payload.get("D2"), (-1,))
    R  = _reshape_or_none(payload.get("R"),  (3,3))
    T  = _reshape_or_none(payload.get("T"),  (3,))

    R1 = _reshape_or_none(payload.get("R1"), (3,3))
    R2 = _reshape_or_none(payload.get("R2"), (3,3))
    P1 = _reshape_or_none(payload.get("P1"), (3,4))
    P2 = _reshape_or_none(payload.get("P2"), (3,4))
    Q  = _reshape_or_none(payload.get("Q"),  (4,4))

    if Q is None:
        if R is None or T is None:
            raise ValueError("No Q and no R/T; cannot compute Q.")
        R1,R2,P1,P2,Q,_,_ = cv2.stereoRectify(
            K1, D1, K2, D2, (w, h), R, T, flags=cv2.CALIB_ZERO_DISPARITY, alpha=0)

    return {"size": size, "K1":K1, "D1":D1, "K2":K2, "D2":D2,
            "R1":R1, "R2":R2, "P1":P1, "P2":P2, "Q":Q, "R":R, "T":T}

def make_rectify_maps(K, D, R, P, img_size):
    """Build remap tables for rectification."""
    return cv2.initUndistortRectifyMap(K, D, R, P, img_size, cv2.CV_16SC2)

def build_sgbm(num_disp=192, block_size=5, lrc=1, uniq=8, speckle_win=120, speckle_range=2):
    """Create SGBM with the same params as previous version."""
    num_disp = max(16, (num_disp//16)*16)
    return cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=num_disp,
        blockSize=block_size,
        P1=8*block_size*block_size,
        P2=32*block_size*block_size,
        uniquenessRatio=uniq,
        speckleWindowSize=speckle_win,
        speckleRange=speckle_range,
        disp12MaxDiff=lrc,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY
    )

def colorize_disparity(disp):
    """Pseudo-color disparity for visualization."""
    d = np.nan_to_num(disp.copy(), nan=0.0, posinf=0.0, neginf=0.0)
    if np.any(d>0):
        d = np.clip(d, 0, np.percentile(d[d>0], 99))
    d8 = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.applyColorMap(d8, cv2.COLORMAP_TURBO)

def colorize_depth(depth_m):
    """Pseudo-color depth (Z in meters) using 95th percentile for upper bound."""
    z = depth_m.copy()
    z[~np.isfinite(z)] = np.nan
    if np.any(np.isfinite(z)):
        vmax = np.nanpercentile(z, 95)
        vmax = vmax if vmax>0 else np.nanmax(z)
        vmax = float(vmax) if np.isfinite(vmax) and vmax>0 else 1.0
        z = np.clip(z, 0, vmax)
        z8 = (255 * (1 - z / vmax)).astype(np.uint8)
        return cv2.applyColorMap(z8, cv2.COLORMAP_TURBO)
    else:
        return np.zeros((depth_m.shape[0], depth_m.shape[1], 3), dtype=np.uint8)

def find_pairs(img_dir, keyL, keyR):
    """
    Pair files by replacing keyL with keyR in the left filename.
    Example: ..._cam1_0001.png -> ..._cam2_0001.png
    """
    Ls = sorted(glob.glob(os.path.join(img_dir, f"*{keyL}*.*")))
    rights_all = set(sorted(glob.glob(os.path.join(img_dir, f"*{keyR}*.*"))))
    pairs = []
    for lp in Ls:
        rp = lp.replace(keyL, keyR)
        if rp in rights_all:
            pairs.append((lp, rp))
    return pairs

def reproject_points3d(disp, Q):
    """Reproject disparity to 3D points (meters) using Q."""
    return cv2.reprojectImageTo3D(disp, Q)

def sample_3d(pts3d, u, v, win=2):
    """
    Robustly sample a 3D point by taking the median within a small window.
    Returns None if no valid depth found.
    """
    h,w,_ = pts3d.shape
    u0,u1 = max(0,u-win), min(w,u+win+1)
    v0,v1 = max(0,v-win), min(h,v+win+1)
    patch = pts3d[v0:v1, u0:u1, :]
    m = np.isfinite(patch[...,2])
    if not np.any(m): return None
    return np.median(patch[m], axis=0)

def process_pair(left_path, right_path, calib, sgbm, out_dir, enable_measure=True):
    """
    Process a single pair:
      - Rectify, disparity, depth pseudo-color, save outputs
      - If enable_measure=True: open interactive measuring UI
    """
    # Read images
    imL_raw = cv2.imread(left_path, cv2.IMREAD_COLOR)
    imR_raw = cv2.imread(right_path, cv2.IMREAD_COLOR)
    if imL_raw is None or imR_raw is None:
        print(f"[Skip] Failed to read: {left_path} | {right_path}")
        return False
    if imL_raw.shape[:2] != imR_raw.shape[:2]:
        print(f"[Skip] Size mismatch: {left_path} | {right_path}")
        return False
    h,w = imL_raw.shape[:2]

    # Rectify
    map1L,map2L = make_rectify_maps(calib["K1"],calib["D1"],calib["R1"],calib["P1"],(w,h))
    map1R,map2R = make_rectify_maps(calib["K2"],calib["D2"],calib["R2"],calib["P2"],(w,h))
    imL = cv2.remap(imL_raw, map1L, map2L, cv2.INTER_LINEAR)
    imR = cv2.remap(imR_raw, map1R, map2R, cv2.INTER_LINEAR)

    # Disparity
    grayL = cv2.cvtColor(imL, cv2.COLOR_BGR2GRAY)
    grayR = cv2.cvtColor(imR, cv2.COLOR_BGR2GRAY)
    disp = sgbm.compute(grayL, grayR).astype(np.float32) / 16.0
    disp[disp <= 0] = np.nan
    disp_vis = colorize_disparity(disp)

    # 3D & depth
    pts3d = reproject_points3d(disp, calib["Q"])
    depth_m = pts3d[..., 2]
    depth_vis = colorize_depth(depth_m)

    # Save batch outputs
    stem = os.path.splitext(os.path.basename(left_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    cv2.imwrite(os.path.join(out_dir, f"{stem}_left_rect.png"), imL)
    cv2.imwrite(os.path.join(out_dir, f"{stem}_right_rect.png"), imR)
    cv2.imwrite(os.path.join(out_dir, f"{stem}_disp_vis.png"), disp_vis)
    cv2.imwrite(os.path.join(out_dir, f"{stem}_depth_vis.png"), depth_vis)
    np.save(os.path.join(out_dir, f"{stem}_disp.npy"), disp)
    np.save(os.path.join(out_dir, f"{stem}_depth_m.npy"), depth_m)

    if not enable_measure:
        return True

    # -------- Interactive measuring (optional) --------
    print("\n[Measure] UI controls — Left window is interactive:")
    print("  • Left click: select points (two at a time)")
    print("  • c: compute & log distance for the last two clicks")
    print("  • s: save CSV of all logged distances + annotated image")
    print("  • r: reset current clicks and overlay")
    print("  • n: next pair (finish this pair)")
    print("  • q: quit measuring for this pair\n")

    clicks = []            # current clicked 2D points [(u,v), ...]
    measures = []          # logged distances: [(u1,v1,x1,y1,z1, u2,v2,x2,y2,z2, dist_m, dist_mm)]
    view = imL.copy()

    def on_mouse(event, x, y, flags, param):
        nonlocal clicks, view
        if event == cv2.EVENT_LBUTTONDOWN:
            clicks.append((x,y))
            cv2.circle(view, (x,y), 5, (0,255,0), -1)
            cv2.putText(view, f"P{len(clicks)}({x},{y})", (x+6, y-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
            # Keep only the last two clicks visible
            if len(clicks) > 2:
                clicks = clicks[-2:]
                view = imL.copy()
                for i,(u,v) in enumerate(clicks,1):
                    cv2.circle(view, (u,v), 5, (0,255,0), -1)
                    cv2.putText(view, f"P{i}({u},{v})", (u+6, v-6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)

    cv2.namedWindow("Left (rectified) — measure", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Disparity", cv2.WINDOW_NORMAL)
    cv2.imshow("Disparity", disp_vis)
    cv2.setMouseCallback("Left (rectified) — measure", on_mouse)

    while True:
        cv2.imshow("Left (rectified) — measure", view)
        k = cv2.waitKey(20) & 0xFF
        if k == ord('q') or k == ord('n'):
            # End measuring for this pair
            break
        elif k == ord('r'):
            clicks.clear()
            view = imL.copy()
            print("[Measure] Cleared current clicks.")
        elif k == ord('c'):
            if len(clicks) < 2:
                print("[Measure] Need two clicks before 'c'.")
                continue
            (u1,v1),(u2,v2) = clicks[:2]
            p1 = sample_3d(pts3d, u1, v1, win=2)
            p2 = sample_3d(pts3d, u2, v2, win=2)
            if p1 is None or p2 is None or not np.all(np.isfinite([*p1, *p2])):
                print("[Measure] Invalid depth near clicked points; choose another area.")
                continue
            dist_m = float(np.linalg.norm(p1 - p2))
            dist_mm = dist_m * 1000.0
            measures.append((u1,v1,p1[0],p1[1],p1[2], u2,v2,p2[0],p2[1],p2[2], dist_m, dist_mm))
            # Draw line and label on the overlay
            line = view.copy()
            cv2.line(line, (u1,v1), (u2,v2), (0,255,255), 2)
            mid = ((u1+u2)//2, (v1+v2)//2)
            cv2.putText(line, f"{dist_mm:.1f} mm", (mid[0]+8, mid[1]-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255), 2)
            view = line
            print(f"[Measure] Distance: {dist_m:.4f} m ({dist_mm:.1f} mm)")
        elif k == ord('s'):
            # Save CSV + annotated image
            os.makedirs(out_dir, exist_ok=True)
            csv_path = os.path.join(out_dir, f"{stem}_measurements.csv")
            img_path = os.path.join(out_dir, f"{stem}_annotated.png")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["u1","v1","x1_m","y1_m","z1_m","u2","v2","x2_m","y2_m","z2_m","distance_m","distance_mm"])
                writer.writerows(measures)
            cv2.imwrite(img_path, view)
            print(f"[Measure] Saved CSV: {csv_path}")
            print(f"[Measure] Saved annotated image: {img_path}")

    # Close windows for this pair
    cv2.destroyWindow("Left (rectified) — measure")
    cv2.destroyWindow("Disparity")
    return True

def main():
    print(f"[Info] Loading calibration: {PARAMS_PATH}")
    calib = load_stereo_params(PARAMS_PATH)
    sgbm = build_sgbm(num_disp=192, block_size=5)  # keep same params

    pairs = find_pairs(IMG_DIR, CAM1_KEY, CAM2_KEY)
    if not pairs:
        raise FileNotFoundError(f"No pairs found in {IMG_DIR} using keys '{CAM1_KEY}' & '{CAM2_KEY}'")
    print(f"[Info] Found {len(pairs)} pairs. Processing... Results -> {os.path.abspath(SAVE_DIR)}")

    for i,(lp, rp) in enumerate(pairs, 1):
        print(f"\n[{i}/{len(pairs)}] {os.path.basename(lp)}  <->  {os.path.basename(rp)}")
        ok = process_pair(lp, rp, calib, sgbm, SAVE_DIR, enable_measure=True)
        if not ok:
            print("[Warn] Pair skipped due to errors.")

    print("\n[Done] All pairs processed.")

if __name__ == "__main__":
    main()

