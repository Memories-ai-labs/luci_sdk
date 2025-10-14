# stereo_depth_enhanced_en.py
# Near-field focused depth with richer, cleaner reconstruction:
# - Dual SGBM (block=3 & 7) + edge/consistency-aware fusion
# - Guided filtering (edge-preserving) refinement
# - Optional superpixel plane fill (SLIC + RANSAC)
# - Near-band disparity search & hard far-mask
# - 2-point measuring UI (English)

import json, glob, math
from pathlib import Path
import numpy as np, cv2

# ========= Config (edit) =========
PARAMS_PATH = "../calibration_result/stereo_params.yaml"
IMG_DIR     = "../test_images"
CAM1_KEY, CAM2_KEY = "cam1", "cam2"

# Near Z range of interest (meters)
NEAR_Z_MIN = 0.20
NEAR_Z_MAX = 2.0

# SGBM base settings
LRC_THRESH      = 1.0
SPECKLE_WIN     = 120
SPECKLE_RANGE   = 2
UNIQUENESS      = 8

# Postproc
USE_WLS             = True      # guided WLS on disparity
USE_GUIDED_ON_DEPTH = True      # ximgproc.guidedFilter on depth
USE_SUPERPIXEL_PLANE= True      # SLIC + plane fill (requires ximgproc)
GUIDED_RADIUS       = 9         # guided filter radius
GUIDED_EPS          = 1e-3      # guided filter eps (normalize 0..1 image)

# Preproc
ENABLE_HIST_MATCH   = True
ENABLE_BILATERAL    = True

# Save
SAVE_DIR = "./depth_out_enhanced"
# =================================

def load_params(path):
    t = Path(path).read_text(encoding="utf-8"); s,e = t.find("{"), t.rfind("}")
    d = json.loads(t[s:e+1])
    W,H = d["image_size"]["w"], d["image_size"]["h"]
    def M(key, r, c): return np.array(d[key], dtype=np.float64).reshape(r,c)
    K1 = M("K1",3,3); D1 = np.array(d["D1"], dtype=np.float64).reshape(1,-1)
    K2 = M("K2",3,3); D2 = np.array(d["D2"], dtype=np.float64).reshape(1,-1)
    R1 = M("R1",3,3); R2 = M("R2",3,3)
    P1 = M("P1",3,4); P2 = M("P2",3,4)
    Q  = M("Q", 4,4)
    roi1 = tuple(d.get("roi1", [0,0,W,H]))
    roi2 = tuple(d.get("roi2", [0,0,W,H]))
    return (W,H), K1,D1,K2,D2,R1,R2,P1,P2,Q, roi1, roi2

def strict_pairs(img_dir, k1, k2):
    exts = ("*.jpg","*.jpeg","*.png","*.bmp","*.tif","*.tiff")
    L = sorted([f for ext in exts for f in glob.glob(str(Path(img_dir)/ext))
                if k1.lower() in Path(f).name.lower()])
    R = sorted([f for ext in exts for f in glob.glob(str(Path(img_dir)/ext))
                if k2.lower() in Path(f).name.lower()])
    rmap = {Path(f).name.lower(): f for f in R}
    pairs, miss, extra = [], [], []
    for fl in L:
        n = Path(fl).name.lower()
        exp = n.replace(k1.lower(), k2.lower(), 1)
        if exp in rmap: pairs.append((fl, rmap[exp]))
        else: miss.append((Path(fl).name, exp))
    expected = set([Path(a).name.lower().replace(k1.lower(), k2.lower(), 1) for a,_ in pairs])
    for fr in R:
        if Path(fr).name.lower() not in expected: extra.append(Path(fr).name)
    if miss or extra or len(pairs)==0:
        msg = ["Strict pairing failed:"]
        if miss:  msg += [f"  - Left {a} -> expected Right {b}" for a,b in miss[:10]]
        if extra: msg += [f"  - Extra Right {n}" for n in extra[:10]]
        raise RuntimeError("\n".join(msg))
    print(f"[PAIR] {len(pairs)} pairs")
    return pairs

def make_maps(K1,D1,K2,D2,R1,R2,P1,P2,size):
    w,h = size
    m1x,m1y = cv2.initUndistortRectifyMap(K1,D1,R1,P1,(w,h),cv2.CV_32FC1)
    m2x,m2y = cv2.initUndistortRectifyMap(K2,D2,R2,P2,(w,h),cv2.CV_32FC1)
    return m1x,m1y,m2x,m2y

def fx_B_from_P(P1,P2):
    fx = float(P1[0,0]); B = float(-P2[0,3]/fx) if fx!=0 else None
    return fx, B

def d_from_Z(fx,B,Z): return (fx*B)/max(Z,1e-6)

def disp_window_for_near(fx,B,zmin,zmax, guard_low=6, guard_high=10):
    d_near = d_from_Z(fx,B,zmin)  # larger
    d_far  = d_from_Z(fx,B,zmax)  # smaller
    min_disp = int(max(0, np.floor(d_far) - guard_low))
    max_disp = int(np.ceil(d_near) + guard_high)
    num_disp = int(np.ceil((max_disp - min_disp)/16.0)*16)
    num_disp = max(64, min(512, num_disp))
    return min_disp, num_disp

def hist_match_R_to_L(R, L):
    src_yuv = cv2.cvtColor(R, cv2.COLOR_BGR2YCrCb)
    ref_yuv = cv2.cvtColor(L, cv2.COLOR_BGR2YCrCb)
    src_y, src_cr, src_cb = cv2.split(src_yuv)
    ref_y, _, _ = cv2.split(ref_yuv)
    hs,_ = np.histogram(src_y.ravel(),256,[0,256])
    hr,_ = np.histogram(ref_y.ravel(),256,[0,256])
    cdfs = np.cumsum(hs)/max(1,hs.sum())
    cdfr = np.cumsum(hr)/max(1,hr.sum())
    lut  = np.interp(cdfs, cdfr, np.arange(256)).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([cv2.LUT(src_y,lut), src_cr, src_cb]), cv2.COLOR_YCrCb2BGR)

def create_sgbm(num_disp, block, min_disp=0):
    P1 = 8*3*block*block; P2 = 32*3*block*block
    return cv2.StereoSGBM_create(
        minDisparity=min_disp, numDisparities=num_disp, blockSize=block,
        P1=P1, P2=P2,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        disp12MaxDiff=1, uniquenessRatio=UNIQUENESS,
        speckleWindowSize=SPECKLE_WIN, speckleRange=SPECKLE_RANGE
    )

def sgbm_with_wls(gL,gR,min_disp,num_disp,block):
    left = create_sgbm(num_disp, block, min_disp)
    dispL16 = left.compute(gL,gR)
    dispL = dispL16.astype(np.float32)/16.0
    dispR = None
    if USE_WLS:
        try:
            import cv2.ximgproc as xip
            right = xip.createRightMatcher(left)
            dispR16 = right.compute(gR,gL)
            dispR = dispR16.astype(np.float32)/16.0
            wls = xip.createDisparityWLSFilter(matcher_left=left)
            wls.setLambda(12000.0); wls.setSigmaColor(1.2)
            dispL = wls.filter(dispL16, gL, None, dispR16).astype(np.float32)/16.0
        except Exception:
            pass
    return dispL, dispR

def lrc_mask(dL, dR, t=LRC_THRESH):
    if dR is None: return np.ones_like(dL,bool)
    h,w = dL.shape
    xs = np.arange(w)[None,:].repeat(h,0).astype(np.float32)
    ys = np.arange(h)[:,None].repeat(w,1).astype(np.float32)
    xR = (xs - dL).round().astype(int); yR = ys.astype(int)
    valid = (xR>=0)&(xR<w)
    sampl = np.zeros_like(dR); sampl[valid] = dR[yR[valid], xR[valid]]
    ok = np.abs(dL + sampl) <= t
    return ok & valid

def edge_strength(img_bgr):
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g,(3,3),0)
    sx = cv2.Sobel(g, cv2.CV_32F, 1,0,ksize=3)
    sy = cv2.Sobel(g, cv2.CV_32F, 0,1,ksize=3)
    mag = cv2.magnitude(sx,sy)
    mag/= (mag.max()+1e-6)
    return mag

def fuse_disparities(d_small, d_large, edge_mag, conf_mask):
    # Rule: near edges -> prefer small-block (finer detail); in flat & confident -> prefer large-block
    th_edge = 0.15
    choose_small = (edge_mag >= th_edge)
    fused = d_large.copy()
    fused[choose_small] = d_small[choose_small]
    # keep only confident
    fused[~conf_mask] = 0.0
    return fused

def depth_from_Q(disp, Q):
    pts3 = cv2.reprojectImageTo3D(disp, Q)
    Z = pts3[:,:,2]
    return Z, pts3

def colorize_depth(Z, invalid_mask):
    valid = (~invalid_mask) & np.isfinite(Z) & (Z>0)
    if not np.any(valid):
        return np.zeros((Z.shape[0], Z.shape[1], 3), np.uint8)
    lo, hi = np.percentile(Z[valid], (2, 98))
    hi = max(hi, lo+1e-6)
    norm = np.zeros_like(Z, np.float32)
    norm[valid] = (Z[valid]-lo)/(hi-lo)
    norm = np.clip(norm,0,1)
    return cv2.applyColorMap((norm*255).astype(np.uint8), cv2.COLORMAP_JET)

def guided_filter_depth(Z, guide_bgr, radius=GUIDED_RADIUS, eps=GUIDED_EPS):
    try:
        import cv2.ximgproc as xip
        # normalize guide to 0..1 gray
        g = cv2.cvtColor(guide_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)/255.0
        Zm = Z.copy()
        mask = ~np.isfinite(Zm) | (Zm<=0)
        Zm[mask] = 0.0
        Zf = xip.guidedFilter(guide=g, src=Zm.astype(np.float32), radius=radius, eps=eps)
        Zf[mask] = 0.0
        return Zf
    except Exception:
        return Z

def superpixel_plane_fill(Z, img_bgr, max_size=200, ransac_thr=0.01):
    """SLIC superpixels; per superpixel plane fitting to fill holes & smooth flats."""
    try:
        import cv2.ximgproc as xip
        h,w = Z.shape
        sp = xip.createSuperpixelSLIC(img_bgr, algorithm=xip.SLICO, region_size=max(20, min(h,w)//50), ruler=10.0)
        sp.iterate(10)
        labels = sp.getLabels()
        n = sp.getNumberOfSuperpixels()
        Z_out = Z.copy()
        for lbl in range(n):
            mask = (labels==lbl)
            ys,xs = np.where(mask)
            if ys.size < 30: continue
            vals = Z[mask]
            ok = np.isfinite(vals) & (vals>0)
            if ok.sum() < 20:  # not enough valid -> skip
                continue
            # fit plane z = ax + by + c in pixel coords (scaled)
            xs_f = xs[ok].astype(np.float32)
            ys_f = ys[ok].astype(np.float32)
            zs_f = vals[ok].astype(np.float32)
            X = np.stack([xs_f, ys_f, np.ones_like(xs_f)], axis=1)  # [x y 1]
            # RANSAC
            rng = np.random.default_rng(123)
            best_inl = -1; best_abc = None
            for _ in range(60):
                idx = rng.choice(X.shape[0], size=min(20, X.shape[0]), replace=False)
                A = X[idx]; b = zs_f[idx]
                abc, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
                pred = (X @ abc)
                inl = np.sum(np.abs(pred - zs_f) < ransac_thr)
                if inl > best_inl:
                    best_inl = inl; best_abc = abc
            if best_abc is None: continue
            # fill missing or smooth using plane (but only where we were invalid/weak)
            pred_all = (np.stack([xs.astype(np.float32), ys.astype(np.float32), np.ones_like(xs, np.float32)],1) @ best_abc)
            # fill invalid
            inv = ~np.isfinite(vals) | (vals<=0)
            if inv.any():
                Z_out[ys[inv], xs[inv]] = pred_all[inv]
            # light smooth on valid too (blend)
            Z_out[ys[~inv], xs[~inv]] = 0.7*vals[~inv] + 0.3*pred_all[~inv]
        return Z_out
    except Exception:
        return Z

def roi_intersection(roi1, roi2):
    x1,y1,w1,h1 = roi1; x2,y2,w2,h2 = roi2
    r1=(x1,y1,x1+w1,y1+h1); r2=(x2,y2,x2+w2,y2+h2)
    xi1=max(r1[0],r2[0]); yi1=max(r1[1],r2[1]); xi2=min(r1[2],r2[2]); yi2=min(r1[3],r2[3])
    if xi2<=xi1 or yi2<=yi1: return (0,0,0,0)
    return (xi1,yi1,xi2-xi1,yi2-yi1)

def main():
    Path(SAVE_DIR).mkdir(parents=True, exist_ok=True)
    (W,H),K1,D1,K2,D2,R1,R2,P1,P2,Q, roi1, roi2 = load_params(PARAMS_PATH)
    m1x,m1y,m2x,m2y = make_maps(K1,D1,K2,D2,R1,R2,P1,P2,(W,H))
    pairs = strict_pairs(IMG_DIR, CAM1_KEY, CAM2_KEY)

    fx,B = fx_B_from_P(P1,P2)
    min_disp, num_disp = disp_window_for_near(fx,B,NEAR_Z_MIN,NEAR_Z_MAX)
    print(f"[Near band] fx={fx:.2f}px  B={B:.4f}m  Z∈[{NEAR_Z_MIN},{NEAR_Z_MAX}]m "
          f"-> minDisp={min_disp}, numDisp={num_disp}")

    roi = roi_intersection(roi1, roi2)
    has_roi = (roi[2]>0 and roi[3]>0)

    for i,(fl,fr) in enumerate(pairs):
        L = cv2.imdecode(np.fromfile(fl, dtype=np.uint8), cv2.IMREAD_COLOR)
        R = cv2.imdecode(np.fromfile(fr, dtype=np.uint8), cv2.IMREAD_COLOR)
        if L is None or R is None:
            print("Failed to read:", fl, fr); continue

        # Rectify
        rL = cv2.remap(L, m1x, m1y, cv2.INTER_LINEAR)
        rR = cv2.remap(R, m2x, m2y, cv2.INTER_LINEAR)
        if ENABLE_HIST_MATCH: rR = hist_match_R_to_L(rR, rL)
        if ENABLE_BILATERAL:
            rL = cv2.bilateralFilter(rL, 5, 10, 5)
            rR = cv2.bilateralFilter(rR, 5, 10, 5)

        gL = cv2.cvtColor(rL, cv2.COLOR_BGR2GRAY)
        gR = cv2.cvtColor(rR, cv2.COLOR_BGR2GRAY)

        # --- Dual SGBM ---
        d_small, dR_small = sgbm_with_wls(gL,gR,min_disp,num_disp,block=3)
        d_large, dR_large = sgbm_with_wls(gL,gR,min_disp,num_disp,block=7)

        # Consistency masks
        lrc_small = lrc_mask(d_small, dR_small)
        lrc_large = lrc_mask(d_large, dR_large)
        conf_small = (d_small > (min_disp+0.5)) & lrc_small
        conf_large = (d_large > (min_disp+0.5)) & lrc_large

        # Edge-aware fusion
        edges = edge_strength(rL)   # 0..1
        conf = conf_small | conf_large
        disp_fused = fuse_disparities(d_small, d_large, edges, conf)

        # Depth
        Z, pts3 = depth_from_Q(disp_fused, Q)
        invalid = ~conf | ~np.isfinite(Z) | (Z<=0) | (Z > NEAR_Z_MAX)
        if has_roi:
            x,y,wroi,hroi = roi
            roi_mask = np.zeros_like(invalid,bool); roi_mask[y:y+hroi,x:x+wroi]=True
            invalid |= ~roi_mask

        # Superpixel plane fill (optional) to add structure on flats / fill small holes
        if USE_SUPERPIXEL_PLANE:
            Z = superpixel_plane_fill(Z, rL, max_size=200, ransac_thr=0.01)
            invalid |= ~np.isfinite(Z) | (Z<=0) | (Z>NEAR_Z_MAX)

        # Guided filtering on depth (edge-preserving smoothing)
        if USE_GUIDED_ON_DEPTH:
            Z = guided_filter_depth(Z, rL, radius=GUIDED_RADIUS, eps=GUIDED_EPS)
            invalid |= ~np.isfinite(Z) | (Z<=0) | (Z>NEAR_Z_MAX)

        # Visualization
        depth_vis = colorize_depth(Z, invalid)
        vis = rL.copy()
        small = cv2.resize(depth_vis, (vis.shape[1]//3, vis.shape[0]//3))
        vis[0:small.shape[0], vis.shape[1]-small.shape[1]:vis.shape[1]] = small

        base = str(Path(SAVE_DIR)/f"pair_{i:03d}")
        Path(SAVE_DIR).mkdir(parents=True, exist_ok=True)
        cv2.imencode(".jpg", rL)[1].tofile(base+"_rectL.jpg")
        cv2.imencode(".jpg", vis)[1].tofile(base+"_depth_vis.jpg")

        # Save depth
        Z_mm = np.where((~invalid)&np.isfinite(Z)&(Z>0), (Z*1000.0), 0).astype(np.uint16)
        cv2.imencode(".png", Z_mm)[1].tofile(base+"_depth_mm.png")
        np.save(base+"_depth.npy", Z.astype(np.float32))

        # --- Interactive 2-point distance (near-only valid) ---
        clicks = []
        def robust_xyz_at(u,v,ks=5):
            h,w = Z.shape; x0,x1 = max(0,u-ks),min(w-1,u+ks); y0,y1=max(0,v-ks),min(h-1,v+ks)
            patch = pts3[y0:y1+1, x0:x1+1, :]
            m = (~invalid[y0:y1+1, x0:x1+1]) & np.isfinite(patch).all(2)
            if not np.any(m): return None
            return np.median(patch[m],0)
        def dist3(a,b): return float(np.linalg.norm(a-b))
        win = "depth-enhanced-measure"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)

        canvas = vis.copy()
        cv2.putText(canvas, "[HELP] e=2-point  c=clear  q/ESC=quit",
                    (10,26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
        def on_mouse(event,x,y,flags,param):
            nonlocal canvas, clicks
            if event==cv2.EVENT_LBUTTONDOWN:
                P = robust_xyz_at(x,y,ks=5)
                if P is None:
                    cv2.circle(canvas,(x,y),5,(0,0,255),-1)
                    cv2.putText(canvas,"NaN",(x+6,y-6),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,255),1)
                else:
                    cv2.circle(canvas,(x,y),5,(0,255,0),-1)
                    cv2.putText(canvas,f"Z={P[2]:.3f} m",(x+6,y-6),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),2)
                clicks.append((x,y,P))
                if len(clicks)%2==0:
                    (x1,y1,p1),(x2,y2,p2) = clicks[-2], clicks[-1]
                    if p1 is not None and p2 is not None:
                        d = dist3(p1,p2)
                        cv2.line(canvas,(x1,y1),(x2,y2),(255,0,0),2)
                        mid = ((x1+x2)//2,(y1+y2)//2)
                        cv2.putText(canvas,f"{d:.4f} m", mid, cv2.FONT_HERSHEY_SIMPLEX,0.6,(255,0,0),2)
        cv2.setMouseCallback(win, on_mouse)

        while True:
            cv2.imshow(win, canvas)
            k = cv2.waitKey(1) & 0xFF
            if k in (ord('q'),27): break
            elif k == ord('c'):
                clicks.clear()
                canvas = vis.copy()
                cv2.putText(canvas, "[HELP] e=2-point  c=clear  q/ESC=quit",
                            (10,26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
        cv2.destroyWindow(win)

if __name__ == "__main__":
    main()
