# Figure 1 — caption

**File:** `fig1-pipeline.svg` · 180 × 144 mm (double-column) · vector, no raster elements

---

**Figure 1. From retinal OCT acquisition to biomarker-informed clinical interpretation.**
**(A)** OCT images the macula through the cornea and lens, resolving the retina in
cross-section across approximately 6 mm. **(B)** Each acquisition yields a volume of 49
contiguous B-scans (Heidelberg Spectralis, 504 × 496 px, 8-bit greyscale). **(C)** A single
B-scan resolves the retina by depth — vitreous gel (1), inner retina (2), photoreceptor
layers (3) and the retinal pigment epithelium (4) — with the foveal depression at the
centre. **(D)** A RETFound ViT-L/16 encoder (303M parameters, retinal pre-training) with
sixteen independent sigmoid heads was fine-tuned on 9,408 expert-annotated B-scans from
87 patients under five-fold patient-grouped cross-validation with zero patient overlap,
reaching mean AUROC 0.8916 ± 0.0360 across the twelve evaluable biomarkers, and was then
applied to 143,607 previously unlabelled scans. Filled squares denote emitted biomarkers;
open squares the four withheld. **(E)** The sixteen biomarkers divide into four classes,
each bearing on a distinct clinical question. Asterisks mark the four biomarkers whose
positive examples originated from only one to five patients; these cannot be validated
under a patient-grouped split, and no value is emitted for them rather than a guessed
negative. **(F)** Summary of contribution and of the binding limitation.

*Abbreviations:* EZ, ellipsoid zone; DRIL, disorganisation of retinal inner layers; PED,
pigment epithelial detachment; RPE, retinal pigment epithelium.

*Schematics are illustrative and are not reproduced patient images.*

---

## Submission notes

- **Size** `width="180mm" height="144mm"`, `viewBox="0 0 510 408"`. One user unit = 1 pt,
  so stated font sizes are true point sizes. Smallest type is 5.5 pt (panel D legend);
  raise the viewBox scale if a journal sets a 6 pt or 7 pt floor.
- **Self-contained** no external images, stylesheets, fonts or scripts; renders identically
  offline. Verified: no external references.
- **Fonts** `Helvetica, Arial, sans-serif` only. If the publisher requires it, convert text
  to outlines on export (Illustrator: Type → Create Outlines; Inkscape: Path → Object to
  Path) and keep this file as the editable master.
- **Colour** four categorical hues — `#2a78d6` blue, `#eb6834` orange, `#1baf7a` green,
  `#4a3aa7` violet — validated for colour-vision deficiency across all pairs
  (worst pair ΔE 9.2 deutan, 16.3 normal vision). Every colour-coded block is also
  labelled in text, so no information is carried by colour alone. Safe in greyscale.
- **If a journal wants raster too** `rsvg-convert -d 600 -p 600 fig1-pipeline.svg -o fig1.png`
  or `inkscape --export-dpi=600 --export-type=png fig1-pipeline.svg` for 600 dpi.
