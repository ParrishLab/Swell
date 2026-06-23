# Performance and Quality Optimization Plan

## Purpose

Define a ranked plan to improve:

- application responsiveness
- end-to-end processing speed
- segmentation quality

This plan separates runtime optimizations from model-quality work so they can be prioritized independently.

## Context

The current analysis workflow has three major cost centers:

1. frame preprocessing
2. SAM 2.1 initialization and propagation
3. UI-driven repeated inference and redraw work

Relevant implementation points:

- preprocessing stack construction: [swell/shared/frame_source/preprocessing.py](/Users/claydunford/Development/Combined tool test/swell/shared/frame_source/preprocessing.py)
- host popup processing and caches: [swell/host/processing_engine.py](/Users/claydunford/Development/Combined tool test/swell/host/processing_engine.py)
- trace computation: [swell/host/signal_analysis.py](/Users/claydunford/Development/Combined tool test/swell/host/signal_analysis.py)
- SAM 2.1 initialization: [swell/analysis/core/segmentation.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/segmentation.py)
- prompt inference and propagation: [swell/analysis/core/inference_manager.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/inference_manager.py)

## Ranking Method

Items are ranked by:

- expected impact
- implementation risk
- fit with current architecture
- likelihood of helping on current hardware

Priority labels:

- P1: high-value and low-to-moderate risk
- P2: meaningful but requires more architecture work
- P3: valuable later or only after measurement confirms the bottleneck

## Section 1: Low-Risk Speed Wins

### P1. Cache SAM-ready frame directories

Problem:

- SAM initialization currently serializes every visualization frame to disk before `predictor.init_state(...)`.

Current behavior:

- each frame is converted from grayscale to BGR and written via `cv2.imwrite(...)` during initialization

Relevant code:

- [swell/analysis/core/segmentation.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/segmentation.py#L440)

Proposal:

- cache exported SAM-ready frame directories keyed by:
  - event or stack scope
  - preprocessing settings
  - frame count
  - checkpoint-compatible visualization mode
- reuse the directory when none of those inputs changed

Expected impact:

- materially faster model reinitialization
- reduced event-open latency
- less repeated disk work

Risk:

- low

Notes:

- this treats the cause rather than the symptom by removing repeated work instead of trying to hide it

### P1. Reuse computed visualization stats everywhere possible

Problem:

- baseline and normalization stats can be recomputed across multiple flows unless shared explicitly

Relevant code:

- [swell/shared/frame_source/preprocessing.py](/Users/claydunford/Development/Combined tool test/swell/shared/frame_source/preprocessing.py#L140)
- [swell/shared/frame_source/preprocessing.py](/Users/claydunford/Development/Combined tool test/swell/shared/frame_source/preprocessing.py#L174)

Proposal:

- compute visualization stats once per event plus processing-settings tuple
- pass those stats through:
  - event-open preprocessing
  - popup preview generation
  - specialist dataset export
  - SAM-ready frame export

Expected impact:

- lower repeated percentile and baseline work
- more consistent visual behavior across the app

Risk:

- low

### P1. Add analysis-mode read-ahead and prewarming

Problem:

- nearby frames are often requested immediately after the current frame
- current popup processing has warm-up logic, but analysis mode can likely benefit from a broader equivalent

Relevant code:

- [swell/host/processing_engine.py](/Users/claydunford/Development/Combined tool test/swell/host/processing_engine.py#L115)
- [swell/analysis/controllers/host_mode_controller.py](/Users/claydunford/Development/Combined tool test/swell/analysis/controllers/host_mode_controller.py)

Proposal:

- on frame navigation, prewarm a configurable window around the active frame
- precompute:
  - raw frame reads
  - smoothed frames
  - normalized visualization frames

Expected impact:

- smoother scrubbing
- lower apparent latency during manual review

Risk:

- low to moderate

### P1. Reduce unnecessary redraw frequency

Problem:

- some UI updates and marker recomputations are triggered frequently during inference and propagation

Relevant code:

- [swell/analysis/core/inference_manager.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/inference_manager.py#L359)

Proposal:

- batch UI refreshes where possible
- avoid immediate redraw when result is not visible
- defer marker recomputation during grouped updates

Expected impact:

- better perceived responsiveness
- less main-thread churn

Risk:

- low

## Section 2: Best Multithreading Opportunities

### P1. Parallelize frame export for SAM initialization

Problem:

- frame export for SAM init is currently a serial loop

Relevant code:

- [swell/analysis/core/segmentation.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/segmentation.py#L443)

Proposal:

- use a bounded thread pool for image encoding and writing
- preserve deterministic frame naming
- combine with directory caching so only missing outputs are written

Expected impact:

- faster cold start for SAM initialization

Risk:

- low to moderate

Constraints:

- cap worker count to avoid saturating disk and harming UI responsiveness

### P1. Turn preprocessing into a staged producer-consumer pipeline

Problem:

- frame read, smoothing, subtraction, normalization, and output creation are mostly done serially

Relevant code:

- [swell/shared/frame_source/preprocessing.py](/Users/claydunford/Development/Combined tool test/swell/shared/frame_source/preprocessing.py#L192)

Proposal:

- use a small number of bounded worker threads
- split into stages:
  - read frames
  - smooth and subtract
  - normalize and convert to uint8
  - optional SAM-ready export

Expected impact:

- better overlap of I/O and CPU work
- faster event preparation

Risk:

- moderate

Notes:

- this is a better use of multithreading than trying to run multiple SAM predictions concurrently on one GPU

### P1. Background prefetch queue for user navigation

Problem:

- user movement through frames is locally predictable

Proposal:

- queue likely-next frames for preprocessing based on:
  - current frame
  - scrub direction
  - active event range

Expected impact:

- lower interaction latency

Risk:

- low to moderate

### P2. Parallelize trace computation

Problem:

- `compute_trace(...)` is a serial pass over all frames and uses uncached reads

Relevant code:

- [swell/host/signal_analysis.py](/Users/claydunford/Development/Combined tool test/swell/host/signal_analysis.py#L12)

Proposal:

- process frames in chunks
- use either:
  - a bounded thread pool if I/O dominates
  - a process pool if CPU statistics dominate and memory cost is acceptable
- benchmark first before choosing thread vs process

Expected impact:

- faster stack-level analysis metrics

Risk:

- moderate

### P2. Background checkpoint/config preparation

Problem:

- some SAM initialization work can begin before all frames are ready

Proposal:

- pre-resolve checkpoint metadata
- pre-validate config candidates
- warm any reusable runtime state before final init

Expected impact:

- lower apparent initialization latency

Risk:

- moderate

## Section 3: Medium-Risk Architectural Changes

### P2. Separate preview resolution from model resolution

Problem:

- the app may be doing more work than needed for on-screen preview while the model requires full-quality data

Proposal:

- maintain a lightweight preview representation for UI rendering
- preserve full-quality frames for model and export paths

Expected impact:

- improved UI responsiveness
- reduced redraw cost

Risk:

- moderate because overlay and export behavior must remain consistent

### P2. Persistent prepared-frame cache

Problem:

- opening the same event again may repeat much of the same preprocessing work

Proposal:

- persist prepared raw/subtracted/visual outputs on disk
- invalidate by:
  - source stack fingerprint
  - event scope
  - preprocessing settings
  - app version if needed

Expected impact:

- major speedup for repeated sessions on the same project

Risk:

- moderate

### P2. Decouple analysis responsiveness from model state transitions

Problem:

- the analysis workflow still has points where model state changes can feel blocking

Proposal:

- keep analysis UI usable while model prep continues in background
- make intermediate states explicit:
  - frames ready
  - preview ready
  - model ready

Expected impact:

- better perceived performance without changing core compute cost

Risk:

- moderate

## Section 4: Model-Quality Improvements

These improve results rather than raw speed. Some also reduce operator time, which improves throughput at the workflow level.

### P1. Specialist auto-initializer

Problem:

- the current SAM workflow relies heavily on prompt quality

Proposal:

- train a lightweight specialist baseline
- use it to generate an initial mask
- inject that mask into the current analysis flow before propagation

Integration fit:

- compatible with the existing mask injection path and `masks_cache`

Expected impact:

- fewer manual prompts
- better initialization on hard cases
- lower user correction time

Risk:

- moderate

### P1. Better threshold calibration for logits-to-mask conversion

Problem:

- mask output currently depends on a sensitivity threshold after logit generation

Relevant code:

- [swell/analysis/core/inference_manager.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/inference_manager.py#L359)

Proposal:

- calibrate thresholds by:
  - stack
  - event type
  - confidence regime
- compare static threshold vs adaptive threshold

Expected impact:

- better precision/recall balance with minimal compute cost

Risk:

- low

### P1. Hard-negative expansion and failure-case sampling

Problem:

- quality may be limited more by confusing negative examples than by model capacity

Proposal:

- explicitly include:
  - pre-event frames
  - post-event frames
  - noise bursts
  - vascular/confounding artifacts
  - weak-signal non-SD changes

Expected impact:

- fewer false positives
- better real-world robustness

Risk:

- low

### P2. Prompt policy improvements

Problem:

- SAM performance depends strongly on prompt placement

Proposal:

- test smarter prompt seeding:
  - auto-positive seeds from candidate SD region
  - auto-negative seeds from common false-positive regions
- use this to reduce operator burden

Expected impact:

- improved SAM quality without retraining

Risk:

- moderate

### P2. Specialist benchmark before heavy SAM fine-tuning

Problem:

- it is not yet clear that SAM 2.1 is the best core learner for this task

Proposal:

- train a 2D or 2.5D specialist baseline first
- compare against the current SAM protocol on held-out clips

Expected impact:

- better model-family decision making
- may avoid expensive low-yield fine-tuning work

Risk:

- low to moderate

## Section 5: What Not To Parallelize First

These are poor initial targets:

- concurrent SAM predictor calls on one GPU in the same session
- multiple simultaneous propagation jobs against the same predictor
- adding threads around code paths already serialized by `predictor_lock`
- parallelizing everything before capturing timing data

Reason:

- these paths are bottlenecked by shared model state, GPU execution, or both
- naive parallelism here is more likely to increase contention than reduce latency

## Section 6: Recommended Order of Work

### Sprint 1: High-Value, Low-Risk Speed Work

1. Cache SAM-ready frame directories
2. Reuse computed visualization stats globally
3. Add analysis-mode prewarm/read-ahead
4. Reduce unnecessary redraw and marker recomputation churn

Expected outcome:

- faster event opening
- smoother frame navigation
- less repeated compute

### Sprint 2: Controlled Multithreading

1. Parallelize SAM frame export
2. Add staged preprocessing pipeline
3. Add navigation-aware prefetch queue
4. Benchmark and optionally parallelize trace computation

Expected outcome:

- faster cold path for event preparation
- better overlap of I/O and CPU work

### Sprint 3: Quality and Workflow Efficiency

1. Threshold calibration experiments
2. Hard-negative expansion
3. Specialist baseline benchmark
4. Optional specialist auto-initializer prototype

Expected outcome:

- fewer false positives
- lower operator effort
- clearer decision on whether SAM fine-tuning is worth pursuing

## Section 7: Measurement Plan

Do not merge performance changes without timing before and after.

Measure at minimum:

- event open to first preview
- event open to model ready
- average frame-scrub latency
- popup warm-up latency
- propagation completion time by event length
- CPU and GPU memory footprint

For quality changes, measure:

- Dice
- IoU
- false positive frames per clip
- false negative frames per clip
- operator prompts per event
- manual correction time per event

## Recommendation

The best immediate path is:

1. eliminate repeated work through caching
2. use multithreading for preprocessing and export pipelines, not for concurrent SAM inference
3. improve mask quality with thresholding and specialist initialization before attempting expensive SAM retraining

This gives the highest chance of improving both speed and quality on current hardware without destabilizing the analysis workflow.
