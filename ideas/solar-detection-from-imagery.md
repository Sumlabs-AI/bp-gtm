# Idea: detect rooftop solar from aerial imagery

Status: **later** (captured 2026-09-26). Not scheduled.

## Why

Solar is one of the strongest lead signals (Base sells battery + backup to homes that often
already have panels), but our structured sources are thin or lagging:

- Permits: Harris County's feed records almost no residential solar; Houston's weekly
  reports only go back to Jan 2026.
- HCAD appraisal "extra features" flag solar PV on ~22k Harris homes (now used in scoring),
  but only once the appraiser has recorded it, which can lag installs by a year or more.

Imagery would catch panels regardless of permits or appraisal lag, and in every county.

## Sketch

1. For each eligible lead (lat/lon from county parcels), fetch a small roof-level image tile.
2. Run a vision model: either a multimodal LLM ("are there solar panels on this roof? count
   them") or a dedicated detector/segmenter (cheaper at scale, e.g. a fine-tuned YOLO /
   segmentation model; self-supervised vision backbones help with few labels).
3. Store `solar_detected`, confidence, image date and source as a new signal with evidence
   (thumbnail), and only count it above a confidence threshold.
4. Re-run for new leads weekly and for everyone yearly (new imagery vintages).

**Free labels:** the ~22k HCAD solar flags (plus permits) are ground truth for training and
for measuring precision/recall before trusting the detector.

## Imagery options (check terms first)

| Source | Resolution | Notes |
| --- | --- | --- |
| Google Maps satellite / Static Maps / Map Tiles API | High | Google Maps Platform terms restrict extracting or deriving data from Google imagery and storing it outside Google products; running our own detection on it is likely not allowed. Needs legal review before any use. Google's **Solar API** gives roof solar *potential*, not existing panels. |
| TxGIO StratMap orthoimagery | ~15–30 cm in metro counties | Public Texas imagery program; check vintage per county. Likely the best free option. |
| USDA NAIP | ~60 cm | Public domain, statewide, every ~2 years; panels are borderline visible at this resolution. |
| Nearmap / EagleView / Vexcel | ~5–10 cm, frequent | Commercial licenses explicitly allow analytics; cost scales with area. |

## Open questions

- Cost per home at ~800k Harris leads (LLM vision vs. own detector).
- Imagery date vs. install date: how fresh does it need to be?
- Store only derived flags + confidence, not the imagery itself, unless the license allows it.
