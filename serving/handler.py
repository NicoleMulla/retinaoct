"""HuggingFace Inference Endpoints handler — OLIVES biomarkers from an OCT B-scan.

Public uploads are untrusted and mostly will not be OLIVES-style Spectralis
B-scans, so the model is never reached unless the image passes a distance gate
in the encoder's embedding space. Without that, the endpoint returns sixteen
confident probabilities for a fundus photo, a phone snap, or a chest X-ray.

Verdicts:
  ok            in-domain          full predictions
  out_of_domain OCT-like but off   predictions returned, explicitly unvalidated
  rejected      far outside        no predictions at all

Repo layout expected by the endpoint:
  handler.py  model.pt  reference.npz  serving_config.json  requirements.txt
"""
import base64, io, json, os
import numpy as np, torch, timm
from PIL import Image

MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
SIDE = 224
MAX_PIXELS = 40_000_000          # reject decompression bombs before decode
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class EndpointHandler:
    def __init__(self, path=""):
        cfg = json.load(open(os.path.join(path, "serving_config.json")))
        self.bm       = cfg["biomarkers"]
        self.usable   = cfg["usable"]
        self.thr      = cfg["thresholds"]
        self.gate     = cfg["gate"]
        self.license  = cfg["license"]

        ref = np.load(os.path.join(path, "reference.npz"))
        self.mu, self.P = ref["mu"], ref["precision"]

        ck = torch.load(os.path.join(path, "model.pt"), map_location="cpu",
                        weights_only=False)
        self.model = timm.create_model("vit_large_patch16_224",
                                       pretrained=False, num_classes=len(self.bm))
        self.model.load_state_dict(ck["model"])
        self.model.eval()
        torch.set_num_threads(max(1, os.cpu_count() or 1))

    # ---------- input handling ----------

    def _decode(self, blob):
        if isinstance(blob, str):
            blob = base64.b64decode(blob)
        im = Image.open(io.BytesIO(blob))
        im.verify()                              # cheap structural check
        im = Image.open(io.BytesIO(blob))
        if im.width * im.height > MAX_PIXELS:
            raise ValueError("image too large")
        return im

    def _preprocess(self, im):
        """Scale until the shorter side reaches 224, then centre-crop the
        overflow. One rule for every input, no special case.

        This previously cropped to a square only when the aspect ratio fell
        outside 0.8-1.25 and resized non-uniformly otherwise, which squashed
        57% of Kermany scans by up to 25%. Layer geometry is the whole signal,
        so distorting it is worse than cropping it. For genuinely wide scans
        the two routes select the same region; the difference is confined to
        the band that used to be squashed.

        Resizing before cropping also leaves real pixels just outside the crop
        for the resampling kernel to draw on, so the edges are slightly
        cleaner than cropping at full resolution first."""
        im = im.convert("RGB")
        w, h = im.size
        notes = []
        scale = max(SIDE / w, SIDE / h)
        nw, nh = max(SIDE, round(w * scale)), max(SIDE, round(h * scale))
        if (nw, nh) != (w, h):
            im = im.resize((nw, nh), Image.BICUBIC)
        kept = 100.0 * min(w, h) / max(w, h)
        if (nw, nh) != (SIDE, SIDE):
            left, top = (nw - SIDE) // 2, (nh - SIDE) // 2
            im = im.crop((left, top, left + SIDE, top + SIDE))
        # Only say so when it is worth saying. Every image is cropped by some
        # sub-pixel amount after a uniform scale, and reporting "centre-cropped"
        # on a 504x496 scan that kept 98% reads as a warning about nothing.
        if kept < 95.0:
            notes.append(f"centre-cropped from {w}x{h} (aspect {w/h:.2f}:1); "
                         f"{kept:.0f}% of the longer side was analysed")
        x = np.asarray(im, dtype=np.float32) / 255.0
        x = (x - np.array(MEAN)) / np.array(STD)
        return torch.from_numpy(x.transpose(2, 0, 1)).float()[None], notes

    # ---------- inference ----------

    def __call__(self, data):
        blob = data.get("inputs")
        if blob is None:
            return {"error": "no 'inputs' field"}
        try:
            im = self._decode(blob)
        except Exception as e:
            return {"error": f"could not decode image: {e}"}

        x, notes = self._preprocess(im)
        # Follow the model's device: CPU here, CUDA under ZeroGPU. Both moves
        # are no-ops when the model is already on the CPU, so this changes
        # nothing about CPU results.
        x = x.to(next(self.model.parameters()).device)
        with torch.no_grad():
            f = self.model.forward_features(x)[:, 0]
            logits = self.model.head(self.model.fc_norm(f)) \
                     if hasattr(self.model, "fc_norm") else self.model.head(f)
            probs = torch.sigmoid(logits.float()).cpu().numpy()[0]

        e = f.float().cpu().numpy()[0] - self.mu
        dist = float(np.sqrt(e @ self.P @ e))

        if dist > self.gate["loose"]:
            return {"verdict": "rejected", "distance": round(dist, 1),
                    "reason": "image is far outside the training distribution "
                              "(not an OCT B-scan, or a very different device)",
                    "predictions": None, "notes": notes, "license": self.license}

        verdict = "ok" if dist <= self.gate["strict"] else "out_of_domain"
        out = []
        for j, b in enumerate(self.bm):
            if not self.usable[j]:
                continue                       # too few training patients to mean anything
            p = float(probs[j])
            out.append({"biomarker": b, "probability": round(p, 4),
                        "present": bool(p >= self.thr[b]),
                        "threshold": self.thr[b]})
        out.sort(key=lambda r: -r["probability"])

        res = {"verdict": verdict, "distance": round(dist, 1),
               "in_domain_median": self.gate["in_domain_median"],
               "predictions": out, "notes": notes,
               "suppressed": [b for b, u in zip(self.bm, self.usable) if not u],
               "license": self.license,
               "disclaimer": "Research use only. Not a medical device and not "
                             "for diagnostic use."}
        if verdict == "out_of_domain":
            res["warning"] = ("This image is OCT-like but outside the distribution "
                              "the model was validated on (OLIVES / Spectralis). "
                              "Predictions are unvalidated — treat as indicative only.")
        return res
