#!/usr/bin/env python3
"""Continue RETFound's MAE pretraining on the OLIVES corpus, then the biomarker
head is fine-tuned on top (train_olives_v2.py --weights mae_olives).

Why this and not a bigger model: the scaling sweep showed a 7.4x parameter
increase bought +0.0059 while swapping ImageNet pretraining for RETFound bought
+0.011. Pretraining is the lever; capacity is not. See docs/scaling.md.

Why it should transfer: the official checkpoint records its own pretraining
corpus as `oct/topcon_median_slice/` — RETFound's OCT stage was trained on
**Topcon** scans. OLIVES is **Spectralis**. Continuing MAE on 153,045 OLIVES
B-scans adapts the encoder to the device actually being served.

Hyperparameters are taken from the checkpoint's own `args` rather than guessed:
mask_ratio 0.85, norm_pix_loss, base lr 1.5e-4, 15 warmup epochs.

  python3 mae_continue.py --ckpt RETFound_mae_natureOCT.pth --epochs 100
"""
import argparse, json, math, os, sys, time
import numpy as np, torch, torch.nn as nn
from PIL import Image
from torch.utils.data import Dataset, DataLoader

ROOT = os.environ.get("OLIVES_MAE_ROOT", "/workspace/mae_data")
OUT  = os.environ.get("OLIVES_MAE_OUT", "/workspace/mae_out")
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


class Scans(Dataset):
    """Unlabelled B-scans. Augmentation is deliberately mild — MAE's own masking
    is the hard task, and heavy geometric warping fights the reconstruction
    objective."""
    def __init__(self, files, img=224):
        self.files, self.img = files, img
    def __len__(self): return len(self.files)
    def __getitem__(self, i):
        im = Image.open(self.files[i]).convert("RGB")
        if np.random.rand() < 0.5: im = im.transpose(Image.FLIP_LEFT_RIGHT)
        s = np.random.uniform(0.85, 1.0)
        w, h = im.size; cw, ch = int(w*s), int(h*s)
        x0 = np.random.randint(0, w-cw+1); y0 = np.random.randint(0, h-ch+1)
        im = im.crop((x0, y0, x0+cw, y0+ch)).resize((self.img, self.img), Image.BICUBIC)
        x = (np.asarray(im, dtype=np.float32)/255.0 - np.array(MEAN))/np.array(STD)
        return torch.from_numpy(x.transpose(2, 0, 1)).float()


def build_mae(ckpt_path, mask_ratio, norm_pix_loss):
    """timm's MAE isn't a drop-in for the original facebookresearch layout, so the
    model is built from timm's ViT and given the original decoder, matching the
    checkpoint's key names exactly."""
    import timm
    from timm.models.vision_transformer import Block

    class MAE(nn.Module):
        def __init__(self, dec_dim=512, dec_depth=8, dec_heads=16):
            super().__init__()
            v = timm.create_model("vit_large_patch16_224", pretrained=False, num_classes=0)
            self.patch_embed = v.patch_embed
            self.blocks = v.blocks
            self.norm = v.norm
            self.cls_token = v.cls_token
            self.pos_embed = v.pos_embed
            n = self.patch_embed.num_patches
            self.mask_token = nn.Parameter(torch.zeros(1, 1, dec_dim))
            self.decoder_embed = nn.Linear(1024, dec_dim, bias=True)
            self.decoder_pos_embed = nn.Parameter(torch.zeros(1, n+1, dec_dim))
            self.decoder_blocks = nn.ModuleList(
                [Block(dec_dim, dec_heads, 4.0, qkv_bias=True) for _ in range(dec_depth)])
            self.decoder_norm = nn.LayerNorm(dec_dim)
            self.decoder_pred = nn.Linear(dec_dim, 16*16*3, bias=True)
            self.norm_pix_loss = norm_pix_loss

        def patchify(self, x):
            p = 16; B, C, H, W = x.shape; h = w = H // p
            x = x.reshape(B, C, h, p, w, p).permute(0, 2, 4, 3, 5, 1)
            return x.reshape(B, h*w, p*p*C)

        def random_mask(self, x, ratio):
            B, L, D = x.shape
            keep = int(L * (1 - ratio))
            noise = torch.rand(B, L, device=x.device)
            shuf = torch.argsort(noise, dim=1)
            restore = torch.argsort(shuf, dim=1)
            idx = shuf[:, :keep]
            kept = torch.gather(x, 1, idx.unsqueeze(-1).repeat(1, 1, D))
            mask = torch.ones(B, L, device=x.device)
            mask[:, :keep] = 0
            mask = torch.gather(mask, 1, restore)
            return kept, mask, restore

        def forward(self, imgs, ratio):
            x = self.patch_embed(imgs)
            x = x + self.pos_embed[:, 1:, :]
            x, mask, restore = self.random_mask(x, ratio)
            cls = (self.cls_token + self.pos_embed[:, :1, :]).expand(x.shape[0], -1, -1)
            x = torch.cat([cls, x], dim=1)
            for b in self.blocks: x = b(x)
            x = self.norm(x)

            y = self.decoder_embed(x)
            B, _, D = y.shape
            L = restore.shape[1]
            pad = self.mask_token.repeat(B, L + 1 - y.shape[1], 1)
            y_ = torch.cat([y[:, 1:, :], pad], dim=1)
            y_ = torch.gather(y_, 1, restore.unsqueeze(-1).repeat(1, 1, D))
            y = torch.cat([y[:, :1, :], y_], dim=1) + self.decoder_pos_embed
            for b in self.decoder_blocks: y = b(y)
            y = self.decoder_pred(self.decoder_norm(y))[:, 1:, :]

            tgt = self.patchify(imgs)
            if self.norm_pix_loss:
                mu = tgt.mean(-1, keepdim=True); var = tgt.var(-1, keepdim=True)
                tgt = (tgt - mu) / (var + 1e-6) ** .5
            loss = ((y - tgt) ** 2).mean(-1)
            return (loss * mask).sum() / mask.sum()

    m = MAE()
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    sd = ck.get("model", ck)
    missing, unexpected = m.load_state_dict(sd, strict=False)
    enc_missing = [k for k in missing if "decoder" not in k and "mask_token" not in k]
    print(f"  loaded {len(sd)} tensors from epoch {ck.get('epoch','?')}")
    print(f"  missing {len(missing)} (encoder-side: {len(enc_missing)}), unexpected {len(unexpected)}")
    if enc_missing[:5]: print(f"  encoder gaps: {enc_missing[:5]}")
    return m, ck.get("epoch", 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--blr", type=float, default=1.5e-4, help="base lr, from checkpoint args")
    ap.add_argument("--mask-ratio", type=float, default=0.85, help="from checkpoint args")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    files = []
    for r, _, fs in os.walk(ROOT):
        for f in fs:
            if f.lower().endswith((".tif", ".png", ".jpg")): files.append(os.path.join(r, f))
    files.sort()
    if a.limit: files = files[:a.limit]
    print(f"{len(files):,} B-scans for MAE continuation")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("building model...")
    model, start_ep = build_mae(a.ckpt, a.mask_ratio, True)
    model.to(dev)

    eff = a.bs * a.accum
    lr = a.blr * eff / 256                      # linear scaling rule, as in MAE
    print(f"effective batch {eff}, lr {lr:.2e}, mask ratio {a.mask_ratio}, "
          f"resuming from epoch {start_ep}")

    dl = DataLoader(Scans(files), batch_size=a.bs, shuffle=True, num_workers=a.workers,
                    pin_memory=True, drop_last=True, persistent_workers=True)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95), weight_decay=0.05)
    scaler = torch.amp.GradScaler("cuda", enabled=(dev == "cuda"))
    os.makedirs(OUT, exist_ok=True)
    steps_per_ep = len(dl)

    hist = []
    for ep in range(1, a.epochs+1):
        model.train(); t0 = time.time(); tot = 0.0; n = 0
        for i, x in enumerate(dl):
            # half-cycle cosine with warmup, matching the original schedule
            frac = (ep-1) + i/steps_per_ep
            if frac < a.warmup: cur = lr * frac / a.warmup
            else: cur = lr * 0.5 * (1 + math.cos(math.pi*(frac-a.warmup)/(a.epochs-a.warmup)))
            for g in opt.param_groups: g["lr"] = cur

            x = x.to(dev, non_blocking=True)
            with torch.amp.autocast("cuda", enabled=(dev == "cuda")):
                loss = model(x, a.mask_ratio) / a.accum
            scaler.scale(loss).backward()
            if (i+1) % a.accum == 0:
                scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True)
            tot += loss.item()*a.accum*len(x); n += len(x)
        el = time.time()-t0
        hist.append(dict(epoch=ep, loss=tot/max(n,1), lr=cur, seconds=round(el)))
        print(f"ep {ep:>3}/{a.epochs}  mae_loss {tot/max(n,1):.4f}  lr {cur:.2e}  {el:.0f}s", flush=True)
        if ep % 10 == 0 or ep == a.epochs:
            torch.save({"model": model.state_dict(), "epoch": start_ep+ep,
                        "mae_loss": tot/max(n,1), "continued_on": "OLIVES",
                        "n_images": len(files), "args": vars(a)},
                       f"{OUT}/mae_olives_ep{ep}.pt")
            json.dump(hist, open(f"{OUT}/mae_history.json","w"), indent=1)
    # encoder-only export, in the layout train_olives_v2.py expects
    enc = {k: v for k, v in model.state_dict().items()
           if not k.startswith(("decoder", "mask_token"))}
    torch.save({"model": enc}, f"{OUT}/mae_olives_encoder.pt")
    print(f"\nwrote {OUT}/mae_olives_encoder.pt ({len(enc)} tensors)")


if __name__ == "__main__":
    main()
